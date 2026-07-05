from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_generated_board_release_gate import build_report, report_json

REPORT_PATH = Path("docs/reports/generated-board-release-gate.json")

EXPECTED_ARTIFACT_KINDS = [
    "intent",
    "design-ir-compile-report",
    "kicad-project",
    "kicad-schematic",
    "schematic-generation-report",
    "kicad-pcb",
    "pcb-generation-report",
    "manufacturing-export-manifest",
    "review-handoff",
]

EXPECTED_ARTIFACT_HASHES = {
    "intent": "a8ab42aff48cf91fe15396c3a1e219d7b1648d7bb46c5754005e7997df83958f",
    "design-ir-compile-report": "1cb74987d98b141bf5361e1a308d8895f62e3a388562430c4f40ee1185dcabb1",
    "kicad-project": "e672a2fd0ef2bf3edc4b29f5f44cc49bc3af3a9f6cc9a6f42ee249209b9ae2e7",
    "kicad-schematic": "30d94e94ccd4ff8a5ef61bc397905ecd7b38873075c43d6c299386fbd13f67ab",
    "schematic-generation-report": "b064a39a858074b7a21e431c2afd25fd3472d43a5380a37f1608dbfd933b3fdb",
    "kicad-pcb": "a073adc8841402f3a1a06278f22d8fb98301370d0c7133d459030b51fbdd4f57",
    "pcb-generation-report": "a30f065c9376814348706f6135917bcfdfba4dda313631c2cad2cc976b2d6967",
    "manufacturing-export-manifest": "1f49b6c584e94847734e89ac715f650a95ab19e4606df67d5532a3238e3a9576",
    "review-handoff": "df586620a33f74ae270aa193e0a4bdf4e59eb947d7b45da2e34513b6680b30ed",
}

EXPECTED_ARTIFACT_PATHS = {
    "intent": "board-generation-intent.json",
    "design-ir-compile-report": "esp32_usb_sensor_generated_v1.design_ir_compilation.json",
    "kicad-project": "esp32_usb_sensor_generated_v1.kicad_pro",
    "kicad-schematic": "esp32_usb_sensor_generated_v1.kicad_sch",
    "schematic-generation-report": "esp32_usb_sensor_generated_v1.kicad_schematic_generation.json",
    "kicad-pcb": "esp32_usb_sensor_generated_v1.kicad_pcb",
    "pcb-generation-report": "esp32_usb_sensor_generated_v1.kicad_pcb_generation.json",
    "manufacturing-export-manifest": "exports/manifest.json",
    "review-handoff": "review/handoff.json",
}


def _committed_report() -> dict[str, object]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_generated_board_committed_report_matches_current_pipeline(tmp_path) -> None:
    current = build_report(tmp_path / "generated-board-release-gate")
    committed = _committed_report()

    assert current == committed
    assert report_json(current) == REPORT_PATH.read_text(encoding="utf-8")


def test_generated_board_artifact_hash_snapshot() -> None:
    report = _committed_report()

    assert report["expected_artifact_kinds"] == EXPECTED_ARTIFACT_KINDS
    assert report["artifact_hashes"] == EXPECTED_ARTIFACT_HASHES
    assert report["artifact_paths"] == EXPECTED_ARTIFACT_PATHS


def test_generated_board_report_required_structure_snapshot() -> None:
    report = _committed_report()

    assert report["schema_version"] == "1.0"
    assert report["gate_id"] == "generated-board-release-gate-v1"
    assert report["family_id"] == "esp32_usb_sensor"
    assert report["design_name"] == "esp32_usb_sensor_generated_v1"
    assert report["passed"] is True
    assert report["generated_project_evidence_passed"] is True
    assert report["artifact_count"] == 9
    assert report["required_artifact_count"] == 9
    assert report["missing_required_artifact_count"] == 0
    assert report["requirement_trace_count"] == 2
    assert report["provenance_record_count"] == 1
    assert report["schematic_passed"] is True
    assert report["pcb_passed"] is True
    assert report["manufacturing_manifest_present"] is True
    assert report["review_handoff_present"] is True
    assert report["blocking_reasons"] == []
    assert report["non_claims_enforced"] is True


def test_generated_board_report_non_claim_snapshot() -> None:
    report = _committed_report()

    assert report["non_claims"] == [
        "generated board project is for engineering review only",
        "not fabrication-ready",
        "not manufacturer-approved",
        "not production-ready",
    ]
    assert "fabrication-ready" not in set(report["non_claims"]) - {"not fabrication-ready"}
