"""Generate strict generated-board release-gate evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.ee.footprint_proof import build_footprint_proof, validate_risky_package_policy  # noqa: E402
from zaptrace.generation import (  # noqa: E402
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)
from zaptrace.generation.compiler import CompiledDesignIR  # noqa: E402
from zaptrace.generation.evidence import GeneratedProjectEvidenceBundle  # noqa: E402


def _artifact_hashes(bundle: GeneratedProjectEvidenceBundle) -> dict[str, str]:
    return {artifact.kind: artifact.sha256 for artifact in bundle.artifacts}


def _artifact_paths(bundle: GeneratedProjectEvidenceBundle) -> dict[str, str]:
    return {artifact.kind: artifact.path for artifact in bundle.artifacts}


def _evaluate_risky_package_policy(
    compiled: CompiledDesignIR,
    *,
    reviewed: bool,
    approval_id: str,
) -> dict[str, Any]:
    checked_components = 0
    risky_components: list[dict[str, Any]] = []
    blocked_components: list[dict[str, Any]] = []
    for component in compiled.design.components.values():
        footprint_def = getattr(component, "footprint_def", None)
        if footprint_def is None:
            continue
        checked_components += 1
        package_id = component.footprint or component.type or component.ref
        footprint_name = component.footprint or package_id
        proof = build_footprint_proof(package_id, footprint_def, footprint_name=footprint_name)
        policy = validate_risky_package_policy(proof, reviewed=reviewed, approval_id=approval_id)
        if not policy.risky:
            continue
        row = {
            "component_id": component.id,
            "component_ref": component.ref,
            "package_id": proof.package_id,
            "family": policy.family,
            "blocked": policy.blocked,
            "diagnostic_codes": [item.code for item in policy.diagnostics],
        }
        risky_components.append(row)
        if policy.blocked:
            blocked_components.append(row)
    return {
        "reviewed": reviewed,
        "approval_id": approval_id,
        "checked_component_count": checked_components,
        "risky_component_count": len(risky_components),
        "blocked_component_count": len(blocked_components),
        "risky_components": risky_components,
        "blocked_components": blocked_components,
    }


def build_report(
    artifact_dir: Path,
    *,
    risky_package_reviewed: bool = False,
    risky_package_approval_id: str = "",
) -> dict[str, Any]:
    """Run the generated-board pipeline and return release-gate evidence."""
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    compiled = compile_intent_to_design_ir(intent)
    result = generate_project_evidence_bundle(intent, compiled, artifact_dir)
    bundle = result.bundle
    risky_package_policy = _evaluate_risky_package_policy(
        compiled,
        reviewed=risky_package_reviewed,
        approval_id=risky_package_approval_id,
    )
    expected_artifact_kinds = [
        "intent",
        "design-ir-compile-report",
        "kicad-project",
        "kicad-schematic",
        "schematic-generation-report",
        "kicad-pcb",
        "pcb-generation-report",
        "manufacturing-export-manifest",
        "review-handoff",
    ]
    artifact_hashes = _artifact_hashes(bundle)
    missing_kinds = sorted(set(expected_artifact_kinds) - set(artifact_hashes))
    malformed_hash_kinds = sorted(kind for kind, value in artifact_hashes.items() if len(value) != 64)
    non_claims_text = " ".join(bundle.non_claims).lower()
    missing_non_claims = [] if "not fabrication-ready" in non_claims_text else ["not fabrication-ready"]
    blocking_reasons = list(bundle.blocking_reasons)
    if missing_kinds:
        blocking_reasons.append(f"missing artifact kind(s): {', '.join(missing_kinds)}")
    if malformed_hash_kinds:
        blocking_reasons.append(f"malformed SHA-256 hash for kind(s): {', '.join(malformed_hash_kinds)}")
    if missing_non_claims:
        blocking_reasons.append(f"missing non-claim(s): {', '.join(missing_non_claims)}")
    if risky_package_policy["blocked_component_count"]:
        refs = ", ".join(row["component_ref"] for row in risky_package_policy["blocked_components"])
        blocking_reasons.append(f"risky-package policy blocked component(s): {refs}")

    passed = bundle.passed and not blocking_reasons
    return {
        "schema_version": "1.0",
        "gate_id": "generated-board-release-gate-v1",
        "family_id": bundle.family_id,
        "design_name": bundle.design_name,
        "passed": passed,
        "generated_project_evidence_passed": bundle.passed,
        "artifact_count": bundle.artifact_count,
        "required_artifact_count": bundle.required_artifact_count,
        "missing_required_artifact_count": bundle.missing_required_artifact_count,
        "expected_artifact_kinds": expected_artifact_kinds,
        "artifact_paths": _artifact_paths(bundle),
        "artifact_hashes": artifact_hashes,
        "requirement_trace_count": bundle.requirement_trace_count,
        "provenance_record_count": bundle.provenance_record_count,
        "schematic_passed": bundle.schematic_passed,
        "pcb_passed": bundle.pcb_passed,
        "manufacturing_manifest_present": bundle.manufacturing_manifest_present,
        "review_handoff_present": bundle.review_handoff_present,
        "non_claims": bundle.non_claims,
        "blocking_reasons": blocking_reasons,
        "risky_package_policy": risky_package_policy,
        "non_claims_enforced": True,
        "path_policy": (
            "generated artifacts are written to a working directory; "
            "this report stores relative paths and stable content hashes"
        ),
    }


def report_json(report: dict[str, Any]) -> str:
    """Serialize a release-gate report as stable JSON."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    """Render generated-board release-gate evidence as Markdown."""
    lines = ["# Generated Board Release Gate", ""]
    lines.append(f"Gate: `{report['gate_id']}`")
    lines.append(f"Family: `{report['family_id']}`")
    lines.append(f"Design: `{report['design_name']}`")
    lines.append(f"Passed: `{str(report['passed']).lower()}`")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Artifacts: {report['artifact_count']}")
    lines.append(f"- Required artifacts: {report['required_artifact_count']}")
    lines.append(f"- Missing required artifacts: {report['missing_required_artifact_count']}")
    lines.append(f"- Requirement traces: {report['requirement_trace_count']}")
    lines.append(f"- Provenance records: {report['provenance_record_count']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append(f"- Schematic generation passed: `{str(report['schematic_passed']).lower()}`")
    lines.append(f"- PCB generation passed: `{str(report['pcb_passed']).lower()}`")
    lines.append(f"- Manufacturing manifest present: `{str(report['manufacturing_manifest_present']).lower()}`")
    lines.append(f"- Review handoff present: `{str(report['review_handoff_present']).lower()}`")
    lines.append("")
    lines.append("## Artifact hashes")
    lines.append("")
    lines.append("| Kind | SHA-256 |")
    lines.append("|------|---------|")
    for kind in report["expected_artifact_kinds"]:
        lines.append(f"| `{kind}` | `{report['artifact_hashes'].get(kind, '')}` |")
    lines.append("")
    lines.append("## Non-claims")
    lines.append("")
    for claim in report["non_claims"]:
        lines.append(f"- {claim}")
    lines.append("")
    lines.append("## Blocking reasons")
    lines.append("")
    if report["blocking_reasons"]:
        for reason in report["blocking_reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Risky package policy")
    lines.append("")
    policy = report.get("risky_package_policy", {})
    lines.append(f"- Checked components: {policy.get('checked_component_count', 0)}")
    lines.append(f"- Risky components: {policy.get('risky_component_count', 0)}")
    lines.append(f"- Blocked components: {policy.get('blocked_component_count', 0)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate strict generated-board release-gate evidence")
    parser.add_argument("--artifact-dir", type=Path, default=Path(".generated/generated-board-release-gate"))
    parser.add_argument("--output", type=Path, help="Write JSON release-gate evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Write Markdown release-gate summary to this path")
    parser.add_argument(
        "--risky-package-reviewed",
        action="store_true",
        help="Treat risky packages as human-reviewed for policy evaluation",
    )
    parser.add_argument(
        "--risky-package-approval-id",
        default="",
        help="Approval identifier for risky-package policy exceptions",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero if the release gate does not pass")
    args = parser.parse_args(argv)

    report = build_report(
        args.artifact_dir,
        risky_package_reviewed=args.risky_package_reviewed,
        risky_package_approval_id=args.risky_package_approval_id,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json(report), encoding="utf-8")
    else:
        print(report_json(report), end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.strict and not report["passed"]:
        print("generated-board release gate failed")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
