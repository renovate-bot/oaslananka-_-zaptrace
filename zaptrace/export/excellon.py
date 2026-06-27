"""Excellon drill file format exporter.

Generates NC drill files (``*.DRL`` / ``*.TXT``) from a
:class:`~zaptrace.core.models.Design`. Handles both plated (PTH) and
non-plated (NPTH) holes.

Output format follows the standard Excellon / CNC-7 format used by
PCB manufacturers (JLCPCB, PCBWay, etc.).
"""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import Design

# ---------------------------------------------------------------------------
# Excellon constants
# ---------------------------------------------------------------------------

_HEADER = """M48
; LEADER: ZapTrace generated Excellon drill file
;FILE={filename}
FORMAT={format_str}
{tool_defs}
{units}
""".lstrip()

_TRAILER = """M30
"""

_UNITS_MM = "METRIC,TZ\n"
_UNITS_INCH = "INCH,TZ\n"

# ---------------------------------------------------------------------------
# Drill tool management
# ---------------------------------------------------------------------------


class _ToolManager:
    """Manages drill tool definitions.

    Tools are assigned incrementing T-codes (T01+). Holes with the same
    diameter share the same tool.
    """

    def __init__(self) -> None:
        self._tools: list[tuple[int, float, bool]] = []  # (number, diameter_mm, plated)
        self._diam_to_tool: dict[float, int] = {}

    def get_or_create(self, diameter_mm: float, plated: bool = True) -> int:
        """Get or create a drill tool for the given diameter."""
        key = round(diameter_mm, 4)
        if key in self._diam_to_tool:
            return self._diam_to_tool[key]
        number = len(self._tools) + 1
        self._tools.append((number, key, plated))
        self._diam_to_tool[key] = number
        return number

    def tool_defs_lines(self) -> list[str]:
        """Generate tool definition lines."""
        lines: list[str] = []
        for number, diameter, plated in self._tools:
            # Some manufacturers use different codes for plated vs NPTH
            if plated:
                lines.append(f"T{number:02d}C{diameter:.4f}\n")
            else:
                lines.append(f"T{number:02d}C{diameter:.4f}\n")
        return lines

    def format_string(self) -> str:
        """Determine format string based on max diameter precision."""
        return "METRIC,TZ\n"

    def count(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_excellon(design: Design, output_dir: str | Path | None = None, prefix: str = "") -> dict[str, str | Path]:
    """Generate Excellon drill files.

    Produces one drill file for all holes. Both plated (PTH) and non-plated
    holes are included, sorted by tool size.

    Args:
        design: The design containing footprint pad definitions.
        output_dir: Directory to write files. ``None`` = return content as strings.
        prefix: Filename prefix (usually design name).

    Returns:
        Map of drill type → file path (if ``output_dir``) or content string.
    """
    use_files = output_dir is not None
    out_dir = Path(output_dir) if output_dir else Path()
    if use_files:
        out_dir.mkdir(parents=True, exist_ok=True)

    prefix = prefix or design.meta.name or "board"

    # Collect all holes from component footprints
    holes: list[tuple[float, float, float, bool]] = []  # (x, y, diameter, plated)
    for comp in design.components.values():
        if comp.footprint_def and comp.position:
            cx, cy = comp.position
            for pad in comp.footprint_def.pads:
                drill = pad.drill
                if drill is None or drill <= 0:
                    continue
                px = cx + pad.position[0]
                py = cy + pad.position[1]
                holes.append((px, py, drill, pad.plated))

    # Also collect from mounting holes
    if design.board_def and design.board_def.mounting_holes:
        for mh in design.board_def.mounting_holes:
            holes.append((mh.position[0], mh.position[1], mh.diameter, mh.plated))

    # No vias from routing — vias are handled by the routing result
    if design.routing:
        for via in design.routing.vias:
            x, y, _dia, hole = via[:4]
            holes.append((x, y, hole, True))

    # Group into PTH and NPTH
    pth_holes = [(x, y, d) for x, y, d, plated in holes if plated]
    npth_holes = [(x, y, d) for x, y, d, plated in holes if not plated]

    def _write_drill(holes_list: list[tuple[float, float, float]], filename: str) -> str:
        """Write a single drill file."""
        tools = _ToolManager()
        lines: list[str] = []

        # Header
        lines.append("M48\n")
        lines.append("; ZapTrace generated Excellon drill file\n")
        lines.append(f";FILE={filename}\n")
        lines.append("METRIC,TZ\n")
        lines.append("%\n")

        # Assign tools and group holes
        tool_holes: dict[int, list[tuple[float, float]]] = {}
        for x, y, d in sorted(holes_list, key=lambda h: h[2]):
            t = tools.get_or_create(d, True)
            if t not in tool_holes:
                tool_holes[t] = []
            tool_holes[t].append((x, y))

        # Tool definitions (after header, before coordinates)
        for number, diameter, _ in tools._tools:  # noqa: SLF001
            lines.append(f"T{number:02d}C{diameter:.4f}\n")

        # Coordinates
        for tool_num in sorted(tool_holes):
            lines.append(f"T{tool_num:02d}\n")
            for x, y in tool_holes[tool_num]:
                ix = int(round(x * 1_000_000))
                iy = int(round(y * 1_000_000))
                lines.append(f"X{ix}Y{iy}\n")

        # Trailer
        lines.append("M30\n")
        return "".join(lines)

    result: dict[str, str | Path] = {}

    if pth_holes:
        fn = prefix + ".DRL"
        content = _write_drill(pth_holes, fn)
        result["plated"] = content
        if use_files:
            fp = out_dir / fn
            fp.write_text(content, encoding="utf-8")
            result["plated"] = fp

    if npth_holes:
        fn = prefix + "-NPTH.DRL"
        content = _write_drill(npth_holes, fn)
        result["non_plated"] = content
        if use_files:
            fp = out_dir / fn
            fp.write_text(content, encoding="utf-8")
            result["non_plated"] = fp

    return result


def generate_composite_drill(design: Design, output_dir: str | Path | None = None, prefix: str = "") -> str | Path:
    """Generate a single combined drill file (PTH + NPTH).

    Convenience wrapper that combines all holes into one file.
    """
    use_files = output_dir is not None
    out_dir = Path(output_dir) if output_dir else Path()
    if use_files:
        out_dir.mkdir(parents=True, exist_ok=True)

    prefix = prefix or design.meta.name or "board"

    # Collect all holes
    holes: list[tuple[float, float, float]] = []
    for comp in design.components.values():
        if comp.footprint_def and comp.position:
            cx, cy = comp.position
            for pad in comp.footprint_def.pads:
                drill = pad.drill
                if drill is None or drill <= 0:
                    continue
                holes.append((cx + pad.position[0], cy + pad.position[1], drill))

    if design.board_def and design.board_def.mounting_holes:
        for mh in design.board_def.mounting_holes:
            holes.append((mh.position[0], mh.position[1], mh.diameter))

    if design.routing:
        for via in design.routing.vias:
            x, y, _dia, hole = via[:4]
            holes.append((x, y, hole))

    tools = _ToolManager()
    lines: list[str] = []

    lines.append("M48\n")
    lines.append("; ZapTrace combined drill file\n")
    lines.append(f";FILE={prefix}-ALL.DRL\n")
    lines.append("METRIC,TZ\n")
    lines.append("%\n")

    tool_holes: dict[int, list[tuple[float, float]]] = {}
    for x, y, d in sorted(holes, key=lambda h: h[2]):
        t = tools.get_or_create(d, True)
        if t not in tool_holes:
            tool_holes[t] = []
        tool_holes[t].append((x, y))

    for number, diameter, _ in tools._tools:  # noqa: SLF001
        lines.append(f"T{number:02d}C{diameter:.4f}\n")

    for tool_num in sorted(tool_holes):
        lines.append(f"T{tool_num:02d}\n")
        for x, y in tool_holes[tool_num]:
            ix, iy = int(round(x * 1_000_000)), int(round(y * 1_000_000))
            lines.append(f"X{ix}Y{iy}\n")

    lines.append("M30\n")
    content = "".join(lines)

    if use_files:
        fp = out_dir / f"{prefix}-ALL.DRL"
        fp.write_text(content, encoding="utf-8")
        return fp
    return content
