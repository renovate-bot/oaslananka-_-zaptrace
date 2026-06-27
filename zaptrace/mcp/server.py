"""FastMCP server exposing all agent tools as MCP tools + resources.

Hardening layer (Issue #21):
  - Session management: create / destroy / list sessions
  - Structured error wrapping: every tool output wrapped in a consistent envelope
  - Input validation: file path sandboxing, parameter type/bounds checks
  - Timeout protection: long-running tools get a configurable timeout
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from zaptrace import __version__
from zaptrace.agent._tool_impls import TOOL_REGISTRY, _get_session, _sessions
from zaptrace.security.policy import (
    authorize_capability,
    granted_capabilities_from_header,
    record_audit_event,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "zaptrace"
SERVER_VERSION = __version__
SESSION_ID_HEADER = "x-zaptrace-session-id"
_DEFAULT_SESSION_ID = "mcp-default-session"
_DEFAULT_TIMEOUT_S = 120  # per-tool timeout
_MAX_PATH_LENGTH = 4096
_ALLOWED_EXPORT_ROOT = Path.cwd()  # sandbox base for file exports

# ---------------------------------------------------------------------------
# Structured response helpers
# ---------------------------------------------------------------------------

_ERROR_SENTINEL = object()


def _ok(data: Any = None) -> dict[str, Any]:
    """Return a success envelope."""
    return {"ok": True, "data": data}


def _err(message: str, code: str = "TOOL_ERROR", details: dict | None = None) -> dict[str, Any]:
    """Return an error envelope."""
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": details or {}},
    }


def _is_path_safe(path: str) -> tuple[bool, str]:
    """Validate that a path is within the allowed sandbox.

    Returns (safe, reason_if_unsafe).
    """
    if not path or not path.strip():
        return False, "Path is empty"
    if len(path) > _MAX_PATH_LENGTH:
        return False, f"Path exceeds max length ({_MAX_PATH_LENGTH})"
    normalized_path = path.replace("\\", "/")
    p = Path(normalized_path)
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        return False, f"Cannot resolve path: {path}"
    cwd = _ALLOWED_EXPORT_ROOT.resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError:
        return False, f"Path escapes allowed sandbox: {resolved}"
    return True, ""


def _validate_tool_params(tool_name: str, tool_def: dict, kwargs: dict) -> list[str]:
    """Validate tool parameters against registry schema.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    param_spec = tool_def.get("params", {})
    for pname, pval in kwargs.items():
        if pname == "session_id":
            continue
        spec = param_spec.get(pname, {})
        ptype = spec.get("type", "any")
        if ptype == "string" and not isinstance(pval, str):
            errors.append(f"Parameter '{pname}' expected string, got {type(pval).__name__}")
        elif ptype == "integer" and not isinstance(pval, int):
            errors.append(f"Parameter '{pname}' expected integer, got {type(pval).__name__}")
        elif ptype == "number" and not isinstance(pval, (int, float)):
            errors.append(f"Parameter '{pname}' expected number, got {type(pval).__name__}")
        elif ptype == "boolean" and not isinstance(pval, bool):
            errors.append(f"Parameter '{pname}' expected boolean, got {type(pval).__name__}")
        # Path safety check for path/file parameters
        if ("path" in pname.lower() or "file" in pname.lower()) and isinstance(pval, str):
            safe, reason = _is_path_safe(pval)
            if not safe:
                errors.append(f"Parameter '{pname}': {reason}")
    return errors


def _session_capabilities(session_id: str) -> set[str]:
    """Return explicit capabilities granted to an MCP session plus env grants."""
    session = _get_session(session_id)
    caps = set(session.get("capabilities", set()))
    caps.update(granted_capabilities_from_header(os.environ.get("ZAPTRACE_MCP_CAPABILITIES")))
    return caps


# ---------------------------------------------------------------------------
# Per-session tools exposed as MCP resources
# ---------------------------------------------------------------------------


def _list_session_designs(session_id: str) -> list[dict[str, Any]]:
    """List all designs in a session (internal helper)."""
    session = _get_session(session_id)
    designs = session.get("designs", {})
    return [
        {
            "name": name,
            "component_count": len(d.components),
            "net_count": len(d.nets),
            "board": f"{d.board.width_mm}x{d.board.height_mm}mm",
        }
        for name, d in designs.items()
    ]


# ---------------------------------------------------------------------------
# Sandboxed wrapper that wraps every tool call
# ---------------------------------------------------------------------------


def _make_sandboxed_tool(tool_name: str, tool_def: dict) -> Callable:
    """Wrap a raw tool function with validation, error handling, and timeout."""

    fn: Callable = tool_def["fn"]
    sig = inspect.signature(fn)
    has_session = "session_id" in sig.parameters

    @functools.wraps(fn)
    async def _sandboxed_wrapper(**kwargs: Any) -> dict[str, Any]:
        # 1. Inject session_id if the tool expects it
        if has_session and "session_id" not in kwargs:
            kwargs["session_id"] = _DEFAULT_SESSION_ID

        # 2. Validate types and path safety
        param_errors = _validate_tool_params(tool_name, tool_def, kwargs)
        if param_errors:
            return _err(
                "; ".join(param_errors),
                code="INVALID_PARAMETER",
            )

        # 3. Enforce deny-by-default capability policy for mutating/export tools
        session_id = str(kwargs.get("session_id", _DEFAULT_SESSION_ID))
        required_capability = str(tool_def.get("capability", "read"))
        granted_capabilities = _session_capabilities(session_id)
        allowed, reason = authorize_capability(required_capability, granted_capabilities)
        if required_capability != "read":
            session = _get_session(session_id)
            record_audit_event(
                session,
                surface="mcp",
                session_id=session_id,
                actor="mcp-client",
                tool=tool_name,
                capability=required_capability,
                decision="allow" if allowed else "deny",
                reason=reason,
                metadata={"granted_capabilities": sorted(granted_capabilities)},
            )
        if not allowed:
            return _err(
                reason,
                code="OPERATION_NOT_AUTHORIZED",
                details={"tool": tool_name, "required_capability": required_capability},
            )

        # 4. Determine timeout
        #    - proof tools and routing can be slow -> use longer timeout
        slow_indicators = ("proof_", "synthesize_", "route_", "pipeline_", "export_")
        timeout = 300 if any(tool_name.startswith(p) for p in slow_indicators) else _DEFAULT_TIMEOUT_S

        # 5. Run with timeout
        try:
            loop = asyncio.get_event_loop()
            if inspect.iscoroutinefunction(fn):
                result = await asyncio.wait_for(fn(**kwargs), timeout=timeout)
            else:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, functools.partial(fn, **kwargs)),
                    timeout=timeout,
                )
        except TimeoutError:
            return _err(
                f"Tool '{tool_name}' timed out after {timeout}s",
                code="TOOL_TIMEOUT",
            )
        except Exception as exc:
            return _err(
                str(exc),
                code="TOOL_ERROR",
                details={"tool": tool_name},
            )

        # 6. Wrap non-dict results
        if result is None:
            return _ok({"message": f"Tool '{tool_name}' completed successfully"})
        if not isinstance(result, dict):
            return _ok({"result": str(result)})
        return _ok(result)

    # Update the wrapper's signature to match the original fn
    # so FastMCP can extract the parameter schema
    _sandboxed_wrapper.__signature__ = sig  # type: ignore[attr-defined]
    _sandboxed_wrapper.__name__ = tool_name
    _sandboxed_wrapper.__qualname__ = tool_name

    return _sandboxed_wrapper


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

server = FastMCP(
    SERVER_NAME,
    instructions=(
        "Agent-native electronics design assistant. "
        "Use tools to parse, synthesize, validate, place, route, "
        "and export electronics designs.\n\n"
        "All tools return a structured envelope: { ok: bool, data?: ..., error?: { code, message, details } }.\n"
        "On success ok=true with data in 'data' field. On failure ok=false with error info in 'error' field.\n"
        "Use session_create() first if you need an isolated session, otherwise a default session is used."
    ),
    version=SERVER_VERSION,
)

# ---------------------------------------------------------------------------
# Session management (administrative tools)
# ---------------------------------------------------------------------------


@server.tool(description="Create a new isolated session and return its ID")
def session_create(capabilities: str | None = None) -> dict[str, Any]:
    session_id = f"mcp-{int(time.time() * 1000)}-{hash(str(time.time_ns())) & 0xFFFF:04x}"
    session = _get_session(session_id)  # initialize
    allow_local_grants = os.environ.get("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if capabilities and allow_local_grants:
        session["capabilities"] = granted_capabilities_from_header(capabilities)
    return _ok({"session_id": session_id, "capabilities": sorted(session.get("capabilities", set()))})


@server.tool(description="Destroy a session and release its resources")
def session_destroy(session_id: str) -> dict[str, Any]:
    if session_id not in _sessions:
        return _err(f"Session '{session_id}' not found", code="SESSION_NOT_FOUND")
    del _sessions[session_id]
    return _ok({"message": f"Session '{session_id}' destroyed"})


@server.tool(description="List all active sessions and their design counts")
def session_list() -> dict[str, Any]:
    result = []
    for sid, session_data in _sessions.items():
        designs = session_data.get("designs", {})
        result.append(
            {
                "session_id": sid,
                "design_count": len(designs),
            }
        )
    return _ok({"sessions": result})


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@server.resource("zaptrace://designs")
def list_designs() -> list[dict[str, Any]] | dict[str, Any]:
    """List all designs in the current MCP session."""
    try:
        return _list_session_designs(_DEFAULT_SESSION_ID)
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://library/categories")
def library_categories() -> dict[str, Any]:
    """List component library categories."""
    try:
        from zaptrace.agent._tool_impls import tool_library_list_categories

        return _ok(tool_library_list_categories())
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://templates")
def synthesis_templates() -> dict[str, Any]:
    """List available synthesis templates."""
    try:
        from zaptrace.agent._tool_impls import tool_list_synthesis_templates

        return _ok({"templates": tool_list_synthesis_templates()})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://proof/result")
def last_proof_result() -> dict[str, Any]:
    """Show the last proof pack run result (if available)."""
    try:
        from zaptrace.agent._tool_impls import _get_session as _gs

        session = _gs(_DEFAULT_SESSION_ID)
        result = session.get("_last_proof_result")
        if result is None:
            return _ok({"message": "No proof pack has been run in this session"})
        return _ok(result)
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://audit/events")
def audit_events() -> dict[str, Any]:
    """List recent audit events for the default MCP session."""
    try:
        session = _get_session(_DEFAULT_SESSION_ID)
        events = list(session.get("audit_events", []))
        return _ok({"session_id": _DEFAULT_SESSION_ID, "count": len(events), "events": events[-50:]})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://snapshots")
def design_snapshots() -> dict[str, Any]:
    """List available snapshots for all designs."""
    try:
        session = _get_session(_DEFAULT_SESSION_ID)
        all_snaps = session.get("snapshots", {})
        result = {}
        for dname, snaps in all_snaps.items():
            result[dname] = list(snaps.keys())
        return _ok({"snapshots_by_design": result})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


@server.resource("zaptrace://erc/rules")
def erc_rules() -> dict[str, Any]:
    """List all registered ERC rules."""
    try:
        from zaptrace.agent._tool_impls import tool_erc_list_rules

        rules = tool_erc_list_rules()
        return _ok(rules if isinstance(rules, dict) else {"rules": rules})
    except Exception as exc:
        return _err(str(exc), code="RESOURCE_ERROR")


# ---------------------------------------------------------------------------
# Register all tools from TOOL_REGISTRY
# ---------------------------------------------------------------------------


def _register_tools() -> None:
    """Register all tools with sandboxed wrappers."""
    for tool_name, tool_def in TOOL_REGISTRY.items():
        wrapped = _make_sandboxed_tool(tool_name, tool_def)
        server.tool(
            name=tool_name,
            description=tool_def["description"],
        )(wrapped)


_register_tools()

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run() -> None:
    """Run the MCP server on stdio (for `zaptrace-mcp` CLI entry point)."""
    server.run()


def run_http(host: str = "0.0.0.0", port: int = 8090) -> None:
    """Run the MCP server over HTTP (for development/testing)."""
    import uvicorn

    uvicorn.run(server.http_app(), host=host, port=port)


if __name__ == "__main__":
    run()
