from __future__ import annotations

from datetime import UTC, datetime

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design
from zaptrace.erc.models import ERCResult


def generate_report(design: Design, erc_result: ERCResult | None = None) -> str:
    """Generate a comprehensive Markdown design report."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    board = canonical_board_definition(design)
    lines = [
        f"# Design Report: {design.meta.name}",
        "",
        f"**Version:** {design.meta.version}  ",
        f"**Revision:** {design.meta.revision}  ",
        f"**Author:** {design.meta.author or 'N/A'}  ",
        f"**Generated:** {now}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Components | {len(design.components)} |",
        f"| Nets | {len(design.nets)} |",
        f"| Board size | {board.width} x {board.height} mm |",
        f"| Layers | {board.layers} |",
    ]

    if erc_result:
        status = "PASS" if erc_result.passed else "FAIL"
        lines += [
            f"| ERC status | {status} |",
            f"| ERC errors | {erc_result.total_errors} |",
            f"| ERC warnings | {erc_result.total_warnings} |",
        ]
        if erc_result.checks_run:
            lines.append(f"| ERC coverage | {erc_result.coverage_summary()} |")

    lines += ["", "## Components", ""]
    lines += [
        "| Ref | Type | Value | Footprint | MPN |",
        "|-----|------|-------|-----------|-----|",
    ]
    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        lines.append(f"| {comp.ref} | {comp.type} | {comp.value or ''} | {comp.footprint} | {comp.mpn or ''} |")

    lines += ["", "## Nets", ""]
    for net in sorted(design.nets.values(), key=lambda n: n.name):
        node_str = ", ".join(f"{nd.component_ref}.{nd.pin_name}" for nd in net.nodes)
        lines.append(f"- **{net.name}** ({net.type.value}): {node_str}")

    if erc_result and erc_result.violations:
        lines += ["", "## ERC Violations", ""]
        for v in erc_result.violations:
            icon = {"error": "E", "warning": "W", "info": "I"}.get(v.severity.value, ".")
            lines.append(f"- **{icon}** `{v.rule_id}` {v.message}")
            if v.patch_suggestion:
                lines.append(f"  - Suggestion: {v.patch_suggestion}")

    if erc_result and erc_result.coverage_gaps:
        lines += ["", "## ERC Coverage Gaps", ""]
        lines.append("ERC is a rule-based pre-check, not full electrical verification. Not yet checked:")
        lines.append("")
        lines += [f"- {gap}" for gap in erc_result.coverage_gaps]

    return "\n".join(lines)
