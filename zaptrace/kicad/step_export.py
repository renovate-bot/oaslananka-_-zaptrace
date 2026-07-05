"""KiCad CLI STEP export — delegated, skip-aware, evidence-recording.

Delegates PCB-to-STEP conversion to ``kicad-cli pcb export-step``.
Missing KiCad or unsupported STEP export yields SKIPPED evidence rather than
a false PASS.  All evidence fields required by issue #140 are recorded.

Usage::

    from zaptrace.kicad.step_export import export_step, StepExportResult

    result = export_step("/path/to/board.kicad_pcb")
    if result.status == "passed":
        print(result.output_path, result.output_sha256)
    elif result.status == "skipped":
        print("KiCad not available:", result.skip_reason)
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Evidence schema
# ---------------------------------------------------------------------------


@dataclass
class StepExportResult:
    """Evidence record for a delegated KiCad STEP export."""

    status: str  # "passed" | "failed" | "skipped"
    """Outcome: passed (STEP generated), failed (CLI error), or skipped (unavailable)."""

    skip_reason: str = ""
    """Human-readable reason when status == 'skipped'."""

    kicad_version: str = ""
    """Detected kicad-cli version string, e.g. '8.0.2'."""

    cli_path: str = ""
    """Resolved path to the kicad-cli binary."""

    command: list[str] = field(default_factory=list)
    """Exact argument list that was executed."""

    input_path: str = ""
    """Absolute path to the source .kicad_pcb file."""

    input_sha256: str = ""
    """SHA-256 hex digest of the input file."""

    output_path: str = ""
    """Absolute path to the generated .step file (when status == 'passed')."""

    output_sha256: str = ""
    """SHA-256 hex digest of the generated .step file."""

    output_size_bytes: int = 0
    """Byte length of the generated .step file (smoke check: must be > 0)."""

    step_smoke_check: str = ""
    """Structural smoke-check verdict: 'pass', 'fail', or 'skip'."""

    step_smoke_reason: str = ""
    """Why the smoke check passed/failed."""

    exit_code: int | None = None
    """kicad-cli process exit code."""

    runtime_ms: float = 0.0
    """Wall-clock time for the export command in milliseconds."""

    delegated: bool = True
    """Always True — STEP export is fully delegated to the KiCad CLI."""

    stderr_snippet: str = ""
    """Last 512 chars of stderr (for diagnostics on failure)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "step-export-v1",
            "status": self.status,
            "skip_reason": self.skip_reason,
            "kicad_version": self.kicad_version,
            "cli_path": self.cli_path,
            "command": self.command,
            "input_path": self.input_path,
            "input_sha256": self.input_sha256,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "output_size_bytes": self.output_size_bytes,
            "step_smoke_check": self.step_smoke_check,
            "step_smoke_reason": self.step_smoke_reason,
            "exit_code": self.exit_code,
            "runtime_ms": self.runtime_ms,
            "delegated": self.delegated,
            "stderr_snippet": self.stderr_snippet,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _smoke_check_step(step_path: Path) -> tuple[str, str]:
    """Validate STEP file structure minimally.

    Checks:
    1. File is non-empty.
    2. First line starts with "ISO-10303" (standard STEP header).
    3. File contains at least one CARTESIAN_POINT record.

    Returns (verdict, reason) where verdict is 'pass' or 'fail'.
    """
    try:
        size = step_path.stat().st_size
        if size == 0:
            return "fail", "empty file"

        content = step_path.read_text(encoding="ascii", errors="replace")
        lines = content.splitlines()
        if not lines:
            return "fail", "no lines"

        first_line = lines[0].strip()
        if not first_line.startswith("ISO-10303"):
            return "fail", f"unexpected first line: {first_line[:60]!r}"

        if "CARTESIAN_POINT" not in content:
            return "fail", "no CARTESIAN_POINT entities found"

        return "pass", f"ISO-10303 header OK; {size} bytes; CARTESIAN_POINT present"
    except Exception as exc:  # noqa: BLE001
        return "fail", f"smoke-check exception: {exc}"


def _find_kicad_cli() -> tuple[str | None, str]:
    """Locate kicad-cli; return (path_or_None, version_or_empty)."""
    cli = shutil.which("kicad-cli")
    if cli is None:
        # Known install paths
        candidates = [
            "/usr/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
            "/snap/bin/kicad-cli",
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
        ]
        for c in candidates:
            if Path(c).is_file():
                cli = c
                break

    if cli is None:
        return None, ""

    try:
        r = subprocess.run(
            [cli, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = r.stdout.strip() if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, ""

    return cli, version


def _supports_step_export(cli: str, version: str) -> tuple[bool, str]:
    """Return (supported, reason).  KiCad 6+ supports pcb export-step."""
    # Try to detect version number
    import re

    m = re.search(r"(\d+)\.", version)
    if m:
        major = int(m.group(1))
        if major < 6:
            return False, f"kicad-cli {version} < 6.0 — pcb export-step unsupported"
    # Attempt a help probe to confirm the sub-command exists
    try:
        r = subprocess.run(
            [cli, "pcb", "export-step", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode not in (0, 1):  # some CLIs return 1 for --help
            return False, "pcb export-step --help returned unexpected exit code"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, f"help probe failed: {exc}"

    return True, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_step(
    pcb_path: str | Path,
    *,
    output_path: str | Path | None = None,
    timeout: int = 120,
    subst_models: bool = True,
    grid_origin: bool = False,
    no_dnp: bool = True,
) -> StepExportResult:
    """Export a KiCad PCB file to STEP via delegated kicad-cli.

    Parameters
    ----------
    pcb_path:
        Path to a ``.kicad_pcb`` file.
    output_path:
        Destination ``.step`` file.  If *None*, a temporary file is created
        in the same directory as *pcb_path*.
    timeout:
        Maximum seconds for the kicad-cli process.
    subst_models:
        Pass ``--subst-models`` to replace unavailable 3D models with
        bounding-box substitutes (default True).
    grid_origin:
        If True pass ``--grid-origin`` (use grid origin as reference).
    no_dnp:
        If True pass ``--no-dnp`` (exclude do-not-populate components).

    Returns
    -------
    StepExportResult
        Evidence record (never raises).
    """
    pcb_path = Path(pcb_path).resolve()

    # ---- Hash input ----
    input_sha256 = ""
    if pcb_path.is_file():
        input_sha256 = _sha256_file(pcb_path)

    # ---- Locate KiCad CLI ----
    cli, version = _find_kicad_cli()
    if cli is None:
        return StepExportResult(
            status="skipped",
            skip_reason="kicad-cli not found in PATH or known install locations",
            input_path=str(pcb_path),
            input_sha256=input_sha256,
        )

    # ---- Check STEP export support ----
    supported, reason = _supports_step_export(cli, version)
    if not supported:
        return StepExportResult(
            status="skipped",
            skip_reason=reason,
            kicad_version=version,
            cli_path=cli,
            input_path=str(pcb_path),
            input_sha256=input_sha256,
        )

    # ---- Validate input file ----
    if not pcb_path.is_file():
        return StepExportResult(
            status="skipped",
            skip_reason=f"input file not found: {pcb_path}",
            kicad_version=version,
            cli_path=cli,
            input_path=str(pcb_path),
            input_sha256=input_sha256,
        )

    # ---- Resolve output path ----
    _tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    if output_path is None:
        _tmp_dir = tempfile.TemporaryDirectory(prefix="zaptrace_step_")
        output_path = Path(_tmp_dir.name) / (pcb_path.stem + ".step")
    else:
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- Build command ----
    cmd: list[str] = [
        cli,
        "pcb",
        "export-step",
        "--output",
        str(output_path),
    ]
    if subst_models:
        cmd.append("--subst-models")
    if grid_origin:
        cmd.append("--grid-origin")
    if no_dnp:
        cmd.append("--no-dnp")
    cmd.append(str(pcb_path))

    # ---- Execute ----
    t0 = time.perf_counter()
    stderr_text = ""
    exit_code: int | None = None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = proc.returncode
        stderr_text = proc.stderr[-512:] if proc.stderr else ""
        runtime_ms = (time.perf_counter() - t0) * 1000
    except subprocess.TimeoutExpired:
        runtime_ms = (time.perf_counter() - t0) * 1000
        if _tmp_dir:
            _tmp_dir.cleanup()
        return StepExportResult(
            status="failed",
            skip_reason="",
            kicad_version=version,
            cli_path=cli,
            command=cmd,
            input_path=str(pcb_path),
            input_sha256=input_sha256,
            exit_code=None,
            runtime_ms=runtime_ms,
            stderr_snippet="TIMEOUT",
        )
    except OSError as exc:
        runtime_ms = (time.perf_counter() - t0) * 1000
        if _tmp_dir:
            _tmp_dir.cleanup()
        return StepExportResult(
            status="failed",
            kicad_version=version,
            cli_path=cli,
            command=cmd,
            input_path=str(pcb_path),
            input_sha256=input_sha256,
            exit_code=None,
            runtime_ms=runtime_ms,
            stderr_snippet=str(exc),
        )

    # ---- Check output ----
    out_path = Path(str(output_path))
    if exit_code != 0 or not out_path.is_file():
        if _tmp_dir:
            _tmp_dir.cleanup()
        return StepExportResult(
            status="failed",
            kicad_version=version,
            cli_path=cli,
            command=cmd,
            input_path=str(pcb_path),
            input_sha256=input_sha256,
            exit_code=exit_code,
            runtime_ms=runtime_ms,
            stderr_snippet=stderr_text,
        )

    out_sha256 = _sha256_file(out_path)
    out_size = out_path.stat().st_size
    smoke_verdict, smoke_reason = _smoke_check_step(out_path)

    result = StepExportResult(
        status="passed",
        kicad_version=version,
        cli_path=cli,
        command=cmd,
        input_path=str(pcb_path),
        input_sha256=input_sha256,
        output_path=str(out_path),
        output_sha256=out_sha256,
        output_size_bytes=out_size,
        step_smoke_check=smoke_verdict,
        step_smoke_reason=smoke_reason,
        exit_code=exit_code,
        runtime_ms=runtime_ms,
        stderr_snippet=stderr_text,
    )

    # Do NOT cleanup _tmp_dir here — caller may read output_path.
    # Temporary directory will be cleaned on GC.
    return result


def export_step_from_text(
    kicad_pcb_text: str,
    *,
    timeout: int = 120,
) -> StepExportResult:
    """Export a KiCad PCB from in-memory text content to STEP.

    Creates a temporary ``.kicad_pcb`` file, runs the export, and returns
    the evidence record.  Useful when the caller only has PCB text content.
    """
    with tempfile.NamedTemporaryFile(
        suffix=".kicad_pcb",
        mode="w",
        delete=False,
        prefix="zaptrace_step_in_",
    ) as tmp:
        tmp.write(kicad_pcb_text)
        tmp_path = Path(tmp.name)

    try:
        return export_step(tmp_path, timeout=timeout)
    finally:
        with contextlib_suppress():
            tmp_path.unlink()


def contextlib_suppress() -> Any:
    """Return a context manager that suppresses all exceptions."""
    from contextlib import suppress

    return suppress(Exception)
