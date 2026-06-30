"""Synthesis → Proof Pack: an auditable verification bundle for a synthesized board.

Connects the from-scratch composition synthesizer to the proof-pack system so a
one-sentence intent yields not just a netlist but a portable, hash-stamped record
of *what was built, why, and how it verifies*: the routed design, every synthesis
decision (component, topology, value — with rationale and confidence), and the
ERC/DRC results captured as accepted baselines, plus the runtime environment.

The pack is evidence, not a fabrication certificate — the manifest's limitations
say so, mirroring the honest hand-off of :mod:`zaptrace.synthesis.fab`. The DRC
and ERC checks record the design's measured violation counts as the accepted
baseline: re-running the pack reproduces it, and a change that makes the design
worse fails the pack, so it doubles as a regression guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from zaptrace.core.parser import design_to_dict
from zaptrace.proof import (
    ArtifactRecord,
    AssumptionsEvidence,
    CheckDefinition,
    InputRecord,
    ProofManifest,
    ProofPack,
    ProofRunner,
    RequirementsCoverageEvidence,
    capture_environment,
    hash_file,
)
from zaptrace.proof.checker import CheckResult, CheckStatus
from zaptrace.proof.manifest import AgentDecisionRecord, CheckCategory, CheckRecord
from zaptrace.proof.pack import hash_bytes
from zaptrace.synthesis.fab import route_synthesized_design
from zaptrace.synthesis.requirements import (
    parse_requirements,
    requirements_assumption_report,
    requirements_coverage_report,
)

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.explain import SynthesisDecisionLog

# CheckResult statuses map onto the manifest's record vocabulary; an errored
# check is recorded as a failure (it did not pass) so the bundle never hides it.
_STATUS_TO_RECORD: dict[CheckStatus, str] = {
    CheckStatus.PASS: "pass",
    CheckStatus.FAIL: "fail",
    CheckStatus.ERROR: "fail",
    CheckStatus.SKIP: "skipped",
}


def _baseline_checks(design: Design) -> list[CheckDefinition]:
    """Standard checks for a synthesized board, with ERC/DRC baselines snapshotted.

    The board is run through ERC and DRC once so the accepted violation count is
    captured as ``expected_count``: the pack then passes at this baseline and
    fails only if a later change increases the count.
    """
    from zaptrace.ee.drc.engine import DRCEngine
    from zaptrace.erc.runner import ERCRunner

    erc_count = len(ERCRunner().run(design).violations)
    drc_count = len(DRCEngine().run(design).violations)
    return [
        CheckDefinition(
            name="erc",
            type="erc",
            category=CheckCategory.ERC,
            description="Electrical rule check; accepted violation baseline captured at synthesis",
            expected_count=erc_count,
        ),
        CheckDefinition(
            name="drc",
            type="drc",
            category=CheckCategory.DRC,
            description="Design rule check; accepted violation baseline captured at synthesis",
            expected_count=drc_count,
        ),
        CheckDefinition(
            name="footprints",
            type="footprint_exists",
            category=CheckCategory.FOOTPRINT,
            description="Every component has an assigned footprint",
        ),
    ]


def _decision_records(log: SynthesisDecisionLog) -> list[AgentDecisionRecord]:
    """Map the synthesis decision log into auditable agent-decision records."""
    records: list[AgentDecisionRecord] = []
    for i, d in enumerate(log.decisions, 1):
        summary = f"{d.parameter}: {d.value}".strip(": ") or d.category
        records.append(
            AgentDecisionRecord(
                decision_id=f"SYN-{i:03d}",
                actor="zaptrace-synthesis",
                decision_type=d.category,
                summary=summary,
                rationale=d.rationale,
                evidence_refs=[d.calculator] if d.calculator else [],
            )
        )
    return records


def _check_records(results: list[CheckResult]) -> list[CheckRecord]:
    return [
        CheckRecord(
            name=r.check.name,
            source="zaptrace",
            status=_STATUS_TO_RECORD.get(r.status, "fail"),
            severity=r.check.severity.value,
            summary=r.message,
        )
        for r in results
    ]


def generate_synthesis_proof(
    intent: str,
    output_dir: str | Path,
    *,
    name: str = "SynthesizedBoard",
) -> ProofPack:
    """Synthesize a board from *intent* and emit an auditable proof pack in *output_dir*.

    Writes ``design.yaml`` (the routed design, hashed), ``requirements_coverage.json``
    (requirement ID traceability), ``assumptions.json`` (explicit unresolved
    assumptions), ``proof.yaml`` (the manifest with synthesis
    decisions, input/environment provenance, and check records), and ``report.json``
    (the check results). Returns the completed
    :class:`~zaptrace.proof.ProofPack`.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    design, synth = route_synthesized_design(intent, name=name)

    # The routed design is the artifact the pack verifies; serialize it losslessly
    # so the bundle is portable and re-verifiable, then hash it for the manifest.
    design_yaml = out_dir / "design.yaml"
    design_yaml.write_text(yaml.safe_dump(design_to_dict(design), sort_keys=False), encoding="utf-8")

    checks = _baseline_checks(design)
    results = ProofRunner(design).run_checks(checks)
    parsed_requirements = parse_requirements(intent)
    coverage_report = requirements_coverage_report(
        parsed_requirements,
        design=design,
        checks=checks,
        exports=["design.yaml", "proof.yaml", "report.json", "assumptions.json"],
    )
    coverage_path = out_dir / "requirements_coverage.json"
    coverage_path.write_text(json.dumps(coverage_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assumptions_report = requirements_assumption_report(parsed_requirements)
    assumptions_path = out_dir / "assumptions.json"
    assumptions_path.write_text(json.dumps(assumptions_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = ProofManifest(
        name=f"{name} synthesis proof",
        description=f"Auditable verification of the board synthesized from: {intent}",
        design_path="design.yaml",
        checks=checks,
        author="zaptrace-synthesis",
        tags=["synthesis", "auto-generated"],
        captured_intent=intent,
        input_record=InputRecord(
            source_type="intent",
            normalized_intent_checksum_sha256=hash_bytes(intent.strip().lower().encode("utf-8")),
        ),
        environment=capture_environment(),
        agent_decisions=_decision_records(synth["decision_log"]),
        check_records=_check_records(results),
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash=str(assumptions_report["requirements_hash"]),
            approved=bool(assumptions_report["approved"]),
            assumption_count=len(assumptions_report["assumptions"]),
            unconfirmed_high_risk_count=int(assumptions_report["unconfirmed_high_risk_count"]),
            message=(
                "requirements assumptions confirmed"
                if assumptions_report["approved"]
                else "requirements assumptions require confirmation"
            ),
        ),
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash=str(coverage_report["requirements_hash"]),
            fully_covered=bool(coverage_report["fully_covered"]),
            fully_traced=bool(coverage_report["fully_traced"]),
            requirement_count=len(coverage_report["requirements"]),
            untraced_artifact_count=len(coverage_report["untraced_artifacts"]),
            message=(
                "requirements coverage complete"
                if coverage_report["fully_covered"]
                else "requirements coverage has gaps or untraced artifacts"
            ),
        ),
        artifacts=[
            ArtifactRecord(
                path="design.yaml",
                kind="netlist",
                sha256=hash_file(design_yaml),
                size_bytes=design_yaml.stat().st_size,
            ),
            ArtifactRecord(
                path="requirements_coverage.json",
                kind="report",
                sha256=hash_file(coverage_path),
                size_bytes=coverage_path.stat().st_size,
            ),
            ArtifactRecord(
                path="assumptions.json",
                kind="report",
                sha256=hash_file(assumptions_path),
                size_bytes=assumptions_path.stat().st_size,
            ),
        ],
    )

    pack = ProofPack(manifest=manifest, base_path=out_dir, results=results)
    pack.update_autonomous_signoff()
    (out_dir / "proof.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    (out_dir / "report.json").write_text(pack.report_json(), encoding="utf-8")
    return pack
