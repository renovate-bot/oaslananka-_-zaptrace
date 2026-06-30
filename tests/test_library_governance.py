from __future__ import annotations

import json
from pathlib import Path

from zaptrace.library.governance import (
    ComponentGovernanceSeverity,
    governed_component_from_spec,
    validate_component_library,
    validate_governed_component,
    write_component_governance_report,
)
from zaptrace.library.loader import ComponentSpec, LibraryLoader


def _reviewed_spec(**overrides: object) -> ComponentSpec:
    data: dict[str, object] = {
        "id": "ldo-1",
        "name": "LDO 1",
        "category": "power",
        "manufacturer": "Acme Analog",
        "mpn": "ACME-LDO-1",
        "description": "reviewed regulator",
        "datasheet": "https://example.com/acme-ldo-1.pdf",
        "package": "SOT-23-5",
        "footprint": "Package_TO_SOT_SMD:SOT-23-5",
        "lifecycle": "active",
        "voltage_supply": "3.3",
        "pins": {
            "1": {"type": "input", "description": "VIN"},
            "2": {"type": "power", "description": "GND"},
            "5": {"type": "output", "description": "VOUT"},
        },
        "electrical_limits": {"max_voltage_v": 6.0, "current_rating_a": 0.3},
        "sourcing": {"authorized_distributors": ["Digi-Key"], "mpn": "ACME-LDO-1"},
        "compliance": {"rohs": True, "reach": True},
        "provenance": {"reviewed_by": "library-ci", "datasheet_sha256": "a" * 64},
    }
    data.update(overrides)
    return ComponentSpec(**data)  # type: ignore[arg-type]


def test_governed_component_schema_v1_contains_required_contract_fields() -> None:
    governed = governed_component_from_spec(_reviewed_spec())
    dumped = governed.model_dump(mode="json")

    for field in (
        "mpn",
        "manufacturer",
        "datasheet",
        "lifecycle",
        "package",
        "footprint",
        "pins",
        "electrical_limits",
        "sourcing",
        "compliance",
        "provenance",
    ):
        assert field in dumped
    assert dumped["schema_version"] == "1.0"
    assert dumped["pins"]["1"]["type"] == "input"


def test_reviewed_component_validates_ready() -> None:
    validation = validate_governed_component(_reviewed_spec())

    assert validation.valid is True
    assert validation.reviewed_ready is True
    assert validation.findings == []
    assert validation.coverage_score == 1.0


def test_missing_identity_or_traceability_is_error() -> None:
    validation = validate_governed_component(_reviewed_spec(datasheet="", footprint=""))

    assert validation.valid is False
    assert validation.reviewed_ready is False
    fields = {finding.field: finding.severity for finding in validation.findings}
    assert fields["datasheet"] == ComponentGovernanceSeverity.ERROR
    assert fields["footprint"] == ComponentGovernanceSeverity.ERROR


def test_missing_governance_sections_are_warnings_not_schema_errors() -> None:
    validation = validate_governed_component(
        _reviewed_spec(electrical_limits={}, sourcing={}, compliance={}, provenance={}, voltage_supply="")
    )

    assert validation.valid is True
    assert validation.reviewed_ready is False
    fields = {finding.field: finding.severity for finding in validation.findings}
    assert fields["electrical_limits"] == ComponentGovernanceSeverity.WARNING
    assert fields["compliance"] == ComponentGovernanceSeverity.WARNING
    assert "sourcing" not in fields  # derived from MPN/manufacturer
    assert "provenance" not in fields  # derived from datasheet URL


def test_validate_component_library_report_is_deterministic() -> None:
    specs = {"b": _reviewed_spec(id="b", mpn="B"), "a": _reviewed_spec(id="a", mpn="A", datasheet="")}

    report = validate_component_library(specs)

    assert report.component_count == 2
    assert report.valid_count == 1
    assert report.error_count == 1
    assert [row.component_id for row in report.validations] == ["a", "b"]


def test_loader_writes_machine_readable_governance_report(tmp_path: Path) -> None:
    spec = _reviewed_spec(id="part-1")
    report_path = write_component_governance_report({"part-1": spec}, tmp_path / "component-governance.json")

    data = json.loads(report_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["component_count"] == 1
    assert data["reviewed_ready_count"] == 1


def test_library_loader_exposes_governance_report(tmp_path: Path) -> None:
    root = tmp_path / "library"
    path = root / "power" / "ldo.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "id: ldo",
                "name: LDO",
                "category: power",
                "manufacturer: Acme",
                "mpn: ACME-LDO",
                "datasheet: https://example.com/ds.pdf",
                "package: SOT-23-5",
                "footprint: SOT-23-5",
                "pins:",
                "  '1': {type: input}",
                "electrical_limits: {max_voltage_v: 6}",
                "sourcing: {authorized_distributors: [Digi-Key]}",
                "compliance: {rohs: true}",
                "provenance: {reviewed_by: ci}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    loader = LibraryLoader(root)

    report = loader.governance_report()
    out = loader.write_governance_report(tmp_path / "report.json")

    assert report.component_count == 1
    assert report.reviewed_ready_count == 1
    assert json.loads(out.read_text(encoding="utf-8"))["valid_count"] == 1


def test_real_shipped_library_can_be_validated_against_schema_v1() -> None:
    loader = LibraryLoader()
    report = loader.governance_report()

    assert report.component_count >= 80
    assert report.error_count >= 0
    assert 0.0 <= report.mean_coverage_score <= 1.0
    assert len(report.validations) == report.component_count
