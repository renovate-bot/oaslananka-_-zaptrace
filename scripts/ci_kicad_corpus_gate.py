"""CI gate: KiCad project import corpus validation.

Imports each corpus KiCad project in ``tests/corpus/kicad/`` using the
hierarchical importer and asserts that:

1. Each project imports without errors (``error_count == 0``).
2. The mean net-identity score across all corpus projects is >= the
   ``NET_SCORE_THRESHOLD`` constant (default 0.90).

Exit codes:
    0  All corpus projects pass the gate.
    1  One or more projects failed to import, or mean net score is below
       threshold.

Usage::

    uv run python scripts/ci_kicad_corpus_gate.py

The script writes a JSON summary to stdout suitable for CI annotation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Gate configuration
# ---------------------------------------------------------------------------

NET_SCORE_THRESHOLD: float = 0.90
"""Minimum acceptable mean net-identity score across all corpus projects."""

CORPUS_DIR: Path = Path(__file__).parent.parent / "tests" / "corpus" / "kicad"


def _discover_projects(corpus_dir: Path) -> list[Path]:
    """Return a sorted list of corpus project root directories.

    Each directory must contain exactly one ``.kicad_pro`` or ``.kicad_sch``
    file to count as a project root.
    """
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
    """Import all corpus projects and evaluate gate criteria.

    Returns 0 on success, 1 on failure.
    """
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
    all_net_scores: list[float] = []
    failures: list[str] = []

    for project_dir in projects:
        project_name = project_dir.name
        try:
            result = import_kicad_project(project_dir)
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

        net_score = result.net_score
        error_count = result.error_count
        warning_count = result.warning_count
        all_net_scores.append(net_score)

        project_status = "pass" if error_count == 0 else "fail"
        if error_count > 0:
            failures.append(project_name)

        results.append(
            {
                "project": project_name,
                "status": project_status,
                "component_count": len(result.design.components),
                "net_count": len(result.design.nets),
                "sheet_count": len(result.sheets),
                "net_score": net_score,
                "error_count": error_count,
                "warning_count": warning_count,
                "findings": [f.to_dict() for f in result.findings],
            }
        )

    mean_net_score = sum(all_net_scores) / len(all_net_scores) if all_net_scores else 0.0
    gate_pass = not failures and mean_net_score >= NET_SCORE_THRESHOLD

    report = {
        "status": "pass" if gate_pass else "fail",
        "projects_evaluated": len(projects),
        "mean_net_score": round(mean_net_score, 4),
        "threshold": NET_SCORE_THRESHOLD,
        "failures": failures,
        "results": results,
    }

    print(json.dumps(report, indent=2))

    if not gate_pass:
        if failures:
            print(
                f"\n[FAIL] {len(failures)} project(s) had import errors: {failures}",
                file=sys.stderr,
            )
        if mean_net_score < NET_SCORE_THRESHOLD:
            print(
                f"\n[FAIL] Mean net score {mean_net_score:.4f} is below threshold {NET_SCORE_THRESHOLD}",
                file=sys.stderr,
            )
        return 1

    print(
        f"\n[PASS] {len(projects)} projects, mean net score {mean_net_score:.4f} >= {NET_SCORE_THRESHOLD}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_corpus_gate())
