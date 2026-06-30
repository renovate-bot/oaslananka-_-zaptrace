from __future__ import annotations

import json

from zaptrace.proof import CheckDefinition, CheckResult, CheckStatus, ManifestModel, ProofManifest, ProofPack
from zaptrace.proof.manifest import CheckSeverity
from zaptrace.proof.signoff import AutonomousSignoffStatus


def _pack_with_results(results: list[CheckResult]) -> ProofPack:
    manifest = ProofManifest(
        name="SignoffSummary",
        design_path="design.yaml",
        model=ManifestModel(),
        checks=[result.check for result in results],
    )
    return ProofPack(manifest=manifest, results=results)


def test_report_json_includes_autonomous_pass_status() -> None:
    pack = _pack_with_results([CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)])

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert report["autonomous_signoff"]["blocking_checks"] == []
    assert "Autonomous status: autonomous-pass" in pack.summary


def test_report_json_includes_blocked_status_and_blocking_evidence() -> None:
    pack = _pack_with_results(
        [CheckResult(check=CheckDefinition(name="kicad-drc", type="drc"), status=CheckStatus.FAIL)]
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad-drc"]
    assert "Blocking evidence: kicad-drc" in pack.summary


def test_report_json_includes_human_review_required_status() -> None:
    pack = _pack_with_results(
        [
            CheckResult(
                check=CheckDefinition(name="rf-layout-risk", type="custom", severity=CheckSeverity.WARNING),
                status=CheckStatus.FAIL,
            )
        ]
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.HUMAN_REVIEW_REQUIRED
    assert report["autonomous_signoff"]["human_review_checks"] == ["rf-layout-risk"]
    assert "Human review: rf-layout-risk" in pack.summary


def test_manifest_stores_autonomous_signoff_decision() -> None:
    pack = _pack_with_results([CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)])

    pack.update_autonomous_signoff()

    assert pack.manifest.autonomous_signoff.status == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert pack.manifest.model_dump(mode="json")["autonomous_signoff"]["status"] == "autonomous-pass"


def test_requirements_coverage_blocks_autonomous_pass_when_incomplete() -> None:
    from zaptrace.proof.manifest import RequirementsCoverageEvidence

    manifest = ProofManifest(
        name="CoverageBlocked",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="abc123",
            fully_covered=False,
            fully_traced=False,
            requirement_count=2,
            untraced_artifact_count=1,
            message="requirements coverage has gaps",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["requirements-coverage"]
    assert "Blocking evidence: requirements-coverage" in pack.summary


def test_requirements_coverage_allows_pass_when_complete() -> None:
    from zaptrace.proof.manifest import RequirementsCoverageEvidence

    manifest = ProofManifest(
        name="CoveragePass",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="abc123",
            fully_covered=True,
            fully_traced=True,
            requirement_count=2,
            untraced_artifact_count=0,
            message="requirements coverage complete",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS
    assert report["autonomous_signoff"]["blocking_checks"] == []


def test_unconfirmed_high_risk_assumptions_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence

    manifest = ProofManifest(
        name="AssumptionsBlocked",
        design_path="design.yaml",
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="abc123",
            approved=False,
            assumption_count=2,
            unconfirmed_high_risk_count=1,
            message="requirements assumptions require confirmation",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["requirements-assumptions"]
    assert "Blocking evidence: requirements-assumptions" in pack.summary


def test_confirmed_assumptions_do_not_block_autonomous_pass() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence

    manifest = ProofManifest(
        name="AssumptionsPass",
        design_path="design.yaml",
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="abc123",
            approved=True,
            assumption_count=1,
            unconfirmed_high_risk_count=0,
            message="requirements assumptions confirmed",
        ),
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.AUTONOMOUS_PASS


def test_stable_id_ignores_runtime_requirements_and_assumptions_evidence() -> None:
    from zaptrace.proof.manifest import AssumptionsEvidence, RequirementsCoverageEvidence

    base_manifest = ProofManifest(name="StableRuntimeEvidence", design_path="design.yaml")
    with_runtime = ProofManifest(
        name="StableRuntimeEvidence",
        design_path="design.yaml",
        requirements_coverage=RequirementsCoverageEvidence(
            report_path="requirements_coverage.json",
            requirements_hash="hash-a",
            fully_covered=False,
            fully_traced=False,
            requirement_count=3,
            untraced_artifact_count=2,
            message="runtime coverage state",
        ),
        assumptions_evidence=AssumptionsEvidence(
            report_path="assumptions.json",
            requirements_hash="hash-b",
            approved=False,
            assumption_count=2,
            unconfirmed_high_risk_count=1,
            message="runtime assumptions state",
        ),
    )
    result = CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)

    assert (
        ProofPack(manifest=base_manifest, results=[result]).stable_id
        == ProofPack(
            manifest=with_runtime,
            results=[result],
        ).stable_id
    )


def test_failed_kicad_schematic_erc_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.kicad.oracle import KiCadErcResult

    erc = KiCadErcResult(
        available=True,
        success=False,
        message="1 ERC errors, 0 warnings",
        version="9.0.0",
        cli_path="/usr/bin/kicad-cli",
        command=["/usr/bin/kicad-cli", "sch", "erc", "design.kicad_sch"],
        exit_code=1,
        report_path="erc.json",
        errors=1,
        warnings=0,
    )
    manifest = ProofManifest(
        name="FailedSchematicErc",
        design_path="design.yaml",
        kicad_oracle=[erc.to_oracle_evidence()],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="erc", type="erc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:schematic_erc"]
    assert "Blocking evidence: kicad:schematic_erc" in pack.summary


def test_failed_kicad_pcb_drc_evidence_blocks_autonomous_pass() -> None:
    from zaptrace.kicad.oracle import KiCadDrcResult

    drc = KiCadDrcResult(
        available=True,
        success=False,
        message="1 DRC errors, 0 warnings",
        version="9.0.0",
        cli_path="/usr/bin/kicad-cli",
        command=["/usr/bin/kicad-cli", "pcb", "drc", "board.kicad_pcb"],
        exit_code=1,
        report_path="drc.json",
        errors=1,
        warnings=0,
    )
    manifest = ProofManifest(
        name="FailedPcbDrc",
        design_path="design.yaml",
        kicad_oracle=[drc.to_oracle_evidence()],
    )
    pack = ProofPack(
        manifest=manifest,
        results=[CheckResult(check=CheckDefinition(name="drc", type="drc"), status=CheckStatus.PASS)],
    )

    report = json.loads(pack.report_json())

    assert report["autonomous_signoff"]["status"] == AutonomousSignoffStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    assert report["autonomous_signoff"]["blocking_checks"] == ["kicad:pcb_drc"]
    assert "Blocking evidence: kicad:pcb_drc" in pack.summary
