"""Tests for MCP server registration and hardening."""

from __future__ import annotations

from zaptrace.agent._tool_impls import _sessions
from zaptrace.mcp.server import (
    SERVER_NAME,
    SERVER_VERSION,
    _err,
    _is_path_safe,
    _make_sandboxed_tool,
    _ok,
    server,
)

# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------


def test_server_name() -> None:
    assert SERVER_NAME == "zaptrace"


def test_server_version() -> None:
    assert SERVER_VERSION == "0.2.2"


async def test_server_has_all_tools() -> None:
    """Server exposes 77 registry tools + 3 session management tools = 80."""
    tools = await server.list_tools()
    assert len(tools) == 90
    tool_names = {t.name for t in tools}
    # Design analysis tools (mechanical / security / testability)
    assert {"mechanical_review", "security_review", "testability_report"} <= tool_names
    # Original tools
    assert "design_parse_file" in tool_names
    assert "synthesize_design" in tool_names
    assert "erc_validate" in tool_names
    assert "place_components" in tool_names
    assert "route_nets" in tool_names
    assert "pipeline_run" in tool_names
    assert "export_gerber" in tool_names
    assert "export_excellon" in tool_names
    assert "drc_run" in tool_names
    assert "design_route_smart" in tool_names
    assert "schematic_render" in tool_names
    assert "footprint_generate" in tool_names
    assert "footprint_list_packages" in tool_names
    assert "export_manufacturing" in tool_names
    assert "export_pick_and_place" in tool_names
    assert "proof_run" in tool_names
    assert "proof_run_design" in tool_names
    assert "proof_list_checks" in tool_names
    assert "audit_list_events" in tool_names
    assert "design_transaction_preview" in tool_names
    assert "design_transaction_validate" in tool_names
    assert "design_transaction_commit" in tool_names
    assert "design_transaction_rollback" in tool_names
    assert "design_transaction_list" in tool_names
    # Session management tools
    assert "session_create" in tool_names
    assert "session_destroy" in tool_names
    assert "session_list" in tool_names


async def test_server_has_resources() -> None:
    resources = await server.list_resources()
    resource_uris = {str(r.uri) for r in resources}
    assert "zaptrace://designs" in resource_uris
    assert "zaptrace://library/categories" in resource_uris
    assert "zaptrace://templates" in resource_uris
    assert "zaptrace://erc/rules" in resource_uris
    assert "zaptrace://proof/result" in resource_uris
    assert "zaptrace://audit/events" in resource_uris


def test_server_instructions() -> None:
    assert "electronics" in server.instructions
    assert "structured envelope" in server.instructions


# ---------------------------------------------------------------------------
# Structured response helpers
# ---------------------------------------------------------------------------


def test_ok_response() -> None:
    resp = _ok({"design_name": "test"})
    assert resp == {"ok": True, "data": {"design_name": "test"}}


def test_ok_no_data() -> None:
    resp = _ok()
    assert resp == {"ok": True, "data": None}


def test_err_response() -> None:
    resp = _err("something broke", code="TEST_ERROR", details={"tool": "x"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "TEST_ERROR"
    assert resp["error"]["message"] == "something broke"
    assert resp["error"]["details"] == {"tool": "x"}


# ---------------------------------------------------------------------------
# Path safety validation
# ---------------------------------------------------------------------------


def test_path_safe() -> None:
    safe, _ = _is_path_safe("build/output.gbr")
    assert safe


def test_path_empty() -> None:
    safe, reason = _is_path_safe("")
    assert not safe
    assert "empty" in reason


def test_path_sandbox_escape() -> None:
    safe, reason = _is_path_safe("..\\..\\Windows\\system32")
    assert not safe
    assert "escapes" in reason


def test_path_sandbox_escape_unix() -> None:
    """Unix-style path traversal on Windows should also be caught."""
    safe, reason = _is_path_safe("../../../etc/passwd")
    assert not safe
    assert "escapes" in reason or "Cannot resolve" in reason


# ---------------------------------------------------------------------------
# Session management integration
# ---------------------------------------------------------------------------


def test_session_create() -> None:
    from zaptrace.mcp.server import session_create

    result = session_create()
    assert result["ok"] is True
    assert "session_id" in result["data"]
    sid = result["data"]["session_id"]
    assert sid.startswith("mcp-")
    assert sid in _sessions
    assert result["data"]["capabilities"] == []


def test_session_list() -> None:
    from zaptrace.mcp.server import session_list

    result = session_list()
    assert result["ok"] is True
    assert isinstance(result["data"]["sessions"], list)


def test_session_destroy_not_found() -> None:
    from zaptrace.mcp.server import session_destroy

    result = session_destroy("session-nonexistent")
    assert result["ok"] is False
    assert result["error"]["code"] == "SESSION_NOT_FOUND"


def test_session_create_and_destroy() -> None:
    from zaptrace.mcp.server import session_create, session_destroy

    created = session_create()
    sid = created["data"]["session_id"]
    destroyed = session_destroy(sid)
    assert destroyed["ok"] is True
    assert sid not in _sessions


# ---------------------------------------------------------------------------
# Resource endpoints return structured envelopes
# ---------------------------------------------------------------------------


async def test_resource_designs() -> None:
    from zaptrace.mcp.server import list_designs

    result = list_designs()
    # Can be either a list (empty) or a dict (error)
    if isinstance(result, dict):
        assert "ok" in result or "error" in result


def test_session_create_does_not_accept_self_declared_capability_grants(monkeypatch) -> None:
    from zaptrace.mcp.server import session_create

    monkeypatch.delenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", raising=False)
    result = session_create(capabilities="preview-write,sandbox-write")
    assert result["ok"] is True
    assert result["data"]["capabilities"] == []


def test_session_create_capability_grants_require_explicit_local_opt_in(monkeypatch) -> None:
    from zaptrace.mcp.server import session_create

    monkeypatch.setenv("ZAPTRACE_MCP_ALLOW_SESSION_CAPABILITY_GRANTS", "true")
    result = session_create(capabilities="preview-write,sandbox-write")
    assert result["ok"] is True
    assert result["data"]["capabilities"] == ["preview-write", "sandbox-write"]


async def test_mcp_denies_write_tool_without_capability_and_records_audit() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    wrapped = _make_sandboxed_tool("design_parse_str", TOOL_REGISTRY["design_parse_str"])
    result = await wrapped(session_id="mcp-denied-session", yaml_content="meta:\n  name: DeniedMcp\n")
    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    events = _sessions["mcp-denied-session"]["audit_events"]
    assert events[-1]["decision"] == "deny"
    assert events[-1]["tool"] == "design_parse_str"


async def test_mcp_allows_write_tool_with_session_capability_and_records_audit() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    _sessions["mcp-allowed-session"] = {"designs": {}, "capabilities": {"preview-write"}}
    wrapped = _make_sandboxed_tool("design_parse_str", TOOL_REGISTRY["design_parse_str"])
    result = await wrapped(session_id="mcp-allowed-session", yaml_content="meta:\n  name: AllowedMcp\n")
    assert result["ok"] is True
    events = _sessions["mcp-allowed-session"]["audit_events"]
    assert events[-1]["decision"] == "allow"
    assert events[-1]["capability"] == "preview-write"
