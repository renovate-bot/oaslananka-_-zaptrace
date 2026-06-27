"""KiCad CLI oracle — detect, version, ERC, DRC, and structured results.

Usage:
    from zaptrace.kicad.oracle import detect_kicad, run_erc, run_drc

    oracle = detect_kicad()
    if oracle.available:
        erc_result = run_erc("/path/to/project.kicad_pro")
        drc_result = run_drc("/path/to/board.kicad_pcb")

Every method returns a result object — never raises.  When the CLI is
unavailable the result carries ``available=False`` and an explanatory message.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ======================================================================
# Known KiCad install paths per platform
# ======================================================================

_COMMON_KICAD_PATHS: list[str] = [
    # Linux (AppImage, apt, snap)
    "kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/snap/bin/kicad-cli",
    # macOS
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/Applications/KiCad/kicad-cli",
    # Windows (KiCad 7+)
    "C:/Program Files/KiCad/8.0/bin/kicad-cli.exe",
    "C:/Program Files/KiCad/9.0/bin/kicad-cli.exe",
    "C:/Program Files/KiCad/10.0/bin/kicad-cli.exe",
    "C:/Program Files/KiCad/7.0/bin/kicad-cli.exe",
]


# ======================================================================
# Result models
# ======================================================================


@dataclass
class KiCadResult:
    """Base result for any KiCad oracle operation."""

    available: bool
    """Whether the KiCad CLI was found and executed."""

    success: bool = False
    """Whether the operation completed without errors."""

    message: str = ""
    """Human-readable summary."""

    duration_ms: float = 0.0
    """Wall-clock time for the operation."""

    @property
    def error(self) -> str:
        """Human-readable error when the operation failed, else empty."""
        return self.message if not self.success else ""


@dataclass
class KiCadErcItem:
    """A single ERC violation from the KiCad report."""

    rule: str = ""
    severity: str = "error"
    message: str = ""
    sheet: str = ""
    item: str = ""  # e.g. "J1:1 -> U1:10"
    comment: list[str] = field(default_factory=list)
    source: list[dict] | None = None


@dataclass
class KiCadErcResult(KiCadResult):
    """ERC check result with structured violations."""

    violations: list[KiCadErcItem] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    @property
    def passed(self) -> bool:
        return self.success and self.errors == 0

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def error_count(self) -> int:
        return self.errors

    @property
    def warning_count(self) -> int:
        return self.warnings


@dataclass
class KiCadDrcItem:
    """A single DRC violation from the KiCad report."""

    rule: str = ""
    severity: str = "error"
    message: str = ""
    layer: str = ""
    position: tuple[float, float] | None = None
    code: int = 0
    comment: list[str] = field(default_factory=list)


@dataclass
class KiCadDrcResult(KiCadResult):
    """DRC check result with structured violations."""

    violations: list[KiCadDrcItem] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    @property
    def passed(self) -> bool:
        return self.success and self.errors == 0

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def error_count(self) -> int:
        return self.errors

    @property
    def warning_count(self) -> int:
        return self.warnings


# ======================================================================
# Oracle class
# ======================================================================


class KiCadOracle:
    """Detect and interact with the KiCad CLI.

    Usage:
        oracle = KiCadOracle()
        if oracle.available:
            print(oracle.version)
            erc = oracle.run_erc("project.kicad_pro")
    """

    def __init__(self, cli_path: str | None = None) -> None:
        self._cli_path: str | None = cli_path
        self._version: str = ""
        self._detect()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._cli_path is not None

    @property
    def cli_path(self) -> str | None:
        return self._cli_path

    @property
    def version(self) -> str:
        if not self._cli_path:
            return ""
        if not self._version:
            self._version = self._capture_version()
        return self._version

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect(self) -> None:
        """Locate the kicad-cli binary."""
        if self._cli_path:
            self._cli_path = self._resolve(self._cli_path)
            return

        # Try PATH first
        resolved = shutil.which("kicad-cli")
        if resolved:
            self._cli_path = resolved
            return

        # Try known install paths
        for p in _COMMON_KICAD_PATHS:
            if self._resolve(p):
                self._cli_path = p
                return

        self._cli_path = None

    @staticmethod
    def _resolve(path: str) -> str | None:
        """Resolve *path* — return the absolute path if it exists."""
        if not path:
            return None
        # shutil.which already resolved — just check
        if os.path.isfile(path):
            return os.path.abspath(path)
        resolved = shutil.which(path)
        if resolved and os.path.isfile(resolved):
            return resolved
        return None

    def _capture_version(self) -> str:
        """Run ``kicad-cli --version`` and return the output."""
        if not self._cli_path:
            return ""
        try:
            result = subprocess.run(
                [self._cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return ""
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""

    # ------------------------------------------------------------------
    # ERC
    # ------------------------------------------------------------------

    def run_erc(
        self,
        project_file: str | Path,
        *,
        output_path: str | Path | None = None,
        timeout: int = 120,
        severity: str = "all",
        exit_code_violations: bool = True,
    ) -> KiCadErcResult:
        """Run Electrical Rules Check via ``kicad-cli sch erc``.

        Args:
            project_file: Path to a ``.kicad_pro`` project file.
            output_path: Optional path for the JSON report.  If omitted a
                temporary file is used.
            timeout: Max seconds to wait for the CLI.
            severity: ``"all"``, ``"error"``, or ``"warning"``.
            exit_code_violations: If True, violations cause a non-zero
                exit code (detected as failure).

        Returns:
            ``KiCadErcResult`` with structured violations.
        """
        base = KiCadErcResult(available=self.available)
        if not self._cli_path:
            base.message = "KiCad CLI not found"
            return base

        import tempfile
        import time

        start = time.perf_counter()

        proj = Path(project_file)
        if not proj.exists():
            base.message = f"Project file not found: {proj}"
            base.duration_ms = (time.perf_counter() - start) * 1000
            return base

        out = Path(output_path) if output_path else Path(tempfile.mktemp(suffix="-erc.json"))

        cmd = [
            self._cli_path,
            "sch",
            "erc",
            str(proj),
            "--format",
            "json",
            "--output",
            str(out),
            f"--severity-{severity}",
        ]
        if exit_code_violations:
            cmd.append("--exit-code-violations")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            elapsed = (time.perf_counter() - start) * 1000
            base.duration_ms = elapsed

            # Parse output file
            if out.exists():
                raw = json.loads(out.read_text(encoding="utf-8"))
                base = self._parse_erc_json(raw)
                base.available = True
                base.duration_ms = elapsed

            # If exit code signals error (exit_code_violations mode)
            if exit_code_violations and proc.returncode != 0 and proc.returncode != 3:
                base.success = False
                base.message = proc.stderr.strip() or f"ERC failed (exit {proc.returncode})"

            base.success = base.success or proc.returncode == 0
            base.message = base.message or f"ERC complete: {base.errors} errors, {base.warnings} warnings"

        except FileNotFoundError:
            base.message = f"KiCad CLI not found at {self._cli_path}"
        except subprocess.TimeoutExpired:
            base.message = f"ERC timed out after {timeout}s"
        except json.JSONDecodeError as e:
            base.message = f"ERC output parse error: {e}"
        except Exception as e:
            base.message = f"ERC unexpected error: {e}"
        finally:
            # Clean up temp file
            if not output_path and out.exists():
                with suppress(OSError):
                    out.unlink()

        return base

    @staticmethod
    def _parse_erc_json(raw: dict[str, Any]) -> KiCadErcResult:
        """Parse the KiCad ERC JSON report into a structured result."""
        result = KiCadErcResult(available=True, success=True)

        violations_data = raw.get("violations", [])
        for v in violations_data:
            item = KiCadErcItem(
                rule=v.get("rule", ""),
                severity=v.get("severity", "error"),
                message=v.get("message", ""),
                sheet=v.get("sheet", ""),
                item=v.get("item", ""),
                comment=v.get("comment", []),
                source=v.get("source"),
            )
            result.violations.append(item)
            if item.severity == "error":
                result.errors += 1
            elif item.severity == "warning":
                result.warnings += 1

        result.message = f"{result.errors} ERC errors, {result.warnings} warnings"
        result.success = result.errors == 0
        return result

    # ------------------------------------------------------------------
    # DRC
    # ------------------------------------------------------------------

    def run_drc(
        self,
        pcb_file: str | Path,
        *,
        output_path: str | Path | None = None,
        timeout: int = 120,
        severity: str = "all",
        exit_code_violations: bool = True,
        schematic_parity: bool = False,
    ) -> KiCadDrcResult:
        """Run Design Rules Check via ``kicad-cli pcb drc``.

        Args:
            pcb_file: Path to a ``.kicad_pcb`` board file.
            output_path: Optional path for the JSON report.
            timeout: Max seconds to wait for the CLI.
            severity: ``"all"``, ``"error"``, or ``"warning"``.
            exit_code_violations: If True, violations cause a non-zero
                exit code.
            schematic_parity: Also check schematic-PCB parity.

        Returns:
            ``KiCadDrcResult`` with structured violations.
        """
        base = KiCadDrcResult(available=self.available)
        if not self._cli_path:
            base.message = "KiCad CLI not found"
            return base

        import tempfile
        import time

        start = time.perf_counter()

        pcb = Path(pcb_file)
        if not pcb.exists():
            base.message = f"PCB file not found: {pcb}"
            base.duration_ms = (time.perf_counter() - start) * 1000
            return base

        out = Path(output_path) if output_path else Path(tempfile.mktemp(suffix="-drc.json"))

        cmd = [
            self._cli_path,
            "pcb",
            "drc",
            str(pcb),
            "--format",
            "json",
            "--output",
            str(out),
            f"--severity-{severity}",
        ]
        if exit_code_violations:
            cmd.append("--exit-code-violations")
        if schematic_parity:
            cmd.append("--schematic-parity")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            elapsed = (time.perf_counter() - start) * 1000
            base.duration_ms = elapsed

            if out.exists():
                raw = json.loads(out.read_text(encoding="utf-8"))
                base = self._parse_drc_json(raw)
                base.available = True
                base.duration_ms = elapsed

            if exit_code_violations and proc.returncode != 0 and proc.returncode != 3:
                base.success = False
                base.message = proc.stderr.strip() or f"DRC failed (exit {proc.returncode})"

            base.success = base.success or proc.returncode == 0
            base.message = base.message or f"DRC complete: {base.errors} errors, {base.warnings} warnings"

        except FileNotFoundError:
            base.message = f"KiCad CLI not found at {self._cli_path}"
        except subprocess.TimeoutExpired:
            base.message = f"DRC timed out after {timeout}s"
        except json.JSONDecodeError as e:
            base.message = f"DRC output parse error: {e}"
        except Exception as e:
            base.message = f"DRC unexpected error: {e}"
        finally:
            if not output_path and out.exists():
                with suppress(OSError):
                    out.unlink()

        return base

    @staticmethod
    def _parse_drc_json(raw: dict[str, Any]) -> KiCadDrcResult:
        """Parse the KiCad DRC JSON report into a structured result."""
        result = KiCadDrcResult(available=True, success=True)

        violations_data = raw.get("violations", [])
        for v in violations_data:
            pos = v.get("position", {})
            position = None
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                position = (float(pos["x"]), float(pos["y"]))

            item = KiCadDrcItem(
                rule=v.get("rule", ""),
                severity=v.get("severity", "error"),
                message=v.get("message", ""),
                layer=v.get("layer", ""),
                position=position,
                code=v.get("code", 0),
                comment=v.get("comment", []),
            )
            result.violations.append(item)
            if item.severity == "error":
                result.errors += 1
            elif item.severity == "warning":
                result.warnings += 1

        result.message = f"{result.errors} DRC errors, {result.warnings} warnings"
        result.success = result.errors == 0
        return result

    def __repr__(self) -> str:
        if self.available:
            return f"<KiCadOracle {self._cli_path} v{self.version}>"
        return "<KiCadOracle unavailable>"


# ======================================================================
# Module-level convenience functions
# ======================================================================

_ORACLE_CACHE: KiCadOracle | None = None


def detect_kicad() -> KiCadOracle:
    """Detect the KiCad CLI on this system.

    Results are cached — subsequent calls return the same ``KiCadOracle``
    instance.
    """
    global _ORACLE_CACHE
    if _ORACLE_CACHE is None:
        _ORACLE_CACHE = KiCadOracle()
    return _ORACLE_CACHE


def get_kicad_version() -> str | None:
    """Return the detected KiCad CLI version, or ``None``."""
    oracle = detect_kicad()
    return oracle.version or None


def run_erc(project_file: str | Path, **kwargs: Any) -> KiCadErcResult:
    """Convenience: detect, then run ERC."""
    return detect_kicad().run_erc(project_file, **kwargs)


def run_drc(pcb_file: str | Path, **kwargs: Any) -> KiCadDrcResult:
    """Convenience: detect, then run DRC."""
    return detect_kicad().run_drc(pcb_file, **kwargs)
