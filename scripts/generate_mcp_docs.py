#!/usr/bin/env python3
"""Regenerate docs/mcp/tools-reference.md from TOOL_REGISTRY.

Usage:
    python scripts/generate_mcp_docs.py

The output is written to docs/mcp/tools-reference.md.
Run this whenever TOOL_REGISTRY changes, and commit the updated file.
"""

from __future__ import annotations

from pathlib import Path

from zaptrace.agent._tool_impls import list_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "mcp" / "tools-reference.md"

HEADER = """# MCP Tools Reference

> **Auto-generated from `TOOL_REGISTRY`**
> Run `python scripts/generate_mcp_docs.py` to regenerate.
> Total tools: {count}

---

"""


def _param_table(params: dict) -> str:
    if not params:
        return "*No parameters*"
    rows = []
    for name, info in params.items():
        ptype = info.get("type", "any")
        desc = info.get("description", "")
        rows.append(f"| `{name}` | `{ptype}` | {desc} |")
    header = "| Parameter | Type | Description |\n|-----------|------|-------------|\n"
    return header + "\n".join(rows)


def generate() -> str:
    tools = list_tools()
    lines = [HEADER.format(count=len(tools))]

    # Group tools by category based on naming prefix
    categories: dict[str, list[dict]] = {}
    for t in tools:
        name: str = t["name"]
        if name.startswith("design_"):
            cat = "Design I/O"
        elif name.startswith("synthesize_") or name.startswith("list_synthesis_"):
            cat = "Synthesis"
        elif name.startswith("erc_"):
            cat = "Electrical Rule Checking (ERC)"
        elif name.startswith("drc_"):
            cat = "Design Rule Checking (DRC)"
        elif name.startswith("place_"):
            cat = "Placement"
        elif name.startswith("route_") or name.endswith("_route_smart"):
            cat = "Routing"
        elif name.startswith("library_") or name.startswith("footprint_"):
            cat = "Library & Footprints"
        elif name.startswith("export_"):
            cat = "Export"
        elif name.startswith("pipeline_"):
            cat = "Pipeline"
        elif name.startswith("board_"):
            cat = "Board"
        elif name.startswith("schematic_"):
            cat = "Schematic"
        elif name.startswith("component_") or name.startswith("patch_suggest"):
            cat = "Component Operations"
        elif name.startswith("proof_"):
            cat = "Proof Pack"
        else:
            cat = "Other"
        categories.setdefault(cat, []).append(t)

    for cat_name, cat_tools in sorted(categories.items()):
        lines.append(f"## {cat_name}\n")
        for t in cat_tools:
            lines.append(f"### `{t['name']}`\n")
            lines.append(f"{t['description']}\n")
            lines.append("**Parameters:**\n")
            lines.append(_param_table(t.get("params", {})))
            lines.append("")
        lines.append("---\n")

    # Error handling appendix
    lines.extend(
        [
            "## Error Handling\n",
            "All tools return errors as structured JSON envelopes:\n",
            "```json\n"
            "{\n"
            '  "error": true,\n'
            '  "code": "TOOL_ERROR",\n'
            '  "message": "Human-readable description",\n'
            '  "details": {}\n'
            "}\n"
            "```\n",
            "Common error codes:\n",
            "- `DESIGN_NOT_FOUND` — Design name not found in session\n",
            "- `INVALID_PARAMETER` — Parameter out of range or invalid\n",
            "- `EXPORT_FAILED` — Export process failed\n",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    import sys

    output = generate()
    is_check = "--check" in sys.argv
    if is_check:
        current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
        if current != output:
            print(f"ERROR: {DOC_PATH} is stale. Run `python scripts/generate_mcp_docs.py` to regenerate.")
            sys.exit(1)
        print(f"OK: {DOC_PATH} is up to date ({output.count('### `')} tools)")
    else:
        DOC_PATH.write_text(output, encoding="utf-8")
        print(f"Wrote {DOC_PATH} ({len(output)} chars, {output.count('### `')} tools)")


if __name__ == "__main__":
    main()
