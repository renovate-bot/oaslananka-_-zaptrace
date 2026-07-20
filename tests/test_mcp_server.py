"""Tests for MCP server registration and hardening."""

from __future__ import annotations

from zaptrace.agent._tool_impls import TOOL_REGISTRY, _sessions
from zaptrace.mcp.server import (
    SERVER_NAME,
    SERVER_VERSION,
    _err,
    _is_path_safe,
    _make_sandboxed_tool,
    _ok,
    _validate_tool_params,
    server,
)

# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------


def test_server_name() -> None:
    assert SERVER_NAME == "zaptrace"


def test_server_version() -> None:
    assert SERVER_VERSION == "0.3.0"


async def test_server_has_all_tools() -> None:
    """Server exposes 91 registry tools + 3 session management tools = 94."""
    tools = await server.list_tools()
    assert len(tools) == 96
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


def test_session_scoped_resources_enforce_default_session_owner(monkeypatch) -> None:
    import zaptrace.mcp.server as mcp_server
    from zaptrace.security.objects import reset_object_authorization_state

    reset_object_authorization_state()
    _sessions.clear()
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTIVE", True)
    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTOR", "resource-owner")

    assert mcp_server.list_designs() == []
    assert mcp_server.last_proof_result()["ok"] is True
    audit = mcp_server.audit_events()
    assert audit["ok"] is True
    assert audit["data"]["object_authorization_count"] >= 1
    assert audit["data"]["object_authorization_events"][-1]["action"] == "resource:audit-events"
    assert mcp_server.design_snapshots()["ok"] is True

    monkeypatch.setattr(mcp_server, "_HTTP_AUTH_ACTOR", "resource-intruder")
    for resource in (
        mcp_server.list_designs,
        mcp_server.last_proof_result,
        mcp_server.audit_events,
        mcp_server.design_snapshots,
    ):
        denied = resource()
        assert denied["ok"] is False
        assert denied["error"]["code"] == "OBJECT_NOT_AUTHORIZED"

    reset_object_authorization_state()
    _sessions.clear()


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


def test_registry_output_dir_policy_rejects_sandbox_escape() -> None:
    errors = _validate_tool_params(
        "export_manufacturing",
        TOOL_REGISTRY["export_manufacturing"],
        {"output_dir": "../../../outside-workspace"},
    )
    assert any("escapes allowed sandbox" in error for error in errors)


def test_non_path_profile_parameter_is_not_path_validated() -> None:
    errors = _validate_tool_params(
        "drc_run",
        TOOL_REGISTRY["drc_run"],
        {"fab_profile": "../../../named-manufacturer-profile"},
    )
    assert errors == []


def test_custom_profile_path_policy_rejects_sandbox_escape() -> None:
    errors = _validate_tool_params(
        "drc_run",
        TOOL_REGISTRY["drc_run"],
        {"fab_profile": "../../../untrusted-profile.yaml"},
    )
    assert any("escapes allowed sandbox" in error for error in errors)


def test_filesystem_parameters_expose_explicit_path_policy() -> None:
    expected = {
        ("design_parse_file", "path"),
        ("export_report", "output_path"),
        ("export_svg", "output_path"),
        ("export_kicad", "output_dir"),
        ("kicad_import_project", "project_path"),
        ("kicad_to_easyeda_pro", "project_path"),
        ("kicad_to_easyeda_pro", "output_path"),
        ("pipeline_run", "source"),
        ("pipeline_run", "output_dir"),
        ("pipeline_run_stage", "source"),
        ("pipeline_run_stage", "output_dir"),
        ("export_gerber", "output_dir"),
        ("export_excellon", "output_dir"),
        ("drc_run", "fab_profile"),
        ("synthesize_board_manufacture", "output_dir"),
        ("export_manufacturing", "output_dir"),
        ("proof_run", "path"),
        ("proof_list_checks", "path"),
    }
    actual = {
        (tool_name, param_name)
        for tool_name, tool in TOOL_REGISTRY.items()
        for param_name, param in tool["params"].items()
        if "path_policy" in param
    }
    assert actual == expected


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
    assert result["error"]["code"] == "OBJECT_NOT_AUTHORIZED"


def test_session_create_and_destroy_releases_linked_runtime_state() -> None:
    from zaptrace.mcp.server import session_create, session_destroy
    from zaptrace.review.workflow import _REVIEW_SESSIONS, create_review_session
    from zaptrace.security.replay import get_replay, record_tool_call
    from zaptrace.security.sandbox import _sandboxes, sandbox_status

    created = session_create()
    sid = created["data"]["session_id"]
    review = create_review_session("DestroyDesign", design_session_id=sid, owner_principal="mcp-local")
    sandbox_status(sid)
    record_tool_call(sid, "design_inspect", {}, {"ok": True}, 1.0)

    destroyed = session_destroy(sid)

    assert destroyed["ok"] is True
    assert destroyed["data"]["removed_review_sessions"] == [review.session_id]
    assert sid not in _sessions
    assert sid not in _sandboxes
    assert get_replay(sid) is None
    assert review.session_id not in _REVIEW_SESSIONS


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
    from zaptrace.mcp.server import session_create

    created = session_create()
    session_id = created["data"]["session_id"]
    _sessions[session_id]["capabilities"] = {"preview-write"}
    wrapped = _make_sandboxed_tool("design_parse_str", TOOL_REGISTRY["design_parse_str"])
    result = await wrapped(session_id=session_id, yaml_content="meta:\n  name: AllowedMcp\n")
    assert result["ok"] is True
    events = _sessions[session_id]["audit_events"]
    assert events[-1]["decision"] == "allow"
    assert events[-1]["capability"] == "preview-write"


async def test_mcp_cannot_claim_preexisting_unowned_session() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY
    from zaptrace.security.objects import reset_object_authorization_state

    reset_object_authorization_state()
    session_id = "legacy-unowned-mcp-session"
    _sessions[session_id] = {"designs": {}, "capabilities": {"preview-write"}}
    wrapped = _make_sandboxed_tool("design_parse_str", TOOL_REGISTRY["design_parse_str"])

    result = await wrapped(session_id=session_id, yaml_content="meta:\n  name: LegacyDenied\n")

    assert result["ok"] is False
    assert result["error"]["code"] == "OBJECT_NOT_AUTHORIZED"
    reset_object_authorization_state()
    _sessions.pop(session_id, None)


async def test_mcp_read_only_principal_cannot_create_manufacturing_artifacts(tmp_path, monkeypatch) -> None:
    from zaptrace.mcp.server import session_create

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    created = session_create()
    session_id = created["data"]["session_id"]
    wrapped = _make_sandboxed_tool(
        "synthesize_board_manufacture",
        TOOL_REGISTRY["synthesize_board_manufacture"],
    )
    output_dir = tmp_path / "forbidden-bundle"

    result = await wrapped(
        session_id=session_id,
        intent="minimal board",
        output_dir=str(output_dir),
        approval_id="approval-read-only",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "OPERATION_NOT_AUTHORIZED"
    assert result["error"]["details"]["required_capability"] == "release-export"
    assert not output_dir.exists()
    events = _sessions[session_id]["audit_events"]
    assert events[-1]["tool"] == "synthesize_board_manufacture"
    assert events[-1]["decision"] == "deny"


async def test_mcp_records_allowed_release_export_audit_event() -> None:
    from zaptrace.mcp.server import session_create

    created = session_create()
    session_id = created["data"]["session_id"]
    _sessions[session_id]["capabilities"] = {"release-export"}

    def release_probe(session_id: str) -> dict[str, str]:
        return {"session_id": session_id, "status": "authorized"}

    wrapped = _make_sandboxed_tool(
        "release_probe",
        {
            "fn": release_probe,
            "params": {"session_id": {"type": "string"}},
            "capability": "release-export",
        },
    )
    result = await wrapped(session_id=session_id)

    assert result["ok"] is True
    event = _sessions[session_id]["audit_events"][-1]
    assert event["tool"] == "release_probe"
    assert event["capability"] == "release-export"
    assert event["decision"] == "allow"
