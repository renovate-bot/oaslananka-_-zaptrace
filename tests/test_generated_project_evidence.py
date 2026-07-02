from __future__ import annotations

import json

from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    generated_project_evidence_bundle_json,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)


def _intent_and_compiled():
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    return intent, compile_intent_to_design_ir(intent)


def test_generate_project_evidence_bundle_emits_required_artifacts(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()

    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    assert result.bundle_path.exists()
    assert result.schematic.schematic_path.exists()
    assert result.pcb.pcb_path.exists()
    assert result.bundle.passed is True
    assert result.bundle.family_id == "esp32_usb_sensor"
    assert result.bundle.artifact_count == 9
    assert result.bundle.required_artifact_count == 9
    assert result.bundle.missing_required_artifact_count == 0
    assert result.bundle.requirement_trace_count == 2
    assert result.bundle.provenance_record_count == 1
    assert result.bundle.schematic_passed is True
    assert result.bundle.pcb_passed is True
    assert result.bundle.manufacturing_manifest_present is True
    assert result.bundle.review_handoff_present is True
    assert result.bundle.blocking_reasons == []
    assert "not fabrication-ready" in " ".join(result.bundle.non_claims)

    artifact_kinds = {artifact.kind for artifact in result.bundle.artifacts}
    assert artifact_kinds == {
        "intent",
        "design-ir-compile-report",
        "kicad-project",
        "kicad-schematic",
        "schematic-generation-report",
        "kicad-pcb",
        "pcb-generation-report",
        "manufacturing-export-manifest",
        "review-handoff",
    }
    for artifact in result.bundle.artifacts:
        assert (tmp_path / artifact.path).is_file()
        assert artifact.sha256
        assert artifact.size_bytes > 0


def test_generated_project_evidence_bundle_json_round_trip(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    payload = json.loads(generated_project_evidence_bundle_json(result.bundle))

    assert payload["schema_version"] == "1.0"
    assert payload["passed"] is True
    assert payload["design_name"] == "esp32_usb_sensor_generated_v1"
    assert payload["artifact_count"] == 9


def test_generated_project_evidence_bundle_hashes_are_stable(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    first = generate_project_evidence_bundle(intent, compiled, tmp_path / "first")
    second = generate_project_evidence_bundle(intent, compiled, tmp_path / "second")

    first_hashes = {artifact.kind: artifact.sha256 for artifact in first.bundle.artifacts}
    second_hashes = {artifact.kind: artifact.sha256 for artifact in second.bundle.artifacts}

    assert first_hashes == second_hashes


def test_generated_project_evidence_writes_manufacturing_and_review_handoff(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    generate_project_evidence_bundle(intent, compiled, tmp_path)

    manifest = json.loads((tmp_path / "exports/manifest.json").read_text(encoding="utf-8"))
    handoff = json.loads((tmp_path / "review/handoff.json").read_text(encoding="utf-8"))

    assert manifest["artifact_kind"] == "generated-manufacturing-export-manifest"
    assert "not fabrication-ready" in manifest["non_claims"]
    assert handoff["status"] == "human-review-required"
    assert "KiCad ERC/DRC oracle evidence" in handoff["required_review_items"]


def test_generated_project_evidence_bundle_file_matches_returned_model(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    payload = json.loads(result.bundle_path.read_text(encoding="utf-8"))

    assert payload == result.bundle.model_dump(mode="json")
