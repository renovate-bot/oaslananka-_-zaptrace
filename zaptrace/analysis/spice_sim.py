"""ngspice operating-point runner (optional external tool).

This is a thin, skip-aware adapter around ``ngspice``: if the binary is not on
PATH it returns a ``skipped`` result rather than failing, mirroring how the
KiCad oracle treats a missing ``kicad-cli``. It does not bundle a simulator.

The pure helpers — :func:`with_op_control` (inject a ``.op`` control block) and
:func:`parse_op_output` (read node voltages from ngspice batch output) — are
unit-tested directly so the logic is covered even where ngspice is absent (CI).

Transient analysis is supported via :func:`run_transient`, which runs a ``.tran``
simulation and parses per-timepoint waveform data for startup-time and
steady-state ripple checks.

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

# Transient waveform: ngspice .tran print output can have optional integer index:
# "0.000000e+00  3.300000e+00" (time<space>value)  OR
# "0  0.000000e+00  3.300000e+00" (index<space>time<space>value)
_TRAN_ROW_RE = re.compile(
    r"^\s*(?:\d+\s+)?"  # optional leading integer index
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # time
    r"\s+"
    r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"  # voltage
    r"\s*$"
)


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


@dataclass
class TransientWaveform:
    """Time-series waveform from a transient analysis run.

    Attributes
    ----------
    node:
        Net name the waveform was measured on (e.g. ``"vout"``).
    times_s:
        Simulation time samples in seconds.
    voltages_v:
        Corresponding voltage samples in volts.
    """

    node: str
    times_s: list[float] = field(default_factory=list)
    voltages_v: list[float] = field(default_factory=list)

    @property
    def min_v(self) -> float | None:
        return min(self.voltages_v) if self.voltages_v else None

    @property
    def max_v(self) -> float | None:
        return max(self.voltages_v) if self.voltages_v else None

    @property
    def final_v(self) -> float | None:
        return self.voltages_v[-1] if self.voltages_v else None

    def steady_state_window(self, *, last_fraction: float = 0.2) -> list[float]:
        """Return voltages in the last *last_fraction* of the simulation time."""
        if not self.voltages_v:
            return []
        n = max(1, int(len(self.voltages_v) * last_fraction))
        return self.voltages_v[-n:]

    def ripple_v(self, *, last_fraction: float = 0.2) -> float:
        """Peak-to-peak voltage ripple in the steady-state window."""
        window = self.steady_state_window(last_fraction=last_fraction)
        return max(window) - min(window) if len(window) >= 2 else 0.0

    def startup_time_s(self, target_v: float, *, threshold: float = 0.9) -> float | None:
        """Time (in seconds) when the waveform first reaches *threshold* × *target_v*.

        Returns ``None`` if the voltage never reaches the threshold.
        """
        threshold_v = threshold * target_v
        for t, v in zip(self.times_s, self.voltages_v, strict=False):
            if v >= threshold_v:
                return t
        return None


@dataclass
class TransientResult:
    """Result of an ngspice transient analysis run.

    ``status`` is one of ``"ok"``, ``"skipped"`` (ngspice not installed), or
    ``"error"`` (ngspice ran but failed / timed out).
    """

    status: str
    waveforms: dict[str, TransientWaveform] = field(default_factory=dict)
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


def with_tran_control(netlist: str, step_s: float, stop_s: float, node: str) -> str:
    """Insert a ``.tran`` control block for transient analysis.

    Parameters
    ----------
    netlist:
        SPICE netlist string (must end with ``.end``).
    step_s:
        Timestep size in seconds (e.g. ``1e-9`` for 1 ns).
    stop_s:
        Simulation stop time in seconds (e.g. ``100e-6`` for 100 µs).
    node:
        Net name to print (e.g. ``"vout"``).
    """
    control = f".control\ntran {step_s:g} {stop_s:g}\nprint v({node})\n.endc\n"
    lines = netlist.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().lower() == ".end":
            lines.insert(i, control.rstrip("\n"))
            return "\n".join(lines) + "\n"
    return netlist.rstrip("\n") + "\n" + control + ".end\n"


def parse_op_output(text: str) -> dict[str, float]:
    """Parse node voltages from ngspice batch output into ``{node: volts}``."""
    voltages: dict[str, float] = {}
    for match in _VOLTAGE_RE.finditer(text):
        voltages[match.group(1).lower()] = float(match.group(2))
    return voltages


def parse_tran_output(text: str, node: str) -> TransientWaveform:
    """Parse ngspice transient print output into a :class:`TransientWaveform`.

    ngspice batch ``print v(node)`` emits rows of the form::

        0.000000e+00  3.300000e+00
        1.000000e-09  3.301000e+00

    Parameters
    ----------
    text:
        Raw stdout/stderr output from ngspice batch mode.
    node:
        The node name that was printed (used to populate :attr:`TransientWaveform.node`).
    """
    waveform = TransientWaveform(node=node)
    for line in text.splitlines():
        m = _TRAN_ROW_RE.match(line)
        if m:
            waveform.times_s.append(float(m.group(1)))
            waveform.voltages_v.append(float(m.group(2)))
    return waveform


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


def run_transient(
    netlist: str,
    node: str,
    *,
    step_s: float = 1e-9,
    stop_s: float = 100e-6,
    timeout_s: float = 60.0,
) -> TransientResult:
    """Run a transient (``.tran``) simulation on *netlist* and return a waveform.

    Parameters
    ----------
    netlist:
        SPICE netlist to simulate.  Must not already contain a ``.tran`` or
        ``.control`` block — this function injects one automatically.
    node:
        Net name to capture (e.g. ``"vout"``).
    step_s:
        Timestep in seconds.
    stop_s:
        Stop time in seconds.
    timeout_s:
        Maximum wall-clock time for the ngspice process.

    Returns
    -------
    TransientResult
        ``status="skipped"`` when ngspice is absent; ``status="error"`` on
        timeout or non-zero exit; ``status="ok"`` with parsed waveform data.
    """
    if not ngspice_available():
        return TransientResult(status="skipped", reason="ngspice not installed")

    sim_netlist = with_tran_control(netlist, step_s, stop_s, node)
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
            return TransientResult(status="error", raw_output=output, reason=f"ngspice exited {proc.returncode}")
        waveform = parse_tran_output(output, node)
        return TransientResult(status="ok", waveforms={node: waveform}, raw_output=output)
    except subprocess.TimeoutExpired:
        return TransientResult(status="error", reason=f"ngspice timed out after {timeout_s}s")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
