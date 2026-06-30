"""Governed component schema v1 and validation reports.

The schema is intentionally stricter than the historical lightweight library
loader. It captures the metadata a professional autonomous electronics flow
needs before a component can be treated as reviewed: exact sourcing identity,
pin/footprint traceability, electrical limits, compliance, and provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComponentGovernanceSeverity(StrEnum):
    """Severity for governed component schema findings."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class GovernedPin(BaseModel):
    """One pin entry in the governed component schema."""

    model_config = ConfigDict(strict=False)

    name: str
    type: str = ""
    description: str = ""
    function: str = ""
    electrical_type: str = ""


class GovernedComponentV1(BaseModel):
    """Machine-readable governed component contract, schema version 1.0."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    id: str
    name: str
    category: str
    mpn: str
    manufacturer: str
    datasheet: str
    lifecycle: str
    package: str
    footprint: str
    pins: dict[str, GovernedPin]
    electrical_limits: dict[str, Any] = Field(default_factory=dict)
    sourcing: dict[str, Any] = Field(default_factory=dict)
    compliance: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ComponentGovernanceFinding(BaseModel):
    """One schema validation finding for one component."""

    component_id: str
    field: str
    severity: ComponentGovernanceSeverity
    message: str


class ComponentGovernanceValidation(BaseModel):
    """Validation result for one component against schema v1."""

    component_id: str
    schema_version: str = "1.0"
    valid: bool
    reviewed_ready: bool
    findings: list[ComponentGovernanceFinding] = Field(default_factory=list)
    coverage_score: float = 0.0


class ComponentGovernanceReport(BaseModel):
    """Machine-readable report for a library validation run."""

    schema_version: str = "1.0"
    component_count: int
    valid_count: int
    reviewed_ready_count: int
    error_count: int
    warning_count: int
    mean_coverage_score: float
    validations: list[ComponentGovernanceValidation]

    @property
    def valid(self) -> bool:
        return self.error_count == 0


@dataclass(frozen=True)
class GovernedComponentSchema:
    """Field policy for governed component schema v1."""

    required_identity_fields: tuple[str, ...] = ("id", "name", "category", "mpn", "manufacturer")
    required_traceability_fields: tuple[str, ...] = ("datasheet", "package", "footprint", "pins")
    required_governance_sections: tuple[str, ...] = (
        "electrical_limits",
        "sourcing",
        "compliance",
        "provenance",
    )

    @property
    def all_fields(self) -> tuple[str, ...]:
        return self.required_identity_fields + self.required_traceability_fields + self.required_governance_sections


SCHEMA_V1 = GovernedComponentSchema()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _field(spec: Any, name: str, default: Any = "") -> Any:
    return getattr(spec, name, default)


def _pin_map(raw_pins: dict[str, Any]) -> dict[str, GovernedPin]:
    pins: dict[str, GovernedPin] = {}
    for pin_name, pin_data in raw_pins.items():
        if isinstance(pin_data, dict):
            pins[str(pin_name)] = GovernedPin(name=str(pin_name), **pin_data)
        else:
            pins[str(pin_name)] = GovernedPin(name=str(pin_name), description=str(pin_data))
    return pins


def _derived_electrical_limits(spec: Any) -> dict[str, Any]:
    properties = _as_dict(_field(spec, "properties", {}))
    result = _as_dict(_field(spec, "electrical_limits", {})).copy()
    if _field(spec, "voltage_supply", "") and "voltage_supply" not in result:
        result["voltage_supply"] = _field(spec, "voltage_supply")
    for key in (
        "rated_power_w",
        "max_voltage_v",
        "voltage_rating_v",
        "current_rating_a",
        "frequency_mhz",
        "temperature_range",
    ):
        if key in properties and key not in result:
            result[key] = properties[key]
    return result


def governed_component_from_spec(spec: Any) -> GovernedComponentV1:
    """Convert a loader ComponentSpec-like object into governed schema v1."""
    properties = _as_dict(_field(spec, "properties", {}))
    sourcing = _as_dict(_field(spec, "sourcing", {})).copy()
    if _field(spec, "mpn", "") and "mpn" not in sourcing:
        sourcing["mpn"] = _field(spec, "mpn")
    if _field(spec, "manufacturer", "") and "manufacturer" not in sourcing:
        sourcing["manufacturer"] = _field(spec, "manufacturer")
    compliance = _as_dict(_field(spec, "compliance", {})).copy()
    if "rohs" in properties and "rohs" not in compliance:
        compliance["rohs"] = properties["rohs"]
    provenance = _as_dict(_field(spec, "provenance", {})).copy()
    if _field(spec, "datasheet", "") and "datasheet" not in provenance:
        provenance["datasheet"] = _field(spec, "datasheet")
    return GovernedComponentV1(
        id=_field(spec, "id"),
        name=_field(spec, "name"),
        category=_field(spec, "category"),
        mpn=_field(spec, "mpn", ""),
        manufacturer=_field(spec, "manufacturer", ""),
        datasheet=_field(spec, "datasheet", ""),
        lifecycle=_field(spec, "lifecycle", ""),
        package=_field(spec, "package", ""),
        footprint=_field(spec, "footprint", ""),
        pins=_pin_map(_as_dict(_field(spec, "pins", {}))),
        electrical_limits=_derived_electrical_limits(spec),
        sourcing=sourcing,
        compliance=compliance,
        provenance=provenance,
    )


def _has_value(value: Any) -> bool:
    return bool(value)


def validate_governed_component(
    spec: Any, *, schema: GovernedComponentSchema = SCHEMA_V1
) -> ComponentGovernanceValidation:
    """Validate one component against governed schema v1."""
    component = governed_component_from_spec(spec)
    findings: list[ComponentGovernanceFinding] = []
    populated = 0
    for field_name in schema.all_fields:
        value = getattr(component, field_name)
        if _has_value(value):
            populated += 1
            continue
        severity = (
            ComponentGovernanceSeverity.ERROR
            if field_name in schema.required_identity_fields + schema.required_traceability_fields
            else ComponentGovernanceSeverity.WARNING
        )
        findings.append(
            ComponentGovernanceFinding(
                component_id=component.id,
                field=field_name,
                severity=severity,
                message=f"governed component schema v1 requires {field_name}",
            )
        )
    errors = [finding for finding in findings if finding.severity == ComponentGovernanceSeverity.ERROR]
    warnings = [finding for finding in findings if finding.severity == ComponentGovernanceSeverity.WARNING]
    return ComponentGovernanceValidation(
        component_id=component.id,
        valid=not errors,
        reviewed_ready=not errors and not warnings,
        findings=findings,
        coverage_score=round(populated / len(schema.all_fields), 3),
    )


def validate_component_library(specs: dict[str, Any]) -> ComponentGovernanceReport:
    """Validate loaded component specs and return a deterministic schema report."""
    validations = [validate_governed_component(specs[key]) for key in sorted(specs)]
    error_count = sum(
        1 for row in validations for finding in row.findings if finding.severity == ComponentGovernanceSeverity.ERROR
    )
    warning_count = sum(
        1 for row in validations for finding in row.findings if finding.severity == ComponentGovernanceSeverity.WARNING
    )
    mean = round(sum(row.coverage_score for row in validations) / len(validations), 3) if validations else 0.0
    return ComponentGovernanceReport(
        component_count=len(validations),
        valid_count=sum(1 for row in validations if row.valid),
        reviewed_ready_count=sum(1 for row in validations if row.reviewed_ready),
        error_count=error_count,
        warning_count=warning_count,
        mean_coverage_score=mean,
        validations=validations,
    )


def write_component_governance_report(specs: dict[str, Any], output_path: str | Path) -> Path:
    """Write a machine-readable governed component schema report."""
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected governance report suffix: {out.suffix}")
    report = validate_component_library(specs)
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return resolved
