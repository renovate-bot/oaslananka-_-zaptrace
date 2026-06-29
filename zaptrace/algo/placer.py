from __future__ import annotations

import math

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design


def place_components(design: Design) -> dict[str, tuple[float, float]]:
    """
    Assign (x, y) positions to all components on the board.

    Algorithm:
    1. Grid-based initial placement (equal spacing across board)
    2. Force-directed refinement (20 iterations):
       - Spring attraction between connected components
       - Coulomb repulsion between all component pairs
    3. Clamp to board bounds
    4. Enforce min 5mm spacing

    Returns: dict mapping component_id -> (x_mm, y_mm)
    """
    try:
        from zaptrace._core import place_components as _rust_place

        n = len(design.components)
        connections = _build_connections(design)
        board = canonical_board_definition(design)
        positions_raw = _rust_place(n, board.width, board.height, connections, 5.0)
        ids = list(design.components.keys())
        return {ids[i]: pos for i, pos in enumerate(positions_raw)}
    except ImportError:
        return _place_python(design)


_POWER_NET_PREFIXES = ("GND", "VSS", "VDD", "VCC", "VBUS", "VBAT", "VIN", "AGND", "DGND")


def _is_power_net(name: str) -> bool:
    """Power/ground nets fan out to nearly every part; they steer placement
    nowhere useful and go to copper pour, so they are excluded from the springs."""
    upper = name.upper()
    return any(upper.startswith(p) for p in _POWER_NET_PREFIXES)


def _build_connections(design: Design) -> list[tuple[int, int]]:
    # Build index from component ref (designator) to position in component list
    ref_to_idx: dict[str, int] = {}
    for c in design.components.values():
        if c.ref not in ref_to_idx:
            ref_to_idx[c.ref] = len(ref_to_idx)
    connections: list[tuple[int, int]] = []
    for net in design.nets.values():
        if _is_power_net(net.name):
            continue
        refs = [n.component_ref for n in net.nodes]
        # A high-fan-out net (a bus) connected all-pairs would over-attract; wire
        # it as a star to its first node instead.
        if len(refs) > 4:
            for k in range(1, len(refs)):
                if refs[0] in ref_to_idx and refs[k] in ref_to_idx:
                    connections.append((ref_to_idx[refs[0]], ref_to_idx[refs[k]]))
            continue
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                if refs[i] in ref_to_idx and refs[j] in ref_to_idx:
                    connections.append((ref_to_idx[refs[i]], ref_to_idx[refs[j]]))
    return connections


def _place_python(design: Design) -> dict[str, tuple[float, float]]:
    """Pure Python grid placement + force-directed refinement."""
    comp_ids = list(design.components.keys())
    n = len(comp_ids)
    if n == 0:
        return {}

    board = canonical_board_definition(design)
    w, h = board.width, board.height
    margin = 5.0
    grid_cols = max(1, math.ceil(math.sqrt(n * w / h)))
    grid_rows = max(1, math.ceil(n / grid_cols))
    cell_w = (w - 2 * margin) / grid_cols
    cell_h = (h - 2 * margin) / grid_rows

    positions: dict[str, tuple[float, float]] = {}
    for idx, cid in enumerate(comp_ids):
        col = idx % grid_cols
        row = idx // grid_cols
        positions[cid] = (
            margin + col * cell_w + cell_w / 2,
            margin + row * cell_h + cell_h / 2,
        )

    connections = _build_connections(design)
    comp_ids_list = list(comp_ids)

    for _ in range(20):
        forces: dict[str, list[float]] = {cid: [0.0, 0.0] for cid in comp_ids}

        rest_length = 8.0  # target spacing between connected parts (no collapse)
        for a_idx, b_idx in connections:
            aid, bid = comp_ids_list[a_idx], comp_ids_list[b_idx]
            ax, ay = positions[aid]
            bx, by = positions[bid]
            dx, dy = bx - ax, by - ay
            dist = max(math.sqrt(dx**2 + dy**2), 0.1)
            # Spring with a rest length: attract past `rest_length`, push apart
            # within it, so highly-connected parts settle near (not on top of)
            # each other instead of collapsing to a point.
            k = 0.05
            stretch = dist - rest_length
            ux, uy = dx / dist, dy / dist
            forces[aid][0] += k * stretch * ux
            forces[aid][1] += k * stretch * uy
            forces[bid][0] -= k * stretch * ux
            forces[bid][1] -= k * stretch * uy

        for i, cid_i in enumerate(comp_ids):
            for j, cid_j in enumerate(comp_ids):
                if i >= j:
                    continue
                ax, ay = positions[cid_i]
                bx, by = positions[cid_j]
                dx, dy = bx - ax, by - ay
                dist = max(math.sqrt(dx**2 + dy**2), 0.1)
                if dist < 10.0:
                    rep = 2.0 / (dist**2)
                    fx, fy = -rep * dx / dist, -rep * dy / dist
                    forces[cid_i][0] += fx
                    forces[cid_i][1] += fy
                    forces[cid_j][0] -= fx
                    forces[cid_j][1] -= fy

        for cid in comp_ids:
            x, y = positions[cid]
            x = max(margin, min(w - margin, x + forces[cid][0]))
            y = max(margin, min(h - margin, y + forces[cid][1]))
            positions[cid] = (x, y)

    return positions
