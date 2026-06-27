"""Tests for constraint-aware placement intelligence. (#113)"""

from __future__ import annotations

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    Pin,
    PinType,
    PlacementIntent,
)
from zaptrace.synthesis.placement import (
    PlacementAnalysis,
    analyze_placement,
    group_components,
)


def _make_design(
    placement_data: dict[str, tuple[float, float]] | None = None,
) -> Design:
    d = Design(meta=DesignMeta(name="test"))
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="ic",
        pins={
            "VCC": Pin(name="VCC", type=PinType.POWER),
            "GND": Pin(name="GND", type=PinType.POWER),
            "SDA": Pin(name="SDA", type=PinType.BIDIRECTIONAL),
            "SCL": Pin(name="SCL", type=PinType.INPUT),
        },
    )
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF")
    d.components["c2"] = Component(id="c2", ref="C2", type="capacitor", value="10uF")
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k")
    d.components["j1"] = Component(id="j1", ref="J1", type="connector")
    d.components["sensor1"] = Component(id="sensor1", ref="U2", type="sensor")
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC_3V3",
        nodes=[
            NetNode(component_ref="U1", pin_name="VCC"),
            NetNode(component_ref="C1", pin_name="p1"),
            NetNode(component_ref="C2", pin_name="p1"),
        ],
    )
    d.nets["gnd"] = Net(
        id="gnd",
        name="GND",
        nodes=[
            NetNode(component_ref="U1", pin_name="GND"),
            NetNode(component_ref="C1", pin_name="p2"),
            NetNode(component_ref="C2", pin_name="p2"),
            NetNode(component_ref="R1", pin_name="p2"),
        ],
    )
    d.nets["i2c"] = Net(
        id="i2c",
        name="I2C_BUS",
        nodes=[
            NetNode(component_ref="U1", pin_name="SDA"),
            NetNode(component_ref="U1", pin_name="SCL"),
            NetNode(component_ref="U2", pin_name="SDA"),
            NetNode(component_ref="U2", pin_name="SCL"),
        ],
    )
    if placement_data is not None:
        d.placement = placement_data
    return d


class TestGroupComponents:
    def test_returns_groups(self) -> None:
        d = _make_design()
        groups = group_components(d)
        # There should be groups based on shared nets
        group_names = {g.name for g in groups}
        assert any("VCC_3V3" in gn for gn in group_names), f"No VCC_3V3 group in {group_names}"
        assert any("GND" in gn for gn in group_names), f"No GND group in {group_names}"

    def test_disjoint_groups(self) -> None:
        d = _make_design()
        groups = group_components(d)
        # No component should be in more than one group
        all_comps: list[str] = []
        for g in groups:
            all_comps.extend(g.component_ids)
        assert len(all_comps) == len(set(all_comps)), "Component appears in multiple groups"

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        groups = group_components(d)
        assert groups == []

    def test_no_nets_no_groups(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        d.components["r1"] = Component(id="r1", ref="R1", type="resistor")
        groups = group_components(d)
        assert groups == []


class TestDecouplingProximity:
    def test_decap_too_far_from_ic(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 28.0),  # 12mm from U1 → warning (>10mm)
                "r1": (20.0, 20.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        # Override c2 to be a decoupling cap (100nF) and place it far away
        d.components["c2"] = Component(id="c2", ref="C2", type="capacitor", value="100nF")
        assert d.placement is not None
        d.placement["c2"] = (10.0, 10.0)

        analysis = analyze_placement(d)
        proximity_obs = [o for o in analysis.observations if o.category == "proximity"]
        assert len(proximity_obs) >= 2, f"Expected ≥2 proximity obs, got: {proximity_obs}"
        warn_obs = [o for o in proximity_obs if o.severity == "warning"]
        # Both c1 (12mm) and c2 (~53mm) are >10mm from nearest IC → warnings
        assert len(warn_obs) >= 1, f"No warning-level proximity obs: {proximity_obs}"

    def test_decap_close_to_ic_no_warning(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),  # ~2.8mm from U1 — ideal
                "c2": (48.0, 38.0),  # ~2.8mm from U1 — ideal
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        proximity_obs = [o for o in analysis.observations if o.category == "proximity"]
        # All caps are within 5mm of U1, so no warnings/infos
        assert len(proximity_obs) == 0, f"Unexpected proximity obs: {proximity_obs}"


class TestKeepoutConstraints:
    def test_edge_placement_violation(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 30.0),
                "c2": (50.0, 20.0),
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),  # center of board, not at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        # Add a constraint that expects J* at bottom edge
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="USB connector on board edge")
        )
        analysis = analyze_placement(d)
        edge_obs = [o for o in analysis.observations if o.category == "edge"]
        assert len(edge_obs) >= 1, f"No edge observations: {analysis.observations}"
        assert any("J1" in o.message for o in edge_obs), f"J1 not in edge obs: {edge_obs}"

    def test_near_constraint_violation(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 30.0),
                "c2": (50.0, 20.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        # Decoupling caps should be near U1
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling caps near IC",
            )
        )
        analysis = analyze_placement(d)
        keepout_obs = [o for o in analysis.observations if o.category == "keepout"]
        assert len(keepout_obs) >= 1, f"No keepout observations: {analysis.observations}"

    def test_all_constraints_satisfied(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),  # near U1
                "c2": (48.0, 38.0),  # near U1
                "r1": (10.0, 10.0),
                "j1": (50.0, 2.0),  # at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="connector on bottom edge")
        )
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling caps",
            )
        )
        analysis = analyze_placement(d)
        warning_obs = [o for o in analysis.observations if o.severity != "info"]
        assert len(warning_obs) == 0, f"Unexpected warnings: {warning_obs}"


class TestAnalogDigitalSeparation:
    def test_analog_too_close_to_digital(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (52.0, 38.0),  # 2mm from U1 → warning
            }
        )
        analysis = analyze_placement(d)
        separation_obs = [o for o in analysis.observations if o.category == "separation"]
        assert len(separation_obs) >= 1, f"No separation observations: {analysis.observations}"
        assert any("sensor" in o.message.lower() for o in separation_obs)


class TestPlacementCandidateScoring:
    def test_score_perfect_placement(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (20.0, 20.0),
                "j1": (50.0, 2.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        assert len(analysis.candidates) == len(d.components)
        for cand in analysis.candidates:
            assert 0.0 <= cand.score <= 1.0, f"Candidate {cand.component_id} has invalid score {cand.score}"

    def test_score_drops_with_constraint_violations(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (50.0, 5.0),  # far from U1
                "c2": (70.0, 30.0),  # far from U1
                "r1": (10.0, 10.0),
                "j1": (50.0, 40.0),  # not at bottom edge
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="connector at bottom")
        )
        d.constraints.placement.append(
            PlacementIntent(
                component="C*",
                near="U1",
                max_distance_mm=5.0,
                reason="decoupling",
            )
        )
        analysis = analyze_placement(d)
        # Some candidates should have slightly lower scores from violations
        low_scores = [c for c in analysis.candidates if c.score < 0.95]
        assert len(low_scores) >= 4, f"Not enough low scores: {[c.score for c in analysis.candidates]}"
        # Overall score should be < 1.0
        assert analysis.score < 1.0, f"Overall score should be < 1.0, got {analysis.score}"

    def test_reasons_are_recorded(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (52.0, 42.0),
                "c2": (48.0, 38.0),
                "r1": (80.0, 20.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        candidates_with_reasons = [c for c in analysis.candidates if c.reasons]
        assert len(candidates_with_reasons) >= 1, "No candidates have reasons"


class TestOverallScore:
    def test_perfect_placement_scores_one(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (20.0, 20.0),
                "j1": (50.0, 2.0),
                "sensor1": (80.0, 60.0),
            }
        )
        d.constraints.placement.append(
            PlacementIntent(component="J*", edge="bottom", reason="edge connector")
        )
        analysis = analyze_placement(d)
        # Should be close to 1.0 since constraints are met and no violations
        assert analysis.score > 0.8, f"Score too low: {analysis.score}"

    def test_no_placement_data_has_minimal_observations(self) -> None:
        d = _make_design()  # no placement data
        analysis = analyze_placement(d)
        assert analysis.score == 1.0  # no placement to score
        # No observations either — nothing to check
        assert len(analysis.observations) == 0, f"Unexpected observations: {analysis.observations}"


class TestPlacementAnalysisStructure:
    def test_analysis_has_all_fields(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
            }
        )
        analysis = analyze_placement(d)
        assert isinstance(analysis, PlacementAnalysis)
        assert isinstance(analysis.groups, list)
        assert isinstance(analysis.observations, list)
        assert isinstance(analysis.candidates, list)
        assert isinstance(analysis.score, float)

    def test_groups_include_all_components(self) -> None:
        d = _make_design(
            placement_data={
                "u1": (50.0, 40.0),
                "c1": (51.0, 41.0),
                "c2": (49.0, 39.0),
                "r1": (10.0, 10.0),
                "j1": (5.0, 5.0),
                "sensor1": (80.0, 60.0),
            }
        )
        analysis = analyze_placement(d)
        grouped_comps: set[str] = set()
        for g in analysis.groups:
            grouped_comps.update(g.component_ids)
        # Components on nets: u1, c1, c2, r1, sensor1 (j1 is not on any net)
        assert "u1" in grouped_comps
        assert "sensor1" in grouped_comps
        # j1 has no nets, so it's not grouped
        assert "j1" not in grouped_comps
