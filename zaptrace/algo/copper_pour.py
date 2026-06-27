"""Copper pour (flood fill) engine.

Generates copper pour areas — typically ground planes — on PCB layers
with thermal relief spokes and stitching vias.

Algorithm
---------
1.  Create a high-resolution grid over the board area.
2.  Mark obstacles: board outline (reverse), component bodies, pads,
    mounting holes, board cutouts.
3.  Flood fill from a seed point inside the board boundary to find
    all reachable free cells.
4.  Trace the outline of the filled region to produce the pour polygon.
5.  (Optional)  Add thermal-relief spokes for specified pads/vias.
6.  (Optional)  Generate stitching-via positions along the pour.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from zaptrace.core.models import (
    BoardConfig,
    BoardDefinition,
    Component,
    CopperPourArea,
    Design,
    ThermalRelief,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RESOLUTION = 0.25  # mm per grid cell
_THERMAL_DEFAULT_SPOKES = 4
_THERMAL_DEFAULT_WIDTH = 0.3  # mm
_THERMAL_DEFAULT_GAP = 0.2  # mm
_STITCH_SPACING = 5.0  # mm between stitching vias


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GridPt:
    x: int
    y: int


def _mm_to_grid(pos: tuple[float, float], res: float) -> _GridPt:
    return _GridPt(
        int(round(pos[0] / res)),
        int(round(pos[1] / res)),
    )


def _grid_to_mm(pt: _GridPt, res: float) -> tuple[float, float]:
    return (round(pt.x * res, 3), round(pt.y * res, 3))


def _in_polygon(
    pt: _GridPt,
    poly: list[tuple[float, float]],
    res: float,
) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = pt.x * res, pt.y * res
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Obstacle helpers
# ---------------------------------------------------------------------------


def _component_keepout(
    comp: Component,
    position: tuple[float, float] | None,
    clearance: float = 0.3,
) -> list[tuple[float, float]]:
    """Conservative rectangular keepout polygon for a component.

    Uses the footprint courtyard if available, otherwise falls back
    to a default 10×10 mm bounding box centred on the placement
    position.
    """
    pos = position or (0.0, 0.0)
    if comp.footprint_def is not None:
        cw, ch = comp.footprint_def.courtyard
        ox, oy = pos
        return [
            (ox - cw / 2 - clearance, oy - ch / 2 - clearance),
            (ox + cw / 2 + clearance, oy - ch / 2 - clearance),
            (ox + cw / 2 + clearance, oy + ch / 2 + clearance),
            (ox - cw / 2 - clearance, oy + ch / 2 + clearance),
        ]
    # Fallback: 10×10 mm box
    hw = 5.0 + clearance
    hh = 5.0 + clearance
    return [
        (pos[0] - hw, pos[1] - hh),
        (pos[0] + hw, pos[1] - hh),
        (pos[0] + hw, pos[1] + hh),
        (pos[0] - hw, pos[1] + hh),
    ]


def _board_outline_points(board: BoardDefinition | BoardConfig) -> list[tuple[float, float]]:
    """Board outline as a closed polygon.

    Returns the explicit outline if present, otherwise a simple
    rectangle from width/height.
    """
    if isinstance(board, BoardDefinition) and board.outline:
        return list(board.outline)
    w = board.width if isinstance(board, BoardDefinition) else board.width_mm
    h = board.height if isinstance(board, BoardDefinition) else board.height_mm
    return [(0, 0), (w, 0), (w, h), (0, h)]


# ---------------------------------------------------------------------------
# Flood fill
# ---------------------------------------------------------------------------


def _grid_size(
    board: BoardDefinition | BoardConfig,
    res: float,
) -> tuple[int, int]:
    w = board.width if isinstance(board, BoardDefinition) else board.width_mm
    h = board.height if isinstance(board, BoardDefinition) else board.height_mm
    return max(int(math.ceil(w / res)), 1), max(int(math.ceil(h / res)), 1)


# ---------------------------------------------------------------------------
# Copper pour generator
# ---------------------------------------------------------------------------


class CopperPourGenerator:
    """Generates copper pour/flood-fill areas for a PCB design layer.

    Typical usage::

        gen = CopperPourGenerator(resolution_mm=0.25)
        pour = gen.generate_ground_pour(
            design=design,
            positions=design.placement or {},
            layer="F.Cu",
            net_id="GND",
            add_stitching_vias=True,
        )
        design.copper_pours["F.Cu_GND"] = pour
    """

    def __init__(self, resolution_mm: float = _DEFAULT_RESOLUTION) -> None:
        self.res = resolution_mm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_ground_pour(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        layer: str = "F.Cu",
        net_id: str = "GND",
        add_thermal_reliefs: bool = True,
        add_stitching_vias: bool = True,
        stitch_spacing: float = _STITCH_SPACING,
        component_clearance: float = 0.3,
        keepout_fn: Callable | None = None,
    ) -> CopperPourArea:
        """Generate a ground copper pour on *layer*.

        Parameters
        ----------
        design:
            The design to generate the pour for.
        positions:
            Mapping of ``component_id -> (x, y)`` placement positions.
        layer:
            Target PCB layer (e.g. ``"F.Cu"``, ``"B.Cu"``).
        net_id:
            Net that this pour belongs to (default ``"GND"``).
        add_thermal_reliefs:
            Generate thermal-relief spokes for pads/vias on this layer.
        add_stitching_vias:
            Generate stitching via positions.
        stitch_spacing:
            Spacing in mm between stitching vias.
        component_clearance:
            Clearance gap (mm) around component keepouts.
        keepout_fn:
            Optional custom keepout polygon generator.  Receives
            ``(component, position)`` and returns a polygon or ``None``.

        Returns
        -------
        CopperPourArea
            Filled pour area with thermal-relief and stitching data.
        """
        board = design.board_def if design.board_def is not None else design.board
        gw, gh = _grid_size(board, self.res)

        # --- 1. Initialise grid (0 = pour, 1 = obstacle) ---
        grid: list[list[int]] = [[0] * gw for _ in range(gh)]

        # Board outline as obstacle reversal: cells outside board are blocked
        outline_poly = _board_outline_points(board)
        self._block_outside_board(grid, outline_poly)

        # Cutouts
        if isinstance(board, BoardDefinition):
            for cutout in board.cutouts:
                self._block_polygon(grid, cutout)

        # Mounting holes
        if isinstance(board, BoardDefinition):
            for mh in board.mounting_holes:
                r = int(math.ceil((mh.diameter / 2 + 0.2) / self.res))
                cx = int(round(mh.position[0] / self.res))
                cy = int(round(mh.position[1] / self.res))
                self._block_circle(grid, cx, cy, r)

        # Component keepouts
        for comp in design.components.values():
            pos = positions.get(comp.id) or positions.get(comp.ref)
            if keepout_fn is not None:
                keepout = keepout_fn(comp, pos)
            else:
                keepout = _component_keepout(comp, pos, component_clearance)
            self._block_polygon(grid, keepout)

        # Existing trace/via obstacles (power/ground traces on same layer)
        self._block_traces(grid, design, layer)

        # --- 2. Flood fill from board centre ---
        centre = _GridPt(gw // 2, gh // 2)
        filled = self._flood_fill(grid, centre)

        if not filled:
            # Fallback: fill entire board except obstacles
            for y in range(gh):
                for x in range(gw):
                    if grid[y][x] == 0:
                        filled.add(_GridPt(x, y))

        # --- 3. Trace outline ---
        polygon = self._trace_outline(filled, gw, gh)

        # --- 4. Thermal reliefs ---
        thermal_reliefs: list[ThermalRelief] = []
        if add_thermal_reliefs:
            thermal_reliefs = self._generate_thermal_reliefs(design, positions, filled)

        # --- 5. Stitching vias ---
        stitching_vias: list[tuple[float, float]] = []
        if add_stitching_vias:
            stitching_vias = self._generate_stitching_vias(
                design,
                positions,
                filled,
                stitch_spacing,
            )

        return CopperPourArea(
            layer=layer,
            net_id=net_id,
            polygon=polygon,
            thermal_reliefs=thermal_reliefs,
            stitching_vias=stitching_vias,
        )

    # ------------------------------------------------------------------
    # Grid blocking
    # ------------------------------------------------------------------

    def _block_outside_board(
        self,
        grid: list[list[int]],
        outline: list[tuple[float, float]],
    ) -> None:
        """Block all cells outside the board outline polygon."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not outline:
            return
        for y in range(gh):
            for x in range(gw):
                if not _in_polygon(_GridPt(x, y), outline, self.res):
                    grid[y][x] = 1

    def _block_polygon(
        self,
        grid: list[list[int]],
        polygon: list[tuple[float, float]],
    ) -> None:
        """Block all cells inside the given polygon."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not polygon:
            return
        # Bounding box
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        min_x = max(0, int(math.floor(min(xs) / self.res)))
        max_x = min(gw - 1, int(math.ceil(max(xs) / self.res)))
        min_y = max(0, int(math.floor(min(ys) / self.res)))
        max_y = min(gh - 1, int(math.ceil(max(ys) / self.res)))
        for y in range(min_y, max_y + 1):
            row = grid[y]
            for x in range(min_x, max_x + 1):
                if row[x] == 0 and _in_polygon(_GridPt(x, y), polygon, self.res):
                    row[x] = 1

    def _block_circle(
        self,
        grid: list[list[int]],
        cx: int,
        cy: int,
        radius: int,
    ) -> None:
        """Block cells within a circle."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        r2 = radius * radius
        for dy in range(-radius, radius + 1):
            y = cy + dy
            if y < 0 or y >= gh:
                continue
            row = grid[y]
            for dx in range(-radius, radius + 1):
                x = cx + dx
                if x < 0 or x >= gw:
                    continue
                if dx * dx + dy * dy <= r2:
                    row[x] = 1

    def _block_traces(
        self,
        grid: list[list[int]],
        design: Design,
        layer: str,
    ) -> None:
        """Block grid cells occupied by existing traces on *layer*."""
        if design.routing is None:
            return
        half_cells = max(int(math.ceil(0.15 / self.res)), 1)
        for seg in design.routing.traces:
            if seg.layer != layer:
                continue
            w2 = int(math.ceil(seg.width / self.res / 2))
            b = max(w2, half_cells)
            x0 = int(round(seg.start[0] / self.res))
            y0 = int(round(seg.start[1] / self.res))
            x1 = int(round(seg.end[0] / self.res))
            y1 = int(round(seg.end[1] / self.res))
            self._block_line(grid, x0, y0, x1, y1, b)

    def _block_line(
        self,
        grid: list[list[int]],
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        radius: int = 1,
    ) -> None:
        """Bresenham line with optional radius."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            for ry in range(-radius, radius + 1):
                yy = y + ry
                if yy < 0 or yy >= gh:
                    continue
                row = grid[yy]
                for rx in range(-radius, radius + 1):
                    xx = x + rx
                    if 0 <= xx < gw:
                        row[xx] = 1
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    # ------------------------------------------------------------------
    # Flood fill
    # ------------------------------------------------------------------

    @staticmethod
    def _flood_fill(
        grid: list[list[int]],
        seed: _GridPt,
    ) -> set[_GridPt]:
        """BFS flood fill from *seed*, returning all reachable free cells."""
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if not (0 <= seed.x < gw and 0 <= seed.y < gh):
            return set()
        if grid[seed.y][seed.x] != 0:
            return set()

        filled: set[_GridPt] = set()
        q: deque[_GridPt] = deque()
        q.append(seed)
        filled.add(seed)

        while q:
            p = q.popleft()
            for dx, dy in (
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ):
                nx, ny = p.x + dx, p.y + dy
                if not (0 <= nx < gw and 0 <= ny < gh):
                    continue
                np = _GridPt(nx, ny)
                if np in filled:
                    continue
                if grid[ny][nx] != 0:
                    continue
                filled.add(np)
                q.append(np)
        return filled

    # ------------------------------------------------------------------
    # Outline tracing
    # ------------------------------------------------------------------

    def _trace_outline(
        self,
        filled: set[_GridPt],
        gw: int,
        gh: int,
    ) -> list[tuple[float, float]]:
        """Extract the outer boundary of the filled region.

        Uses a simple Moore-neighbour boundary walk.  Returns the
        outline as a list of ``(x_mm, y_mm)`` points (clockwise).
        """
        if not filled:
            return []

        # Find top-leftmost filled cell
        start = min(filled, key=lambda p: (p.y, p.x))

        # Moore neighbour ordering: starts at (1,0) and goes clockwise
        moore = [
            (1, 0),
            (1, 1),
            (0, 1),
            (-1, 1),
            (-1, 0),
            (-1, -1),
            (0, -1),
            (1, -1),
        ]

        boundary: list[_GridPt] = [start]
        current = start
        prev_dir = 7  # Start pointing to the previous search direction

        for _ in range(gw * gh):  # Upper bound
            found = False
            for offset in range(8):
                idx = (prev_dir + 1 + offset) % 8
                dx, dy = moore[idx]
                nb = _GridPt(current.x + dx, current.y + dy)
                if nb in filled:
                    boundary.append(nb)
                    current = nb
                    prev_dir = (idx + 4) % 8  # opposite of entry direction
                    found = True
                    break
            if not found or current == start:
                break

        # Remove trailing duplicates of start
        while len(boundary) > 1 and boundary[-1] == start:
            boundary.pop()

        return [_grid_to_mm(p, self.res) for p in boundary]

    # ------------------------------------------------------------------
    # Thermal reliefs
    # ------------------------------------------------------------------

    def _generate_thermal_reliefs(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        filled: set[_GridPt],
    ) -> list[ThermalRelief]:
        """Generate thermal relief spokes for pads/vias inside the pour."""
        reliefs: list[ThermalRelief] = []
        seen: set[tuple[float, float]] = set()

        # Vias from routing
        if design.routing is not None:
            for via in design.routing.vias:
                x, y, pd, _hole = via[:4]
                key = (round(x, 2), round(y, 2))
                if key in seen:
                    continue
                seen.add(key)
                gx = int(round(x / self.res))
                gy = int(round(y / self.res))
                if _GridPt(gx, gy) in filled:
                    reliefs.append(
                        ThermalRelief(
                            pad_position=(x, y),
                            pad_diameter=pd,
                        )
                    )

        # Pads from components
        for comp in design.components.values():
            pos = positions.get(comp.id) or positions.get(comp.ref)
            if pos is None:
                continue
            if comp.footprint_def is not None:
                for pad in comp.footprint_def.pads:
                    px = round(pos[0] + pad.position[0], 3)
                    py = round(pos[1] + pad.position[1], 3)
                    key = (px, py)
                    if key in seen:
                        continue
                    seen.add(key)
                    gx = int(round(px / self.res))
                    gy = int(round(py / self.res))
                    if _GridPt(gx, gy) in filled:
                        pd = max(pad.size) if pad.size else 0.45
                        reliefs.append(
                            ThermalRelief(
                                pad_position=(px, py),
                                pad_diameter=pd,
                            )
                        )

        return reliefs

    # ------------------------------------------------------------------
    # Stitching vias
    # ------------------------------------------------------------------

    def _generate_stitching_vias(
        self,
        design: Design,
        positions: dict[str, tuple[float, float]],
        filled: set[_GridPt],
        spacing: float,
    ) -> list[tuple[float, float]]:
        """Generate stitching via positions along the pour area.

        Vias are placed near the pour boundary at regular intervals,
        avoiding component positions.
        """
        vias: list[tuple[float, float]] = []

        # Build set of occupied positions
        occupied: set[tuple[float, float]] = set()
        for comp in design.components.values():
            pos = positions.get(comp.id) or positions.get(comp.ref)
            if pos is not None:
                occupied.add((round(pos[0], 1), round(pos[1], 1)))

        step = max(int(round(spacing / self.res)), 5)
        last_placed = -step  # grid cells

        boundary_points = sorted(
            filled,
            key=lambda p: (p.y, p.x),
        )
        count = 0
        for pt in boundary_points:
            # Check if this cell is near the boundary of the fill
            is_edge = False
            for dx, dy in (
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
            ):
                nb = _GridPt(pt.x + dx, pt.y + dy)
                if nb not in filled:
                    is_edge = True
                    break
            if not is_edge:
                continue

            count += 1
            if count - last_placed < step:
                continue

            x_mm, y_mm = _grid_to_mm(pt, self.res)
            # Check not too close to any component
            too_close = False
            for ox, oy in occupied:
                if math.dist((x_mm, y_mm), (ox, oy)) < 3.0:
                    too_close = True
                    break
            if too_close:
                continue

            vias.append((x_mm, y_mm))
            last_placed = count

        return vias
