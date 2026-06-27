"""Constraint-aware placement intelligence. (#113)

Analyses placement constraints from the :class:`ConstraintSet`, groups
components functionally by net connectivity, scores placement candidates
against constraints, and detects potential issues (decoupling caps far from
ICs, mixed-signal separation, keepout violations, edge-proximity rules).

This is *intelligence*, not a placer: it does not move components. It reads a
design's existing or proposed placement and tells an agent or downstream tool
*what* to fix and *why*, using the same deterministic, evidence-bearing style
as the rest of the synthesis module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from zaptrace.core.models import ConstraintSet, Design, PlacementIntent

# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionalGroup:
    """A cluster of components that share a common function via net connectivity."""

    name: str
    component_ids: tuple[str, ...]
    net_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlacementObservation:
    """A single structured observation about a placement.

    Each observation carries an explicit *severity*, a human-readable *message*,
    a list of *component_ids* involved, and the *constraint* that produced it
    (or ``None`` for advisory observations like decoupling-cap proximity).
    """

    severity: str  # "info" | "warning" | "error"
    category: str  # "grouping" | "proximity" | "keepout" | "edge" | "separation" | "intent"
    message: str
    component_ids: list[str] = field(default_factory=list)
    constraint: PlacementIntent | None = None
    suggestion: str = ""


@dataclass(frozen=True)
class PlacementCandidate:
    """A scored placement option for a component or group.

    ``score`` ranges from 0.0 (worst) to 1.0 (perfect). Two candidates with
    the same component can be compared to choose the better placement.
    """

    component_id: str
    x_mm: float
    y_mm: float
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlacementAnalysis:
    """Full constraint-aware placement analysis result."""

    groups: list[FunctionalGroup] = field(default_factory=list)
    observations: list[PlacementObservation] = field(default_factory=list)
    candidates: list[PlacementCandidate] = field(default_factory=list)
    score: float = 1.0  # overall placement score (1.0 = all constraints met)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _glob_match(pattern: str, value: str) -> bool:
    """Simple glob match: supports trailing ``*`` wildcard."""
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern.rstrip("*"))
    return value == pattern


def _comp_ids_for_glob(design: Design, pattern: str) -> list[str]:
    """Return component IDs whose ref or id matches *pattern*."""
    return [
        cid
        for cid, comp in design.components.items()
        if _glob_match(pattern, comp.ref) or _glob_match(pattern, cid)
    ]


def _comp_id_by_ref(design: Design, ref: str) -> str | None:
    """Return the component ID for a given reference designator."""
    for cid, comp in design.components.items():
        if comp.ref == ref:
            return cid
    return None


def _distance_mm(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# ---------------------------------------------------------------------------
# Functional grouping
# ---------------------------------------------------------------------------


def group_components(design: Design) -> list[FunctionalGroup]:
    """Group components by shared-net connectivity.

    Every component that shares a net with another becomes part of that net's
    group. A component on multiple nets merges those nets' groups.  The result
    is a list of disjoint functional clusters, each with a human-readable name
    derived from the net names.
    """
    # Build ref -> component_id lookup
    ref_to_id: dict[str, str] = {}
    for cid, comp in design.components.items():
        ref_to_id[comp.ref] = cid

    # net_id -> set of component IDs
    net_to_comps: dict[str, set[str]] = {}
    for net_id, net in design.nets.items():
        comps: set[str] = set()
        for node in net.nodes:
            cid = node.component_ref
            # node.component_ref could be a ref or id — resolve to id
            if cid in design.components:
                comps.add(cid)
            elif cid in ref_to_id:
                comps.add(ref_to_id[cid])
        if comps:
            net_to_comps[net_id] = comps

    if not net_to_comps:
        return []

    # Union-find to merge groups that share components
    parent: dict[str, str] = {}
    all_comp_ids: set[str] = set()

    def _find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for comps in net_to_comps.values():
        comp_list = list(comps)
        for c in comp_list:
            all_comp_ids.add(c)
            if c not in parent:
                parent[c] = c
        for i in range(1, len(comp_list)):
            _union(comp_list[0], comp_list[i])

    # Collect groups
    root_to_comps: dict[str, set[str]] = {}
    for cid in all_comp_ids:
        root = _find(cid)
        root_to_comps.setdefault(root, set()).add(cid)

    # Name groups from their nets
    groups: list[FunctionalGroup] = []
    for root, comps in root_to_comps.items():
        net_ids: set[str] = set()
        for net_id, comps_on_net in net_to_comps.items():
            if comps_on_net & comps:
                net_ids.add(net_id)
        net_names = [design.nets[nid].name for nid in net_ids if nid in design.nets]
        name = ", ".join(sorted(net_names)) if net_names else f"group_{root}"
        groups.append(
            FunctionalGroup(
                name=name,
                component_ids=tuple(sorted(comps)),
                net_ids=tuple(sorted(net_ids)),
            )
        )

    return groups


# ---------------------------------------------------------------------------
# Decoupling-cap heuristics
# ---------------------------------------------------------------------------


def _is_decoupling_cap(component: Any) -> bool:
    """Heuristic check: is this component likely a decoupling capacitor?"""
    ctype = getattr(component, "type", "").lower()
    ref = getattr(component, "ref", "").upper()
    value = getattr(component, "value", "") or ""
    if ctype == "capacitor" or ref.startswith("C"):
        val_lower = value.lower().strip()
        if val_lower:
            if "uf" in val_lower or "µf" in val_lower or "mf" in val_lower:
                try:
                    num = float(val_lower.replace("uf", "").replace("µf", "").replace("mf", "").strip())
                    if num >= 10.0:
                        return False  # bulk cap, not decoupling
                except ValueError:
                    pass
            elif "pf" in val_lower or "nf" in val_lower:
                return True  # definitely decoupling / filter
            elif val_lower.endswith("f"):
                try:
                    num = float(val_lower.rstrip("f"))
                    if num < 1.0:
                        return True
                except ValueError:
                    pass
        return True
    return False


# ---------------------------------------------------------------------------
# Keepout / clearance checks
# ---------------------------------------------------------------------------


def _check_keepouts(
    design: Design,
    constraints: ConstraintSet,
) -> list[PlacementObservation]:
    """Check that placement constraints are satisfied."""
    observations: list[PlacementObservation] = []
    placement = design.placement
    if not placement:
        return observations

    for intent in constraints.placement:
        # Intent with `near`: check proximity
        if intent.near and intent.max_distance_mm:
            target_ids = _comp_ids_for_glob(design, intent.near)
            subject_ids = _comp_ids_for_glob(design, intent.component)
            if not target_ids:
                continue

            for cid in subject_ids:
                if cid not in placement:
                    continue
                pos = placement[cid]
                distances = [_distance_mm(pos, placement[tc]) for tc in target_ids if tc in placement]
                if distances:
                    min_dist = min(distances)
                    if min_dist > intent.max_distance_mm:
                        comp = design.components[cid]
                        observations.append(
                            PlacementObservation(
                                severity="warning",
                                category="keepout",
                                message=(
                                    f"{comp.ref} ({cid}) is {min_dist:.1f} mm from {intent.near}, "
                                    f"exceeds max_distance_mm={intent.max_distance_mm:.1f} mm"
                                ),
                                component_ids=[cid] + target_ids,
                                constraint=intent,
                                suggestion=f"Move {comp.ref} within {intent.max_distance_mm:.1f} mm of {intent.near}",
                            )
                        )

        # Intent with `edge`: check board-edge proximity
        if intent.edge:
            board = design.board
            bw = board.width_mm if hasattr(board, "width_mm") else 100.0
            bh = board.height_mm if hasattr(board, "height_mm") else 80.0
            edge_margin = 10.0

            subject_ids = _comp_ids_for_glob(design, intent.component)
            for cid in subject_ids:
                if cid not in placement:
                    continue
                pos = placement[cid]
                x, y = pos
                near_edge = False
                if (
                    intent.edge == "left" and x < edge_margin
                    or intent.edge == "right" and x > bw - edge_margin
                    or intent.edge == "top" and y > bh - edge_margin
                    or intent.edge == "bottom" and y < edge_margin
                ):
                    near_edge = True
                if not near_edge:
                    comp = design.components[cid]
                    observations.append(
                        PlacementObservation(
                            severity="warning",
                            category="edge",
                            message=(
                                f"{comp.ref} ({cid}) should be near the {intent.edge} board edge "
                                f"(current: x={x:.1f}, y={y:.1f})"
                            ),
                            component_ids=[cid],
                            constraint=intent,
                            suggestion=f"Move {comp.ref} to the {intent.edge} edge of the board",
                        )
                    )

    return observations


# ---------------------------------------------------------------------------
# Decoupling cap proximity check
# ---------------------------------------------------------------------------


def _check_decoupling_proximity(design: Design) -> list[PlacementObservation]:
    """Check that decoupling capacitors are close to the ICs they serve.

    For each decoupling cap, finds the *nearest* IC and warns if it's too far.
    A cap that is within 5 mm of at least one IC is considered well-placed.
    """
    observations: list[PlacementObservation] = []
    placement = design.placement
    if not placement:
        return observations

    ic_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower() in ("ic", "mcu", "microcontroller", "regulator", "sensor", "op-amp", "amplifier")
    ]
    if not ic_ids:
        return observations

    # Pre-compute IC positions
    ic_positions = {ic_id: placement[ic_id] for ic_id in ic_ids if ic_id in placement}
    if not ic_positions:
        return observations

    for cid, comp in design.components.items():
        if not _is_decoupling_cap(comp) or cid not in placement:
            continue
        cap_pos = placement[cid]

        # Find the closest IC
        min_dist = min(
            (_distance_mm(cap_pos, ic_pos) for ic_pos in ic_positions.values()),
            default=float("inf"),
        )
        if min_dist == float("inf"):
            continue

        if min_dist > 10.0:
            nearest_ic_id = min(
                ic_positions,
                key=lambda ic_id: _distance_mm(cap_pos, ic_positions[ic_id]),
            )
            nearest_ic = design.components[nearest_ic_id]
            observations.append(
                PlacementObservation(
                    severity="warning",
                    category="proximity",
                    message=(
                        f"Decoupling cap {comp.ref} ({cid}) is {min_dist:.1f} mm from "
                        f"nearest IC {nearest_ic.ref} ({nearest_ic_id}); "
                        "recommend < 5 mm for effective decoupling"
                    ),
                    component_ids=[cid, nearest_ic_id],
                    suggestion=f"Move {comp.ref} within 5 mm of an IC",
                )
            )
        elif min_dist > 5.0:
            nearest_ic_id = min(
                ic_positions,
                key=lambda ic_id: _distance_mm(cap_pos, ic_positions[ic_id]),
            )
            nearest_ic = design.components[nearest_ic_id]
            observations.append(
                PlacementObservation(
                    severity="info",
                    category="proximity",
                    message=(
                        f"Decoupling cap {comp.ref} ({cid}) is {min_dist:.1f} mm from "
                        f"nearest IC {nearest_ic.ref} ({nearest_ic_id}); "
                        "optimal is < 5 mm"
                    ),
                    component_ids=[cid, nearest_ic_id],
                    suggestion=f"Move {comp.ref} within 5 mm of {nearest_ic.ref} for best decoupling",
                )
            )

    return observations


# ---------------------------------------------------------------------------
# Analog / digital separation check
# ---------------------------------------------------------------------------


def _check_analog_digital_separation(design: Design) -> list[PlacementObservation]:
    """Flag analog components placed near noisy digital components."""
    observations: list[PlacementObservation] = []
    placement = design.placement
    if not placement:
        return observations

    analog_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower() in ("sensor", "op-amp", "amplifier", "adc", "dac", "analog", "filter")
    ]
    digital_ids = [
        cid
        for cid, comp in design.components.items()
        if comp.type.lower()
        in ("ic", "mcu", "microcontroller", "regulator", "switcher", "dc-dc", "digital", "cpld", "fpga")
    ]

    for a_id in analog_ids:
        if a_id not in placement:
            continue
        a_pos = placement[a_id]
        for d_id in digital_ids:
            if d_id not in placement:
                continue
            d_pos = placement[d_id]
            dist = _distance_mm(a_pos, d_pos)
            if dist < 5.0:
                a_comp = design.components[a_id]
                d_comp = design.components[d_id]
                observations.append(
                    PlacementObservation(
                        severity="warning",
                        category="separation",
                        message=(
                            f"Analog component {a_comp.ref} ({a_id}) is {dist:.1f} mm from "
                            f"digital/noisy component {d_comp.ref} ({d_id}); "
                            "recommend >= 5 mm separation to reduce noise coupling"
                        ),
                        component_ids=[a_id, d_id],
                        suggestion=f"Increase separation between {a_comp.ref} and {d_comp.ref}",
                    )
                )

    return observations


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------


def _score_placement_for_component(
    design: Design,
    component_id: str,
    x_mm: float,
    y_mm: float,
    constraints: ConstraintSet,
) -> PlacementCandidate:
    """Score a single (component_id, x, y) placement candidate.

    Score components:
    - 0.3: proximity to connected components (via nets)
    - 0.3: constraint intent matching (edge, near)
    - 0.2: board-edge margin (avoid placing near edges unless required)
    - 0.2: analog/digital separation
    """
    score = 1.0
    reasons: list[str] = []
    placement = design.placement
    assert placement is not None, "design.placement must be set before scoring"
    comp = design.components.get(component_id)
    if comp is None:
        return PlacementCandidate(
            component_id=component_id, x_mm=x_mm, y_mm=y_mm, score=0.0, reasons=["unknown component"]
        )

    board = design.board
    bw = board.width_mm if hasattr(board, "width_mm") else 100.0
    bh = board.height_mm if hasattr(board, "height_mm") else 80.0
    margin = 5.0

    # --- Board-edge margin (0.2) ---
    edge_dist = min(x_mm, bw - x_mm, y_mm, bh - y_mm)
    if edge_dist < margin:
        score -= 0.15
        reasons.append(f"too close to board edge ({edge_dist:.1f} mm < {margin:.1f} mm margin)")

    # --- Constraint intent matching (0.3) ---
    constraint_score = 0.3
    for intent in constraints.placement:
        if not _glob_match(intent.component, comp.ref) and not _glob_match(intent.component, component_id):
            continue

        if intent.edge:
            on_correct_edge = False
            if (
                intent.edge == "bottom" and y_mm < margin
                or intent.edge == "top" and y_mm > bh - margin
                or intent.edge == "left" and x_mm < margin
                or intent.edge == "right" and x_mm > bw - margin
            ):
                on_correct_edge = True
            if on_correct_edge:
                constraint_score += 0.05
                reasons.append(f"on correct board edge ({intent.edge})")
            else:
                constraint_score -= 0.03

        if intent.near and intent.max_distance_mm:
            target_ids = _comp_ids_for_glob(design, intent.near)
            target_positions = [placement[tcid] for tcid in target_ids if tcid in placement]
            if target_positions:
                min_d = min(_distance_mm((x_mm, y_mm), tp) for tp in target_positions)
                if min_d <= intent.max_distance_mm:
                    constraint_score += 0.05
                    reasons.append(
                        f"within {intent.max_distance_mm:.1f} mm of {intent.near} ({min_d:.1f} mm)"
                    )
                else:
                    constraint_score -= 0.03

    score -= (0.3 - constraint_score)

    # --- Proximity to connected components (0.3) ---
    connected_comps: set[str] = set()
    for net in design.nets.values():
        for node in net.nodes:
            if node.component_ref in (component_id, comp.ref):
                for other in net.nodes:
                    if other.component_ref not in (component_id, comp.ref):
                        connected_comps.add(other.component_ref)

    if connected_comps:
        avg_dist = 0.0
        count = 0
        for cc_ref in connected_comps:
            cc_id = next(
                (cid for cid, c in design.components.items() if c.ref == cc_ref),
                None,
            )
            if cc_id and cc_id in placement:
                cd = _distance_mm((x_mm, y_mm), placement[cc_id])
                avg_dist += cd
                count += 1
        if count > 0:
            avg_dist /= count
            if avg_dist < 10.0:
                score += 0.05
                reasons.append(f"close to {count} connected component(s) (avg {avg_dist:.1f} mm)")
            elif avg_dist > 30.0:
                score -= 0.1
                reasons.append(f"far from {count} connected component(s) (avg {avg_dist:.1f} mm)")

    # --- Analog/digital separation (0.2) ---
    is_analog = comp.type.lower() in ("sensor", "op-amp", "amplifier", "adc", "dac", "analog", "filter")
    is_digital = comp.type.lower() in ("mcu", "microcontroller", "digital", "cpld", "fpga", "switcher", "dc-dc")
    if is_analog or is_digital:
        for other_id, other_comp in design.components.items():
            if other_id == component_id:
                continue
            other_type = other_comp.type.lower()
            if other_id not in placement:
                continue
            other_pos = placement[other_id]
            d = _distance_mm((x_mm, y_mm), other_pos)
            if is_analog and other_type in ("mcu", "microcontroller", "switcher", "dc-dc", "digital") and d < 5.0:
                score -= 0.1
                reasons.append(f"analog {comp.ref} too close to digital {other_comp.ref} ({d:.1f} mm)")
            if is_digital and other_type in ("sensor", "analog", "adc", "dac") and d < 5.0:
                score -= 0.05

    return PlacementCandidate(
        component_id=component_id,
        x_mm=x_mm,
        y_mm=y_mm,
        score=max(0.0, min(1.0, score)),
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_placement(design: Design) -> PlacementAnalysis:
    """Run a full constraint-aware placement analysis on *design*.

    Produces:
    - Functional groups (clusters of connected components)
    - Observations (warnings, infos, errors about the current placement)
    - Scored placement candidates for each component
    - An overall placement score (1.0 = all constraints met, no issues)
    """
    groups = group_components(design)
    observations: list[PlacementObservation] = []
    candidates: list[PlacementCandidate] = []
    constraints = design.constraints

    observations.extend(_check_keepouts(design, constraints))
    observations.extend(_check_decoupling_proximity(design))
    observations.extend(_check_analog_digital_separation(design))

    if not constraints.placement and design.placement:
        observations.append(
            PlacementObservation(
                severity="info",
                category="intent",
                message="Design has placement data but no placement constraints; consider adding PlacementIntent items",
                suggestion="Add placement constraints via design.constraints.placement",
            )
        )

    if design.placement:
        for cid in design.components:
            if cid in design.placement:
                pos = design.placement[cid]
                candidate = _score_placement_for_component(design, cid, pos[0], pos[1], constraints)
                candidates.append(candidate)

    # Overall score: average of candidate scores, penalized by warnings/errors
    warning_count = sum(1 for o in observations if o.severity == "warning")
    error_count = sum(1 for o in observations if o.severity == "error")
    base_score = sum(c.score for c in candidates) / max(len(candidates), 1) if candidates else 1.0
    overall = base_score - (warning_count * 0.02) - (error_count * 0.05)
    overall = max(0.0, min(1.0, overall))

    return PlacementAnalysis(
        groups=groups,
        observations=observations,
        candidates=candidates,
        score=overall,
    )
