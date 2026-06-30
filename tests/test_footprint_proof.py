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
