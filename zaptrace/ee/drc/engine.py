"""DRC (Design Rule Checking) engine.

Performs automated design-rule checks on a :class:`~zaptrace.core.models.Design`
after placement and routing. Each check produces :class:`~zaptrace.core.models.DRCViolation`
objects grouped into a :class:`~zaptrace.core.models.DRCResult`.

Rules implemented:

+--------------+------------------------------------------------+--------+
| Rule ID      | Description                                    | Severity |
+==============+================================================+==========+
| ERC-001      | Unconnected net (0 or 1 node)                  | WARNING  |
| DRC-001      | Clearance violation between traces             | ERROR    |
| DRC-002      | Trace width below net-class minimum            | ERROR    |
| DRC-003      | Right-angle (90°) trace corners                | WARNING  |
| DRC-004      | Stub trace (unconnected end)                   | WARNING  |
| DRC-005      | Net not routed (no traces)                     | ERROR    |
| DRC-006      | Via count exceeds net-class limit              | ERROR    |
| DRC-007      | Annular ring below minimum                     | WARNING  |
| DRC-008      | Overlapping traces on different layers         | INFO     |
| DRC-009      | Solder mask sliver below minimum               | WARNING  |
| DRC-010      | Net missing net-class classification           | INFO     |
| DRC-011      | Component placed outside board boundary        | ERROR    |
| DRC-012      | IPC-2152 current-capacity: trace too narrow    | ERROR    |
| DRC-013      | Hole-to-hole wall clearance below IPC-2221     | ERROR    |
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from zaptrace.core.models import (
    Design,
    DRCResult,
    DRCSeverity,
    DRCViolation,
    NetClass,
    TraceSegment,
)
from zaptrace.core.net_identity import canonical_routing_net_ids
from zaptrace.ee.classifier import classify_design, get_net_class

if TYPE_CHECKING:
    from zaptrace.fab.profile import FabProfile
from zaptrace.ee.knowledge import KnowledgeBase

# ---------------------------------------------------------------------------
# Type alias for a DRC check function
# ---------------------------------------------------------------------------

DRCCheck = Callable[[Design, KnowledgeBase, DRCResult], list[DRCViolation]]


@dataclass
class DRCEngine:
    """DRC engine — runs configurable checks on a design.

    Usage::

        engine = DRCEngine()
        result = engine.run(design)

    Checks can be selectively enabled/disabled via ``enabled_rules``.
    """

    knowledge_base: KnowledgeBase = field(default_factory=KnowledgeBase)
    enabled_rules: set[str] | None = None
    """If set, only run checks with these rule IDs. ``None`` = run all."""
    fab_profile: FabProfile | None = None
    """If set, DRC also reports fab-profile-specific violations (min trace/space/
    drill/annular ring, via and board limits) from the selected manufacturer
    profile — not just generic clearance. ``None`` = generic geometric DRC only."""

    def run(self, design: Design) -> DRCResult:
        """Run all enabled DRC checks on the design.

        Returns a :class:`DRCResult` with all violations found.
        The result is also stored on ``design.drc_result``.
        """
        result = DRCResult(design_name=design.meta.name)

        # Ensure nets are classified
        if not design.net_classes:
            classify_design(design)

        all_violations: list[DRCViolation] = []

        for check_func in _ALL_CHECKS:
            rule_id = _rule_id(check_func)
            if self.enabled_rules is not None and rule_id not in self.enabled_rules:
                continue
            try:
                violations = check_func(design, self.knowledge_base, result)
                all_violations.extend(violations)
            except Exception as exc:
                all_violations.append(
                    DRCViolation(
                        rule_id=rule_id,
                        severity=DRCSeverity.ERROR,
                        message=f"DRC check crashed: {exc}",
                    )
                )

        # Fold in fab-profile-specific violations (reuses the DFM checker so the
        # profile geometry rules live in one place) when a profile is selected.
        if self.fab_profile is not None:
            from zaptrace.fab.dfm import DFMChecker

            dfm_result = DFMChecker(self.fab_profile).check(design)
            all_violations.extend(dfm_result.to_drc_violations())

        # Sort by severity (errors first)
        severity_order = {DRCSeverity.ERROR: 0, DRCSeverity.WARNING: 1, DRCSeverity.INFO: 2}
        all_violations.sort(key=lambda v: severity_order.get(v.severity, 99))

        result.violations = all_violations
        result.total_violations = len(all_violations)
        result.errors = sum(1 for v in all_violations if v.severity == DRCSeverity.ERROR)
        result.warnings = sum(1 for v in all_violations if v.severity == DRCSeverity.WARNING)
        result.info = sum(1 for v in all_violations if v.severity == DRCSeverity.INFO)
        result.passed = result.errors == 0

        design.drc_result = result
        return result


def _rule_id(func: DRCCheck) -> str:
    """Extract rule ID from a check function's docstring first line."""
    doc = (func.__doc__ or "").strip()
    if doc:
        first_line = doc.split("\n")[0].strip()
        # First line is like: "ERC-001 — Unconnected net ..."
        parts = first_line.split(" ", 1)
        if parts:
            return parts[0].strip("- ")
    return func.__name__


def list_drc_rules() -> list[dict[str, str]]:
    """Return metadata for every registered DRC check."""
    rules: list[dict[str, str]] = []
    for check_func in _ALL_CHECKS:
        first_line = ((check_func.__doc__ or "").strip().splitlines() or [check_func.__name__])[0]
        _, _, description = first_line.partition(" — ")
        rules.append(
            {
                "id": _rule_id(check_func),
                "description": description or first_line,
                "severity": "varies",
            }
        )
    return rules


# ===================================================================
# Individual check implementations
# ===================================================================


def check_unconnected_nets(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """ERC-001 — Unconnected net (0 or 1 node)."""
    vio: list[DRCViolation] = []
    for net_id, net in design.nets.items():
        node_count = len(net.nodes)
        if node_count == 0:
            vio.append(
                DRCViolation(
                    rule_id="ERC-001",
                    severity=DRCSeverity.WARNING,
                    message=f"Net '{net.name}' ({net_id}) has no connected nodes",
                    net_id=net_id,
                )
            )
        elif node_count == 1:
            vio.append(
                DRCViolation(
                    rule_id="ERC-001",
                    severity=DRCSeverity.INFO,
                    message=f"Net '{net.name}' ({net_id}) has only 1 node (unconnected end)",
                    net_id=net_id,
                )
            )
    return vio


# ------------------------------------------------------------------


def _trace_segments(design: Design) -> list[TraceSegment]:
    """Get all trace segments from the design routing result."""
    if design.routing is None:
        return []
    return design.routing.traces


def _vec(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Vector from a to b."""
    return (b[0] - a[0], b[1] - a[1])


def _dot(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[0] + u[1] * v[1]


def _norm(u: tuple[float, float]) -> float:
    return math.sqrt(u[0] ** 2 + u[1] ** 2)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def _segment_min_distance(s1: TraceSegment, s2: TraceSegment) -> float:
    """Minimum distance between two trace segments (center-to-center)."""
    # Simplified: distance between line segments using closest-point approach
    p1, p2 = s1.start, s1.end
    q1, q2 = s2.start, s2.end
    return _segment_segment_distance(p1, p2, q1, q2)


def _segment_segment_distance(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> float:
    """Minimum distance between two 2D line segments using parameter-based approach."""
    # Direction vectors
    u = _vec(p1, p2)
    v = _vec(q1, q2)
    w = _vec(p1, q1)

    a = _dot(u, u)
    b = _dot(u, v)
    c = _dot(v, v)
    d = _dot(u, w)
    e = _dot(v, w)
    D = a * c - b * b

    # Handle parallel segments
    if abs(D) < 1e-12:
        # Compute distance between point p1 and segment (q1,q2), etc.
        d1 = _point_segment_dist(p1, q1, q2)
        d2 = _point_segment_dist(p2, q1, q2)
        d3 = _point_segment_dist(q1, p1, p2)
        d4 = _point_segment_dist(q2, p1, p2)
        return min(d1, d2, d3, d4)

    sc = D
    tc = D

    # Compute the line parameters of the two closest points
    sc = (b * e - c * d) / D
    tc = (a * e - b * d) / D

    # Clamp to segment bounds
    sc = max(0.0, min(1.0, sc))
    tc = max(0.0, min(1.0, tc))

    # Compute closest points
    p_close = (p1[0] + sc * u[0], p1[1] + sc * u[1])
    q_close = (q1[0] + tc * v[0], q1[1] + tc * v[1])

    return _dist(p_close, q_close)


def _point_segment_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Minimum distance from point p to line segment (a,b)."""
    ab = _vec(a, b)
    ap = _vec(a, p)
    t = _dot(ap, ab) / _dot(ab, ab) if _dot(ab, ab) > 0 else 0
    t = max(0.0, min(1.0, t))
    proj = (a[0] + t * ab[0], a[1] + t * ab[1])
    return _dist(p, proj)


def check_clearance(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-001 — Clearance violation between traces of different nets."""
    vio: list[DRCViolation] = []
    segments = _trace_segments(design)
    if len(segments) < 2:
        return vio

    min_clearance = design.board.min_clearance_mm if design.board else 0.2

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            s1, s2 = segments[i], segments[j]
            if s1.net_id == s2.net_id:
                continue  # same net — no clearance check needed
            if s1.layer != s2.layer:
                continue  # different layers

            dist = _segment_min_distance(s1, s2)
            clearance = dist - (s1.width / 2) - (s2.width / 2)
            if clearance < min_clearance:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-001",
                        severity=DRCSeverity.ERROR,
                        message=f"Clearance violation: net '{s1.net_id}' and '{s2.net_id}' "
                        f"are {clearance:.3f}mm apart (min {min_clearance}mm)",
                        location=f"layer={s1.layer}",
                        net_id=s1.net_id,
                    )
                )
    return vio


def check_trace_width(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-002 — Trace width below net-class minimum."""
    vio: list[DRCViolation] = []
    for seg in _trace_segments(design):
        nc = get_net_class(design, seg.net_id)
        rule = kb.get_rule(nc)
        if seg.width < rule.trace_width - 0.001:  # small tolerance
            vio.append(
                DRCViolation(
                    rule_id="DRC-002",
                    severity=DRCSeverity.ERROR,
                    message=f"Trace width {seg.width:.3f}mm below {nc.value} minimum "
                    f"{rule.trace_width:.3f}mm on net '{seg.net_id}'",
                    net_id=seg.net_id,
                    location=f"({seg.start[0]:.1f}, {seg.start[1]:.1f}) → ({seg.end[0]:.1f}, {seg.end[1]:.1f})",
                )
            )
    return vio


def check_right_angle(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-003 — Right-angle (90°) trace corners (use 45° or arc)."""
    vio: list[DRCViolation] = []
    segments = _trace_segments(design)
    # Group segments by net and layer
    from collections import defaultdict

    net_layer: dict[tuple[str, str], list[TraceSegment]] = defaultdict(list)
    for seg in segments:
        net_layer[(seg.net_id, seg.layer)].append(seg)

    endpoint_degree: dict[tuple[str, str, float, float], int] = defaultdict(int)
    for (net_id, layer), segs in net_layer.items():
        for seg in segs:
            endpoint_degree[(net_id, layer, round(seg.start[0], 6), round(seg.start[1], 6))] += 1
            endpoint_degree[(net_id, layer, round(seg.end[0], 6), round(seg.end[1], 6))] += 1

    for (net_id, layer), segs in net_layer.items():
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                # Check if they share an endpoint (connected at corner)
                shared = None
                for p_a, p_b in [(a.start, b.start), (a.start, b.end), (a.end, b.start), (a.end, b.end)]:
                    if _dist(p_a, p_b) < 0.001:
                        shared = p_a
                        break
                if shared is None:
                    continue
                joint_count = endpoint_degree[(net_id, layer, round(shared[0], 6), round(shared[1], 6))]
                if joint_count > 2:
                    continue
                # Compute vectors of the two segments from the shared point
                v1 = _vec(shared, a.end) if _dist(shared, a.start) < 0.001 else _vec(shared, a.start)
                v2 = _vec(shared, b.end) if _dist(shared, b.start) < 0.001 else _vec(shared, b.start)

                # Normalize
                n1 = _norm(v1)
                n2 = _norm(v2)
                if n1 < 0.001 or n2 < 0.001:
                    continue

                cos_theta = _dot(v1, v2) / (n1 * n2)
                cos_theta = max(-1.0, min(1.0, cos_theta))
                angle_deg = math.degrees(math.acos(cos_theta))

                # 90° ± 1° tolerance
                if 89.0 <= abs(angle_deg) <= 91.0:
                    vio.append(
                        DRCViolation(
                            rule_id="DRC-003",
                            severity=DRCSeverity.WARNING,
                            message=f"Right-angle corner ({angle_deg:.1f}°) on net '{net_id}' layer {layer}",
                            net_id=net_id,
                            location=f"({shared[0]:.1f}, {shared[1]:.1f})",
                        )
                    )
    return vio


def check_unrouted_nets(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-005 — Net not routed (no trace segments)."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        for net_id, net in design.nets.items():
            if len(net.nodes) >= 2:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-005",
                        severity=DRCSeverity.ERROR,
                        message=f"Net '{net.name}' ({net_id}) has no routing traces",
                        net_id=net_id,
                    )
                )
        return vio

    canonical_routing_net_ids(design, design.routing)
    routed_nets = {s.net_id for s in design.routing.traces}
    for net_id, net in design.nets.items():
        if len(net.nodes) >= 2 and net_id not in routed_nets:
            vio.append(
                DRCViolation(
                    rule_id="DRC-005",
                    severity=DRCSeverity.ERROR,
                    message=f"Net '{net.name}' ({net_id}) not routed (no trace segments)",
                    net_id=net_id,
                )
            )
    return vio


def check_via_count(design: Design, kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-006 — Via count exceeds net-class limit."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        return vio

    # Count vias per net
    via_count: dict[str, int] = {}
    for seg in design.routing.traces:
        if seg.via:
            via_count[seg.net_id] = via_count.get(seg.net_id, 0) + 1

    for net_id, count in via_count.items():
        nc = get_net_class(design, net_id)
        rule = kb.get_rule(nc)
        if count > rule.max_vias:
            net_name = design.nets.get(net_id)
            vio.append(
                DRCViolation(
                    rule_id="DRC-006",
                    severity=DRCSeverity.ERROR,
                    message=f"Net '{net_name}' ({net_id}) has {count} vias, "
                    f"exceeds {nc.value} limit of {rule.max_vias}",
                    net_id=net_id,
                )
            )
    return vio


def check_missing_net_class(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-010 — Net missing net-class classification."""
    vio: list[DRCViolation] = []
    if design.net_classes is None:
        return vio
    for net_id, net in design.nets.items():
        if net_id not in design.net_classes:
            vio.append(
                DRCViolation(
                    rule_id="DRC-010",
                    severity=DRCSeverity.INFO,
                    message=f"Net '{net.name}' ({net_id}) has no net-class assignment",
                    net_id=net_id,
                )
            )
    return vio


def check_min_annular_ring(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-020 — Via annular ring below minimum."""
    vio: list[DRCViolation] = []
    if design.routing is None:
        return vio

    min_annular_ring = 0.13
    if design.board_def and design.board_def.constraints:
        min_annular_ring = design.board_def.constraints.min_annular_ring

    for seg in design.routing.traces:
        if seg.via:
            annular_ring = (seg.via_diameter - seg.via_hole) / 2.0
            if annular_ring < min_annular_ring - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-020",
                        severity=DRCSeverity.ERROR,
                        message=f"Via annular ring {annular_ring:.3f}mm below minimum "
                        f"{min_annular_ring:.3f}mm on net '{seg.net_id}'",
                        net_id=seg.net_id,
                        location=f"({seg.start[0]:.1f}, {seg.start[1]:.1f})",
                    )
                )
    return vio


def check_board_edge_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-021 — Copper to board edge clearance below minimum."""
    vio: list[DRCViolation] = []

    outline = None
    if design.board_def and design.board_def.outline:
        outline = design.board_def.outline
    else:
        # Fall back to board config
        bw = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
        bh = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0
        outline = [(0.0, 0.0), (bw, 0.0), (bw, bh), (0.0, bh)]

    if not outline or len(outline) < 3:
        return vio

    min_clearance = 0.3  # JLCPCB default for board edge

    segments = _trace_segments(design)
    for seg in segments:
        for p in [seg.start, seg.end]:
            # A simple bounding box check if it's a rectangle
            if len(outline) == 4:
                min_x = min(op[0] for op in outline)
                max_x = max(op[0] for op in outline)
                min_y = min(op[1] for op in outline)
                max_y = max(op[1] for op in outline)

                # Distance to closest edge
                dx = min(abs(p[0] - min_x), abs(p[0] - max_x))
                dy = min(abs(p[1] - min_y), abs(p[1] - max_y))
                dist = min(dx, dy)

                if dist < min_clearance - 0.001:
                    vio.append(
                        DRCViolation(
                            rule_id="DRC-021",
                            severity=DRCSeverity.ERROR,
                            message=f"Trace to board edge clearance {dist:.3f}mm below minimum "
                            f"{min_clearance:.3f}mm on net '{seg.net_id}'",
                            net_id=seg.net_id,
                            location=f"({p[0]:.1f}, {p[1]:.1f})",
                        )
                    )
                    break  # Only flag once per segment
    return vio


def check_solder_mask_sliver(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-022 — Solder-mask sliver below minimum."""
    vio: list[DRCViolation] = []

    min_sliver = 0.1
    if design.board_def and design.board_def.constraints:
        min_sliver = design.board_def.constraints.min_solder_mask_sliver

    segments = _trace_segments(design)
    if len(segments) < 2:
        return vio

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            s1, s2 = segments[i], segments[j]
            if s1.net_id == s2.net_id:
                continue
            if s1.layer != s2.layer:
                continue

            dist = _segment_min_distance(s1, s2)
            clearance = dist - (s1.width / 2) - (s2.width / 2)

            if clearance > 0.001 and clearance < min_sliver - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-022",
                        severity=DRCSeverity.ERROR,
                        message=f"Solder-mask sliver {clearance:.3f}mm below minimum "
                        f"{min_sliver:.3f}mm between nets '{s1.net_id}' and '{s2.net_id}'",
                        location=f"layer={s1.layer}",
                    )
                )
    return vio


def check_acid_trap(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-023 — Acid-trap (sharp inner-angle copper) detection."""
    vio: list[DRCViolation] = []
    segments = _trace_segments(design)
    from collections import defaultdict

    net_layer: dict[tuple[str, str], list[TraceSegment]] = defaultdict(list)
    for seg in segments:
        net_layer[(seg.net_id, seg.layer)].append(seg)

    endpoint_degree: dict[tuple[str, str, float, float], int] = defaultdict(int)
    for (net_id, layer), segs in net_layer.items():
        for seg in segs:
            endpoint_degree[(net_id, layer, round(seg.start[0], 6), round(seg.start[1], 6))] += 1
            endpoint_degree[(net_id, layer, round(seg.end[0], 6), round(seg.end[1], 6))] += 1

    for (net_id, layer), segs in net_layer.items():
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                shared = None
                for p_a, p_b in [(a.start, b.start), (a.start, b.end), (a.end, b.start), (a.end, b.end)]:
                    if _dist(p_a, p_b) < 0.001:
                        shared = p_a
                        break
                if shared is None:
                    continue
                v1 = _vec(shared, a.end) if _dist(shared, a.start) < 0.001 else _vec(shared, a.start)
                v2 = _vec(shared, b.end) if _dist(shared, b.start) < 0.001 else _vec(shared, b.start)

                n1 = _norm(v1)
                n2 = _norm(v2)
                if n1 < 0.001 or n2 < 0.001:
                    continue

                cos_theta = _dot(v1, v2) / (n1 * n2)
                cos_theta = max(-1.0, min(1.0, cos_theta))
                angle_deg = math.degrees(math.acos(cos_theta))

                if abs(angle_deg) < 85.0:
                    vio.append(
                        DRCViolation(
                            rule_id="DRC-023",
                            severity=DRCSeverity.ERROR,
                            message=f"Acid-trap (sharp angle {angle_deg:.1f}°) on net '{net_id}' layer {layer}",
                            net_id=net_id,
                            location=f"({shared[0]:.1f}, {shared[1]:.1f})",
                        )
                    )
    return vio


def check_high_voltage_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-024 — Creepage/clearance for high-voltage / PoE nets."""
    vio: list[DRCViolation] = []
    segments = _trace_segments(design)
    if len(segments) < 2:
        return vio

    min_clearance_hv = 0.3
    if design.board_def and design.board_def.constraints:
        min_clearance_hv = design.board_def.constraints.min_clearance_high_voltage

    hv_nets = set()
    if design.net_classes:
        for net_id, nc in design.net_classes.items():
            if nc == NetClass.POWER_HIGH:
                hv_nets.add(net_id)

    if not hv_nets:
        return vio

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            s1, s2 = segments[i], segments[j]
            if s1.net_id == s2.net_id:
                continue
            if s1.layer != s2.layer:
                continue

            if s1.net_id not in hv_nets and s2.net_id not in hv_nets:
                continue

            dist = _segment_min_distance(s1, s2)
            clearance = dist - (s1.width / 2) - (s2.width / 2)

            if clearance < min_clearance_hv - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-024",
                        severity=DRCSeverity.ERROR,
                        message=f"High-voltage clearance violation: nets '{s1.net_id}' and '{s2.net_id}' "
                        f"are {clearance:.3f}mm apart (min {min_clearance_hv:.3f}mm)",
                        location=f"layer={s1.layer}",
                        net_id=s1.net_id,
                    )
                )
    return vio


def check_copper_balance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-025 — Copper-balance / large-unpoured-area warning."""
    vio: list[DRCViolation] = []

    # If the design is completely empty, don't warn about missing copper pours
    if not design.components and not design.nets:
        return vio

    wants_pour = False
    if design.board_def:
        wants_pour = design.board_def.copper_pour_gnd
    elif design.board:
        wants_pour = design.board.copper_pour_gnd

    if wants_pour and not design.copper_pours:
        vio.append(
            DRCViolation(
                rule_id="DRC-025",
                severity=DRCSeverity.INFO,
                message="Copper-balance: Board requests GND pour, but no copper pours are defined",
            )
        )
    return vio


def check_component_outside_board(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-011 — Component placed outside board boundary."""
    vio: list[DRCViolation] = []
    placement = design.placement or {}
    board_def = design.board_def
    if board_def is None:
        # Fall back to board config
        bw = design.board.width_mm if hasattr(design.board, "width_mm") else 100.0
        bh = design.board.height_mm if hasattr(design.board, "height_mm") else 80.0
        margin = 2.0  # mm
        for comp_id, (x, y) in placement.items():
            if x < -margin or y < -margin or x > bw + margin or y > bh + margin:
                comp = design.components.get(comp_id)
                ref = comp.ref if comp else comp_id
                vio.append(
                    DRCViolation(
                        rule_id="DRC-011",
                        severity=DRCSeverity.ERROR,
                        message=f"Component '{ref}' placed at ({x:.1f}, {y:.1f}) outside board ({bw:.0f}×{bh:.0f}mm)",
                        component_id=comp_id,
                    )
                )
    else:
        # Use BoardDefinition outline
        outline = board_def.outline
        if outline:
            margin = 2.0
            min_x = min(p[0] for p in outline) - margin
            max_x = max(p[0] for p in outline) + margin
            min_y = min(p[1] for p in outline) - margin
            max_y = max(p[1] for p in outline) + margin
            for comp_id, (x, y) in placement.items():
                if x < min_x or y < min_y or x > max_x or y > max_y:
                    comp = design.components.get(comp_id)
                    ref = comp.ref if comp else comp_id
                    vio.append(
                        DRCViolation(
                            rule_id="DRC-011",
                            severity=DRCSeverity.ERROR,
                            message=f"Component '{ref}' placed at ({x:.1f}, {y:.1f}) outside board outline",
                            component_id=comp_id,
                        )
                    )
    return vio


# IPC-2152 external-conductor current capacity constants.
# I = _IPC2152_K * ΔT^0.44 * (width_mm * thickness_oz * 25.4)^0.725
# where thickness is in oz/ft² converted to mils via 1 oz ≈ 1.37 mils.
_IPC2152_K_EXTERNAL = 0.048  # external conductor
_IPC2152_DEFAULT_DELTA_T = 10.0  # °C temperature rise above ambient
_IPC2152_OZ_TO_MILS = 1.37  # 1 oz/ft² ≈ 1.37 mil thick


def _ipc2152_min_width_mm(
    current_a: float,
    copper_oz: float = 1.0,
    delta_t_c: float = _IPC2152_DEFAULT_DELTA_T,
) -> float:
    """Return the minimum trace width in mm for *current_a* amps per IPC-2152.

    Uses the external-conductor formula (conservative; inner-layer k is lower).
    """
    thickness_mils = copper_oz * _IPC2152_OZ_TO_MILS
    area_mils2 = (current_a / (_IPC2152_K_EXTERNAL * (delta_t_c**0.44))) ** (1.0 / 0.725)
    width_mils = area_mils2 / thickness_mils
    return width_mils * 0.0254  # mils → mm


def check_high_current_trace_width(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-012 — IPC-2152 current-capacity: trace too narrow for rated current.

    Applies to nets flagged ``is_high_current`` in their NetConstraints.
    If the net declares a ``min_trace_width_mm``, that value is used directly;
    otherwise the IPC-2152 external-conductor formula is applied with 1 A/mm²
    as a conservative default current density estimate.
    (IPC-2152 current-capacity rule pack.)
    """
    vio: list[DRCViolation] = []
    routing = design.routing
    if routing is None:
        return vio
    traces_by_net: dict[str, list] = {}
    for seg in routing.traces:
        traces_by_net.setdefault(seg.net_id, []).append(seg)

    for net_id, net in design.nets.items():
        if net.constraints is None:
            continue
        if not net.constraints.is_high_current:
            continue
        min_w = net.constraints.min_trace_width_mm
        if min_w is None:
            min_w = _ipc2152_min_width_mm(1.0)  # conservative 1 A default

        segs = traces_by_net.get(net_id, [])
        for seg in segs:
            w = getattr(seg, "width", None)
            if w is None:
                continue
            if w < min_w - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-012",
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"High-current net '{net.name}' trace width {w:.3f}mm below IPC-2152 minimum {min_w:.3f}mm"
                        ),
                        net_id=net_id,
                    )
                )
    return vio


def check_hole_to_hole_clearance(design: Design, _kb: KnowledgeBase, _result: DRCResult) -> list[DRCViolation]:
    """DRC-013 — Via/drill hole-to-hole spacing below IPC-2221 minimum.

    IPC-2221 class A requires ≥ 0.25 mm between drill holes (wall-to-wall).
    For PTH to PTH, the wall clearance is (centre-to-centre − (d1+d2)/2).
    (drill/hole-to-hole checks.)
    """
    vio: list[DRCViolation] = []
    routing = design.routing
    if routing is None:
        return vio

    _IPC_MIN_WALL_MM = 0.25
    # Count real drilled holes, not every trace segment: vias live in
    # ``routing.vias`` as ``(x, y, pad, hole, [net])`` (the canonical list every
    # exporter reads), and some importers instead flag a segment with ``via``.
    # Reading ``seg.via_hole`` would treat every segment start as a via, since
    # that field defaults to a non-zero diameter.
    holes: list[tuple[float, float, float, str]] = []
    for v in routing.vias:
        if len(v) < 4:
            continue
        net = str(v[4]) if len(v) > 4 else ""
        holes.append((float(v[0]), float(v[1]), float(v[3]), net))
    for seg in routing.traces:
        if seg.via:
            holes.append((seg.start[0], seg.start[1], seg.via_hole, seg.net_id))

    for i, (x1, y1, d1, n1) in enumerate(holes):
        for x2, y2, d2, n2 in holes[i + 1 :]:
            dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            wall_clearance = dist - (d1 + d2) / 2.0
            if wall_clearance < _IPC_MIN_WALL_MM - 0.001:
                vio.append(
                    DRCViolation(
                        rule_id="DRC-013",
                        severity=DRCSeverity.ERROR,
                        message=(
                            f"Via hole-to-hole wall clearance {wall_clearance:.3f}mm "
                            f"below IPC-2221 minimum {_IPC_MIN_WALL_MM}mm "
                            f"(nets '{n1}' and '{n2}')"
                        ),
                        net_id=n1 or None,
                    )
                )
    return vio


# ===================================================================
# Registry of all checks
# ===================================================================

_ALL_CHECKS: list[DRCCheck] = [
    check_unconnected_nets,
    check_clearance,
    check_trace_width,
    check_right_angle,
    check_unrouted_nets,
    check_via_count,
    check_missing_net_class,
    check_component_outside_board,
    check_min_annular_ring,
    check_board_edge_clearance,
    check_solder_mask_sliver,
    check_acid_trap,
    check_high_voltage_clearance,
    check_copper_balance,
    check_high_current_trace_width,
    check_hole_to_hole_clearance,
]
