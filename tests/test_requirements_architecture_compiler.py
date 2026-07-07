from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from zaptrace.generation import (
    ArchitectureCompileStatus,
    ElectronicsArchitectureArtifact,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
    electronics_architecture_schema_json,
    minimal_electronics_architecture_example,
)


def test_compile_ready_esp32_usb_sensor_architecture() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )

    assert artifact.status == ArchitectureCompileStatus.READY
    assert artifact.design_name == "esp32_usb_temperature_sensor_architecture_v1"
    assert artifact.blocking_reasons == []
    assert artifact.human_review_required is True
    assert "not fabrication-ready" in " ".join(artifact.non_claims)

    requirement_ids = artifact.release_blocking_requirement_ids
    assert requirement_ids
    assert any(req.category == "power" for req in artifact.requirements)
    assert any(req.category == "interface" for req in artifact.requirements)
    assert {rail.net_name for rail in artifact.power_tree} >= {"VBUS", "VDD_3V3"}
    assert {interface.name for interface in artifact.interfaces} >= {"usb", "i2c"}
    assert any(interface.controlled_impedance for interface in artifact.interfaces if interface.name == "usb")

    coverage = artifact.requirement_coverage_matrix()
    for req_id in requirement_ids:
        assert coverage[req_id], f"missing architecture coverage for {req_id}"


def test_architecture_artifact_json_round_trip() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail"
    )

    payload = json.loads(electronics_architecture_artifact_json(artifact))
    loaded = ElectronicsArchitectureArtifact.model_validate(payload)

    assert loaded == artifact
    assert payload["status"] == "ready"
    assert payload["schema_version"] == "1.0"


def test_architecture_schema_contains_required_sections() -> None:
    schema = json.loads(electronics_architecture_schema_json())

    assert schema["title"] == "ElectronicsArchitectureArtifact"
    required = set(schema["required"])
    assert {"status", "design_name", "source_intent", "requirements"}.issubset(required)


def test_minimal_architecture_example_validates() -> None:
    payload = minimal_electronics_architecture_example()
    artifact = ElectronicsArchitectureArtifact.model_validate(payload)

    assert artifact.status == ArchitectureCompileStatus.READY
    assert artifact.design_name == "esp32_usb_temperature_sensor_architecture_v1"
    assert artifact.requirement_coverage_matrix()


def test_ambiguous_intent_blocks_for_clarification() -> None:
    artifact = compile_electronics_intent_to_architecture("make a small board")

    assert artifact.status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert artifact.blocking_reasons == ["intent is too vague to derive electronics architecture"]
    assert artifact.assumptions[0].confidence == "low"
    assert artifact.release_blocking_requirement_ids


def test_high_risk_intent_blocks_autonomous_generation() -> None:
    artifact = compile_electronics_intent_to_architecture("230V mains medical controller with sensor")

    assert artifact.status == ArchitectureCompileStatus.UNSAFE_BLOCKED
    assert artifact.blocking_reasons
    assert artifact.risks[0].severity == "critical"
    assert artifact.risks[0].human_review_required is True


def test_non_ready_architecture_requires_blocking_reasons() -> None:
    with pytest.raises(ValidationError, match="blocking_reasons"):
        ElectronicsArchitectureArtifact.model_validate(
            {
                "status": ArchitectureCompileStatus.NEEDS_CLARIFICATION,
                "design_name": "bad",
                "source_intent": "ambiguous",
                "requirements": [
                    {
                        "id": "REQ-FUNCTIONAL-001",
                        "text": "Clarify functional intent.",
                        "category": "functional",
                    }
                ],
            }
        )


def test_architecture_requires_fabrication_non_claim() -> None:
    payload = minimal_electronics_architecture_example()
    payload["non_claims"] = ["engineering review only"]

    with pytest.raises(ValidationError, match="not fabrication-ready"):
        ElectronicsArchitectureArtifact.model_validate(payload)
