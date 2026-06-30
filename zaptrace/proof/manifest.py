"""Proof Pack manifest — defines what a proof pack validates.

Schema v1.0 includes:
  - Input record (source type, checksums)
  - Environment metadata (Python, OS, tool versions)
  - Artifact records (path, kind, SHA-256 hash)
  - Check records (source, status, severity, summary)
  - Limitations list

See docs/strategy/proof-pack-spec.md for the full specification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .signoff import AutonomousSignoffDecision, AutonomousSignoffPolicy


class CheckCategory(StrEnum):
    """Categories of proof checks."""

    DRC = "drc"
    ERC = "erc"
    ROUTING = "routing"
    FOOTPRINT = "footprint"
    SIGNAL_INTEGRITY = "signal_integrity"
    THERMAL = "thermal"
    MANUFACTURING = "manufacturing"
    SPICE = "spice"
    CUSTOM = "custom"


class CheckSeverity(StrEnum):
    """Severity of a check."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CheckSource(StrEnum):
    """Source of a validation check."""

    ZAPTRACE = "zaptrace"
    KICAD = "kicad"
    FAB_PROFILE = "fab_profile"
    EXTERNAL = "external"


class CheckStatus(StrEnum):
    """Result status of a single check."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"


class CheckDefinition(BaseModel):
    """Definition of a single proof check."""

    name: str = Field(description="Unique check name")
    description: str = Field(default="", description="Human-readable description")
    category: CheckCategory = Field(default=CheckCategory.CUSTOM)
    severity: CheckSeverity = Field(default=CheckSeverity.ERROR)

    # Check type and parameters
    type: str = Field(description="Check type: drc, erc, routed, footprint_exists, net_connected, clearance, custom")
    params: dict[str, Any] = Field(default_factory=dict)

    # Expected outcome
    expected: str = Field(
        default="pass",
        description="Expected result: 'pass', 'fail', or count threshold",
    )
    expected_count: int | None = Field(
        default=None,
        description="Expected number of violations (0 for clean)",
    )

    # Tagging for filtered runs
    tags: list[str] = Field(default_factory=list)


class ManifestModel(BaseModel):
    """Model-level constraints for the design."""

    min_clearance_mm: float = Field(default=0.15, ge=0)
    min_trace_width_mm: float = Field(default=0.15, ge=0)
    min_annular_ring_mm: float = Field(default=0.05, ge=0)
    max_board_size_mm: tuple[float, float] | None = Field(default=None)
    min_board_size_mm: tuple[float, float] | None = Field(default=None)
    max_layer_count: int = Field(default=2, ge=1)
    allowed_layer_counts: list[int] = Field(default_factory=lambda: [1, 2, 4])


# ---------------------------------------------------------------------------
# v1 evidence records
# ---------------------------------------------------------------------------


class InputRecord(BaseModel):
    """Record of the design input that produced this proof pack."""

    source_type: str = Field(default="file", description="Type of input source: file, intent, api")
    filename: str = Field(default="", description="Original input filename if applicable")
    checksum_sha256: str | None = Field(default=None, description="SHA-256 hex digest of the input file")
    normalized_intent_checksum_sha256: str | None = Field(
        default=None, description="SHA-256 of normalized intent if synthesis was used"
    )


class EnvironmentRecord(BaseModel):
    """Runtime environment snapshot for reproducibility."""

    zaptrace_version: str = Field(default="", description="ZapTrace version")
    python_version: str = Field(default="", description="Python version string")
    platform: str = Field(default="", description="Platform identifier (e.g. 'Linux-6.2-x86_64')")
    os: str = Field(default="", description="OS name (e.g. 'Linux', 'Windows', 'Darwin')")
    tool_versions: dict[str, str] = Field(
        default_factory=dict,
        description="External tool versions captured at runtime (e.g. {'kicad-cli': '8.0.0'})",
    )


class ArtifactRecord(BaseModel):
    """Record of a generated artifact in the proof pack."""

    path: str = Field(description="Relative path of the artifact within the proof pack")
    kind: str = Field(description="Artifact kind: gerber, excellon, bom, kicad, netlist, report, other")
    sha256: str | None = Field(default=None, description="SHA-256 hex digest of the artifact contents")
    size_bytes: int = Field(default=0, description="File size in bytes")


class KiCadOracleEvidence(BaseModel):
    """Structured KiCad oracle evidence stored in a proof-pack manifest."""

    check: str = Field(description="Oracle check name, such as erc, drc, or export_smoke")
    status: str = Field(description="Oracle result: passed, failed, or skipped")
    version: str = Field(default="", description="Detected kicad-cli version")
    cli_path: str = Field(default="", description="Detected kicad-cli executable path")
    command: list[str] = Field(default_factory=list, description="Executed command, if any")
    exit_code: int | None = Field(default=None, description="Process exit code, if a command ran")
    report_path: str | None = Field(default=None, description="Path to detailed oracle report artifact, if any")
    errors: int = Field(default=0, ge=0, description="Parsed error count")
    warnings: int = Field(default=0, ge=0, description="Parsed warning count")
    message: str = Field(default="", description="Human-readable outcome summary")
    skip_reason: str = Field(default="", description="Explicit reason when status is skipped")
    approval_id: str = Field(default="", description="Human approval/waiver identifier, if waived")
    waiver_reason: str = Field(default="", description="Human-readable waiver rationale, if waived")


class BomProvenanceEvidence(BaseModel):
    """Structured BOM intelligence provenance stored in a proof-pack manifest."""

    provider: str = Field(description="BOM intelligence provider name")
    cache_policy: str = Field(
        default="",
        description="Provider cache/offline policy used for this run",
    )
    generated_at: str = Field(default="", description="Timestamp for the BOM risk report")
    report_path: str | None = Field(
        default=None,
        description="Path to detailed BOM risk report artifact",
    )
    highest_risk: str = Field(default="unknown", description="Highest observed BOM risk level")
    blocked: bool = Field(default=False, description="Whether BOM risk blocks release acceptance")
    cache_age_hours: float | None = Field(
        default=None,
        ge=0,
        description="Oldest cache age in the report",
    )
    unresolved_required_parts: int = Field(
        default=0,
        ge=0,
        description="Required parts not resolved by provider",
    )
    obsolete_required_parts: int = Field(
        default=0,
        ge=0,
        description="Required parts marked obsolete",
    )
    message: str = Field(default="", description="Human-readable BOM provenance summary")


class ManufacturingProofEvidence(BaseModel):
    """Structured manufacturing evidence stored in a proof-pack manifest."""

    fab_profile: str = Field(default="", description="Selected fabrication profile")
    report_path: str | None = Field(default=None, description="Path to detailed manufacturing evidence report")
    blocked: bool = Field(default=False, description="Whether manufacturing evidence blocks release acceptance")
    artifact_count: int = Field(default=0, ge=0, description="Number of manufacturing artifacts recorded")
    validation_count: int = Field(default=0, ge=0, description="Number of validations recorded")
    gerber_smoke_status: str = Field(default="unknown", description="Aggregate Gerber smoke validation status")
    excellon_smoke_status: str = Field(default="unknown", description="Aggregate Excellon smoke validation status")
    odbpp_status: str = Field(default="not-attached", description="ODB++ evidence status")
    ipc2581_status: str = Field(default="not-attached", description="IPC-2581 evidence status")
    message: str = Field(default="", description="Human-readable manufacturing evidence summary")


class AssumptionsEvidence(BaseModel):
    """Structured assumptions evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to assumptions.json")
    requirements_hash: str = Field(description="Hash of the frozen requirements contract")
    approved: bool = Field(description="Whether all required assumptions are confirmed")
    assumption_count: int = Field(default=0, ge=0, description="Number of assumptions in the artifact")
    unconfirmed_high_risk_count: int = Field(
        default=0,
        ge=0,
        description="Number of high-risk assumptions that still lack confirmation",
    )
    message: str = Field(default="", description="Human-readable assumptions summary")


class ComponentMetadataEvidence(BaseModel):
    """Structured component metadata gate evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to component metadata gate JSON report")
    valid: bool = Field(description="Whether critical component metadata passed the gate")
    component_count: int = Field(default=0, ge=0, description="Number of components inspected")
    critical_issue_count: int = Field(default=0, ge=0, description="Blocking metadata issue count")
    warning_count: int = Field(default=0, ge=0, description="Non-blocking metadata warning count")
    message: str = Field(default="", description="Human-readable component metadata summary")


class NetlistParityEvidence(BaseModel):
    """Structured netlist parity evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to netlist parity JSON report")
    check: str = Field(default="ir_to_kicad_schematic_netlist", description="Parity check name")
    passed: bool = Field(description="Whether the compared netlists match")
    missing_net_count: int = Field(default=0, ge=0, description="Nets missing from KiCad evidence")
    extra_net_count: int = Field(default=0, ge=0, description="Nets unexpectedly present in KiCad evidence")
    pin_mismatch_count: int = Field(default=0, ge=0, description="Nets with pin-level connectivity mismatch")
    message: str = Field(default="", description="Human-readable parity summary")


class RequirementsCoverageEvidence(BaseModel):
    """Structured requirements coverage evidence stored in a proof-pack manifest."""

    report_path: str = Field(description="Path to requirements_coverage.json")
    requirements_hash: str = Field(description="Hash of the frozen requirements contract")
    fully_covered: bool = Field(description="Whether stated requirements are covered and artifacts are traced")
    fully_traced: bool = Field(description="Whether generated artifacts have requirement IDs")
    requirement_count: int = Field(default=0, ge=0, description="Number of requirement IDs in the report")
    untraced_artifact_count: int = Field(default=0, ge=0, description="Artifact rows without requirement trace IDs")
    message: str = Field(default="", description="Human-readable coverage summary")


class ManufacturingExportEvidence(BaseModel):
    """Structured manufacturing export log stored in a proof-pack manifest."""

    backend: str = Field(description="Export backend, such as zaptrace, kicad-cli, or external")
    tool_version: str = Field(default="", description="Exporter or external tool version")
    command: list[str] = Field(default_factory=list, description="Command/config entry point used for export")
    artifact_kinds: list[str] = Field(
        default_factory=list,
        description="Generated or attached artifact kinds: gerber, drill, bom, pick_and_place, odbpp, ipc2581",
    )
    report_path: str | None = Field(default=None, description="Path to detailed manufacturing export log JSON")
    blocked: bool = Field(default=False, description="Whether unsupported export paths block release")
    warnings: list[str] = Field(default_factory=list, description="Warnings emitted during export")
    unsupported: list[str] = Field(
        default_factory=list,
        description="Unsupported paths or variants that were not hidden",
    )


class CheckRecord(BaseModel):
    """Record of a validation check result in the proof pack."""

    name: str = Field(description="Check name")
    source: str = Field(default="zaptrace", description="Check source: zaptrace, kicad, fab_profile, external")
    status: str = Field(description="Result status: pass, warning, fail, skipped")
    severity: str = Field(default="error", description="Check severity: info, warning, error, critical")
    summary: str = Field(default="", description="Human-readable summary of the check outcome")
    details_path: str | None = Field(default=None, description="Path to detailed JSON report, if any")


# ---------------------------------------------------------------------------
# Main manifest
# ---------------------------------------------------------------------------


class AgentDecisionRecord(BaseModel):
    """A single agent or human decision captured in the Proof Pack.

    Enables post-hoc review of *why* a component was chosen, a topology was
    selected, or a trade-off was made — not just *what* was generated.
    """

    model_config = ConfigDict(strict=False)

    decision_id: str = Field(description="Unique decision identifier")
    actor: str = Field(description="Agent name or human identifier that made the decision")
    decision_type: str = Field(
        description="Category: 'component_selection', 'topology', 'constraint', 'waiver', 'human_approval'"
    )
    summary: str = Field(description="One-line summary of what was decided")
    rationale: str = Field(default="", description="Detailed explanation of why this decision was made")
    alternatives_considered: list[str] = Field(
        default_factory=list, description="Other options that were evaluated and rejected"
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Artifact IDs, datasheet URLs, or requirement IDs that support this decision",
    )
    timestamp: str | None = Field(default=None, description="ISO-8601 timestamp")


class ProofManifest(BaseModel):
    """Complete proof pack manifest (proof.yaml content)."""

    version: str = Field(default="1.0", description="Proof pack format version")
    name: str = Field(description="Proof pack name")
    description: str = Field(default="")

    # Design to validate
    design_path: str = Field(description="Path to the design YAML file")

    # Constraints
    model: ManifestModel = Field(default_factory=ManifestModel)

    # Checks
    checks: list[CheckDefinition] = Field(
        default_factory=list,
        description="List of checks to run",
    )

    # Reference files (golden outputs)
    references: dict[str, str] = Field(
        default_factory=dict,
        description="Map of output file -> reference file path",
    )

    # Metadata
    author: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    requires: list[str] = Field(
        default_factory=list,
        description="Required ZapTrace version or features",
    )

    # --- v1 evidence fields ---
    input_record: InputRecord = Field(default_factory=InputRecord, description="Input source evidence")
    environment: EnvironmentRecord = Field(
        default_factory=EnvironmentRecord, description="Runtime environment snapshot"
    )
    artifacts: list[ArtifactRecord] = Field(default_factory=list, description="Generated artifact records")
    check_records: list[CheckRecord] = Field(default_factory=list, description="Validation check result records")
    kicad_oracle: list[KiCadOracleEvidence] = Field(
        default_factory=list,
        description="KiCad oracle pass/fail/skip evidence metadata",
    )
    requires_kicad_oracle: bool = Field(
        default=False,
        description="Whether missing/skipped KiCad oracle evidence blocks autonomous sign-off",
    )
    bom_provenance: list[BomProvenanceEvidence] = Field(
        default_factory=list,
        description="BOM provider provenance, cache age, and risk summary evidence",
    )
    manufacturing_evidence: list[ManufacturingProofEvidence] = Field(
        default_factory=list,
        description="Manufacturing artifact, smoke-validation, and fab-profile evidence metadata",
    )
    manufacturing_exports: list[ManufacturingExportEvidence] = Field(
        default_factory=list,
        description="Manufacturing export logs with artifact kinds, tool versions, warnings, and unsupported paths",
    )
    kicad_schematic_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="IR-to-KiCad schematic netlist parity evidence metadata",
    )
    kicad_pcb_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="KiCad schematic-to-PCB netlist parity evidence metadata",
    )
    ipc_d356_parity: NetlistParityEvidence | None = Field(
        default=None,
        description="IPC-D-356 manufacturing netlist parity evidence metadata",
    )
    component_metadata: ComponentMetadataEvidence | None = Field(
        default=None,
        description="Component metadata validator/gate evidence metadata",
    )

    requirements_coverage: RequirementsCoverageEvidence | None = Field(
        default=None,
        description="Requirements coverage and traceability evidence metadata",
    )
    assumptions_evidence: AssumptionsEvidence | None = Field(
        default=None,
        description="Assumptions artifact metadata and approval state",
    )

    autonomous_signoff: AutonomousSignoffDecision = Field(
        default_factory=lambda: AutonomousSignoffPolicy().evaluate([]),
        description="Conservative autonomous sign-off decision derived from proof evidence",
    )
    final_state_hash: str = Field(default="", description="Final approved design state hash")
    transaction_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Transaction history evidence for the final state",
    )

    # --- v2 evidence fields: decision & evidence graph ---
    captured_intent: str = Field(
        default="",
        description="Original natural-language design intent verbatim, before normalization",
    )
    agent_decisions: list[AgentDecisionRecord] = Field(
        default_factory=list,
        description="Agent and human decisions captured during the design process",
    )

    limitations: list[str] = Field(
        default_factory=lambda: [
            "Human engineer review is required before fabrication.",
            "ZapTrace is pre-1.0 software — outputs are experimental.",
            "Proof Pack is evidence, not a fabrication guarantee.",
            "KiCad oracle results are external validation, not absolute correctness.",
            "Fab profiles are constraints, not manufacturer approval.",
        ],
        description="List of limitations and warnings accompanying this proof pack",
    )
