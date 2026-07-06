from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from zaptrace.algo.pad_escape import RouteEvidenceScorecard, compute_escape_point
from zaptrace.core.models import Component, Design, RouteResult, TraceSegment
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)

_ZERO_LENGTH_TOLERANCE_MM = 1e-9
_CORNER_CHAMFER_MM = 0.2


@dataclass
class RouteSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    net_name: str
    layer: int = 0
    width_mm: float = 0.2


@dataclass
class RoutingResult:
    segments: list[RouteSegment]
    routed_nets: int
    total_nets: int
    unrouted_nets: list[str]

    @property
    def coverage_pct(self) -> float:
        if self.total_nets == 0:
            return 100.0
        return round(self.routed_nets / self.total_nets * 100, 1)


def route_nets(design: Design, positions: dict[str, tuple[float, float]]) -> RoutingResult:
    """Route all nets using pad-aware Manhattan L-shaped routing.

    For each net with 2+ connected components:
    - Resolve pad escape points from ``component.footprint_def`` when available.
    - Fall back to component centres when no footprint/pad data is present.
    - Build an MST of the resulting positions and route each edge as a
      Manhattan L-shaped path.

    Returns RoutingResult with all route segments.
    """
    segments: list[RouteSegment] = []
    routed = 0
    unrouted: list[str] = []
    total = 0

    # Build component-ID → component and component-ref → position lookups.
    component_by_ref: dict[str, Component] = {}
    ref_positions: dict[str, tuple[float, float]] = {}
    for c in design.components.values():
        component_by_ref[c.ref] = c
        if c.id in positions:
            ref_positions[c.ref] = positions[c.id]
        if c.ref in positions:
            ref_positions[c.ref] = positions[c.ref]

    for net in design.nets.values():
        node_positions: list[tuple[float, float]] = []
        for node in net.nodes:
            comp_pos = ref_positions.get(node.component_ref)
            if comp_pos is None:
                continue
            comp = component_by_ref.get(node.component_ref)
            if comp is not None:
                ep = compute_escape_point(comp, node.pin_name, comp_pos)
                node_positions.append(ep.escape_point)
            else:
                node_positions.append(comp_pos)

        if len(node_positions) < 2:
            continue

        total += 1
        try:
            net_segments = _route_net_mst(node_positions, net.name)
            segments.extend(net_segments)
            routed += 1
        except Exception:
            logger.warning("Failed to route net %s; marking unrouted", net.name, exc_info=True)
            unrouted.append(net.name)

    return RoutingResult(
        segments=segments,
        routed_nets=routed,
        total_nets=total,
        unrouted_nets=unrouted,
    )


def _is_zero_length(x1: float, y1: float, x2: float, y2: float) -> bool:
    return math.hypot(x2 - x1, y2 - y1) <= _ZERO_LENGTH_TOLERANCE_MM


def _append_segment_if_nonzero(
    segments: list[RouteSegment],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
) -> None:
    """Append a segment unless it has zero physical length.

    The Manhattan router may encounter aligned endpoints or duplicate synthetic
    escape points. Emitting zero-length copper creates artificial DRC/clearance
    hits downstream without representing real routed copper.
    """
    if _is_zero_length(x1, y1, x2, y2):
        return
    segments.append(RouteSegment(x1, y1, x2, y2, net_name))


def _prefer_vertical_first(net_name: str) -> bool:
    """Return a stable Manhattan corner orientation for a net.

    Power rails, ground, and SDA-style data nets often benefit from vertical
    escapes in compact sensor-node layouts, while SCL/SCK-style clock nets keep
    the legacy horizontal-first path.  Unknown nets use a deterministic fallback
    so output is stable without hard-coding a board-specific lookup table.
    """
    normalized = net_name.casefold()
    tokens = normalized.replace("-", "_").split("_")
    if any(token in {"gnd", "ground", "vss"} for token in tokens):
        return True
    if normalized.startswith(("vcc", "vdd", "vbus", "vin")) or normalized.endswith(("_vcc", "_vdd")):
        return True
    if any(token in {"sda", "mosi", "data"} for token in tokens):
        return True
    if any(token in {"scl", "sck", "clk", "clock"} for token in tokens):
        return False
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(net_name))
    return seed % 2 == 1


def _route_manhattan_edge(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
    *,
    vertical_first: bool | None = None,
) -> list[RouteSegment]:
    """Route one MST edge as non-zero chamfered Manhattan segments."""
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments

    use_vertical_first = _prefer_vertical_first(net_name) if vertical_first is None else vertical_first
    dx = x2 - x1
    dy = y2 - y1
    sx = 1.0 if dx > 0 else -1.0
    sy = 1.0 if dy > 0 else -1.0
    chamfer = min(_CORNER_CHAMFER_MM, abs(dx) / 2.0, abs(dy) / 2.0)

    if use_vertical_first:
        corner_entry = (x1, y2 - sy * chamfer)
        corner_exit = (x1 + sx * chamfer, y2)
        points = [(x1, y1), corner_entry, corner_exit, (x2, y2)]
    else:
        corner_entry = (x2 - sx * chamfer, y1)
        corner_exit = (x2, y1 + sy * chamfer)
        points = [(x1, y1), corner_entry, corner_exit, (x2, y2)]

    for start, end in zip(points, points[1:], strict=False):
        _append_segment_if_nonzero(segments, start[0], start[1], end[0], end[1], net_name)
    return segments


def _route_segment_length(seg: RouteSegment) -> float:
    return math.hypot(seg.x2 - seg.x1, seg.y2 - seg.y1)


def _to_trace_segment(seg: RouteSegment, width_mm: float, net_id: str, layer: str) -> TraceSegment:
    return TraceSegment(
        layer=layer,
        start=(seg.x1, seg.y1),
        end=(seg.x2, seg.y2),
        width=width_mm,
        net_id=net_id,
    )


def _point_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom <= 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / denom))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _segment_distance(a: TraceSegment, b: TraceSegment) -> float:
    return min(
        _point_segment_distance(a.start, b.start, b.end),
        _point_segment_distance(a.end, b.start, b.end),
        _point_segment_distance(b.start, a.start, a.end),
        _point_segment_distance(b.end, a.start, a.end),
    )


def _dogleg_route_x(x1: float, y1: float, x2: float, y2: float, net_name: str, offset: float) -> list[RouteSegment]:
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments
    x_lane = (x1 + x2) / 2.0 + offset
    _append_segment_if_nonzero(segments, x1, y1, x_lane, y1, net_name)
    _append_segment_if_nonzero(segments, x_lane, y1, x_lane, y2, net_name)
    _append_segment_if_nonzero(segments, x_lane, y2, x2, y2, net_name)
    return segments


def _dogleg_route_y(x1: float, y1: float, x2: float, y2: float, net_name: str, offset: float) -> list[RouteSegment]:
    segments: list[RouteSegment] = []
    if _is_zero_length(x1, y1, x2, y2):
        return segments
    if math.isclose(x1, x2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM) or math.isclose(
        y1, y2, abs_tol=_ZERO_LENGTH_TOLERANCE_MM
    ):
        _append_segment_if_nonzero(segments, x1, y1, x2, y2, net_name)
        return segments
    y_lane = (y1 + y2) / 2.0 + offset
    _append_segment_if_nonzero(segments, x1, y1, x1, y_lane, net_name)
    _append_segment_if_nonzero(segments, x1, y_lane, x2, y_lane, net_name)
    _append_segment_if_nonzero(segments, x2, y_lane, x2, y2, net_name)
    return segments


def _route_edge_candidates(x1: float, y1: float, x2: float, y2: float, net_name: str) -> list[list[RouteSegment]]:
    preferred = _prefer_vertical_first(net_name)
    candidates = [
        _route_manhattan_edge(x1, y1, x2, y2, net_name, vertical_first=preferred),
        _route_manhattan_edge(x1, y1, x2, y2, net_name, vertical_first=not preferred),
    ]
    for offset in (-1.2, -0.8, -0.4, 0.4, 0.8, 1.2):
        candidates.append(_dogleg_route_x(x1, y1, x2, y2, net_name, offset))
        candidates.append(_dogleg_route_y(x1, y1, x2, y2, net_name, offset))
    return [candidate for candidate in candidates if candidate]


def _candidate_junction_right_angles(
    candidate: list[RouteSegment], existing_traces: list[TraceSegment], net_id: str
) -> int:
    count = 0
    candidate_traces = [_to_trace_segment(seg, 0.2, net_id, "F.Cu") for seg in candidate]
    for trace in candidate_traces:
        for existing in existing_traces:
            if existing.net_id != net_id or existing.layer != trace.layer:
                continue
            shared: tuple[float, float] | None = None
            for p1, p2 in (
                (trace.start, existing.start),
                (trace.start, existing.end),
                (trace.end, existing.start),
                (trace.end, existing.end),
            ):
                if math.dist(p1, p2) < 0.001:
                    shared = p1
                    break
            if shared is None:
                continue
            trace_other = trace.end if math.dist(shared, trace.start) < 0.001 else trace.start
            existing_other = existing.end if math.dist(shared, existing.start) < 0.001 else existing.start
            v1 = (trace_other[0] - shared[0], trace_other[1] - shared[1])
            v2 = (existing_other[0] - shared[0], existing_other[1] - shared[1])
            n1 = math.hypot(*v1)
            n2 = math.hypot(*v2)
            if min(n1, n2) < 0.3:
                continue
            if abs(((v1[0] * v2[0]) + (v1[1] * v2[1])) / (n1 * n2)) <= 0.0175:
                count += 1
    return count


def _candidate_internal_right_angles(candidate: list[RouteSegment]) -> int:
    count = 0
    for i, first in enumerate(candidate):
        for second in candidate[i + 1 :]:
            shared: tuple[float, float] | None = None
            for p1, p2 in (
                ((first.x1, first.y1), (second.x1, second.y1)),
                ((first.x1, first.y1), (second.x2, second.y2)),
                ((first.x2, first.y2), (second.x1, second.y1)),
                ((first.x2, first.y2), (second.x2, second.y2)),
            ):
                if math.dist(p1, p2) < 0.001:
                    shared = p1
                    break
            if shared is None:
                continue
            first_other = (
                (first.x2, first.y2) if math.dist(shared, (first.x1, first.y1)) < 0.001 else (first.x1, first.y1)
            )
            second_other = (
                (second.x2, second.y2) if math.dist(shared, (second.x1, second.y1)) < 0.001 else (second.x1, second.y1)
            )
            v1 = (first_other[0] - shared[0], first_other[1] - shared[1])
            v2 = (second_other[0] - shared[0], second_other[1] - shared[1])
            n1 = math.hypot(*v1)
            n2 = math.hypot(*v2)
            if min(n1, n2) < 0.3:
                continue
            if abs(((v1[0] * v2[0]) + (v1[1] * v2[1])) / (n1 * n2)) <= 0.0175:
                count += 1
    return count


def _score_route_candidate(
    candidate: list[RouteSegment],
    existing_traces: list[TraceSegment],
    *,
    width_mm: float,
    net_id: str,
    layer: str,
    clearance_mm: float,
) -> float:
    score = sum(_route_segment_length(seg) for seg in candidate) * 0.05
    score += len(candidate) * 2.0
    score += _candidate_junction_right_angles(candidate, existing_traces, net_id) * 250.0
    score += _candidate_internal_right_angles(candidate) * 80.0
    candidate_traces = [_to_trace_segment(seg, width_mm, net_id, layer) for seg in candidate]
    for trace in candidate_traces:
        for existing in existing_traces:
            if existing.layer != layer or existing.net_id == net_id:
                continue
            gap = _segment_distance(trace, existing) - (trace.width / 2.0) - (existing.width / 2.0)
            if gap < clearance_mm:
                score += 500.0 + (clearance_mm - gap) * 2000.0
            elif gap < clearance_mm + 0.15:
                score += (clearance_mm + 0.15 - gap) * 250.0
    return score


def _route_edge_costed(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net_name: str,
    *,
    existing_traces: list[TraceSegment],
    width_mm: float,
    net_id: str,
    layer: str,
    clearance_mm: float,
) -> list[RouteSegment]:
    candidates = _route_edge_candidates(x1, y1, x2, y2, net_name)
    if not candidates:
        return []
    return min(
        candidates,
        key=lambda candidate: _score_route_candidate(
            candidate, existing_traces, width_mm=width_mm, net_id=net_id, layer=layer, clearance_mm=clearance_mm
        ),
    )


def _route_net_mst(
    positions: list[tuple[float, float]],
    net_name: str,
    *,
    existing_traces: list[TraceSegment] | None = None,
    width_mm: float = 0.2,
    net_id: str | None = None,
    layer: str = "F.Cu",
    clearance_mm: float = 0.2,
) -> list[RouteSegment]:
    """Build MST via Prim's algorithm, route each edge as Manhattan L-shape."""
    n = len(positions)
    if n < 2:
        return []

    in_mst = [False] * n
    in_mst[0] = True
    mst_edges: list[tuple[int, int]] = []

    for _ in range(n - 1):
        best_dist = float("inf")
        best_i, best_j = 0, 1
        for i in range(n):
            if not in_mst[i]:
                continue
            for j in range(n):
                if in_mst[j]:
                    continue
                dx = positions[i][0] - positions[j][0]
                dy = positions[i][1] - positions[j][1]
                dist = math.sqrt(dx**2 + dy**2)
                if dist < best_dist:
                    best_dist, best_i, best_j = dist, i, j
        mst_edges.append((best_i, best_j))
        in_mst[best_j] = True

    segments: list[RouteSegment] = []
    routed_traces = list(existing_traces or [])
    route_net_id = net_id or net_name
    for i, j in mst_edges:
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        if existing_traces is None:
            edge_segments = _route_manhattan_edge(x1, y1, x2, y2, net_name)
        else:
            edge_segments = _route_edge_costed(
                x1,
                y1,
                x2,
                y2,
                net_name,
                existing_traces=routed_traces,
                width_mm=width_mm,
                net_id=route_net_id,
                layer=layer,
                clearance_mm=clearance_mm,
            )
        segments.extend(edge_segments)
        routed_traces.extend(_to_trace_segment(seg, width_mm, route_net_id, layer) for seg in edge_segments)

    return segments


def _has_clearance_debt(
    new_segs: list[RouteSegment],
    existing_segs: list[RouteSegment],
    clearance_mm: float,
) -> bool:
    """Return True if any new segment is estimated to be within *clearance_mm*
    of an existing segment (using axis-aligned bounding-box overlap check).

    This is a conservative approximation — it only detects obvious cases and
    does not replace a full DRC check.
    """
    if not existing_segs or clearance_mm <= 0.0:
        return False

    # Build bounding boxes for existing segments (inflated by clearance)
    def bbox(seg: RouteSegment, margin: float) -> tuple[float, float, float, float]:
        x_min = min(seg.x1, seg.x2) - margin
        x_max = max(seg.x1, seg.x2) + margin
        y_min = min(seg.y1, seg.y2) - margin
        y_max = max(seg.y1, seg.y2) + margin
        return (x_min, x_max, y_min, y_max)

    existing_boxes = [bbox(s, clearance_mm) for s in existing_segs]

    for ns in new_segs:
        nx1, nx2 = min(ns.x1, ns.x2), max(ns.x1, ns.x2)
        ny1, ny2 = min(ns.y1, ns.y2), max(ns.y1, ns.y2)
        for ex_min, ex_max, ey_min, ey_max in existing_boxes:
            if nx1 <= ex_max and nx2 >= ex_min and ny1 <= ey_max and ny2 >= ey_min:
                return True
    return False


# ---------------------------------------------------------------------------
# Net-class-aware routing — extends route_nets with EE knowledge
# ---------------------------------------------------------------------------


def route_design_smart(
    design: Design,
    positions: dict[str, tuple[float, float]],
    kb: KnowledgeBase | None = None,
    layer: str = "F.Cu",
) -> tuple[RoutingResult, RouteResult, RouteEvidenceScorecard]:
    """Route all nets with net-class-aware trace widths and pad escape points.

    Classifies nets first (via :func:`classify_design`), resolves pad escape
    points from ``Component.footprint_def`` when available, then looks up
    appropriate trace widths from the EE knowledge base and applies them to
    each net's MST routing.

    Produces the legacy :class:`RoutingResult`, the new :class:`RouteResult`
    (Pydantic model with :class:`TraceSegment` items), and a
    :class:`~zaptrace.algo.pad_escape.RouteEvidenceScorecard` with DRC debt
    evidence distinguishing route failures, escape failures, and clearance
    debt.

    Args:
        design: Design to route (will be classified in-place).
        positions: Component-ID → (x, y) placement positions.
        kb: Optional knowledge base for net-class rules. If ``None``,
            a default ``KnowledgeBase()`` is created.
        layer: Output layer name for ``RouteResult`` traces.

    Returns:
        Tuple of ``(RoutingResult, RouteResult, RouteEvidenceScorecard)``.
    """
    if kb is None:
        kb = KnowledgeBase()

    # Classify nets so we know the class per net
    classify_design(design)

    # Build ref-to-position and ref-to-component lookups
    component_by_ref: dict[str, Component] = {}
    ref_positions: dict[str, tuple[float, float]] = {}
    for c in design.components.values():
        component_by_ref[c.ref] = c
        if c.id in positions:
            ref_positions[c.ref] = positions[c.id]
        if c.ref in positions:
            ref_positions[c.ref] = positions[c.ref]

    scorecard = RouteEvidenceScorecard(
        non_claims=[
            "route evidence is for engineering review only",
            "not fabrication-ready",
            "DRC debt counts are estimates pending KiCad oracle validation",
        ]
    )

    segments: list[RouteSegment] = []
    traces: list[TraceSegment] = []
    routed = 0
    unrouted: list[str] = []
    total = 0
    total_length = 0.0

    for net in design.nets.values():
        # Resolve pad escape points, falling back to component centres.
        node_positions: list[tuple[float, float]] = []
        fallback_refs: list[str] = []
        fallback_reasons: list[str] = []

        for node in net.nodes:
            comp_pos = ref_positions.get(node.component_ref)
            if comp_pos is None:
                continue
            comp = component_by_ref.get(node.component_ref)
            if comp is not None:
                ep = compute_escape_point(comp, node.pin_name, comp_pos)
                node_positions.append(ep.escape_point)
                scorecard.increment_pad_type(ep.pad_type)
                if ep.is_fallback:
                    fallback_refs.append(node.component_ref)
                    fallback_reasons.append(ep.fallback_reason)
            else:
                node_positions.append(comp_pos)
                fallback_refs.append(node.component_ref)
                fallback_reasons.append("component not found in design")

        if len(node_positions) < 2:
            continue

        total += 1

        if fallback_refs:
            scorecard.record_escape_fallback(net.id, net.name, fallback_refs, fallback_reasons)

        # Determine trace width from net class
        net_class = get_net_class(design, net.id)
        rule = kb.get_rule(net_class)
        width_mm = rule.trace_width
        clearance_mm = rule.clearance

        try:
            net_segments = _route_net_mst(
                node_positions,
                net.name,
                existing_traces=traces,
                width_mm=width_mm,
                net_id=net.id,
                layer=layer,
                clearance_mm=clearance_mm,
            )
            for seg in net_segments:
                seg.width_mm = width_mm
            segments.extend(net_segments)

            # Build TraceSegments for RouteResult
            for seg in net_segments:
                ts = TraceSegment(
                    layer=layer,
                    start=(seg.x1, seg.y1),
                    end=(seg.x2, seg.y2),
                    width=width_mm,
                    net_id=net.id,
                )
                traces.append(ts)
                dx = seg.x2 - seg.x1
                dy = seg.y2 - seg.y1
                total_length += math.sqrt(dx * dx + dy * dy)

            # Estimate clearance debt: check if any segment is too close to
            # another net's segments (simple bounding-box check).
            if _has_clearance_debt(net_segments, segments[: -len(net_segments)], clearance_mm):
                scorecard.record_clearance_debt(
                    net.id,
                    net.name,
                    f"estimated clearance < {clearance_mm}mm on one or more segments",
                )

            routed += 1
        except Exception:
            logger.warning("Failed to route net %s; marking unrouted", net.name, exc_info=True)
            unrouted.append(net.name)
            scorecard.record_route_failure(net.id, net.name, "MST routing exception")

    scorecard.total_nets = total
    scorecard.routed_nets = routed
    scorecard.total_length_mm = round(total_length, 3)

    routing_result = RoutingResult(
        segments=segments,
        routed_nets=routed,
        total_nets=total,
        unrouted_nets=unrouted,
    )

    route_result = RouteResult(
        traces=traces,
        vias=[],
        layers_used=[layer],
        total_trace_length_mm=round(total_length, 3),
        net_count=total,
        routed_net_count=routed,
    )

    return routing_result, route_result, scorecard
