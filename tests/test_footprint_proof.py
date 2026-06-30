from __future__ import annotations

import json
from pathlib import Path

from zaptrace.ee.footprint_proof import (
    FootprintSourceProvenance,
    FootprintSourceType,
    build_footprint_proof,
    file_sha256,
    write_footprint_proof,
)
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint
from zaptrace.ee.footprints import footprint_qfn, footprint_sot


def test_generated_footprint_proof_schema_contains_required_evidence() -> None:
    fp = footprint_sot("SOT-23")
    assert fp is not None

    proof = build_footprint_proof("SOT-23", fp, expected_pin_count=3)

    assert proof.schema_version == "1.0"
    assert proof.package_id == "SOT-23"
    assert proof.source.source_type == FootprintSourceType.GENERATED
    assert proof.pad_count == 3
    assert proof.pin_count == 3
    assert proof.pin_map == {"1": "1", "2": "2", "3": "3"}
    assert proof.courtyard_mm != (0.0, 0.0)
    assert proof.paste_enabled_pad_count == 3
    assert proof.paste_disabled_pad_count == 0
    assert proof.pin1.present is True
    assert proof.pin1.pad_id == "1"


def test_qfn_footprint_proof_records_thermal_pad_and_pin_map() -> None:
    fp = footprint_qfn("QFN-16")
    assert fp is not None

    proof = build_footprint_proof("QFN-16", fp, expected_pin_count=16)

    assert proof.pad_count == 17
    assert proof.pin_count == 16
    assert proof.thermal_pads == ["0"]
    assert proof.pin_map["1"] == "1"


def test_vendored_footprint_proof_records_source_hash() -> None:
    name = "BME280-LGA8"
    filename = VENDOR_FOOTPRINTS[name]
    path = Path("data/footprints/vendor") / filename
    fp = resolve_vendored_footprint(name)
    assert fp is not None

    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name=name,
        source_path=str(path),
        source_sha256=file_sha256(path),
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(name, fp, footprint_name=name, source=source, expected_pin_count=8)

    assert proof.source.source_type == FootprintSourceType.VENDORED
    assert proof.source.source_sha256 == file_sha256(path)
    assert proof.pad_count == 8
    assert proof.pin_count == 8
    assert proof.pin1.present is True


def test_write_footprint_proof(tmp_path: Path) -> None:
    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp)

    out = write_footprint_proof(proof, tmp_path / "footprint_proof.json")
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["package_id"] == "SOT-23"
    assert data["pads"][0]["solder_mask"] is True


def test_sample_fixture_matches_schema() -> None:
    data = json.loads(Path("tests/fixtures/footprints/sot23_footprint_proof.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["package_id"] == "SOT-23"
    assert data["pin1"]["present"] is True


def test_footprint_validator_passes_valid_generated_proof() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proof

    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp, expected_pin_count=3)

    report = validate_footprint_proof(proof, expected_pins={"1", "2", "3"})

    assert report.blocked is False
    assert report.error_count == 0
    assert report.diagnostics == []


def test_footprint_validator_fails_pad_pin_count_mismatch() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proof

    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp, expected_pin_count=4)

    report = validate_footprint_proof(proof)

    assert report.blocked is True
    assert any(item.code == "pad-pin-count-mismatch" for item in report.diagnostics)


def test_footprint_validator_fails_pin_name_mismatch() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proof

    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp, expected_pin_count=3, pin_map={"VIN": "1", "GND": "2", "VOUT": "3"})

    report = validate_footprint_proof(proof, expected_pins={"1", "2", "3"})

    assert report.blocked is True
    diag = next(item for item in report.diagnostics if item.code == "pin-name-mismatch")
    assert "VIN" in diag.observed
    assert "1" in diag.expected


def test_footprint_validator_fails_missing_pad_reference() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proof

    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp, expected_pin_count=3, pin_map={"1": "1", "2": "2", "3": "99"})

    report = validate_footprint_proof(proof)

    assert report.blocked is True
    assert any(item.code == "pin-map-pad-missing" and "99" in item.observed for item in report.diagnostics)


def test_footprint_validator_handles_qfn_thermal_pad() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proof

    fp = footprint_qfn("QFN-16")
    assert fp is not None
    proof = build_footprint_proof("QFN-16", fp, expected_pin_count=16)

    report = validate_footprint_proof(proof)

    assert report.blocked is False
    assert proof.pad_count == 17
    assert proof.pin_count == 16
    assert "0" not in proof.pin_map


def test_aggregate_footprint_validation_report() -> None:
    from zaptrace.ee.footprint_proof import validate_footprint_proofs

    fp = footprint_sot("SOT-23")
    assert fp is not None
    good = build_footprint_proof("SOT-23", fp, expected_pin_count=3)
    bad = build_footprint_proof("SOT-23-bad", fp, expected_pin_count=4)

    report = validate_footprint_proofs([good, bad])

    assert report.proof_count == 2
    assert report.blocked is True
    assert report.error_count >= 1


def test_risky_package_classifier() -> None:
    from zaptrace.ee.footprint_proof import classify_risky_package

    assert classify_risky_package("QFN-32") == "QFN"
    assert classify_risky_package("BME280-LGA8") == "LGA"
    assert classify_risky_package("USB-C-16P-SMD") == "USB-C"
    assert classify_risky_package("RJ45-8P8C-SHIELDED") == "RJ45"
    assert classify_risky_package("SOT-23") == ""


def test_unreviewed_risky_package_blocks_policy() -> None:
    from zaptrace.ee.footprint_proof import validate_risky_package_policy

    fp = footprint_qfn("QFN-16")
    assert fp is not None
    proof = build_footprint_proof("QFN-16", fp, expected_pin_count=16)

    result = validate_risky_package_policy(proof)

    assert result.risky is True
    assert result.blocked is True
    assert result.family == "QFN"
    assert any(item.code == "unreviewed-risky-package" for item in result.diagnostics)
    assert "human-reviewed footprint proof" in result.required_evidence


def test_reviewed_risky_package_with_provenance_passes_policy() -> None:
    from zaptrace.ee.footprint_proof import validate_risky_package_policy

    name = "BME280-LGA8"
    filename = VENDOR_FOOTPRINTS[name]
    path = Path("data/footprints/vendor") / filename
    fp = resolve_vendored_footprint(name)
    assert fp is not None
    source = FootprintSourceProvenance(
        source_type=FootprintSourceType.VENDORED,
        source_name=name,
        source_path=str(path),
        source_sha256=file_sha256(path),
        attribution="data/footprints/vendor/ATTRIBUTION.md",
    )
    proof = build_footprint_proof(name, fp, source=source, expected_pin_count=8)

    result = validate_risky_package_policy(proof, reviewed=True, approval_id="FP-REVIEW-1")

    assert result.risky is True
    assert result.blocked is False
    assert result.approval_id == "FP-REVIEW-1"


def test_non_risky_package_does_not_require_review() -> None:
    from zaptrace.ee.footprint_proof import validate_risky_package_policy

    fp = footprint_sot("SOT-23")
    assert fp is not None
    proof = build_footprint_proof("SOT-23", fp)

    result = validate_risky_package_policy(proof)

    assert result.risky is False
    assert result.blocked is False
