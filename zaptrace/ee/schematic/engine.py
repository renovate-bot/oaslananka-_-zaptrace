"""Schematic engine — orchestrates symbol generation, placement, and rendering.

The :class:`SchematicEngine` takes a :class:`~zaptrace.core.models.Design`
and produces a full schematic SVG with properly drawn symbols, pins, nets
(wires), reference designators, and values.

Usage::

    from zaptrace.ee.schematic import SchematicEngine

    engine = SchematicEngine()
    svg = engine.render(design)
"""

from __future__ import annotations

import math

from zaptrace.core.models import Component, Design, DrawCommand, SymbolDef
from zaptrace.ee.schematic.placement import place_schematic
from zaptrace.ee.schematic.symbols import generate_symbol

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANVAS_W = 1200
CANVAS_H = 900

# Wire styling
WIRE_COLOR = "#1a5c8a"
WIRE_WIDTH = 1.5
PIN_DOT_R = 2.0

# Symbol styling
PIN_LABEL_SIZE = 7
REF_SIZE = 10
VAL_SIZE = 8
TITLE_SIZE = 16

# Spacing
PIN_LABEL_OFFSET = 12  # distance from symbol edge for pin labels
COMP_SPACING_X = 60.0  # minimum gap between symbols horizontally


# ---------------------------------------------------------------------------
# Schematic engine
# ---------------------------------------------------------------------------


class SchematicEngine:
    """Generate schematic SVG diagrams from a Design object.

    The engine:
    1. Generates schematic symbols for every component
    2. Auto-places components on the canvas using connectivity
    3. Routes wires between connected pins
    4. Renders the full schematic as SVG

    Parameters
    ----------
    width_px, height_px:
        Canvas dimensions in pixels.
    show_pin_labels:
        Whether to draw pin names next to pins.
    show_pin_dots:
        Whether to draw small dots at pin ends.
    """

    def __init__(
        self,
        width_px: int = CANVAS_W,
        height_px: int = CANVAS_H,
        show_pin_labels: bool = True,
        show_pin_dots: bool = True,
    ) -> None:
        self.width = width_px
        self.height = height_px
        self.show_pin_labels = show_pin_labels
        self.show_pin_dots = show_pin_dots

    # -- Public API --------------------------------------------------------

    def render(self, design: Design) -> str:
        """Render the design as a full schematic SVG string."""
        comps = list(design.components.values())
        if not comps:
            return _empty_svg(self.width, self.height)

        # 1. Generate symbols
        symbols: dict[str, SymbolDef] = {}
        for comp in comps:
            sym = comp.symbol or generate_symbol(comp)
            symbols[comp.id] = sym

        # 2. Auto-place
        positions = place_schematic(design, width=float(self.width), height=float(self.height))

        # 3. Determine pin connections for wire routing
        wire_segments = self._route_wires(design, symbols, positions)

        # 4. Render SVG
        return self._build_svg(design, symbols, positions, wire_segments)

    # -- SVG builder -------------------------------------------------------

    def _build_svg(
        self,
        design: Design,
        symbols: dict[str, SymbolDef],
        positions: dict[str, tuple[float, float]],
        wires: list[tuple[float, float, float, float, str, float]],
    ) -> str:
        """Assemble the final SVG document."""
        lines: list[str] = [
            '<svg xmlns="http://www.w3.org/2000/svg"',
            f' width="{self.width}" height="{self.height}"',
            f' viewBox="0 0 {self.width} {self.height}">',
            "<defs><style>",
            f".wire{{stroke:{WIRE_COLOR};stroke-width:{WIRE_WIDTH};fill:none;stroke-linecap:round;stroke-linejoin:round}}",
            f".pin-label{{font:{PIN_LABEL_SIZE}px monospace;fill:#555;text-anchor:end}}",
            f".ref{{font:bold {REF_SIZE}px sans-serif;fill:#222}}",
            f".value{{font:{VAL_SIZE}px sans-serif;fill:#666}}",
            f".title{{font:bold {TITLE_SIZE}px sans-serif;fill:#111}}",
            ".sym-body{stroke:#222;stroke-width:1.5;fill:none}",
            ".sym-fill{stroke:#222;stroke-width:1.5;fill:#fff}",
            ".pin-dot{fill:#222}",
            ".net-label{font:7px sans-serif;fill:#4a9;text-anchor:middle;font-style:italic}",
            "</style></defs>",
            f'<rect width="{self.width}" height="{self.height}" fill="#fafbfc"/>',
            f'<text class="title" x="20" y="28">{self._escape(design.meta.name)}</text>',
        ]

        # Title block / metadata
        if design.meta.author:
            lines.append(
                f'<text class="value" x="{self.width - 20}" y="20" text-anchor="end">'
                f"By: {self._escape(design.meta.author)}</text>"
            )

        # Wires (draw first so they appear behind symbols)
        labeled_nets: set[str] = set()
        for x1, y1, x2, y2, net_name, _width in wires:
            lines.append(f'<line class="wire" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
            # Draw net name label at midpoint of first segment per net
            if net_name and net_name not in labeled_nets:
                labeled_nets.add(net_name)
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0 - 6.0
                lines.append(f'<text class="net-label" x="{mx:.1f}" y="{my:.1f}">{self._escape(net_name)}</text>')

        # Symbols
        for comp in design.components.values():
            if comp.id not in positions:
                continue
            sym = symbols.get(comp.id)
            if sym is None:
                continue
            cx, cy = positions[comp.id]

            lines.extend(self._draw_symbol_body(sym, cx, cy))
            lines.extend(self._draw_pins(sym, comp, cx, cy))

            # Reference designator
            lines.append(
                f'<text class="ref" x="{cx + 2:.1f}" y="{cy - sym.height / 2 - 4:.1f}">{self._escape(comp.ref)}</text>'
            )

            # Value
            if comp.value:
                lines.append(
                    f'<text class="value" x="{cx + 2:.1f}" y="{cy - sym.height / 2 + 10:.1f}">'
                    f"{self._escape(comp.value)}</text>"
                )

        # Revision / version footer
        lines.append(
            f'<text class="value" x="20" y="{self.height - 10}">'
            f"Rev {design.meta.revision} | {self._escape(design.meta.version)}</text>"
        )

        lines.append("</svg>")
        return "\n".join(lines)

    # -- Symbol rendering --------------------------------------------------

    def _draw_symbol_body(
        self,
        sym: SymbolDef,
        cx: float,
        cy: float,
    ) -> list[str]:
        """Draw a component's symbol body at canvas coordinates ``(cx, cy)``."""
        lines: list[str] = []
        for cmd in sym.body:
            svg = _draw_command_to_svg(cmd, cx, cy)
            if svg:
                lines.append(svg)
        return lines

    def _draw_pins(
        self,
        sym: SymbolDef,
        comp: Component,
        cx: float,
        cy: float,
    ) -> list[str]:
        """Draw pins with dots and optional labels."""
        lines: list[str] = []
        for sp in sym.pins:
            px = cx + sp.position[0]
            py = cy + sp.position[1]

            # Pin line (from symbol body edge to pin tip)
            dx, dy = _pin_direction(sp.orientation)
            tip_x = px + dx * sp.length
            tip_y = py + dy * sp.length

            lines.append(f'<line class="wire" x1="{px:.1f}" y1="{py:.1f}" x2="{tip_x:.1f}" y2="{tip_y:.1f}"/>')

            # Pin dot at connection point
            if self.show_pin_dots:
                lines.append(f'<circle class="pin-dot" cx="{tip_x:.1f}" cy="{tip_y:.1f}" r="{PIN_DOT_R}"/>')

            # Pin label
            if self.show_pin_labels and sp.name:
                label_x = tip_x + dx * PIN_LABEL_OFFSET
                label_y = tip_y + dy * PIN_LABEL_OFFSET + 3
                anchor = "middle"
                if dx < 0:
                    anchor = "end"
                elif dx > 0:
                    anchor = "start"
                lines.append(
                    f'<text class="pin-label" x="{label_x:.1f}" y="{label_y:.1f}" '
                    f'text-anchor="{anchor}">{self._escape(sp.name)}</text>'
                )

        return lines

    # -- Wire routing ------------------------------------------------------

    def _route_wires(
        self,
        design: Design,
        symbols: dict[str, SymbolDef],
        positions: dict[str, tuple[float, float]],
    ) -> list[tuple[float, float, float, float, str, float]]:
        """Route net connections between component pins.

        For each net, we collect all pin positions (via symbol definition)
        and connect them with orthogonal (right-angle) wire segments.
        """
        wires: list[tuple[float, float, float, float, str, float]] = []
        ref_to_id = {c.ref: c.id for c in design.components.values()}

        for net in design.nets.values():
            pin_positions: list[tuple[float, float, str]] = []

            for node in net.nodes:
                comp_id = ref_to_id.get(node.component_ref)
                if comp_id is None or comp_id not in positions:
                    continue
                cx, cy = positions[comp_id]
                sym = symbols.get(comp_id)
                if sym is None:
                    continue

                # Find matching symbol pin by id or name
                pin_pos = self._get_pin_tip(sym, node.pin_name, cx, cy)
                if pin_pos is not None:
                    pin_positions.append((*pin_pos, comp_id))

            if len(pin_positions) < 2:
                continue

            # Sort to reduce crossings: order by x then y
            pin_positions.sort(key=lambda p: (p[0], p[1]))

            # Connect with orthogonal routing (L-shaped)
            for i in range(len(pin_positions) - 1):
                x1, y1, _ = pin_positions[i]
                x2, y2, _ = pin_positions[i + 1]

                # Use L-shaped routing: horizontal then vertical
                mid_x = (x1 + x2) / 2
                if abs(x2 - x1) > abs(y2 - y1):
                    wires.append((x1, y1, mid_x, y1, net.name, WIRE_WIDTH))
                    wires.append((mid_x, y1, mid_x, y2, net.name, WIRE_WIDTH))
                    wires.append((mid_x, y2, x2, y2, net.name, WIRE_WIDTH))
                else:
                    wires.append((x1, y1, x1, mid_x, net.name, WIRE_WIDTH))
                    wires.append((x1, mid_x, x2, mid_x, net.name, WIRE_WIDTH))
                    wires.append((x2, mid_x, x2, y2, net.name, WIRE_WIDTH))

        return wires

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _get_pin_tip(
        sym: SymbolDef,
        pin_name: str,
        cx: float,
        cy: float,
    ) -> tuple[float, float] | None:
        """Get the absolute tip position (connection point) of a pin."""
        for sp in sym.pins:
            if sp.id == pin_name or sp.name == pin_name or sp.name == pin_name.upper():
                px = cx + sp.position[0]
                py = cy + sp.position[1]
                dx, dy = _pin_direction(sp.orientation)
                return (px + dx * sp.length, py + dy * sp.length)
        return None

    @staticmethod
    def _escape(text: str) -> str:
        """Minimal XML escaping for SVG text content."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _pin_direction(orientation: str) -> tuple[float, float]:
    """Return ``(dx, dy)`` unit vector for a pin orientation."""
    return {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "top": (0.0, -1.0),
        "bottom": (0.0, 1.0),
    }.get(orientation, (0.0, 0.0))


def _draw_command_to_svg(cmd: DrawCommand, cx: float, cy: float) -> str:
    """Convert a DrawCommand to an SVG element string, offset by ``(cx, cy)``."""
    p = cmd.params
    cls = "sym-body" if p.get("fill") != "white" else "sym-fill"

    if cmd.type == "line":
        x1 = p.get("x1", 0) + cx
        y1 = p.get("y1", 0) + cy
        x2 = p.get("x2", 0) + cx
        y2 = p.get("y2", 0) + cy
        stroke = p.get("stroke", "#222")
        return f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}"/>'

    if cmd.type == "rect":
        x = p.get("x", 0) + cx
        y = p.get("y", 0) + cy
        w = p.get("width", 10)
        h = p.get("height", 10)
        fill = p.get("fill", "none")
        stroke = p.get("stroke", "#222")
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" stroke="{stroke}" fill="{fill}"/>'

    if cmd.type == "circle":
        cx_c = p.get("cx", 0) + cx
        cy_c = p.get("cy", 0) + cy
        r = p.get("radius", 5)
        fill = p.get("fill", "none")
        stroke = p.get("stroke", "#222")
        return f'<circle cx="{cx_c:.1f}" cy="{cy_c:.1f}" r="{r:.1f}" stroke="{stroke}" fill="{fill}"/>'

    if cmd.type == "arc":
        # Approximate arc as polyline for simplicity
        x1 = p.get("x1", 0) + cx
        y1 = p.get("y1", 0) + cy
        x2 = p.get("x2", 0) + cx
        y2 = p.get("y2", 0) + cy
        radius = p.get("radius", 5)
        if radius <= 0:
            return ""
        # Simple arc approximation with a few segments
        pts = _approximate_arc(x1, y1, x2, y2, radius)
        if len(pts) < 3:
            return ""
        d = " ".join(f"M{pts[0][0]:.1f},{pts[0][1]:.1f}" + "".join(f" L{x:.1f},{y:.1f}" for x, y in pts[1:]))
        return f'<path class="{cls}" d="{d}"/>'

    if cmd.type == "text":
        x = p.get("x", 0) + cx
        y = p.get("y", 0) + cy
        txt = p.get("text", "")
        font_size = p.get("font_size", 7)
        fill = p.get("fill", "#222")
        return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{font_size}" fill="{fill}">{_escape_text(txt)}</text>'

    if cmd.type == "polygon":
        pts = p.get("points", [])
        stroke = p.get("stroke", "#222")
        fill = p.get("fill", "none")
        if not pts:
            return ""
        offset_pts = [(x + cx, y + cy) for x, y in pts]
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in offset_pts)
        return f'<polygon class="{cls}" points="{d}" fill="{fill}" stroke="{stroke}"/>'

    return ""


def _approximate_arc(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    segments: int = 8,
) -> list[tuple[float, float]]:
    """Approximate an arc between two points with a polyline."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < 0.01:
        return [(x1, y1)]
    h = math.sqrt(max(0.0, radius * radius - (d / 2) ** 2))
    # Perpendicular direction
    nx, ny = -dy / d, dx / d
    cex = mx + nx * h
    cey = my + ny * h
    a1 = math.atan2(y1 - cey, x1 - cex)
    a2 = math.atan2(y2 - cey, x2 - cex)
    # Ensure we traverse the shorter arc
    if a2 < a1:
        a2 += 2 * math.pi
    if a2 - a1 > math.pi:
        a1, a2 = a2, a1 + 2 * math.pi
    pts: list[tuple[float, float]] = []
    for i in range(segments + 1):
        t = a1 + (a2 - a1) * i / segments
        pts.append((cex + radius * math.cos(t), cey + radius * math.sin(t)))
    return pts


def _escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _empty_svg(w: int, h: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
        f'<rect width="{w}" height="{h}" fill="#fafbfc"/>'
        f'<text x="20" y="30" font-family="sans-serif" font-size="14" fill="#888">'
        f"No components</text></svg>"
    )


# ---------------------------------------------------------------------------
# Backward-compatible convenience function
# ---------------------------------------------------------------------------


def render_schematic_svg(
    design: Design,
    *,
    width: int = CANVAS_W,
    height: int = CANVAS_H,
    show_pin_labels: bool = True,
) -> str:
    """Convenience function to render a schematic SVG in one call.

    This replaces the older ``zaptrace.export.svg.render_schematic_svg``
    with a fully symbol-aware version.
    """
    engine = SchematicEngine(
        width_px=width,
        height_px=height,
        show_pin_labels=show_pin_labels,
    )
    return engine.render(design)
