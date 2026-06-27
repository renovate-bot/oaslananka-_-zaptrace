"""ngspice operating-point runner (optional external tool).

This is a thin, skip-aware adapter around ``ngspice``: if the binary is not on
PATH it returns a ``skipped`` result rather than failing, mirroring how the
KiCad oracle treats a missing ``kicad-cli``. It does not bundle a simulator.

The pure helpers — :func:`with_op_control` (inject a ``.op`` control block) and
:func:`parse_op_output` (read node voltages from ngspice batch output) — are
unit-tested directly so the logic is covered even where ngspice is absent (CI).

Note: the live invocation path is calibrated to documented ngspice ``-b``
``print`` output ("``v(node) = value``"); verify against your ngspice build.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# A node-voltage line from ngspice batch `print`: "v(vcc) = 3.300000e+00".
_VOLTAGE_RE = re.compile(r"v\(([^)]+)\)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", re.IGNORECASE)


@dataclass
class SpiceResult:
    """Result of an ngspice operating-point run.

    ``status`` is one of ``"ok"``, ``"skipped"`` (ngspice not installed), or
    ``"error"`` (ngspice ran but failed / timed out).
    """

    status: str
    node_voltages: dict[str, float] = field(default_factory=dict)
    raw_output: str = ""
    reason: str = ""


def ngspice_available() -> bool:
    """True if an ``ngspice`` executable is on PATH."""
    return shutil.which("ngspice") is not None


def with_op_control(netlist: str) -> str:
    """Insert a ``.op`` control block before the final ``.end`` of *netlist*.

    Adds a batch control block that runs the operating point and prints every
    node voltage so the output can be parsed deterministically.
    """
    control = ".control\nop\nprint all\n.endc\n"
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, control.rstrip("\n"))
            return "\n".join(lines) + "\n"
    # No .end found — append control + .end.
    return netlist.rstrip("\n") + "\n" + control + ".end\n"


def parse_op_output(text: str) -> dict[str, float]:
    """Parse node voltages from ngspice batch output into ``{node: volts}``."""
    voltages: dict[str, float] = {}
    for match in _VOLTAGE_RE.finditer(text):
        voltages[match.group(1).lower()] = float(match.group(2))
    return voltages


def run_operating_point(netlist: str, *, timeout_s: float = 30.0) -> SpiceResult:
    """Run a DC operating point on *netlist* with ngspice (skip-aware).

    Returns a :class:`SpiceResult`. When ngspice is not installed the status is
    ``"skipped"`` so callers can record missing-evidence rather than fail.
    """
    if not ngspice_available():
        return SpiceResult(status="skipped", reason="ngspice not installed")

    sim_netlist = with_op_control(netlist)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False, encoding="utf-8") as handle:
            handle.write(sim_netlist)
            tmp_path = Path(handle.name)
        proc = subprocess.run(
            ["ngspice", "-b", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return SpiceResult(status="error", raw_output=output, reason=f"ngspice exited {proc.returncode}")
        return SpiceResult(status="ok", node_voltages=parse_op_output(output), raw_output=output)
    except subprocess.TimeoutExpired:
        return SpiceResult(status="error", reason=f"ngspice timed out after {timeout_s}s")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
