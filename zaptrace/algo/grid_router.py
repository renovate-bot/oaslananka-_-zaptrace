"""Grid-based A* PCB router with 45-degree angle support.

This module provides a high-quality PCB routing engine that:
- Routes traces on a discretised grid using A* pathfinding
- Supports 8-direction movement for 45-degree routing angles
- Avoids obstacles (component bodies, board edges, other traces)
- Applies net-class-aware trace widths and clearances
- Supports multi-layer routing with via cost penalty
- Smoothes paths by removing collinear waypoints

Usage::

    from zaptrace.algo.grid_router import GridRouter

    router = GridRouter(resolution_mm=0.25)
    result = router.route(design, positions)
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design, NetClass, RouteResult, TraceSegment, Via
from zaptrace.ee.classifier import classify_design, get_net_class
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.defaults import DEFAULT_VIA_SPECS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQRT2 = math.sqrt(2.0)

# 8-direction movement: (dx, dy, unit_cost)
DIRECTIONS_8: list[tuple[int, int, float]] = [
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (1, 1, SQRT2),
    (-1, 1, SQRT2),
    (1, -1, SQRT2),
    (-1, -1, SQRT2),
]

# ---------------------------------------------------------------------------
# Grid Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridPos:
    """Integer position on the routing grid."""

    x: int
    y: int
    layer: int = 0


@dataclass
class _Node:
    """Internal A* node."""

    pos: GridPos
    g: float = 0.0
    h: float = 0.0
    f: float = 0.0
    parent: _Node | None = None

    def __lt__(self, other: _Node) -> bool:
        return self.f < other.f


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def _octile(a: GridPos, b: GridPos, via_cost: float = 10.0) -> float:
    """Admissible octile heuristic for 8-direction + via movement."""
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    dz = abs(a.layer - b.layer)
    diag = max(dx, dy) + (SQRT2 - 1.0) * min(dx, dy)
    return diag + dz * via_cost


def _reconstruct(node: _Node | None) -> list[GridPos]:
    """Walk parent chain to produce path from start to goal."""
    path: list[GridPos] = []
    while node is not None:
        path.append(node.pos)
        node = node.parent
    path.reverse()
    return path


def _manhattan_dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))


# ---------------------------------------------------------------------------
# Obstacle Map
# ---------------------------------------------------------------------------


class ObstacleMap:
    """Multi-layer grid obstacle map with clearance dilation.

    Each cell stores 0 (free) or 1 (blocked). Blocked cells can be
    dilated by a clearance radius so paths maintain minimum spacing.
    """

    def __init__(self, width: int, height: int, layers: int = 2) -> None:
        self.width = width
        self.height = height
        self.layers = layers
        # cells[layer][row][col]
        self._cells: list[list[list[int]]] = [[[0] * width for _ in range(height)] for _ in range(layers)]

    # -- Query ------------------------------------------------------------

    def in_bounds(self, pos: GridPos) -> bool:
        return 0 <= pos.layer < self.layers and 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def is_free(self, pos: GridPos) -> bool:
        return self.in_bounds(pos) and self._cells[pos.layer][pos.y][pos.x] == 0

    # -- Blocking primitives ----------------------------------------------

    def block(self, pos: GridPos) -> None:
        if self.in_bounds(pos):
            self._cells[pos.layer][pos.y][pos.x] = 1

    def unblock(self, pos: GridPos) -> None:
        """Mark a single cell as free."""
        if self.in_bounds(pos):
            self._cells[pos.layer][pos.y][pos.x] = 0

    def block_rect(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        layer: int = 0,
    ) -> None:
        y0c = max(0, y0)
        y1c = min(self.height - 1, y1)
        x0c = max(0, x0)
        x1c = min(self.width - 1, x1)
        for y in range(y0c, y1c + 1):
            row = self._cells[layer][y]
            for x in range(x0c, x1c + 1):
                row[x] = 1

    def block_line(self, p0: GridPos, p1: GridPos, radius: int = 0) -> None:
        """Bresenham line. Optionally dilate by ``radius`` cells."""
        dx = abs(p1.x - p0.x)
        sx = 1 if p0.x < p1.x else -1
        dy = -abs(p1.y - p0.y)
        sy = 1 if p0.y < p1.y else -1
        err = dx + dy
        x, y = p0.x, p0.y
        while True:
            gp = GridPos(x, y, p0.layer)
            self.block(gp)
            if radius > 0:
                self.block_rect(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    p0.layer,
                )
            if x == p1.x and y == p1.y:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def dilate(self, radius: int) -> None:
        """Expand every blocked cell by ``radius`` cells (Manhattan)."""
        if radius <= 0:
            return
        for layer in range(self.layers):
            orig = [row[:] for row in self._cells[layer]]
            for y in range(self.height):
                for x in range(self.width):
                    if orig[y][x]:
                        self.block_rect(
                            x - radius,
                            y - radius,
                            x + radius,
                            y + radius,
                            layer,
                        )


# ---------------------------------------------------------------------------
# Grid Router
# ---------------------------------------------------------------------------


class GridRouter:
    """A* grid-based PCB router with 45-degree angle support.

    Parameters
    ----------
    resolution_mm:
        Side length of one grid cell in mm.  Smaller = finer routes but
        larger search space.  Default 0.25 mm (400 cells per 100 mm).
    via_cost:
        Additional cost applied for each via (layer change).  Larger
        values discourage unnecessary layer transitions.
    turn_penalty:
        Small additional cost when the path changes direction.  Larger
        values encourage straighter, more PCB-like routes.
    max_iterations:
        Maximum A* expansions per path search.  Prevents runaway on
        impossible-to-route nets.
    """

    def __init__(
        self,
        resolution_mm: float = 0.25,
        via_cost: float = 10.0,
        turn_penalty: float = 0.2,
        max_iterations: int = 200_000,
    ) -> None:
        self.resolution = resolution_mm
        self.via_cost = via_cost
        self.turn_penalty = turn_penalty
        self.max_iterations = max_iterations

    # -- Public API -------------------------------------------------------

    def route(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        kb: KnowledgeBase | None = None,
    ) -> RouteResult:
        """Route every net in *design* using A* grid pathfinding.

        Nets are classified via :func:`~zaptrace.ee.classifier.classify_design`
        and sorted by priority (most critical first).  Each multi-terminal
        net is decomposed into a minimum spanning tree whose edges are
        routed independently with A*.

        Args:
            design:
                Design to route.  Nets are classified in-place.
            positions:
                Mapping ``component_id -> (x, y)`` in mm.
            kb:
                Optional EE knowledge base.  A fresh default is created
                when ``None``.

        Returns:
            :class:`RouteResult` with all trace segments, vias, and
            summary statistics.
        """
        if kb is None:
            kb = KnowledgeBase()

        classify_design(design)

        # -- Board geometry -----------------------------------------------
        board = canonical_board_definition(design)
        bw, bh = board.width, board.height
        num_layers = max(board.layers, 1)

        grid_w = max(int(math.ceil(bw / self.resolution)), 1)
        grid_h = max(int(math.ceil(bh / self.resolution)), 1)
        obs = ObstacleMap(grid_w, grid_h, num_layers)

        # -- Static obstacles ---------------------------------------------
        self._block_board_edges(obs, grid_w, grid_h, num_layers)
        self._block_components(obs, design, positions, self.resolution)

        # -- Ref -> position lookup ---------------------------------------
        ref_positions: dict[str, tuple[float, float]] = {}
        for c in design.components.values():
            if c.id in positions:
                ref_positions[c.ref] = positions[c.id]
            if c.ref in positions:
                ref_positions[c.ref] = positions[c.ref]

        def _to_grid(p: tuple[float, float]) -> tuple[int, int]:
            return (
                max(1, min(grid_w - 2, int(round(p[0] / self.resolution)))),
                max(1, min(grid_h - 2, int(round(p[1] / self.resolution)))),
            )

        via_pad = DEFAULT_VIA_SPECS.get("pad_diameter", 0.45)
        via_hole = DEFAULT_VIA_SPECS.get("hole_diameter", 0.2)

        # -- Route nets by priority ---------------------------------------
        sorted_nets = sorted(
            design.nets.values(),
            key=lambda n: kb.get_rule(get_net_class(design, n.id)).priority,
        )

        all_traces: list[TraceSegment] = []
        all_vias: list[Via] = []
        layers_used: set[str] = set()
        routed_count = 0
        total_routable = 0

        for net in sorted_nets:
            net_class = get_net_class(design, net.id)
            layer = self._layer_for_net_class(net_class, num_layers)
            if layer < 0:
                # GROUND and unclassified — leave for copper pour
                continue

            # Collect node positions
            node_positions: list[tuple[float, float]] = []
            for node in net.nodes:
                if node.component_ref in ref_positions:
                    node_positions.append(ref_positions[node.component_ref])

            if len(node_positions) < 2:
                continue

            total_routable += 1
            rule = kb.get_rule(net_class)
            width_mm = rule.trace_width
            clear_cells = max(int(math.ceil(rule.clearance / self.resolution)), 1)

            grid_positions = [_to_grid(p) for p in node_positions]

            # MST decomposition
            mst_edges = self._mst(grid_positions)

            success = True

            for i, j in mst_edges:
                gx1, gy1 = grid_positions[i]
                gx2, gy2 = grid_positions[j]

                start_pos = GridPos(gx1, gy1, layer)
                goal_pos = GridPos(gx2, gy2, layer)

                path = self._astar(obs, start_pos, goal_pos)
                if not path:
                    success = False
                    break

                smooth = _simplify_path(path)

                # Block path for subsequent nets
                for pi in range(len(smooth) - 1):
                    obs.block_line(smooth[pi], smooth[pi + 1], clear_cells)

            if not success:
                continue

            routed_count += 1

            # Convert all MST edge paths to TraceSegments
            # (Re-run A* for each edge since we don't cache paths)
            for i, j in mst_edges:
                gx1, gy1 = grid_positions[i]
                gx2, gy2 = grid_positions[j]

                start_pos = GridPos(gx1, gy1, layer)
                goal_pos = GridPos(gx2, gy2, layer)

                path = self._astar(obs, start_pos, goal_pos)
                if path:
                    smooth = _simplify_path(path)
                    for pi in range(len(smooth) - 1):
                        n0 = smooth[pi]
                        n1 = smooth[pi + 1]

                        x0 = round(n0.x * self.resolution, 3)
                        y0 = round(n0.y * self.resolution, 3)
                        x1 = round(n1.x * self.resolution, 3)
                        y1 = round(n1.y * self.resolution, 3)

                        layer_name = f"layer_{n0.layer}"
                        layers_used.add(layer_name)

                        all_traces.append(
                            TraceSegment(
                                layer=layer_name,
                                start=(x0, y0),
                                end=(x1, y1),
                                width=width_mm,
                                net_id=net.id,
                            )
                        )

                        if n0.layer != n1.layer:
                            all_vias.append((x0, y0, via_pad, via_hole, net.id))

        total_length = sum(math.dist(t.start, t.end) for t in all_traces)

        return RouteResult(
            traces=all_traces,
            vias=all_vias,
            layers_used=sorted(layers_used),
            total_trace_length_mm=round(total_length, 3),
            net_count=total_routable,
            routed_net_count=routed_count,
        )

    # -- A* Pathfinding ---------------------------------------------------

    def _astar(
        self,
        obs: ObstacleMap,
        start: GridPos,
        goal: GridPos,
    ) -> list[GridPos] | None:
        """Find lowest-cost path via A* with 8-direction movement + vias.

        Returns ``None`` when no path exists within *max_iterations*.
        """
        if not obs.is_free(start):
            nearest = self._nearest_free(obs, start)
            if nearest is None:
                return None
            start = nearest

        if not obs.is_free(goal):
            nearest = self._nearest_free(obs, goal)
            if nearest is None:
                return None
            goal = nearest

        open_set: list[_Node] = []
        closed: set[tuple[int, int, int]] = set()

        sn = _Node(pos=start, g=0.0)
        sn.h = _octile(start, goal, self.via_cost)
        sn.f = sn.g + sn.h
        heapq.heappush(open_set, sn)

        iterations = 0

        while open_set and iterations < self.max_iterations:
            iterations += 1
            current = heapq.heappop(open_set)

            key = (current.pos.x, current.pos.y, current.pos.layer)
            if key in closed:
                continue
            closed.add(key)

            if current.pos == goal:
                return _reconstruct(current)

            # Previous direction for turn penalty
            prev_dx: int = 0
            prev_dy: int = 0
            if current.parent is not None:
                prev_dx = current.pos.x - current.parent.pos.x
                prev_dy = current.pos.y - current.parent.pos.y

            # 8-direction neighbors
            for dx, dy, move_cost in DIRECTIONS_8:
                npos = GridPos(
                    current.pos.x + dx,
                    current.pos.y + dy,
                    current.pos.layer,
                )
                if not obs.is_free(npos):
                    continue
                nkey = (npos.x, npos.y, npos.layer)
                if nkey in closed:
                    continue

                turn = self.turn_penalty if (dx, dy) != (prev_dx, prev_dy) else 0.0
                g = current.g + move_cost + turn
                h = _octile(npos, goal, self.via_cost)
                heapq.heappush(open_set, _Node(pos=npos, g=g, h=h, f=g + h, parent=current))

            # Vias (layer changes)
            for d_layer in (-1, 1):
                nl = current.pos.layer + d_layer
                if 0 <= nl < obs.layers:
                    via_pos = GridPos(current.pos.x, current.pos.y, nl)
                    if not obs.is_free(via_pos):
                        continue
                    vkey = (via_pos.x, via_pos.y, via_pos.layer)
                    if vkey in closed:
                        continue
                    g = current.g + self.via_cost
                    h = _octile(via_pos, goal, self.via_cost)
                    heapq.heappush(open_set, _Node(pos=via_pos, g=g, h=h, f=g + h, parent=current))

        return None

    @staticmethod
    def _nearest_free(
        obs: ObstacleMap,
        pos: GridPos,
        max_radius: int = 48,
    ) -> GridPos | None:
        """BFS for nearest free cell within *max_radius*.

        The radius must be large enough to escape a whole component courtyard
        (a net endpoint sits at the component centre): a 7×7 mm part at 0.25 mm
        resolution is ~14 cells from its edge, plus clearance dilation.
        """
        visited: set[tuple[int, int, int]] = {(pos.x, pos.y, pos.layer)}
        q: deque[tuple[GridPos, int]] = deque([(pos, 0)])
        while q:
            current, dist = q.popleft()
            if obs.is_free(current):
                return current
            if dist >= max_radius:
                continue
            for dx, dy, _ in DIRECTIONS_8:
                np = GridPos(current.x + dx, current.y + dy, current.layer)
                key = (np.x, np.y, np.layer)
                if obs.in_bounds(np) and key not in visited:
                    visited.add(key)
                    q.append((np, dist + 1))
        return None

    # -- MST decomposition ------------------------------------------------

    @staticmethod
    def _mst(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Prim's minimum spanning tree.

        Returns a list of ``(i, j)`` edge indices into *points*.
        """
        n = len(points)
        if n < 2:
            return []
        in_mst = [False] * n
        in_mst[0] = True
        edges: list[tuple[int, int]] = []
        for _ in range(n - 1):
            best: tuple[int, int] | None = None
            best_dist = float("inf")
            for i in range(n):
                if not in_mst[i]:
                    continue
                for j in range(n):
                    if in_mst[j]:
                        continue
                    d = _manhattan_dist(points[i], points[j])
                    if d < best_dist:
                        best_dist = d
                        best = (i, j)
            if best is None:
                break
            edges.append(best)
            in_mst[best[1]] = True
        return edges

    # -- Obstacle generation ----------------------------------------------

    @staticmethod
    def _block_board_edges(
        obs: ObstacleMap,
        gw: int,
        gh: int,
        n_layers: int,
    ) -> None:
        for lyr in range(n_layers):
            obs.block_rect(0, 0, gw - 1, 0, lyr)  # top
            obs.block_rect(0, gh - 1, gw - 1, gh - 1, lyr)  # bottom
            obs.block_rect(0, 0, 0, gh - 1, lyr)  # left
            obs.block_rect(gw - 1, 0, gw - 1, gh - 1, lyr)  # right

    # -- Obstacle methods --------------------------------------------------

    def _block_components(
        self,
        obs: ObstacleMap,
        design: Design,
        positions: dict[str, tuple[float, float]],
        resolution: float,
    ) -> None:
        """Block grid cells occupied by component bodies.

        Uses the component's *courtyard* dimensions (from its footprint)
        to reserve space on all routing layers so traces do not overlap
        components.  Falls back to a 2×2 mm block when no footprint is
        available.
        """
        from zaptrace.ee.footprints import generate_footprint_for_component

        for comp in design.components.values():
            # Get component position (try id first, then ref)
            pos = positions.get(comp.id) or positions.get(comp.ref)
            if pos is None:
                continue

            # Determine body (courtyard) dimensions — skip if unknown
            fp: Any = None

            if comp.footprint_def is not None:
                fp = comp.footprint_def
            elif comp.footprint:
                fp = generate_footprint_for_component(comp.footprint, comp.type or "")
                if fp is not None:
                    comp.footprint_def = fp

            if fp is None or fp.courtyard == (0.0, 0.0):
                continue  # no footprint info → skip blocking

            bw, bh = fp.courtyard

            # Convert to grid coordinates
            cx, cy = pos
            gx0 = max(1, int((cx - bw / 2) / resolution))
            gy0 = max(1, int((cy - bh / 2) / resolution))
            gx1 = min(obs.width - 2, int((cx + bw / 2) / resolution))
            gy1 = min(obs.height - 2, int((cy + bh / 2) / resolution))

            for layer in range(obs.layers):
                obs.block_rect(gx0, gy0, gx1, gy1, layer)

    @staticmethod
    def _layer_for_net_class(net_class: NetClass, num_layers: int) -> int:
        """Map a net class to a routing layer index.

        Returns ``-1`` for nets that should **not** be routed (typically
        ``GROUND`` / ``VSS`` — left for copper pour or star-ground).
        """
        bottom = max(0, num_layers - 1)

        # Power stays on top layer
        if net_class in (
            NetClass.POWER_HIGH,
            NetClass.POWER_MED,
            NetClass.POWER_LOW,
        ):
            return 0
        # Ground → leave for copper pour
        if net_class == NetClass.GROUND:
            return -1
        # Analog stays on top (avoid via noise coupling)
        if net_class == NetClass.SIGNAL_ANALOG:
            return 0
        # High-speed / RF / differential — inner layer if available, else bottom
        if net_class in (
            NetClass.SIGNAL_HIGH,
            NetClass.RF,
            NetClass.DIFFERENTIAL,
        ):
            if num_layers >= 4:
                return 1  # inner layer (stripline)
            return bottom
        # Everything else (SIGNAL_LOW) → bottom layer
        return bottom


# ---------------------------------------------------------------------------
# Path simplification
# ---------------------------------------------------------------------------


def _simplify_path(path: list[GridPos]) -> list[GridPos]:
    """Remove collinear waypoints from the path.

    Three consecutive points are collinear when moving from ``p[i-1]``
    to ``p[i]`` has the same direction as ``p[i]`` to ``p[i+1]``.
    """
    if len(path) <= 2:
        return list(path)

    result: list[GridPos] = [path[0]]
    for i in range(1, len(path) - 1):
        prev = path[i - 1]
        cur = path[i]
        nxt = path[i + 1]
        # Only simplify within the same layer
        if cur.layer == prev.layer == nxt.layer:
            dx1 = cur.x - prev.x
            dy1 = cur.y - prev.y
            dx2 = nxt.x - cur.x
            dy2 = nxt.y - cur.y
            if dx1 * dy2 == dx2 * dy1:
                continue  # collinear → skip
        result.append(cur)
    result.append(path[-1])
    return result
