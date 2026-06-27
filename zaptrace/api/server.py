"""FastAPI REST API server for ZapTrace — hardened with safety middleware."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from zaptrace import __version__
from zaptrace.api.routes import api_router

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_PATH_LENGTH = 4096
_RATE_LIMIT_WINDOW_S = 60
_RATE_LIMIT_MAX_REQUESTS = 120

# ---------------------------------------------------------------------------
# Rate limiter (in-memory sliding window)
# ---------------------------------------------------------------------------

_request_log: dict[str, list[float]] = {}
_LAST_CLEANUP: float = 0.0
_CLEANUP_INTERVAL_S: float = 300.0  # full cleanup every 5 minutes


def _rate_limiter(client_ip: str) -> bool:
    """Check if *client_ip* has exceeded the rate limit.  Returns False if blocked."""
    global _LAST_CLEANUP
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_S

    # Periodically purge stale entries for ALL IPs to prevent memory leak
    if now - _LAST_CLEANUP > _CLEANUP_INTERVAL_S:
        stale_before = now - _RATE_LIMIT_WINDOW_S
        _request_log.clear() if not _request_log else _request_log.update(
            (ip, [t for t in ts if t > stale_before]) for ip, ts in _request_log.items()
        )
        _LAST_CLEANUP = now

    hits = _request_log.get(client_ip, [])
    # Prune expired entries for this IP
    hits = [t for t in hits if t > window_start]
    if len(hits) >= _RATE_LIMIT_MAX_REQUESTS:
        return False

    hits.append(now)
    _request_log[client_ip] = hits
    return True


def _rate_limit_info(client_ip: str) -> dict[str, Any]:
    hits = _request_log.get(client_ip, [])
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_S
    # hits are already pruned on each rate_limiter call, so inline filter is fine
    active = [t for t in hits if t > window_start]
    return {
        "limit": _RATE_LIMIT_MAX_REQUESTS,
        "remaining": max(0, _RATE_LIMIT_MAX_REQUESTS - len(active)),
        "window_s": _RATE_LIMIT_WINDOW_S,
    }


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SecurityMiddleware(BaseHTTPMiddleware):
    """Add security headers and rate limiting."""

    @staticmethod
    def _resolve_client_ip(request: Request) -> str:
        """Extract the real client IP, respecting reverse proxy headers."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # Take the leftmost IP (original client)
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        # --- Optional bearer-token authentication ---
        api_token = os.environ.get("ZAPTRACE_API_TOKEN", "")
        if api_token and request.method != "OPTIONS" and request.url.path.startswith("/api/"):
            expected = f"Bearer {api_token}"
            if request.headers.get("Authorization", "") != expected:
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error": {"code": "AUTH_REQUIRED", "message": "Valid bearer token is required"},
                    },
                    headers={"WWW-Authenticate": "Bearer"},
                )
            expected_audience = os.environ.get("ZAPTRACE_API_TOKEN_AUDIENCE", "")
            if expected_audience and request.headers.get("X-ZapTrace-Audience", "") != expected_audience:
                return JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "error": {"code": "AUTH_AUDIENCE_MISMATCH", "message": "Token audience is not accepted"},
                    },
                )
            request.state.zaptrace_auth = {
                "actor": os.environ.get("ZAPTRACE_API_TOKEN_SUBJECT", "api-token"),
                "scopes": {
                    item.strip().lower()
                    for item in os.environ.get("ZAPTRACE_API_TOKEN_SCOPES", "").replace(",", " ").split()
                    if item.strip()
                },
                "audience": expected_audience,
                "allowed_sessions": {
                    item.strip()
                    for item in os.environ.get("ZAPTRACE_API_TOKEN_SESSIONS", "*").replace(",", " ").split()
                    if item.strip()
                },
            }

        # --- Rate limiting ---
        client_ip = self._resolve_client_ip(request)
        if not _rate_limiter(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again later."},
                },
                headers={
                    "Retry-After": str(_RATE_LIMIT_WINDOW_S),
                    "X-RateLimit-Limit": str(_RATE_LIMIT_MAX_REQUESTS),
                },
            )

        # --- Request body size check ---
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                cl = int(content_length)
            except (ValueError, TypeError):
                cl = 0
            if cl > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "ok": False,
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Request body exceeds {_MAX_BODY_BYTES // (1024 * 1024)} MB limit",
                        },
                    },
                )

        # --- Process request ---
        response = await call_next(request)

        # --- Security headers ---
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"  # deprecated but harmless
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"

        # Rate limit headers on every response
        rl_info = _rate_limit_info(client_ip)
        response.headers["X-RateLimit-Limit"] = str(rl_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rl_info["remaining"])

        return response


# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------


def _cors_origins() -> list[str]:
    raw = os.environ.get("ZAPTRACE_CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:5173", "http://localhost:8080"]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — currently a no-op."""
    yield


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="ZapTrace API",
        description="Agent-native electronics design REST API",
        version=__version__,
        lifespan=lifespan,
    )

    # --- Order matters: security middleware first ---
    app.add_middleware(SecurityMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "Accept",
            "Origin",
            "X-ZapTrace-Session-Id",
            "X-ZapTrace-Actor",
            "X-ZapTrace-Reason",
        ],
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


def run(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the API server with uvicorn."""
    import uvicorn

    uvicorn.run("zaptrace.api.server:app", host=host, port=port, reload=False)
