from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_generated_board_release_gate import build_report, render_markdown, report_json


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
