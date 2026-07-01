"""Generate benchmark board-family fixture coverage evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.benchmark.fixtures import (  # noqa: E402
    BenchmarkFixtureCoverageReport,
    evaluate_fixture_coverage,
    fixture_coverage_json,
)


def render_markdown(report: BenchmarkFixtureCoverageReport) -> str:
    """Render a human-readable benchmark fixture coverage summary."""
    lines = ["# Benchmark Fixture Coverage", ""]
    lines.append(f"Complete families: {report.complete_family_count}/{report.family_count}")
    lines.append(f"Missing required artifacts: {report.missing_required_artifact_count}")
    lines.append("")
    lines.append("| Family | Status | Present required | Missing required |")
    lines.append("|--------|--------|------------------|------------------|")
    for family in report.families:
        status = "complete" if family.complete else "incomplete"
        lines.append(
            f"| `{family.family_id}` | `{status}` | "
            f"{family.present_required_artifact_count} | {family.missing_required_artifact_count} |"
        )
    lines.append("")
    lines.append("## Non-claims")
    lines.append("")
    for claim in report.non_claims:
        lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark fixture coverage evidence")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root to inspect")
    parser.add_argument("--output", type=Path, help="Write JSON coverage evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Write Markdown coverage summary to this path")
    parser.add_argument(
        "--min-complete-families",
        type=int,
        default=1,
        help="Minimum complete family fixture count required in strict mode",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if the minimum complete count is not met",
    )
    args = parser.parse_args(argv)

    report = evaluate_fixture_coverage(args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(fixture_coverage_json(report), encoding="utf-8")
    else:
        print(fixture_coverage_json(report), end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")

    if args.strict and report.complete_family_count < args.min_complete_families:
        print(
            f"benchmark fixture coverage below threshold: {report.complete_family_count} < {args.min_complete_families}"
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
