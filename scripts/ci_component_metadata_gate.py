"""Component metadata gate for governed library schema v1.

The gate fails when critical metadata errors exceed the configured budget. The
budget lets the current library debt remain visible while preventing regressions
until the library is fully reviewed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zaptrace.library.governance import ComponentGovernanceReport
from zaptrace.library.loader import LIBRARY_ROOT, LibraryLoader


def _markdown(summary: dict[str, object]) -> str:
    status = "blocked" if summary["blocked"] else "passed"
    return "\n".join(
        [
            "# Component Metadata Gate",
            "",
            f"Status: **{status}**",
            "",
            f"Components: `{summary['component_count']}`",
            f"Schema-valid: `{summary['valid_count']}`",
            f"Reviewed-ready: `{summary['reviewed_ready_count']}`",
            f"Errors: `{summary['error_count']}` / budget `{summary['max_errors']}`",
            f"Warnings: `{summary['warning_count']}` / budget `{summary['max_warnings']}`",
            f"Mean coverage: `{summary['mean_coverage_score']}`",
            "",
            "This gate is evidence only and does not claim manufacturer approval.",
            "",
        ]
    )


def build_gate_summary(
    report: ComponentGovernanceReport,
    *,
    max_errors: int,
    max_warnings: int,
) -> dict[str, object]:
    error_count = report.error_count
    warning_count = report.warning_count
    blocked = error_count > max_errors or warning_count > max_warnings
    return {
        "schema_version": "1.0",
        "gate": "component-metadata",
        "blocked": blocked,
        "component_count": report.component_count,
        "valid_count": report.valid_count,
        "reviewed_ready_count": report.reviewed_ready_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "max_errors": max_errors,
        "max_warnings": max_warnings,
        "mean_coverage_score": report.mean_coverage_score,
        "report": report.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate governed component metadata and enforce a CI budget")
    parser.add_argument("--library-root", type=Path, default=LIBRARY_ROOT)
    parser.add_argument("--max-errors", type=int, default=0, help="Allowed schema error budget")
    parser.add_argument("--max-warnings", type=int, default=0, help="Allowed warning budget")
    parser.add_argument("--output", type=Path, help="Write machine-readable JSON gate evidence")
    parser.add_argument("--markdown", type=Path, help="Append Markdown gate summary")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when the gate is blocked")
    args = parser.parse_args(argv)

    report = LibraryLoader(args.library_root).governance_report()
    summary = build_gate_summary(report, max_errors=args.max_errors, max_warnings=args.max_warnings)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(_markdown(summary))
    if summary["blocked"]:
        print(
            "Component metadata gate FAILED: "
            f"errors={summary['error_count']}/{summary['max_errors']} "
            f"warnings={summary['warning_count']}/{summary['max_warnings']}",
            file=sys.stderr,
        )
        return 1 if args.strict else 0
    print(
        "Component metadata gate PASSED: "
        f"errors={summary['error_count']}/{summary['max_errors']} "
        f"warnings={summary['warning_count']}/{summary['max_warnings']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
