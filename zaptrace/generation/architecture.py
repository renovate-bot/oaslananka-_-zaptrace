"""Requirements-to-architecture compiler for bounded electronics intents."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArchitectureCompileStatus(StrEnum):
    """Status emitted by the requirements-to-architecture compiler."""

    READY = "ready"
    NEEDS_CLARIFICATION = "needs-clarification"
    UNSAFE_BLOCKED = "unsafe-blocked"


class RequirementCategory(StrEnum):
    """Requirement categories used by the architecture artifact."""

    FUNCTIONAL = "functional"
    POWER = "power"
    INTERFACE = "interface"
    MECHANICAL = "mechanical"
    MANUFACTURING = "manufacturing"
    SAFETY = "safety"


class ArchitectureRequirement(BaseModel):
    """Traceable requirement derived from an electronics intent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    category: RequirementCategory
    source: str = Field(default="user-intent")
    release_blocking: bool = True


class ArchitectureAssumption(BaseModel):
    """Assumption that must be carried into proof packs and review."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = "medium"
    requires_confirmation: bool = True
    related_requirement_ids: list[str] = Field(default_factory=list)


class ArchitectureSubsystem(BaseModel):
    """Planned design subsystem."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["mcu", "power", "sensor", "interface", "protection", "mechanical", "generic"] = "generic"
    requirement_ids: list[str] = Field(default_factory=list)


class PowerRailPlan(BaseModel):
    """Planned rail or supply domain."""

    model_config = ConfigDict(extra="forbid")

    net_name: str = Field(min_length=1)
    nominal_voltage_v: float | None = Field(default=None, gt=0)
    max_current_a: float | None = Field(default=None, gt=0)
    source: str = Field(default="architecture-compiler")
    load_subsystems: list[str] = Field(default_factory=list)
    margin_target_pct: float = Field(default=20.0, ge=0)
    requirement_ids: list[str] = Field(default_factory=list)


class InterfacePlan(BaseModel):
    """Planned interface and associated nets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    role: str = Field(default="unspecified")
    nets: list[str] = Field(default_factory=list)
    controlled_impedance: bool = False
    requirement_ids: list[str] = Field(default_factory=list)

    @field_validator("nets")
    @classmethod
    def _nets_must_be_unique(cls, nets: list[str]) -> list[str]:
        if len(nets) != len(set(nets)):
            raise ValueError("interface nets must be unique")
        return nets


class ArchitectureConstraint(BaseModel):
    """Machine-checkable constraint derived from the architecture."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    domain: Literal["erc", "drc", "dfm", "layout", "simulation", "supply-chain", "review"]
    text: str = Field(min_length=1)
    evidence_required: bool = True
    release_blocking: bool = True
    requirement_ids: list[str] = Field(default_factory=list)


class ArchitectureRisk(BaseModel):
    """Risk-register entry for architecture review."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    mitigation: str = Field(min_length=1)
    evidence_required: bool = True
    human_review_required: bool = True
    requirement_ids: list[str] = Field(default_factory=list)


type AcceptanceMethod = Literal["erc", "drc", "simulation", "kicad-oracle", "dfm", "human-review"]


class ArchitectureAcceptanceTest(BaseModel):
    """Acceptance test planned from requirements."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    requirement_ids: list[str] = Field(min_length=1)
    method: AcceptanceMethod
    expected_result: str = Field(min_length=1)


class ElectronicsArchitectureArtifact(BaseModel):
    """Structured architecture artifact produced before schematic and PCB synthesis."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: ArchitectureCompileStatus
    design_name: str = Field(min_length=1)
    source_intent: str = Field(min_length=1)
    requirements: list[ArchitectureRequirement] = Field(min_length=1)
    assumptions: list[ArchitectureAssumption] = Field(default_factory=list)
    subsystems: list[ArchitectureSubsystem] = Field(default_factory=list)
    power_tree: list[PowerRailPlan] = Field(default_factory=list)
    interfaces: list[InterfacePlan] = Field(default_factory=list)
    constraints: list[ArchitectureConstraint] = Field(default_factory=list)
    risks: list[ArchitectureRisk] = Field(default_factory=list)
    acceptance_tests: list[ArchitectureAcceptanceTest] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "architecture artifact is for engineering review only",
            "not fabrication-ready",
            "not manufacturer-approved",
            "not production-ready",
        ],
        min_length=1,
    )

    @field_validator("non_claims")
    @classmethod
    def _must_keep_fabrication_non_claim(cls, claims: list[str]) -> list[str]:
        joined = " ".join(claims).lower()
        if "not fabrication-ready" not in joined:
            raise ValueError("non_claims must include 'not fabrication-ready'")
        return claims

    @model_validator(mode="after")
    def _validate_gate_semantics(self) -> ElectronicsArchitectureArtifact:
        if not any(req.release_blocking for req in self.requirements):
            raise ValueError("at least one release-blocking requirement is required")
        if self.status != ArchitectureCompileStatus.READY and not self.blocking_reasons:
            raise ValueError("non-ready architecture artifacts must include blocking_reasons")
        return self

    @property
    def requirement_ids(self) -> set[str]:
        """Return all declared requirement IDs."""
        return {req.id for req in self.requirements}

    @property
    def release_blocking_requirement_ids(self) -> set[str]:
        """Return release-blocking requirement IDs."""
        return {req.id for req in self.requirements if req.release_blocking}

    def requirement_coverage_matrix(self) -> dict[str, list[str]]:
        """Return artifact classes that reference each requirement ID."""
        matrix: dict[str, list[str]] = {req.id: [] for req in self.requirements}
        for subsystem in self.subsystems:
            for req_id in subsystem.requirement_ids:
                matrix.setdefault(req_id, []).append(f"subsystem:{subsystem.id}")
        for rail in self.power_tree:
            for req_id in rail.requirement_ids:
                matrix.setdefault(req_id, []).append(f"power:{rail.net_name}")
        for interface in self.interfaces:
            for req_id in interface.requirement_ids:
                matrix.setdefault(req_id, []).append(f"interface:{interface.name}")
        for constraint in self.constraints:
            for req_id in constraint.requirement_ids:
                matrix.setdefault(req_id, []).append(f"constraint:{constraint.id}")
        for test in self.acceptance_tests:
            for req_id in test.requirement_ids:
                matrix.setdefault(req_id, []).append(f"test:{test.id}")
        return {key: sorted(set(values)) for key, values in sorted(matrix.items())}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


_KEYWORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _words(intent: str) -> set[str]:
    return {word.lower() for word in _KEYWORD_RE.findall(intent)}


def _slug(text: str) -> str:
    words = _KEYWORD_RE.findall(text.lower())[:8]
    return "_".join(words) or "generated_architecture"


def _has_any(words: set[str], *candidates: str) -> bool:
    return any(candidate in words for candidate in candidates)


def _requirement(
    index: int,
    category: RequirementCategory,
    text: str,
    *,
    release_blocking: bool = True,
) -> ArchitectureRequirement:
    return ArchitectureRequirement(
        id=f"REQ-{category.value.upper()}-{index:03d}",
        text=text,
        category=category,
        release_blocking=release_blocking,
    )


def _acceptance_test(
    index: int,
    req_id: str,
    method: AcceptanceMethod,
    expected: str,
) -> ArchitectureAcceptanceTest:
    return ArchitectureAcceptanceTest(
        id=f"AT-{index:03d}",
        requirement_ids=[req_id],
        method=method,
        expected_result=expected,
    )


def _base_non_claims() -> list[str]:
    return [
        "architecture artifact is for engineering review only",
        "not fabrication-ready",
        "not manufacturer-approved",
        "not production-ready",
    ]


def compile_electronics_intent_to_architecture(
    intent: str,
    *,
    design_name: str | None = None,
) -> ElectronicsArchitectureArtifact:
    """Compile natural-language electronics intent into a structured architecture artifact.

    The compiler is intentionally deterministic and conservative. It extracts common
    electronics requirements and emits human-review gates when the prompt is vague,
    unsafe, or outside the bounded first implementation.
    """
    normalized = " ".join(intent.strip().split())
    if not normalized:
        raise ValueError("intent must not be empty")

    tokens = _words(normalized)
    inferred_design_name = design_name or _slug(normalized)
    requirements: list[ArchitectureRequirement] = []
    assumptions: list[ArchitectureAssumption] = []
    subsystems: list[ArchitectureSubsystem] = []
    power_tree: list[PowerRailPlan] = []
    interfaces: list[InterfacePlan] = []
    constraints: list[ArchitectureConstraint] = []
    risks: list[ArchitectureRisk] = []
    acceptance_tests: list[ArchitectureAcceptanceTest] = []
    blocking_reasons: list[str] = []

    unsafe = _has_any(tokens, "mains", "230v", "220v", "110v", "medical", "automotive", "airbag", "defibrillator")
    if unsafe:
        req = _requirement(
            1,
            RequirementCategory.SAFETY,
            "High-risk or regulated design intent requires qualified engineering review before generation.",
        )
        requirements.append(req)
        risks.append(
            ArchitectureRisk(
                id="RISK-SAFETY-001",
                domain="safety",
                description=(
                    "Intent includes high-risk voltage, regulated, medical, or automotive "
                    "language outside bounded autonomous generation scope."
                ),
                severity="critical",
                mitigation=(
                    "Block autonomous-pass and require a qualified engineer to define safety, "
                    "isolation, compliance, and validation requirements."
                ),
                requirement_ids=[req.id],
            )
        )
        blocking_reasons.append(
            "intent includes high-risk or regulated terms outside bounded autonomous generation scope"
        )
        return ElectronicsArchitectureArtifact(
            status=ArchitectureCompileStatus.UNSAFE_BLOCKED,
            design_name=inferred_design_name,
            source_intent=normalized,
            requirements=requirements,
            risks=risks,
            blocking_reasons=blocking_reasons,
            non_claims=_base_non_claims(),
        )

    feature_count = sum(
        [
            _has_any(tokens, "usb", "usb-c", "usbc"),
            _has_any(tokens, "esp32", "mcu", "microcontroller"),
            _has_any(tokens, "sensor", "temperature", "humidity", "imu"),
            _has_any(tokens, "i2c", "spi", "uart", "can"),
            _has_any(tokens, "battery", "lipo", "charger"),
            _has_any(tokens, "regulator", "buck", "ldo"),
        ]
    )
    if feature_count == 0:
        req = _requirement(
            1,
            RequirementCategory.FUNCTIONAL,
            (
                "Clarify the target circuit function, power source, core components, "
                "interfaces, and manufacturing assumptions."
            ),
        )
        requirements.append(req)
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-CLARIFY-001",
                text=(
                    "The prompt does not contain enough electronics-specific information to derive a safe architecture."
                ),
                confidence="low",
                related_requirement_ids=[req.id],
            )
        )
        blocking_reasons.append("intent is too vague to derive electronics architecture")
        return ElectronicsArchitectureArtifact(
            status=ArchitectureCompileStatus.NEEDS_CLARIFICATION,
            design_name=inferred_design_name,
            source_intent=normalized,
            requirements=requirements,
            assumptions=assumptions,
            blocking_reasons=blocking_reasons,
            non_claims=_base_non_claims(),
        )

    req_index = 1
    test_index = 1

    if _has_any(tokens, "esp32", "mcu", "microcontroller"):
        req = _requirement(
            req_index,
            RequirementCategory.FUNCTIONAL,
            "Provide a microcontroller subsystem with reset, boot, programming, and required support circuits.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-MCU", name="Microcontroller", kind="mcu", requirement_ids=[req.id])
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index, req.id, "erc", "MCU power, reset, boot, and programming nets pass ERC coverage."
            )
        )
        test_index += 1

    if _has_any(tokens, "usb", "usbc") or "usb-c" in normalized.lower():
        req = _requirement(
            req_index,
            RequirementCategory.POWER,
            "Provide USB-C 5 V input with protection and downstream regulation assumptions.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-USB", name="USB-C input and data", kind="interface", requirement_ids=[req.id]
            )
        )
        power_tree.append(
            PowerRailPlan(
                net_name="VBUS",
                nominal_voltage_v=5.0,
                max_current_a=0.5,
                load_subsystems=["SUBSYS-MCU"],
                requirement_ids=[req.id],
            )
        )
        interfaces.append(
            InterfacePlan(
                name="usb",
                protocol="usb2",
                role="device",
                nets=["USB_D_P", "USB_D_N"],
                controlled_impedance=True,
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-USB-001",
                domain="layout",
                text="USB D+/D- require short matched routing, continuous return path, and connector-side ESD review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index, req.id, "kicad-oracle", "USB nets are present and pass KiCad/ERC parity checks."
            )
        )
        test_index += 1

    if _has_any(tokens, "3v3", "3", "esp32", "sensor", "i2c"):
        req = _requirement(
            req_index, RequirementCategory.POWER, "Provide a 3.3 V logic rail with load margin for digital devices."
        )
        req_index += 1
        requirements.append(req)
        power_tree.append(
            PowerRailPlan(
                net_name="VDD_3V3",
                nominal_voltage_v=3.3,
                max_current_a=0.25,
                load_subsystems=["SUBSYS-MCU", "SUBSYS-SENSOR"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-PWR-001",
                domain="simulation",
                text="3.3 V rail margin and startup assumptions require analytical or simulation evidence.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index,
                req.id,
                "simulation",
                "3.3 V rail margin evidence is present or explicitly skipped with human review.",
            )
        )
        test_index += 1

    if _has_any(tokens, "battery", "lipo", "charger"):
        req = _requirement(
            req_index,
            RequirementCategory.POWER,
            "Provide battery input or charging subsystem with current, thermal, and safety review evidence.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(
                id="SUBSYS-BATTERY", name="Battery and charging", kind="power", requirement_ids=[req.id]
            )
        )
        power_tree.append(
            PowerRailPlan(
                net_name="VBAT",
                nominal_voltage_v=3.7,
                max_current_a=1.0,
                load_subsystems=["SUBSYS-MCU"],
                requirement_ids=[req.id],
            )
        )
        risks.append(
            ArchitectureRisk(
                id="RISK-BATTERY-001",
                domain="power",
                description="Battery charging and protection choices require datasheet-backed safety review.",
                severity="high",
                mitigation="Require charger IC datasheet evidence, protection constraints, and thermal/current review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(
                test_index,
                req.id,
                "human-review",
                "Battery safety choices are reviewed with datasheet and layout evidence.",
            )
        )
        test_index += 1

    if _has_any(tokens, "sensor", "temperature", "humidity", "imu"):
        req = _requirement(
            req_index,
            RequirementCategory.FUNCTIONAL,
            "Provide a sensor subsystem with power, decoupling, interface, and placement assumptions.",
        )
        req_index += 1
        requirements.append(req)
        subsystems.append(
            ArchitectureSubsystem(id="SUBSYS-SENSOR", name="Sensor", kind="sensor", requirement_ids=[req.id])
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "Sensor power and interface nets are connected and traceable.")
        )
        test_index += 1

    if _has_any(tokens, "i2c"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide I2C bus with SDA/SCL nets, pull-up evidence, and address-conflict review.",
        )
        req_index += 1
        requirements.append(req)
        interfaces.append(
            InterfacePlan(
                name="i2c", protocol="i2c", role="sensor-bus", nets=["I2C_SDA", "I2C_SCL"], requirement_ids=[req.id]
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-I2C-001",
                domain="erc",
                text="I2C SDA/SCL require pull-up evidence and address-conflict review.",
                requirement_ids=[req.id],
            )
        )
        acceptance_tests.append(
            _acceptance_test(test_index, req.id, "erc", "I2C pull-up and net connectivity evidence is present.")
        )
        test_index += 1

    if _has_any(tokens, "spi"):
        req = _requirement(
            req_index,
            RequirementCategory.INTERFACE,
            "Provide SPI bus with chip-select ownership and signal routing review.",
        )
        req_index += 1
        requirements.append(req)
        interfaces.append(
            InterfacePlan(
                name="spi",
                protocol="spi",
                role="peripheral-bus",
                nets=["SPI_MOSI", "SPI_MISO", "SPI_SCK", "SPI_CS"],
                requirement_ids=[req.id],
            )
        )
        constraints.append(
            ArchitectureConstraint(
                id="CONSTRAINT-SPI-001",
                domain="layout",
                text="SPI nets require length, return-path, and chip-select ownership review.",
                requirement_ids=[req.id],
            )
        )

    if not power_tree:
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-POWER-001",
                text=(
                    "Power source and voltage rails were not explicit enough; downstream "
                    "generation must request confirmation."
                ),
                confidence="low",
            )
        )
        blocking_reasons.append("power source or voltage rails are underspecified")

    if not interfaces:
        assumptions.append(
            ArchitectureAssumption(
                id="ASM-INTERFACE-001",
                text=(
                    "External communication interfaces were not explicit enough; downstream "
                    "generation must request confirmation."
                ),
                confidence="low",
            )
        )

    for req in requirements:
        constraints.append(
            ArchitectureConstraint(
                id=f"CONSTRAINT-TRACE-{req.id}",
                domain="review",
                text=(
                    f"Requirement {req.id} must remain traceable through schematic, PCB, "
                    "verification, and proof-pack artifacts."
                ),
                requirement_ids=[req.id],
            )
        )

    risks.append(
        ArchitectureRisk(
            id="RISK-REVIEW-001",
            domain="signoff",
            description="Generated architecture is a candidate plan and not a fabrication approval.",
            severity="medium",
            mitigation=(
                "Require proof-pack evidence and qualified human engineering review before fabrication decisions."
            ),
            requirement_ids=[requirements[0].id],
        )
    )

    status = ArchitectureCompileStatus.NEEDS_CLARIFICATION if blocking_reasons else ArchitectureCompileStatus.READY
    return ElectronicsArchitectureArtifact(
        status=status,
        design_name=inferred_design_name,
        source_intent=normalized,
        requirements=requirements,
        assumptions=assumptions,
        subsystems=subsystems,
        power_tree=power_tree,
        interfaces=interfaces,
        constraints=constraints,
        risks=risks,
        acceptance_tests=acceptance_tests,
        blocking_reasons=blocking_reasons,
        non_claims=_base_non_claims(),
    )


def electronics_architecture_artifact_json(artifact: ElectronicsArchitectureArtifact) -> str:
    """Serialize an architecture artifact as stable JSON."""
    return json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def electronics_architecture_schema_json() -> str:
    """Return the architecture artifact JSON schema."""
    return json.dumps(ElectronicsArchitectureArtifact.model_json_schema(), indent=2, sort_keys=True) + "\n"


def minimal_electronics_architecture_example() -> dict[str, Any]:
    """Return a minimal ready architecture example for fixture tests and docs."""
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )
    return artifact.model_dump(mode="json")
