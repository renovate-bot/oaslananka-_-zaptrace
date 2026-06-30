"""Convergent self-correction: ERC violation -> typed patch -> re-verify.

This closes the second half of the synthesis loop from
``docs/design/autonomous-synthesis.md``: after :mod:`zaptrace.synthesis.architecture`
emits a candidate and ERC runs, ``repair_design`` maps each *auto-fixable*
violation class to a typed transform on the :class:`~zaptrace.core.models.Design`,
re-runs ERC, and repeats until a fixed point — bounded by a hard iteration cap so
it can never loop forever.

Two honesty invariants, straight from the design note:

* **Measured convergence, not hope.** Every iteration records the violation count
  before and after; if a round of patches does not reduce it, the loop stops
  rather than spinning.
* **Escalate what it cannot fix.** Violations with no handler (e.g. a single-pin
  net that needs a real connector) are left untouched and returned as
  ``remaining`` for a human — never silently "repaired".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.erc.runner import ERCRunner

if TYPE_CHECKING:
    from zaptrace.core.models import Component, Design
    from zaptrace.erc.rules import ERCViolation

# A round that applies patches but does not lower the violation count is a sign
# of a non-converging handler; the loop stops well before this many rounds.
_MAX_ITERATIONS = 8


@dataclass(frozen=True)
class Patch:
    """One typed edit made to fix a specific violation, with provenance."""

    rule_id: str
    component_ref: str
    field: str
    old_value: str
    new_value: str
    rationale: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "component_ref": self.component_ref,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RepairIteration:
    """Provenance for one synthesize/verify round: counts before and after."""

    index: int
    violations_before: int
    violations_after: int
    patches: list[Patch]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "violations_before": self.violations_before,
            "violations_after": self.violations_after,
            "patches": [p.to_dict() for p in self.patches],
        }


@dataclass
class RepairResult:
    """Outcome of the correction loop.

    ``converged`` means the loop reached a stable state (no more auto-fixable
    violations). ``fully_clean`` means nothing is left at all. ``remaining`` is
    the escalation list: violations no handler could fix.
    """

    iterations: list[RepairIteration] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)
    converged: bool = False
    remaining: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fully_clean(self) -> bool:
        return self.converged and not self.remaining

    def to_dict(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "fully_clean": self.fully_clean,
            "patch_count": len(self.patches),
            "iterations": [it.to_dict() for it in self.iterations],
            "patches": [p.to_dict() for p in self.patches],
            "remaining": self.remaining,
        }


# Standard package names by component type/value, matching the bare-name
# convention used across the example/template designs ("0402", "SOT-23-5").
# Confidence < 1.0 marks a reasonable-default choice rather than a part-exact one.
def _default_footprint(comp: Component) -> tuple[str, float] | None:
    """Pick a standard footprint for a component, or None when it cannot be known."""
    ctype = comp.type.lower()
    value = (comp.value or "").upper()
    if ctype == "resistor":
        return ("0402", 1.0)
    if ctype == "capacitor":
        return ("0402", 1.0)
    if ctype == "inductor":
        return ("0805", 0.9)
    if ctype == "led":
        return ("LED-0603", 1.0)
    if "TLV62569" in value:
        return ("SOT-23-5", 1.0)
    if value in ("MAX3485", "SN65HVD230"):
        return ("SOIC-8", 1.0)
    if ctype == "ldo" or value.startswith("LDO_"):
        return ("SOT-23-3", 0.9)
    return None  # unknown part: leave for human escalation, do not guess


def _repair_missing_footprint(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC020 handler: assign a standard footprint where one can be chosen safely."""
    patches: list[Patch] = []
    for violation in violations:
        for ref in violation.component_refs:
            comp = design.components.get(ref)
            if comp is None or comp.footprint:
                continue
            choice = _default_footprint(comp)
            if choice is None:
                continue  # unknown component type: escalate, do not invent
            footprint, confidence = choice
            patches.append(
                Patch(
                    rule_id="ERC020",
                    component_ref=ref,
                    field="footprint",
                    old_value=comp.footprint,
                    new_value=footprint,
                    rationale=f"assign standard {footprint} for {comp.type} {comp.value}".strip(),
                    confidence=confidence,
                )
            )
            comp.footprint = footprint
    return patches


# Board input nets in priority order: a regulator's enable ties to whichever
# input the board actually has.
_INPUT_NET_PRIORITY = ("VBUS", "VBAT", "VIN")


def _board_input_net(design: Design) -> str | None:
    for name in _INPUT_NET_PRIORITY:
        if name in design.nets:
            return name
    # No conventionally-named input: the DC-input rail is the net that carries
    # both the input connector and a regulator's input (the externally-supplied
    # highest rail, e.g. VDD_12 for a 12 V-in board).
    for net_id, net in design.nets.items():
        comps = [design.get_component(node.component_ref) for node in net.nodes]
        types = [c.type.lower() for c in comps if c is not None]
        has_connector = any("connector" in t or "header" in t or "jack" in t for t in types)
        has_regulator = any("regulator" in t for t in types)
        if has_connector and has_regulator:
            return net_id
    return None


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _repair_floating_enable(design: Design, violations: list[ERCViolation]) -> list[Patch]:
    """ERC012 handler: tie a floating regulator-enable net high with a pull-up.

    Only acts on nets following the synthesis enable convention (``EN_<rail>``): a
    floating enable means the regulator would never turn on. Adds a 100 kΩ pull-up
    to the board input so the rail is enabled by default. All other single-pin
    nets (data lines, connector pins, feedback) are left for a human — this never
    invents a connection it cannot justify.
    """
    from zaptrace.core.models import Component, Net, NetNode

    input_net = _board_input_net(design)
    if input_net is None:
        return []

    patches: list[Patch] = []
    for violation in violations:
        for net_id in violation.net_refs:
            net = design.nets.get(net_id)
            if net is None or len(net.nodes) >= 2:
                continue
            if not net_id.upper().startswith("EN_"):
                continue  # only regulator-enable nets; everything else escalates
            ref = _next_ref(design, "R")
            design.components[ref] = Component(id=ref, ref=ref, type="resistor", value="100k", footprint="0402")
            net.nodes.append(NetNode(component_ref=ref, pin_name="2"))
            design.nets.setdefault(input_net, Net(id=input_net, name=input_net)).nodes.append(
                NetNode(component_ref=ref, pin_name="1")
            )
            patches.append(
                Patch(
                    rule_id="ERC012",
                    component_ref=ref,
                    field="net",
                    old_value="",
                    new_value=f"100k pull-up {net_id} -> {input_net}",
                    rationale=f"tie floating enable {net_id} high to {input_net} (always-on)",
                    confidence=0.8,
                )
            )
    return patches


# rule_id -> handler. Each handler mutates the design in place and returns the
# patches it made. A rule with no handler is, by definition, escalated.
_HANDLERS: dict[str, Callable[[Design, list[ERCViolation]], list[Patch]]] = {
    "ERC020": _repair_missing_footprint,
    "ERC012": _repair_floating_enable,
}


def _violation_dict(violation: ERCViolation) -> dict[str, Any]:
    return {
        "rule_id": violation.rule_id,
        "severity": violation.severity.value,
        "message": violation.message,
        "component_refs": list(violation.component_refs),
        "net_refs": list(violation.net_refs),
    }


def repair_design(design: Design, *, max_iterations: int = _MAX_ITERATIONS) -> RepairResult:
    """Run the bounded ERC -> patch -> re-verify loop on *design* in place.

    Returns a :class:`RepairResult` recording every iteration, every patch, and
    the violations left for a human. The design is mutated as patches apply.
    """
    runner = ERCRunner()
    result = RepairResult()

    for index in range(max_iterations):
        erc = runner.run(design)
        before = len(erc.violations)

        by_rule: dict[str, list[ERCViolation]] = defaultdict(list)
        for violation in erc.violations:
            by_rule[violation.rule_id].append(violation)

        patches: list[Patch] = []
        for rule_id, handler in _HANDLERS.items():
            if rule_id in by_rule:
                patches.extend(handler(design, by_rule[rule_id]))

        if not patches:
            # Fixed point: nothing left this loop knows how to fix.
            result.converged = True
            result.remaining = [_violation_dict(v) for v in erc.violations]
            return result

        after = len(runner.run(design).violations)
        result.iterations.append(RepairIteration(index, before, after, patches))
        result.patches.extend(patches)

        if after >= before:
            # A patch round failed to reduce violations: stop rather than spin.
            break

    # Hit the cap or a non-progressing round: report whatever is left.
    final = runner.run(design)
    result.remaining = [_violation_dict(v) for v in final.violations]
    return result


def synthesize_and_repair(intent: str, *, name: str = "SynthesizedBoard") -> dict[str, Any]:
    """Synthesize a board from intent, then run the self-correction loop.

    Ties :func:`zaptrace.synthesis.architecture.build_architecture_design` to
    :func:`repair_design` so an agent gets, in one call, a netlist *and* the
    record of what the loop fixed and what still needs a human.
    """
    from zaptrace.synthesis.architecture import build_architecture_design
    from zaptrace.synthesis.footprint_resolver import resolve_footprints
    from zaptrace.synthesis.requirements import parse_requirements

    requirements = parse_requirements(intent)
    design, plan, log = build_architecture_design(requirements, name=name)
    repair = repair_design(design)
    # Footprint names are now assigned; attach real pad geometry so exports work.
    footprints = resolve_footprints(design)
    return {
        "intent": intent,
        "design": design,
        "plan": plan,
        "decision_log": log,
        "repair": repair,
        "footprints": footprints,
    }
