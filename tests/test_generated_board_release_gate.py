from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.ci_generated_board_release_gate import build_report, render_markdown, report_json
from zaptrace.core.models import Component, Design, DesignMeta, FootprintDef, Pad


def test_generated_board_release_gate_report_passes(tmp_path) -> None:
    report = build_report(tmp_path / "artifacts")

    assert report["schema_version"] == "1.0"
    assert report["gate_id"] == "generated-board-release-gate-v1"
    assert report["family_id"] == "esp32_usb_sensor"
    assert report["design_name"] == "esp32_usb_sensor_generated_v1"
    assert report["passed"] is True
    assert report["generated_project_evidence_passed"] is True
    assert report["artifact_count"] == 9
    assert report["required_artifact_count"] == 9
    assert report["missing_required_artifact_count"] == 0
    assert report["schematic_passed"] is True
    assert report["pcb_passed"] is True
    assert report["manufacturing_manifest_present"] is True
    assert report["review_handoff_present"] is True
    assert report["blocking_reasons"] == []
    assert report["risky_package_policy"]["checked_component_count"] >= 0
    assert report["risky_package_policy"]["blocked_component_count"] == 0
    assert "not fabrication-ready" in " ".join(report["non_claims"])


def test_generated_board_release_gate_hashes_are_stable(tmp_path) -> None:
    first = build_report(tmp_path / "first")
    second = build_report(tmp_path / "second")

    assert first["artifact_hashes"] == second["artifact_hashes"]
    assert set(first["artifact_hashes"]) == set(first["expected_artifact_kinds"])
    assert all(len(value) == 64 for value in first["artifact_hashes"].values())


def test_generated_board_release_gate_json_and_markdown_render() -> None:
    report = build_report(Path("/tmp/zaptrace-generated-board-release-gate-test"))

    payload = json.loads(report_json(report))
    markdown = render_markdown(report)

    assert payload["passed"] is True
    assert "# Generated Board Release Gate" in markdown
    assert "generated-board-release-gate-v1" in markdown
    assert "not fabrication-ready" in markdown


def test_generated_board_release_gate_blocks_unreviewed_risky_packages(tmp_path) -> None:
    with patch(
        "scripts.ci_generated_board_release_gate._evaluate_risky_package_policy",
        return_value={
            "reviewed": False,
            "approval_id": "",
            "checked_component_count": 1,
            "risky_component_count": 1,
            "blocked_component_count": 1,
            "risky_components": [
                {
                    "component_id": "u1",
                    "component_ref": "U1",
                    "package_id": "ESP32-C3-MINI-1",
                    "family": "ESP32-C3-MINI",
                    "blocked": True,
                    "diagnostic_codes": ["unreviewed-risky-package"],
                }
            ],
            "blocked_components": [
                {
                    "component_id": "u1",
                    "component_ref": "U1",
                    "package_id": "ESP32-C3-MINI-1",
                    "family": "ESP32-C3-MINI",
                    "blocked": True,
                    "diagnostic_codes": ["unreviewed-risky-package"],
                }
            ],
        },
    ):
        report = build_report(
            tmp_path / "artifacts",
            risky_package_reviewed=False,
            risky_package_approval_id="",
        )

    assert report["passed"] is False
    assert report["risky_package_policy"]["risky_component_count"] == 1
    assert report["risky_package_policy"]["blocked_component_count"] == 1
    assert any("risky-package policy blocked" in reason for reason in report["blocking_reasons"])


def test_evaluate_risky_package_policy_detects_unreviewed_risky_component() -> None:
    from scripts.ci_generated_board_release_gate import _evaluate_risky_package_policy

    design = Design(meta=DesignMeta(name="risky_design"))
    design.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="module",
        footprint="ESP32-C3-MINI-1",
        footprint_def=FootprintDef(
            courtyard=(0.0, 0.0),
            pads=[Pad(id=str(i), position=(float(i), 0.0)) for i in range(1, 17)],
        ),
    )

    result = _evaluate_risky_package_policy(
        type("Compiled", (), {"design": design})(),
        reviewed=False,
        approval_id="",
    )

    assert result["checked_component_count"] == 1
    assert result["risky_component_count"] == 1
    assert result["blocked_component_count"] == 1
