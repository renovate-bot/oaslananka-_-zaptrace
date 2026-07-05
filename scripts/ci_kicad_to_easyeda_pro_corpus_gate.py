"""CI gate: KiCad → EasyEDA Pro conversion corpus validation.

Converts each corpus KiCad project in ``tests/corpus/kicad/`` to EasyEDA Pro
format using the conversion pipeline (import → write → re-read) and asserts:

1. Each project converts without import errors (``error_count == 0``).
2. The mean overall Jaccard score (component + net) across all corpus projects
   is >= ``SCORE_THRESHOLD`` (default 0.75).

Exit codes:
    0  All corpus projects pass the gate.
    1  One or more projects failed to convert, or mean score is below threshold.

Usage::

    uv run python scripts/ci_kicad_to_easyeda_pro_corpus_gate.py

The script writes a JSON summary to stdout suitable for CI annotation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Gate configuration
# ---------------------------------------------------------------------------

SCORE_THRESHOLD: float = 0.75
"""Minimum acceptable mean Jaccard score across all corpus projects."""

CORPUS_DIR: Path = Path(__file__).parent.parent / "tests" / "corpus" / "kicad"


def _discover_projects(corpus_dir: Path) -> list[Path]:
    """Return a sorted list of corpus project root directories."""
    projects: list[Path] = []
    for entry in sorted(corpus_dir.iterdir()):
        if not entry.is_dir():
            continue
        has_pro = any(entry.glob("*.kicad_pro"))
        has_sch = any(entry.glob("*.kicad_sch"))
        if has_pro or has_sch:
            projects.append(entry)
    return projects


def _run_corpus_gate() -> int:
    """Convert all corpus projects and evaluate gate criteria.

    Returns 0 on success, 1 on failure.
    """
    from zaptrace.eda.easyeda_pro import compute_easyeda_write_fidelity, write_easyeda_pro_zip
    from zaptrace.kicad.project_importer import import_kicad_project

    if not CORPUS_DIR.exists():
        print(json.dumps({"status": "error", "message": f"Corpus directory not found: {CORPUS_DIR}"}))
        return 1

    projects = _discover_projects(CORPUS_DIR)
    if len(projects) < 3:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": f"Expected >= 3 corpus projects, found {len(projects)} in {CORPUS_DIR}",
                }
            )
        )
        return 1

    results: list[dict] = []
    all_scores: list[float] = []
    failures: list[str] = []

    for project_dir in projects:
        project_name = project_dir.name
        try:
            kicad_result = import_kicad_project(project_dir)
        except Exception as exc:
            failures.append(project_name)
            results.append(
                {
                    "project": project_name,
                    "status": "import_error",
                    "error": str(exc),
                }
            )
            continue

        if kicad_result.error_count > 0:
            failures.append(project_name)
            results.append(
                {
                    "project": project_name,
                    "status": "fail",
                    "reason": f"{kicad_result.error_count} import errors",
                    "findings": [f.to_dict() for f in kicad_result.findings],
                }
            )
            continue

        try:
            fidelity = compute_easyeda_write_fidelity(kicad_result.design, project_name=project_name)
        except Exception as exc:
            failures.append(project_name)
            results.append(
                {
                    "project": project_name,
                    "status": "write_error",
                    "error": str(exc),
                }
            )
            continue

        # Artifact hash
        zip_bytes, _ = write_easyeda_pro_zip(kicad_result.design, project_name=project_name)
        artifact_hash = hashlib.sha256(zip_bytes).hexdigest()

        overall = fidelity["overall_score"]
        all_scores.append(overall)

        results.append(
            {
                "project": project_name,
                "status": "pass",
                "kicad_net_score": kicad_result.net_score,
                "component_jaccard": fidelity["component_jaccard"],
                "net_jaccard": fidelity["net_jaccard"],
                "overall_score": overall,
                "artifact_sha256": artifact_hash,
                "zip_size_bytes": len(zip_bytes),
                "write_degradation_accepted": fidelity["degradation_report"].get("accepted", False),
                "roundtrip_errors": fidelity["roundtrip_degradation_count"],
            }
        )

    mean_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
    gate_pass = not failures and mean_score >= SCORE_THRESHOLD

    report = {
        "status": "pass" if gate_pass else "fail",
        "projects_evaluated": len(projects),
        "mean_overall_score": round(mean_score, 4),
        "threshold": SCORE_THRESHOLD,
        "failures": failures,
        "results": results,
    }

    print(json.dumps(report, indent=2))

    if not gate_pass:
        if failures:
            print(
                f"\n[FAIL] {len(failures)} project(s) failed: {failures}",
                file=sys.stderr,
            )
        if mean_score < SCORE_THRESHOLD:
            print(
                f"\n[FAIL] Mean score {mean_score:.4f} is below threshold {SCORE_THRESHOLD}",
                file=sys.stderr,
            )
        return 1

    print(
        f"\n[PASS] {len(projects)} projects, mean score {mean_score:.4f} >= {SCORE_THRESHOLD}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_corpus_gate())
