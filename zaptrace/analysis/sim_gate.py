"""DC operating-point as a blocking verification gate.

:mod:`zaptrace.analysis.spice_orchestrator` produces advisory simulation
evidence. This wraps it as a *gate* with the discipline from
``docs/design/autonomous-synthesis.md``:

* **An explicit skip is recorded, never a silent pass.** When ngspice is absent
  the gate returns ``SKIPPED`` (not ``PASS``); in **strict** mode a skip is
  *blocking*, so a release cannot quietly ship un-simulated.
* **A verified pass is distinct from "nothing was checked."** A run with no
  expected voltages returns ``NO_REFERENCE``, not ``PASS`` — an empty reference
  can never read as success.

The simulator itself is bundled in the container image (see ``Dockerfile``), so
in CI a skip means a real environment problem, not an accepted gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from zaptrace.analysis.spice_orchestrator import orchestrate_spice

if TYPE_CHECKING:
    from zaptrace.core.models import Design


class GateStatus(StrEnum):
    """Outcome of the simulation gate."""

    PASS = "pass"  # ran and every expected rail is within tolerance
    FAIL = "fail"  # ran and a rail is out of tolerance, or ngspice errored
    SKIPPED = "skipped"  # ngspice unavailable — explicitly recorded
    NO_REFERENCE = "no_reference"  # ran but there was nothing to check against


@dataclass
class SimulationGateResult:
    """A blocking verdict plus the evidence behind it."""

    status: GateStatus
    blocking: bool
    strict: bool
    design_name: str
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    node_voltages: dict[str, float] = field(default_factory=dict)

    @property
    def satisfied(self) -> bool:
        """True when the gate does not block the pipeline."""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "strict": self.strict,
            "design_name": self.design_name,
            "reason": self.reason,
            "checks": self.checks,
            "node_voltages": self.node_voltages,
        }


def _gate_verdict(
    orchestration_status: str,
    all_checks_passed: bool,
    has_checks: bool,
    strict: bool,
) -> tuple[GateStatus, bool, str]:
    """Pure mapping from an orchestration outcome to (status, blocking, reason).

    Kept free of I/O so every branch is unit-testable without ngspice installed.
    """
    if orchestration_status == "skipped":
        reason = "ngspice not available; recorded as an explicit skip"
        if strict:
            reason += " (blocking in strict mode)"
        return GateStatus.SKIPPED, strict, reason
    if orchestration_status == "error":
        return GateStatus.FAIL, True, "ngspice ran but failed or timed out"
    # orchestration_status == "ok"
    if not has_checks:
        return GateStatus.NO_REFERENCE, strict, "simulation ran but no expected voltages were supplied to check"
    if all_checks_passed:
        return GateStatus.PASS, False, "all expected rail voltages are within tolerance"
    return GateStatus.FAIL, True, "a simulated rail voltage is outside tolerance"


def run_simulation_gate(
    design: Design,
    *,
    expected_voltages: dict[str, float] | None = None,
    tolerance_pct: float = 5.0,
    strict: bool = False,
    timeout_s: float = 30.0,
) -> SimulationGateResult:
    """Run the DC operating-point gate on *design*.

    With no ``expected_voltages``, rail references are derived from the design's
    power-rail net names via :func:`expected_rail_voltages`, so the gate has
    something to check by default.
    """
    references = expected_voltages if expected_voltages is not None else expected_rail_voltages(design)
    orchestration = orchestrate_spice(
        design,
        expected_voltages=references or None,
        tolerance_pct=tolerance_pct,
        timeout_s=timeout_s,
    )
    has_checks = any(check.passed is not None for check in orchestration.checks)
    status, blocking, reason = _gate_verdict(orchestration.status, orchestration.all_checks_passed, has_checks, strict)
    return SimulationGateResult(
        status=status,
        blocking=blocking,
        strict=strict,
        design_name=orchestration.design_name,
        reason=reason,
        checks=[check.to_dict() for check in orchestration.checks],
        node_voltages=orchestration.node_voltages,
    )


def expected_rail_voltages(design: Design) -> dict[str, float]:
    """Derive expected rail voltages from the synthesis net-name convention.

    ``VDD_3V3`` -> 3.3, ``VDD_5`` -> 5.0, and any ground net -> 0.0. Returns only
    nets it can parse, so an unrecognized net never produces a bogus reference.
    """
    from zaptrace.core.models import NetType

    references: dict[str, float] = {}
    for net in design.nets.values():
        if net.type == NetType.GROUND:
            references[net.name] = 0.0
            continue
        volts = _rail_net_to_volts(net.name)
        if volts is not None:
            references[net.name] = volts
    return references


def _rail_net_to_volts(net_name: str) -> float | None:
    """Inverse of the ``VDD_<v>`` rail-net convention: 'VDD_3V3' -> 3.3."""
    if not net_name.startswith("VDD_"):
        return None
    token = net_name[len("VDD_") :].replace("V", ".", 1).rstrip(".")
    # A trailing 'V' (e.g. "5V") becomes "5." -> strip to "5"; "3V3" -> "3.3".
    try:
        return float(token)
    except ValueError:
        return None
