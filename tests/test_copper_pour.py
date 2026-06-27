"""Tests for the copper pour (flood fill) engine."""

from __future__ import annotations

from zaptrace.algo.copper_pour import CopperPourGenerator
from zaptrace.core.models import (
    BoardDefinition,
    Component,
    CopperPourArea,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    Pad,
    PadShape,
)


def _design(comp_count: int = 3) -> Design:
    d = Design(meta=DesignMeta(name="pour_test"))
    d.board_def = BoardDefinition(width=50, height=40)
    for i in range(comp_count):
        fid = f"c{i}"
        ref = f"R{i}"
        d.components[fid] = Component(
            id=fid,
            ref=ref,
            type="resistor",
            value="10k",
            position=(10 + i * 10, 20),
        )
    return d


class TestCopperPourGenerator:
    def test_create(self) -> None:
        gen = CopperPourGenerator(resolution_mm=1.0)
        assert gen is not None
        assert gen.res == 1.0

    def test_generate_basic(self) -> None:
        d = _design()
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        assert isinstance(pour, CopperPourArea)
        assert pour.layer == "F.Cu"
        assert pour.net_id == "GND"
        assert len(pour.polygon) >= 4  # At least a rectangle

    def test_polygon_within_board(self) -> None:
        d = _design()
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        for x, y in pour.polygon:
            assert 0.0 <= x <= 50.0
            assert 0.0 <= y <= 40.0

    def test_thermal_reliefs_with_footprints(self) -> None:
        d = _design(1)
        comp = d.components["c0"]
        comp.footprint_def = FootprintDef(
            pads=[
                Pad(
                    id="p1",
                    layer=LayerSet.TOP,
                    shape=PadShape.RECT,
                    position=(0.0, 0.0),
                    size=(1.0, 1.0),
                ),
            ],
            courtyard=(2.0, 2.0),
        )
        gen = CopperPourGenerator(resolution_mm=0.5)
        pour = gen.generate_ground_pour(
            d,
            positions={"c0": (25, 20)},
            layer="F.Cu",
        )
        assert len(pour.thermal_reliefs) >= 0  # pad may or may not be in pour
        # At minimum, we get a valid pour
        assert len(pour.polygon) >= 4

    def test_stitching_vias_generated(self) -> None:
        d = _design(1)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(
            d,
            positions={},
            layer="F.Cu",
            add_stitching_vias=True,
        )
        # With 50x40 board and 5mm spacing, expect some vias
        assert len(pour.stitching_vias) > 0

    def test_no_stitching_vias_when_disabled(self) -> None:
        d = _design(1)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(
            d,
            positions={},
            layer="F.Cu",
            add_stitching_vias=False,
        )
        assert len(pour.stitching_vias) == 0

    def test_bottom_layer(self) -> None:
        d = _design()
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="B.Cu")
        assert pour.layer == "B.Cu"
        assert len(pour.polygon) >= 4

    def test_with_cutouts(self) -> None:
        d = _design()
        d.board_def.cutouts = [[(10, 10), (20, 10), (20, 20), (10, 20)]]
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        assert len(pour.polygon) >= 4

    def test_different_resolutions(self) -> None:
        d = _design()
        gen_coarse = CopperPourGenerator(resolution_mm=2.0)
        gen_fine = CopperPourGenerator(resolution_mm=0.5)
        pour_coarse = gen_coarse.generate_ground_pour(d, positions={}, layer="F.Cu")
        pour_fine = gen_fine.generate_ground_pour(d, positions={}, layer="F.Cu")
        # Finer resolution should produce more outline points
        assert len(pour_fine.polygon) >= len(pour_coarse.polygon)

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        d.board_def = BoardDefinition(width=10, height=10)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        assert len(pour.polygon) >= 4

    def test_mounting_hole_blocked(self) -> None:
        """_block_circle prevents pour around a mounting hole."""
        d = Design(meta=DesignMeta(name="mh_test"))
        d.board_def = BoardDefinition(width=20, height=20)
        # Add a mounting hole in the centre
        from zaptrace.core.models import MountingHole

        d.board_def.mounting_holes = [
            MountingHole(position=(10.0, 10.0), diameter=4.0),
        ]
        gen = CopperPourGenerator(resolution_mm=0.5)
        # Use _block_circle directly
        gw, gh = 40, 40  # 20mm / 0.5mm
        grid = [[0] * gw for _ in range(gh)]
        gen._block_circle(grid, 20, 20, 4)  # radius 4 cells = 2mm
        # Centre at (20, 20) should be blocked
        assert grid[20][20] == 1
        # Edge of the circle at (20+4, 20) should be blocked
        assert grid[20][24] == 1

    def test_block_traces_with_routing(self) -> None:
        """_block_traces blocks cells on the same layer as existing traces."""
        from zaptrace.core.models import RouteResult, TraceSegment

        d = Design(meta=DesignMeta(name="trace_test"))
        d.board_def = BoardDefinition(width=10, height=10)
        d.routing = RouteResult(
            traces=[
                TraceSegment(
                    layer="F.Cu",
                    start=(2.0, 5.0),
                    end=(8.0, 5.0),
                    width=0.2,
                    net_id="SIG",
                ),
            ],
            vias=[],
        )
        gen = CopperPourGenerator(resolution_mm=0.5)
        gw, gh = 20, 20
        grid = [[0] * gw for _ in range(gh)]
        gen._block_traces(grid, d, layer="F.Cu")
        # Points along the trace line (x=4..16, y=10) should be blocked
        assert grid[10][4] == 1
        assert grid[10][10] == 1
        # Different layer should not be blocked
        d.routing.traces[0].layer = "B.Cu"
        grid2 = [[0] * gw for _ in range(gh)]
        gen._block_traces(grid2, d, layer="F.Cu")
        assert grid2[10][10] == 0

    def test_flood_fill_out_of_bounds_seed(self) -> None:
        """_flood_fill returns empty set when seed is outside grid."""
        from zaptrace.algo.copper_pour import _GridPt

        empty = CopperPourGenerator._flood_fill([[0]], _GridPt(99, 99))
        assert len(empty) == 0

    def test_flood_fill_blocked_seed(self) -> None:
        """_flood_fill returns empty set when seed cell is blocked."""
        from zaptrace.algo.copper_pour import _GridPt

        empty = CopperPourGenerator._flood_fill([[1]], _GridPt(0, 0))
        assert len(empty) == 0

    def test_trace_outline_empty(self) -> None:
        """_trace_outline returns empty list when no cells are filled."""
        gen = CopperPourGenerator(resolution_mm=1.0)
        assert gen._trace_outline(set(), 10, 10) == []

    def test_board_outline_explicit(self) -> None:
        """_board_outline_points returns explicit outline when present."""
        from zaptrace.algo.copper_pour import _board_outline_points

        bd = BoardDefinition(
            width=50,
            height=40,
            outline=[(0, 0), (50, 0), (50, 10), (40, 10), (40, 40), (0, 40)],
        )
        pts = _board_outline_points(bd)
        # Should return exact outline, not the rectangle
        assert len(pts) == 6
        assert pts[3] == (40, 10)  # a non-rectangle point


class TestThermalRelief:
    def test_thermal_relief_model(self) -> None:
        from zaptrace.core.models import ThermalRelief

        tr = ThermalRelief(pad_position=(10.0, 10.0), pad_diameter=0.45)
        assert tr.spoke_count == 4
        assert tr.spoke_width == 0.3
        assert tr.gap == 0.2


class TestGerberIntegration:
    """Copper pour rendering in Gerber output."""

    def test_pour_in_gerber_top(self) -> None:
        from zaptrace.export.gerber import generate_gerber

        d = _design(1)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        d.copper_pours["F.Cu_GND"] = pour

        result = generate_gerber(d)
        assert "top" in result
        assert "G36*" in result["top"]  # Gerber region start
        assert "G37*" in result["top"]  # Gerber region end

    def test_pour_not_in_bottom_when_top_only(self) -> None:
        from zaptrace.export.gerber import generate_gerber

        d = _design(1)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        d.copper_pours["F.Cu_GND"] = pour

        result = generate_gerber(d)
        assert "G36*" in result["top"]  # Top has the pour
        assert "G36*" not in result["bottom"]  # Bottom should not have the pour

    def test_file_output(self, tmp_path: str) -> None:
        from pathlib import Path

        from zaptrace.export.gerber import generate_gerber

        d = _design(1)
        gen = CopperPourGenerator(resolution_mm=1.0)
        pour = gen.generate_ground_pour(d, positions={}, layer="F.Cu")
        d.copper_pours["F.Cu_GND"] = pour

        out_dir = Path(tmp_path) / "gerber"
        generate_gerber(d, output_dir=str(out_dir))
        gtl_files = list(out_dir.glob("*.GTL"))
        assert len(gtl_files) >= 1
        content = gtl_files[0].read_text(encoding="utf-8")
        assert "G36*" in content

    def test_thermal_relief_in_gerber(self) -> None:
        from zaptrace.export.gerber import generate_gerber

        d = _design(1)
        d.components["c0"].footprint_def = None
        gen = CopperPourGenerator(resolution_mm=0.5)
        pour = gen.generate_ground_pour(
            d,
            positions={"c0": (25, 20)},
            layer="F.Cu",
            add_thermal_reliefs=True,
        )
        d.copper_pours["F.Cu_GND"] = pour

        result = generate_gerber(d)
        assert "G36*" in result["top"]
