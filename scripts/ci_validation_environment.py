"""Validate local toolchain parity for ZapTrace release gates.

This script is intentionally lightweight and stdlib-only so it can run before
``uv sync``. It checks whether a host has the tools required to reproduce the
repository's quality, test, Rust, KiCad, and simulation gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolRequirement:
    name: str
    executable: str
    version_args: tuple[str, ...] = ("--version",)
    required: bool = True
    min_major: int | None = None
    min_minor: int | None = None
    gate: str = "quality"
    install_hint: str = ""


TOOL_REQUIREMENTS: tuple[ToolRequirement, ...] = (
    ToolRequirement(
        name="Python",
        executable="python3",
        min_major=3,
        min_minor=12,
        gate="quality/test/build",
        install_hint="Install Python 3.12+ or use `uv python install 3.12`.",
    ),
    ToolRequirement(
        name="uv",
        executable="uv",
        gate="dependency/install/build",
        install_hint="Install uv from Astral, then run `uv sync --all-extras --all-groups`.",
    ),
    ToolRequirement(
        name="Ruff",
        executable="ruff",
        required=False,
        gate="quality",
        install_hint="Run through `uv run ruff ...` after `uv sync`; a global binary is optional.",
    ),
    ToolRequirement(
        name="Pyright",
        executable="pyright",
        required=False,
        gate="typecheck",
        install_hint="Run through `uv run pyright` after `uv sync`; a global binary is optional.",
    ),
    ToolRequirement(
        name="Rust compiler",
        executable="rustc",
        min_major=1,
        min_minor=91,
        gate="rust-extension",
        install_hint="Install Rust 1.91+ or ensure `/usr/lib/rust-1.91/bin` is on PATH.",
    ),
    ToolRequirement(
        name="Cargo",
        executable="cargo",
        min_major=1,
        min_minor=91,
        gate="rust-extension",
        install_hint="Install Cargo 1.91+ or ensure `/usr/lib/rust-1.91/bin` is on PATH.",
    ),
    ToolRequirement(
        name="maturin",
        executable="maturin",
        required=False,
        gate="rust-extension/build",
        install_hint="Run through `uv run maturin ...` after dependency sync; a global binary is optional.",
    ),
    ToolRequirement(
        name="KiCad CLI",
        executable="kicad-cli",
        min_major=9,
        min_minor=0,
        gate="external-oracle",
        install_hint="Install KiCad 9+ for release validation and KiCad oracle evidence.",
    ),
    ToolRequirement(
        name="ngspice",
        executable="ngspice",
        required=False,
        gate="simulation",
        install_hint="Install ngspice to turn simulation skips into real simulation evidence.",
    ),
)


def _first_version_number(text: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\.(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _candidate_paths(executable: str) -> list[str]:
    candidates: list[str] = []
    if executable in {"rustc", "cargo"}:
        for rust_dir in sorted(Path("/usr/lib").glob("rust-*/bin"), reverse=True):
            candidate = rust_dir / executable
            if candidate.exists():
                candidates.append(str(candidate))
    path = shutil.which(executable)
    if path:
        candidates.append(path)
    local = Path.home() / ".local" / "bin" / executable
    if local.exists():
        candidates.append(str(local))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _which(executable: str) -> str | None:
    candidates = _candidate_paths(executable)
    return candidates[0] if candidates else None


def check_tool(req: ToolRequirement) -> dict[str, Any]:
    path = _which(req.executable)
    result: dict[str, Any] = {
        "name": req.name,
        "executable": req.executable,
        "gate": req.gate,
        "required": req.required,
        "found": bool(path),
        "path": path or "",
        "version": "",
        "status": "missing" if req.required else "optional-missing",
        "install_hint": req.install_hint,
    }
    if not path:
        return result

    try:
        env = os.environ.copy()
        if not env.get("HOME"):
            env["HOME"] = str(Path.home() or "/tmp")
        proc = subprocess.run(
            [path, *req.version_args],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update({"status": "failed", "error": str(exc)})
        return result

    text = (proc.stdout or proc.stderr).strip()
    result.update({"version": text, "exit_code": proc.returncode})
    if proc.returncode != 0:
        result["status"] = "failed" if req.required else "optional-failed"
        return result

    if req.min_major is not None:
        parsed = _first_version_number(text)
        if not parsed:
            result["status"] = "failed"
            result["error"] = "could not parse version"
            return result
        major, minor = parsed
        if major < req.min_major or (major == req.min_major and req.min_minor is not None and minor < req.min_minor):
            result["status"] = "too-old"
            result["required_version"] = f">={req.min_major}.{req.min_minor or 0}"
            return result
    result["status"] = "ok"
    return result


def build_report() -> dict[str, Any]:
    tools = [check_tool(req) for req in TOOL_REQUIREMENTS]
    blockers = [tool for tool in tools if tool["required"] and tool["status"] not in {"ok"}]
    warnings = [tool for tool in tools if not tool["required"] and tool["status"] not in {"ok"}]
    return {
        "schema_version": "1.0",
        "gate_id": "validation-environment-v1",
        "passed": not blockers,
        "tools": tools,
        "blocking_tool_count": len(blockers),
        "warning_tool_count": len(warnings),
        "blocking_tools": [tool["name"] for tool in blockers],
        "warning_tools": [tool["name"] for tool in warnings],
        "recommended_release_commands": [
            "uv sync --all-extras --all-groups",
            "uv run ruff check .",
            "uv run ruff format --check .",
            "uv run pyright",
            "uv run pytest --cov=zaptrace --cov-report=term-missing",
            "cargo fmt --manifest-path zaptrace_core/Cargo.toml --check",
            "cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings",
            "cargo test --manifest-path zaptrace_core/Cargo.toml",
            "uv run python scripts/ci_kicad_oracle.py --strict-skips --output kicad-oracle-summary.json",
            (
                "uv run python scripts/ci_generated_board_release_gate.py "
                "--strict --output generated-board-release-gate.json"
            ),
            ("uv run python scripts/ci_kicad_roundtrip_scorecard.py --strict --output kicad-roundtrip-scorecard.json"),
        ],
        "non_claims": [
            "environment parity does not prove board correctness",
            "tool availability does not imply fabrication readiness",
        ],
    }


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Validation environment: {'PASS' if report['passed'] else 'FAIL'}",
        f"Blocking tools: {report['blocking_tool_count']}",
        f"Warnings: {report['warning_tool_count']}",
    ]
    for tool in report["tools"]:
        marker = "OK" if tool["status"] == "ok" else "!!"
        detail = tool.get("version") or tool.get("path") or "not found"
        lines.append(f"{marker} {tool['name']}: {tool['status']} ({detail})")
        if tool["status"] != "ok" and tool.get("install_hint"):
            lines.append(f"   hint: {tool['install_hint']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ZapTrace release-gate toolchain parity")
    parser.add_argument("--output", type=Path, help="Write JSON evidence to this path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if required tools are missing or too old",
    )
    args = parser.parse_args(argv)

    report = build_report()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report_json(report), encoding="utf-8")
    print(report_json(report) if args.json else render_text(report), end="")
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
