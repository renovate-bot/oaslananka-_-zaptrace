"""Tests for the shared agent/runtime security policy."""

from __future__ import annotations

from zaptrace.agent._tool_impls import (
    TOOL_REGISTRY,
    call_tool,
    list_tools,
    tool_design_parse_str,
    tool_erc_validate,
)
from zaptrace.security.policy import authorize_capability, granted_capabilities_from_header, required_tool_capability


def test_capability_header_parser() -> None:
    assert granted_capabilities_from_header("preview-write, sandbox-write release-export") == {
        "preview-write",
        "sandbox-write",
        "release-export",
    }


def test_write_capability_is_deny_by_default() -> None:
    allowed, reason = authorize_capability("sandbox-write", set())
    assert not allowed
    assert "missing required capability" in reason


def test_higher_capability_satisfies_lower_write_gate() -> None:
    allowed, reason = authorize_capability("sandbox-write", {"release-export"})
    assert allowed
    assert "satisfies" in reason


def test_read_capability_is_public_by_policy() -> None:
    allowed, reason = authorize_capability("read", set())
    assert allowed
    assert "read-only" in reason


def test_every_tool_declares_a_capability() -> None:
    assert all("capability" in tool for tool in TOOL_REGISTRY.values())
    assert all(item["capability"] for item in list_tools())


def test_write_capable_tools_have_expected_capabilities() -> None:
    assert required_tool_capability("component_add") == "sandbox-write"
    assert required_tool_capability("design_commit") == "approved-commit"
    assert required_tool_capability("export_manufacturing") == "release-export"
    assert required_tool_capability("library_search") == "read"


def test_release_exports_require_approval_and_fresh_validation() -> None:
    session_id = "release-gate-policy-test"
    yaml = """meta: {name: ReleaseGatePolicyTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, position: [10.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)

    try:
        call_tool("export_pick_and_place", session_id=session_id, design_name="ReleaseGatePolicyTest")
    except ValueError as exc:
        assert "approval_id is required" in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("release export without approval_id should fail closed")

    try:
        call_tool(
            "export_pick_and_place",
            session_id=session_id,
            design_name="ReleaseGatePolicyTest",
            approval_id="approval-001",
        )
    except ValueError as exc:
        assert "requires a fresh validation status" in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("release export without validation should fail closed")

    validation = tool_erc_validate(session_id=session_id, design_name="ReleaseGatePolicyTest")
    assert validation["passed"] is True
    result = call_tool(
        "export_pick_and_place",
        session_id=session_id,
        design_name="ReleaseGatePolicyTest",
        approval_id="approval-001",
    )
    assert result["release_gate"]["approval_id"] == "approval-001"
    assert result["release_gate"]["validation"]["erc"]["passed"] is True


def test_release_exports_reject_stale_validation_after_design_change() -> None:
    session_id = "release-gate-stale-validation-test"
    first_yaml = """meta: {name: ReleaseGateStaleTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, position: [10.0, 20.0]}
nets: {}
"""
    changed_yaml = """meta: {name: ReleaseGateStaleTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, position: [10.0, 20.0]}
  r1: {ref: R1, type: resistor, value: 10k, position: [12.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=first_yaml)
    tool_erc_validate(session_id=session_id, design_name="ReleaseGateStaleTest")
    tool_design_parse_str(session_id=session_id, yaml_content=changed_yaml)

    try:
        call_tool(
            "export_pick_and_place",
            session_id=session_id,
            design_name="ReleaseGateStaleTest",
            approval_id="approval-stale",
        )
    except ValueError as exc:
        assert "requires fresh validation for the current design state" in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("release export should reject stale validation evidence")


def test_release_gate_attaches_evidence_to_fabrication_exports(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    session_id = "release-gate-fabrication-test"
    yaml = """meta: {name: ReleaseGateFabricationTest}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets:
  n1: {name: VCC, nodes: [R1.1]}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)
    erc = tool_erc_validate(session_id=session_id, design_name="ReleaseGateFabricationTest")
    assert erc["passed"] is True
    drc = call_tool("drc_run", session_id=session_id, design_name="ReleaseGateFabricationTest")
    assert drc["validation_status"]["drc"] is not None

    approval_id = "approval-fab"
    for tool_name, output_name in (
        ("export_kicad", "kicad"),
        ("export_gerber", "gerber"),
        ("export_excellon", "drill"),
    ):
        result = call_tool(
            tool_name,
            session_id=session_id,
            design_name="ReleaseGateFabricationTest",
            output_dir=str(tmp_path / output_name),
            approval_id=approval_id,
        )
        assert result["release_gate"]["approval_id"] == approval_id
        assert result["release_gate"]["validation"]["erc"]["passed"] is True
        assert result["release_gate"]["validation"]["drc"] is not None
