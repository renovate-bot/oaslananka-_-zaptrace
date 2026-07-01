"""Generate benchmark fixture integrity evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zaptrace.benchmark.integrity import (  # noqa: E402
    FixtureIntegrityReport,
    evaluate_fixture_integrity,
    fixture_integrity_json,
)


def render_markdown(report: FixtureIntegrityReport) -> str:
    """Render fixture integrity as a compact Markdown report."""
    lines = ["# Benchmark Fixture Integrity", ""]
    lines.append(f"Passed families: {report.passed_family_count}/{report.family_count}")
    lines.append(f"Failed checks: {report.failed_check_count}")
    lines.append("")
    lines.append("| Family | Status | Failed checks |")
    lines.append("|--------|--------|---------------|")
    for family in report.families:
        lines.append(f"| `{family.family_id}` | `{family.status}` | {family.failed_check_count} |")
    lines.append("")
    lines.append("## Non-claims")
    lines.append("")
    for claim in report.non_claims:
        lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark fixture integrity evidence")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root to inspect")
    parser.add_argument("--output", type=Path, help="Write JSON integrity evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Write Markdown integrity summary to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any integrity check fails")
    args = parser.parse_args(argv)

    report = evaluate_fixture_integrity(args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(fixture_integrity_json(report), encoding="utf-8")
    else:
        print(fixture_integrity_json(report), end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.strict and not report.passed:
        print(f"benchmark fixture integrity failed with {report.failed_check_count} failed check(s)")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
