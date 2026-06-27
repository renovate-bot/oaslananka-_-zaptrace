"""Session ID resolution and REST capability authorization helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from zaptrace.agent._tool_impls import _get_session
from zaptrace.security.policy import (
    authorize_capability,
    granted_capabilities_from_header,
    record_audit_event,
    required_tool_capability,
)


def resolve_session_id(
    x_zaptrace_session_id: str | None = Header(None),
) -> str:
    """Extract the session ID from the request header, defaulting to ``"api-default"``."""
    return x_zaptrace_session_id or "api-default"


def require_session_id(
    request: Request,
    x_zaptrace_session_id: str | None = Header(None),
) -> str:
    """Require an explicit session ID for mutating REST operations."""
    if not x_zaptrace_session_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "SESSION_REQUIRED", "message": "X-ZapTrace-Session-Id is required for mutating operations"},
        )
    auth = getattr(request.state, "zaptrace_auth", None)
    allowed_sessions = set(auth.get("allowed_sessions", {"*"})) if isinstance(auth, dict) else {"*"}
    if "*" not in allowed_sessions and x_zaptrace_session_id not in allowed_sessions:
        raise HTTPException(
            status_code=403,
            detail={"code": "OBJECT_NOT_AUTHORIZED", "message": "Token is not authorized for this session"},
        )
    return x_zaptrace_session_id


def authorize_tool(tool_name: str) -> Callable[..., str]:
    """Build a FastAPI dependency enforcing a tool's capability policy."""

    def _dependency(
        request: Request,
        session_id: str = Depends(require_session_id),
        x_zaptrace_capabilities: str | None = Header(None),
        x_zaptrace_actor: str | None = Header(None),
        x_zaptrace_reason: str | None = Header(None),
    ) -> str:
        required = required_tool_capability(tool_name)
        auth = getattr(request.state, "zaptrace_auth", None)
        if isinstance(auth, dict):
            granted = {str(scope).lower() for scope in auth.get("scopes", set())}
            actor = str(auth.get("actor") or "api-token")
            auth_source = "bearer-token"
        else:
            granted = granted_capabilities_from_header(x_zaptrace_capabilities)
            actor = x_zaptrace_actor or "rest-client"
            auth_source = "local-capability-header"
        allowed, reason = authorize_capability(required, granted)
        session = _get_session(session_id)
        record_audit_event(
            session,
            surface="rest",
            session_id=session_id,
            actor=actor,
            tool=tool_name,
            capability=required,
            decision="allow" if allowed else "deny",
            reason=x_zaptrace_reason or reason,
            metadata={
                "method": request.method,
                "path": str(request.url.path),
                "granted_capabilities": sorted(granted),
                "auth_source": auth_source,
            },
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "OPERATION_NOT_AUTHORIZED",
                    "message": reason,
                    "tool": tool_name,
                    "required_capability": required,
                },
            )
        return session_id

    return _dependency


def session_audit_events(session_id: str, limit: int = 50) -> dict[str, Any]:
    """Return recent audit events for a REST/MCP session."""
    session = _get_session(session_id)
    events = list(session.get("audit_events", []))
    if limit < 1:
        limit = 1
    return {"session_id": session_id, "count": len(events), "events": events[-limit:]}
