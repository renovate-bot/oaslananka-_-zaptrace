from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from zaptrace.core.models import Design, RouteResult, TraceSegment
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)


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
    """
    Route all nets using Manhattan L-shaped routing.

    For each net with 2+ connected components:
    - Find the (x,y) positions of all connected components
    - Build an MST (minimum spanning tree) of component positions
    - Route each MST edge as a Manhattan L-shaped path

    Returns RoutingResult with all route segments.
    """
    segments: list[RouteSegment] = []
    routed = 0
    unrouted: list[str] = []
    total = 0

    # Build a mapping from component ref to position (positions dict uses component ID)
    ref_positions: dict[str, tuple[float, float]] = {}
    for c in design.components.values():
        if c.id in positions:
            ref_positions[c.ref] = positions[c.id]
        # Also check if the ref itself is a key in positions
        if c.ref in positions:
            ref_positions[c.ref] = positions[c.ref]

    for net in design.nets.values():
        nodes_with_pos = [
            ref_positions[node.component_ref] for node in net.nodes if node.component_ref in ref_positions
        ]
        if len(nodes_with_pos) < 2:
            continue

        total += 1
        try:
            net_segments = _route_net_mst(nodes_with_pos, net.name)
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


def _route_net_mst(
    positions: list[tuple[float, float]],
    net_name: str,
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
    for i, j in mst_edges:
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        mid_x = x2
        segments.append(RouteSegment(x1, y1, mid_x, y1, net_name))
        segments.append(RouteSegment(mid_x, y1, x2, y2, net_name))

    return segments


# ---------------------------------------------------------------------------
# Net-class-aware routing — extends route_nets with EE knowledge
# ---------------------------------------------------------------------------


def route_design_smart(
    design: Design,
    positions: dict[str, tuple[float, float]],
    kb: KnowledgeBase | None = None,
    layer: str = "F.Cu",
) -> tuple[RoutingResult, RouteResult]:
    """Route all nets with net-class-aware trace widths.

    Classifies nets first (via :func:`classify_design`), then looks up
    appropriate trace widths from the EE knowledge base and applies them
    to each net's MST routing.

    Produces both the legacy :class:`RoutingResult` and the new
    :class:`RouteResult` (Pydantic model with :class:`TraceSegment` items).

    Args:
        design: Design to route (will be classified in-place).
        positions: Component-ID → (x, y) placement positions.
        kb: Optional knowledge base for net-class rules. If ``None``,
            a default ``KnowledgeBase()`` is created.
        layer: Output layer name for ``RouteResult`` traces.

    Returns:
        Tuple of ``(RoutingResult, RouteResult)``.
    """
    if kb is None:
        kb = KnowledgeBase()

    # Classify nets so we know the class per net
    classify_design(design)

    # Build ref-to-position lookup
    ref_positions: dict[str, tuple[float, float]] = {}
    for c in design.components.values():
        if c.id in positions:
            ref_positions[c.ref] = positions[c.id]
        if c.ref in positions:
            ref_positions[c.ref] = positions[c.ref]

    segments: list[RouteSegment] = []
    traces: list[TraceSegment] = []
    routed = 0
    unrouted: list[str] = []
    total = 0
    total_length = 0.0

    for net in design.nets.values():
        nodes_with_pos = [
            ref_positions[node.component_ref] for node in net.nodes if node.component_ref in ref_positions
        ]
        if len(nodes_with_pos) < 2:
            continue

        total += 1

        # Determine trace width from net class
        net_class = get_net_class(design, net.id)
        rule = kb.get_rule(net_class)
        width_mm = rule.trace_width

        try:
            net_segments = _route_net_mst(nodes_with_pos, net.name)
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

            routed += 1
        except Exception:
            logger.warning("Failed to route net %s; marking unrouted", net.name, exc_info=True)
            unrouted.append(net.name)

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

    return routing_result, route_result
