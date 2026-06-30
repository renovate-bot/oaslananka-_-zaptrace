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
