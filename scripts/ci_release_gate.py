"""Build a machine-readable v0.2.3 release-gate summary.

The script is intentionally small and CI-friendly. GitHub Actions can pass job
results as ``--gate name=result`` pairs; the script normalizes them into the
same vocabulary used by the v0.2.3 gate policy:

- pass
- fail
- skip-approved
- skip-unapproved
- warn

It writes JSON evidence and, optionally, a Markdown summary for
``GITHUB_STEP_SUMMARY``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PASS = "pass"
FAIL = "fail"
SKIP_APPROVED = "skip-approved"
SKIP_UNAPPROVED = "skip-unapproved"
WARN = "warn"

_BLOCKING = {FAIL, SKIP_UNAPPROVED}
_VALID = {PASS, FAIL, SKIP_APPROVED, SKIP_UNAPPROVED, WARN}

_CI_RESULT_MAP = {
    "success": PASS,
    "pass": PASS,
    "passed": PASS,
    "failure": FAIL,
    "failed": FAIL,
    "fail": FAIL,
    "cancelled": FAIL,
    "canceled": FAIL,
    "timed_out": FAIL,
    "timed-out": FAIL,
    "action_required": FAIL,
    "startup_failure": FAIL,
    "skipped": SKIP_APPROVED,
    "skip-approved": SKIP_APPROVED,
    "skip_unapproved": SKIP_UNAPPROVED,
    "skip-unapproved": SKIP_UNAPPROVED,
    "neutral": WARN,
    "warn": WARN,
    "warning": WARN,
}


@dataclass(frozen=True)
class GateRecord:
    name: str
    status: str
    raw_result: str
    reason: str = ""
    required: bool = True

    @property
    def blocks_release(self) -> bool:
        return self.required and self.status in _BLOCKING


def normalize_status(raw_result: str) -> str:
    """Normalize a CI/native result into the ZapTrace release-gate vocabulary."""
    key = raw_result.strip().lower()
    return _CI_RESULT_MAP.get(key, WARN)


def parse_name_value(value: str, *, option: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{option} must use name=value format: {value!r}")
    name, raw = value.split("=", 1)
    name = name.strip()
    raw = raw.strip()
    if not name or not raw:
        raise ValueError(f"{option} must include non-empty name and value: {value!r}")
    return name, raw


def build_records(gates: list[str], skip_reasons: list[str]) -> list[GateRecord]:
    reasons = dict(parse_name_value(item, option="--skip-reason") for item in skip_reasons)
    records: list[GateRecord] = []
    for item in gates:
        name, raw_result = parse_name_value(item, option="--gate")
        status = normalize_status(raw_result)
        reason = reasons.get(name, "")
        if status == SKIP_APPROVED and not reason:
            status = SKIP_UNAPPROVED
            reason = "missing approved skip reason"
        if status not in _VALID:
            status = WARN
        records.append(GateRecord(name=name, raw_result=raw_result, status=status, reason=reason))
    return records


def require_external_oracles(
    records: list[GateRecord],
    required_oracles: list[str],
    skip_reasons: list[str],
) -> list[GateRecord]:
    """Add blocking records for required external oracles that are absent.

    External EDA oracles must be explicitly present in the release-gate
    evidence. A missing oracle is a release blocker unless the same gate has an
    approved skip reason. This keeps tool absence and workflow path filtering
    visible instead of silently passing release summaries.
    """
    if not required_oracles:
        return records

    reasons = dict(parse_name_value(item, option="--skip-reason") for item in skip_reasons)
    existing = {record.name for record in records}
    out = list(records)
    for name in required_oracles:
        if name in existing:
            continue
        reason = reasons.get(name, "required external oracle evidence missing")
        status = SKIP_APPROVED if name in reasons else SKIP_UNAPPROVED
        out.append(GateRecord(name=name, raw_result="missing", status=status, reason=reason))
    return out


def render_markdown(records: list[GateRecord]) -> str:
    blocked = [record for record in records if record.blocks_release]
    lines = ["# ZapTrace v0.2.3 Release Gate Summary", ""]
    lines.append(f"Generated: {datetime.now(UTC).isoformat()}")
    lines.append("")
    lines.append("| Gate | Status | Blocks Release | Reason | Raw Result |")
    lines.append("|------|--------|----------------|--------|------------|")
    for record in records:
        lines.append(
            f"| `{record.name}` | `{record.status}` | {'yes' if record.blocks_release else 'no'} | "
            f"{record.reason or '-'} | `{record.raw_result}` |"
        )
    lines.append("")
    if blocked:
        lines.append(f"**Release blocked:** {len(blocked)} blocking gate(s).")
        for record in blocked:
            lines.append(f"- `{record.name}`: `{record.status}` ({record.reason or record.raw_result})")
    else:
        lines.append("**Release gate summary:** no blocking gates in this run.")
    lines.append("")
    lines.append(
        "This summary is evidence only. It does not claim fabrication readiness, manufacturer approval, "
        "or no-human-review correctness."
    )
    return "\n".join(lines) + "\n"


def build_summary(records: list[GateRecord]) -> dict[str, object]:
    blocked = [record for record in records if record.blocks_release]
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": "v0.2.3",
        "status_vocabulary": [PASS, FAIL, SKIP_APPROVED, SKIP_UNAPPROVED, WARN],
        "blocked": bool(blocked),
        "blocking_gates": [record.name for record in blocked],
        "gates": [asdict(record) | {"blocks_release": record.blocks_release} for record in records],
        "non_claims": [
            "not fabrication-ready",
            "not manufacturer-approved",
            "not no-human-review autonomous signoff",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a v0.2.3 release-gate summary")
    parser.add_argument("--gate", action="append", default=[], help="Gate result in name=value form")
    parser.add_argument("--skip-reason", action="append", default=[], help="Approved skip reason in name=reason form")
    parser.add_argument(
        "--required-oracle",
        action="append",
        default=[],
        help="Required external oracle gate name; missing entries block unless approved via --skip-reason",
    )
    parser.add_argument("--output", type=Path, help="Write JSON evidence to this path")
    parser.add_argument("--markdown", type=Path, help="Append Markdown summary to this path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when a required gate blocks release")
    args = parser.parse_args(argv)

    try:
        records = build_records(args.gate, args.skip_reason)
        records = require_external_oracles(records, args.required_oracle, args.skip_reason)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not records:
        print("ERROR: at least one --gate entry is required", file=sys.stderr)
        return 2

    summary = build_summary(records)
    markdown = render_markdown(records)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        with args.markdown.open("a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)

    if args.strict and summary["blocked"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
