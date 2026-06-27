"""Guard documentation/status claims against stale code facts."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

BANNED_REFERENCES = {
    "zaptrace/proof/generator.py": "proof generator module was consolidated into zaptrace/proof/pack.py",
    "8 ERC rules": "ERC rule count is generated from zaptrace.erc.runner._ALL_RULES",
    'ERC "8 rules"': "ERC rule count is generated from zaptrace.erc.runner._ALL_RULES",
    "629+ tests": "test totals should not be hard-coded in docs",
    "543 tests passing": "test totals should not be hard-coded in docs",
}

ROOTS = (Path("README.md"), Path("docs"), Path("CHANGELOG.md"))


def _list_len_assignment(path: str, name: str) -> int:
    """Return the element count of a module-level ``name = [...]`` list literal.

    Handles both plain assignments (``name = [...]``) and annotated
    assignments (``name: list[T] = [...]``).
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name) and t.id == name]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            targets = [node.target]
            value = node.value
        else:
            continue
        if targets and isinstance(value, ast.List):
            return len(value.elts)
    raise RuntimeError(f"Could not find {name} in {path}")


def actual_erc_rule_count() -> int:
    return _list_len_assignment("zaptrace/erc/runner.py", "_ALL_RULES")


def actual_drc_rule_count() -> int:
    return _list_len_assignment("zaptrace/ee/drc/engine.py", "_ALL_CHECKS")


def actual_tool_count() -> int:
    """Count module-level ``tool_*`` functions in the agent tool registry source."""
    tree = ast.parse(Path("zaptrace/agent/_tool_impls.py").read_text(encoding="utf-8"))
    return sum(1 for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("tool_"))


def _iter_docs() -> list[Path]:
    paths: list[Path] = []
    for root in ROOTS:
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.suffix.lower() in {".md", ".txt", ".json"})
    return sorted(paths)


def validate_docs() -> dict[str, Any]:
    errors: list[str] = []
    erc_count = actual_erc_rule_count()
    drc_count = actual_drc_rule_count()
    tool_count = actual_tool_count()

    # (regex, actual_count, human label). Each capture group 1 is the claimed number.
    # Separators use ``[ \t]`` (not ``\s``) so matches never span line breaks,
    # which would otherwise produce false positives from adjacent lines.
    # The ``(?<![\d.])`` guard keeps section/version numbers like "4.5.1 DRC
    # Rules" from being read as a "1 DRC rules" count claim.
    checks: list[tuple[re.Pattern[str], int, str]] = [
        (re.compile(r"(?<![\d.])(\d+)[ \t]+ERC[ \t]+rules\b", re.IGNORECASE), erc_count, "ERC rules"),
        (re.compile(r"\bERC[ \t]*\((\d+)[ \t]+rules?\)", re.IGNORECASE), erc_count, "ERC rules"),
        (re.compile(r"(?<![\d.])(\d+)[ \t]+DRC[ \t]+rules\b", re.IGNORECASE), drc_count, "DRC rules"),
        (re.compile(r"\bDRC[ \t]*\((\d+)[ \t]+rules?\)", re.IGNORECASE), drc_count, "DRC rules"),
        (re.compile(r"(?<![\d.])(\d+)[ \t]+agent[- ]facing[ \t]+tools\b", re.IGNORECASE), tool_count, "agent tools"),
        (re.compile(r"MCP server[ \t]*\((\d+)[ \t]+tools\)", re.IGNORECASE), tool_count, "MCP tools"),
    ]

    for path in _iter_docs():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for banned, reason in BANNED_REFERENCES.items():
            if banned in text:
                errors.append(f"{path}: banned stale reference {banned!r}: {reason}")
        for pattern, actual, label in checks:
            for match in pattern.finditer(text):
                claimed = int(match.group(1))
                if claimed != actual:
                    errors.append(f"{path}: claims {claimed} {label} but code has {actual}")
    return {
        "passed": not errors,
        "erc_rule_count": erc_count,
        "drc_rule_count": drc_count,
        "tool_count": tool_count,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate docs/status sync guard")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = validate_docs()
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not result["passed"]:
        for error in result["errors"]:
            print(error)
        return 1
    print(
        "docs-status-sync ok: "
        f"ERC rules={result['erc_rule_count']}, "
        f"DRC rules={result['drc_rule_count']}, "
        f"agent tools={result['tool_count']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
