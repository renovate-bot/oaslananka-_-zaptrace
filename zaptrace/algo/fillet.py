"""Arc fillet post-processor for PCB traces.

Turns sharp 45°/90° routing corners into smooth circular arcs,
improving signal integrity, manufacturability, and aesthetic quality.

Usage::

    from zaptrace.algo.fillet import apply_fillets

    result.traces = apply_fillets(
        result.traces,
        default_radius=0.5,    # global max fillet radius
        segments_per_arc=8,    # polyline approximation quality
    )
"""

from __future__ import annotations

import math
from collections import defaultdict

from zaptrace.core.models import TraceSegment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANGLE_EPSILON = math.radians(10)  # skip near-straight joints
_MIN_RADIUS_MM = 0.05  # below this, fillet is skipped
_TANGENT_CLIP_RATIO = 0.40  # max tangent-dist as fraction of segment length


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_fillets(
    traces: list[TraceSegment],
    default_radius: float = 0.5,
    segments_per_arc: int = 8,
    min_radius: float = _MIN_RADIUS_MM,
    max_radius: float | None = None,
    radius_scale: float = 2.5,
    min_angle_deg: float = 15.0,
) -> list[TraceSegment]:
    """Apply arc fillets to every corner in the given traces.

    Parameters
    ----------
    traces:
        Input trace segments (typically from ``RouteResult.traces``).
    default_radius:
        Maximum fillet radius in mm.  Actual radius may be smaller
        if the corner is too tight or the segments too short.
    segments_per_arc:
        Number of linear segments used to approximate each arc.  Higher
        values create smoother curves.
    min_radius:
        Skip corners where the computed radius would be below this
        threshold.
    max_radius:
        Absolute maximum radius override. If ``None``, uses
        *default_radius*.
    radius_scale:
        Fillet radius as a multiple of the trace width at the corner.
        The actual radius is ``min(default_radius, width * radius_scale)``.
    min_angle_deg:
        Minimum corner angle in degrees.  Corners sharper than this
        (i.e., with an internal angle below *min_angle_deg*) are filleted;
        near-straight joints are left as-is.

    Returns
    -------
    list[TraceSegment]:
        New trace list with fillets applied.  Original segments may be
        shortened and new arc-approximation segments inserted.
    """
    if not traces:
        return []

    if max_radius is None:
        max_radius = default_radius

    # Group traces by net and layer for connected-path analysis
    groups: dict[str, list[TraceSegment]] = defaultdict(list)
    for t in traces:
        groups[t.net_id].append(t)

    result: list[TraceSegment] = []
    for _net_id, group in groups.items():
        # Build connection graph: endpoint -> list of trace indices
        endpoint_map: dict[tuple[float, float, str], list[int]] = defaultdict(list)
        for idx, seg in enumerate(group):
            if not seg.net_id:
                continue
            sig = (round(seg.start[0], 6), round(seg.start[1], 6), seg.layer)
            endpoint_map[sig].append(idx)
            eig = (round(seg.end[0], 6), round(seg.end[1], 6), seg.layer)
            endpoint_map[eig].append(idx)

        processed: set[int] = set()

        for idx, _seg in enumerate(group):
            if idx in processed:
                continue

            # Walk the segment chain
            chain = _walk_chain(group, idx, endpoint_map, processed)
            filleted = _fillet_chain(
                chain,
                default_radius=default_radius,
                segments_per_arc=segments_per_arc,
                min_radius=min_radius,
                max_radius=max_radius,
                radius_scale=radius_scale,
                min_angle_deg=min_angle_deg,
            )
            result.extend(filleted)

    return result


# ---------------------------------------------------------------------------
# Chain walking
# ---------------------------------------------------------------------------


def _walk_chain(
    group: list[TraceSegment],
    start_idx: int,
    endpoint_map: dict[tuple[float, float, str], list[int]],
    processed: set[int],
) -> list[TraceSegment]:
    """Walk a connected chain of trace segments starting at *start_idx*.

    Returns the chain as an ordered list of segments (head-to-tail).
    """
    chain: list[TraceSegment] = []
    visited: set[int] = {start_idx}
    queue: list[int] = [start_idx]

    while queue:
        idx = queue.pop(0)
        if idx in processed:
            continue
        processed.add(idx)
        chain.append(group[idx])

        for end_key in [
            (
                round(group[idx].start[0], 6),
                round(group[idx].start[1], 6),
                group[idx].layer,
            ),
            (
                round(group[idx].end[0], 6),
                round(group[idx].end[1], 6),
                group[idx].layer,
            ),
        ]:
            for nidx in endpoint_map.get(end_key, []):
                if nidx not in visited and nidx not in processed:
                    visited.add(nidx)
                    queue.append(nidx)

    # Sort chain into head-to-tail order
    if len(chain) <= 1:
        return chain

    return _order_chain(chain)


def _order_chain(chain: list[TraceSegment]) -> list[TraceSegment]:
    """Topological sort of connected segments into a continuous path.

    Works for simple chains (no branches).  For branched nets (multi-pin),
    each branch is handled independently by the caller via *endpoint_map*.
    """
    if len(chain) <= 1:
        return chain

    # Build endpoint -> list of (segment_index, is_start) mappings
    endpoint_info: dict[tuple[float, float, str], list[tuple[int, bool]]] = defaultdict(list)
    for i, s in enumerate(chain):
        ks = (round(s.start[0], 6), round(s.start[1], 6), s.layer)
        ke = (round(s.end[0], 6), round(s.end[1], 6), s.layer)
        endpoint_info[ks].append((i, True))
        endpoint_info[ke].append((i, False))

    # Find a chain endpoint (point with only one segment connection)
    start_idx = 0
    forward = True
    for conns in endpoint_info.values():
        if len(conns) == 1:
            idx, is_start = conns[0]
            start_idx = idx
            forward = is_start  # walk from start toward end
            break

    # Walk the chain
    ordered: list[TraceSegment] = []
    used: set[int] = set()
    seg = chain[start_idx]
    ordered.append(seg if forward else _reversed_seg(seg))
    used.add(start_idx)

    current_end = (
        round(ordered[-1].end[0], 6),
        round(ordered[-1].end[1], 6),
        ordered[-1].layer,
    )

    while len(ordered) < len(chain):
        found = False
        for idx, s in enumerate(chain):
            if idx in used:
                continue
            ks = (round(s.start[0], 6), round(s.start[1], 6), s.layer)
            ke = (round(s.end[0], 6), round(s.end[1], 6), s.layer)

            if ks == current_end:
                ordered.append(s)
                current_end = ke
                used.add(idx)
                found = True
                break
            if ke == current_end:
                ordered.append(_reversed_seg(s))
                current_end = ks
                used.add(idx)
                found = True
                break
        if not found:
            break

    return ordered


def _reversed_seg(s: TraceSegment) -> TraceSegment:
    """Return a copy of *s* with start/end swapped."""
    return TraceSegment(
        layer=s.layer,
        start=s.end,
        end=s.start,
        width=s.width,
        net_id=s.net_id,
    )


# ---------------------------------------------------------------------------
# Fillet computation
# ---------------------------------------------------------------------------


def _fillet_chain(
    chain: list[TraceSegment],
    default_radius: float = 0.5,
    segments_per_arc: int = 8,
    min_radius: float = _MIN_RADIUS_MM,
    max_radius: float = 0.5,
    radius_scale: float = 2.5,
    min_angle_deg: float = 15.0,
) -> list[TraceSegment]:
    """Apply fillets to all corners in a single trace chain."""
    if not chain:
        return []

    min_angle_rad = math.radians(min_angle_deg)
    result: list[TraceSegment] = []

    def _add(s: TraceSegment) -> None:
        result.append(s)

    prev: TraceSegment | None = None

    for seg in chain:
        if prev is None:
            prev = seg
            continue

        # Corners must be on the same layer
        if prev.layer != seg.layer:
            _add(prev)
            prev = seg
            continue

        # Shared endpoint
        prev_end = (round(prev.end[0], 6), round(prev.end[1], 6))
        seg_start = (round(seg.start[0], 6), round(seg.start[1], 6))

        if prev_end != seg_start:
            _add(prev)
            prev = seg
            continue

        # Corner at P = prev_end = seg_start
        p = prev_end

        # Direction vectors
        v_in = (prev.end[0] - prev.start[0], prev.end[1] - prev.start[1])
        v_out = (seg.end[0] - seg.start[0], seg.end[1] - seg.start[1])

        in_len = math.sqrt(v_in[0] ** 2 + v_in[1] ** 2)
        out_len = math.sqrt(v_out[0] ** 2 + v_out[1] ** 2)
        if in_len < 1e-9 or out_len < 1e-9:
            _add(prev)
            prev = seg
            continue

        v_in_u = (v_in[0] / in_len, v_in[1] / in_len)
        v_out_u = (v_out[0] / out_len, v_out[1] / out_len)

        # External angle between incoming (pointing toward P) and outgoing (away from P)
        # incoming_dir = -v_in_u (from P back along seg)
        # outgoing_dir = v_out_u (from P along seg)
        inv_u = (-v_in_u[0], -v_in_u[1])
        cos_theta = inv_u[0] * v_out_u[0] + inv_u[1] * v_out_u[1]
        cos_theta = max(-1.0, min(1.0, cos_theta))
        theta = math.acos(cos_theta)  # external angle (0 = straight, pi = U-turn)

        # Skip near-straight joints
        if theta < min_angle_rad or theta > math.pi - min_angle_rad:
            _add(prev)
            prev = seg
            continue

        # Internal angle for the arc
        internal = math.pi - theta

        if internal < math.radians(5):
            _add(prev)
            prev = seg
            continue

        # Compute fillet radius from trace width
        trace_w = max(prev.width, seg.width, 0.01)
        r = min(default_radius, trace_w * radius_scale)
        r = min(r, max_radius)

        # Distance from P to tangent point
        half_int = internal / 2.0
        tan_half = math.tan(half_int)
        if tan_half < 1e-9:
            _add(prev)
            prev = seg
            continue
        tangent_dist = r / tan_half

        # Clamp tangent distance to segment lengths
        max_t_in = in_len * _TANGENT_CLIP_RATIO
        max_t_out = out_len * _TANGENT_CLIP_RATIO
        ratio = min(max_t_in / tangent_dist, max_t_out / tangent_dist, 1.0)
        if ratio < 0.01:
            _add(prev)
            prev = seg
            continue
        tangent_dist *= ratio
        r *= ratio  # scale radius proportionally

        if r < min_radius:
            _add(prev)
            prev = seg
            continue

        # Tangent points
        t1 = (prev.end[0] - v_in_u[0] * tangent_dist, prev.end[1] - v_in_u[1] * tangent_dist)
        t2 = (seg.start[0] + v_out_u[0] * tangent_dist, seg.start[1] + v_out_u[1] * tangent_dist)

        # Center of arc
        bisector = (inv_u[0] + v_out_u[0], inv_u[1] + v_out_u[1])
        bisector_len = math.sqrt(bisector[0] ** 2 + bisector[1] ** 2)
        if bisector_len < 1e-9:
            _add(prev)
            prev = seg
            continue
        bisector_u = (bisector[0] / bisector_len, bisector[1] / bisector_len)
        sin_half = math.sin(half_int)
        center_dist = r / sin_half if sin_half > 1e-9 else 0.0
        center = (p[0] + bisector_u[0] * center_dist, p[1] + bisector_u[1] * center_dist)

        # Build shortened prev segment
        if math.dist(prev.start, t1) > 1e-6:
            _add(
                TraceSegment(
                    layer=prev.layer,
                    start=prev.start,
                    end=t1,
                    width=prev.width,
                    net_id=prev.net_id,
                )
            )

        # Arc approximation
        arc_segments = _approx_arc(
            center=center,
            t1=t1,
            t2=t2,
            r=r,
            inv_dir=inv_u,
            out_dir=v_out_u,
            n_segments=segments_per_arc,
            width=trace_w,
            net_id=prev.net_id,
            layer=prev.layer,
        )
        result.extend(arc_segments)

        # Build shortened out segment
        _add(
            TraceSegment(
                layer=seg.layer,
                start=t2,
                end=seg.end,
                width=seg.width,
                net_id=seg.net_id,
            )
        )

        prev = None  # current seg already consumed

    if prev is not None:
        _add(prev)

    return result


# ---------------------------------------------------------------------------
# Arc approximation
# ---------------------------------------------------------------------------


def _approx_arc(
    center: tuple[float, float],
    t1: tuple[float, float],
    t2: tuple[float, float],
    r: float,
    inv_dir: tuple[float, float],  # incoming direction unit (from P along prev seg toward corner)
    out_dir: tuple[float, float],  # outgoing direction unit (from corner along next seg)
    n_segments: int,
    width: float,
    net_id: str,
    layer: str,
) -> list[TraceSegment]:
    """Approximate a circular arc as *n_segments* linear segments."""
    rel1 = (t1[0] - center[0], t1[1] - center[1])
    rel2 = (t2[0] - center[0], t2[1] - center[1])

    a1 = math.atan2(rel1[1], rel1[0])
    a2 = math.atan2(rel2[1], rel2[0])

    # Compute shortest-arc sweep from T1 to T2.
    # The arc centre lies on the inside of the corner (via the bisector),
    # so the shortest angular path from T1 to T2 is the correct fillet arc.
    sweep = (a2 - a1) % (2.0 * math.pi)
    if sweep > math.pi:
        sweep -= 2.0 * math.pi
    if abs(sweep) < 1e-6:
        return []

    segments: list[TraceSegment] = []
    n = max(n_segments, 2)

    for i in range(n):
        frac = (i + 1) / n
        angle = a1 + sweep * frac
        px = center[0] + r * math.cos(angle)
        py = center[1] + r * math.sin(angle)

        prev_frac = i / n
        prev_angle = a1 + sweep * prev_frac
        ppx = center[0] + r * math.cos(prev_angle)
        ppy = center[1] + r * math.sin(prev_angle)

        if math.dist((ppx, ppy), (px, py)) > 1e-6:
            segments.append(
                TraceSegment(
                    layer=layer,
                    start=(round(ppx, 3), round(ppy, 3)),
                    end=(round(px, 3), round(py, 3)),
                    width=width,
                    net_id=net_id,
                )
            )

    return segments
