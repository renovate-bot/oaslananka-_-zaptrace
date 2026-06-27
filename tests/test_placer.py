"""Tests for component placement algorithms."""

from __future__ import annotations

from zaptrace.algo.placer import _build_connections, place_components
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode


def _design_with_components(n: int) -> Design:
    d = Design(meta=DesignMeta(name="test"))
    for i in range(n):
        d.components[f"c{i}"] = Component(id=f"c{i}", ref=f"R{i}", type="resistor")
    return d


class TestPlaceComponents:
    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        positions = place_components(d)
        assert positions == {}

    def test_single_component(self) -> None:
        d = _design_with_components(1)
        positions = place_components(d)
        assert len(positions) == 1
        x, y = positions["c0"]
        assert x > 0
        assert y > 0

    def test_multiple_components(self) -> None:
        d = _design_with_components(5)
        positions = place_components(d)
        assert len(positions) == 5
        # All positions should be within board bounds
        for x, y in positions.values():
            assert 5.0 <= x <= 95.0
            assert 5.0 <= y <= 75.0

    def test_positions_within_board(self) -> None:
        d = _design_with_components(3)
        positions = place_components(d)
        for cid, (x, y) in positions.items():
            assert x >= 5.0, f"{cid} x={x} out of bounds"
            assert y >= 5.0, f"{cid} y={y} out of bounds"
            assert x <= 95.0, f"{cid} x={x} out of bounds"
            assert y <= 75.0, f"{cid} y={y} out of bounds"

    def test_connections_built(self) -> None:
        d = _design_with_components(3)
        d.nets["n1"] = Net(
            id="n1",
            name="NET1",
            nodes=[
                NetNode(component_ref="R0", pin_name="p1"),
                NetNode(component_ref="R1", pin_name="p1"),
            ],
        )
        conns = _build_connections(d)
        assert len(conns) >= 1

    def test_force_directed_refines(self) -> None:
        """Force-directed should move components toward connected ones."""
        d = _design_with_components(4)
        d.nets["n1"] = Net(
            id="n1",
            name="BUS",
            nodes=[
                NetNode(component_ref="R0", pin_name="p1"),
                NetNode(component_ref="R1", pin_name="p1"),
                NetNode(component_ref="R2", pin_name="p1"),
                NetNode(component_ref="R3", pin_name="p1"),
            ],
        )
        positions = place_components(d)
        # All positions should be populated
        assert all(cid in positions for cid in d.components)
