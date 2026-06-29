"""Tests for the convergent self-correction (ERC -> patch -> re-verify) loop."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta
from zaptrace.erc.runner import ERCRunner
from zaptrace.synthesis.repair import (
    RepairResult,
    repair_design,
    synthesize_and_repair,
)


def _design_with(*components: Component) -> Design:
    design = Design(meta=DesignMeta(name="repair_test"))
    for comp in components:
        design.components[comp.ref] = comp
    return design


def _erc020_count(design: Design) -> int:
    return sum(1 for v in ERCRunner().run(design).violations if v.rule_id == "ERC020")


class TestFootprintRepair:
    def test_known_passive_gets_a_footprint(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="10k"))
        assert _erc020_count(design) == 1
        result = repair_design(design)
        assert design.components["R1"].footprint == "0402"
        assert _erc020_count(design) == 0
        assert result.converged

    def test_known_ic_value_maps_to_its_package(self) -> None:
        design = _design_with(Component(id="U1", ref="U1", type="ic", value="TLV62569"))
        repair_design(design)
        assert design.components["U1"].footprint == "SOT-23-5"

    def test_transceiver_ics_get_soic8(self) -> None:
        design = _design_with(
            Component(id="U1", ref="U1", type="ic", value="MAX3485"),
            Component(id="U2", ref="U2", type="ic", value="SN65HVD230"),
        )
        repair_design(design)
        assert design.components["U1"].footprint == "SOIC-8"
        assert design.components["U2"].footprint == "SOIC-8"

    def test_unknown_component_is_escalated_not_guessed(self) -> None:
        design = _design_with(Component(id="U1", ref="U1", type="ic", value="MYSTERY-XYZ"))
        result = repair_design(design)
        # No footprint invented for an unknown part...
        assert design.components["U1"].footprint == ""
        # ...and the violation is surfaced for a human instead.
        assert any(v["rule_id"] == "ERC020" for v in result.remaining)
        assert result.patches == []

    def test_patch_carries_provenance(self) -> None:
        design = _design_with(Component(id="C1", ref="C1", type="capacitor", value="100nF"))
        result = repair_design(design)
        patch = result.patches[0]
        assert patch.rule_id == "ERC020"
        assert patch.field == "footprint"
        assert patch.old_value == ""
        assert patch.new_value == "0402"
        assert "capacitor" in patch.rationale


class TestLoopBehaviour:
    def test_idempotent_second_pass_makes_no_patches(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="1k"))
        repair_design(design)
        again = repair_design(design)
        assert again.patches == []
        assert again.converged

    def test_iterations_record_measured_progress(self) -> None:
        design = _design_with(
            Component(id="R1", ref="R1", type="resistor", value="1k"),
            Component(id="C1", ref="C1", type="capacitor", value="1uF"),
        )
        result = repair_design(design)
        assert len(result.iterations) == 1
        it = result.iterations[0]
        assert it.violations_before > it.violations_after
        assert len(it.patches) == 2

    def test_respects_iteration_cap(self) -> None:
        design = _design_with(Component(id="R1", ref="R1", type="resistor", value="1k"))
        result = repair_design(design, max_iterations=1)
        assert isinstance(result, RepairResult)


class TestEnableTieRepair:
    def test_floating_buck_enable_is_tied_high(self) -> None:
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail at 1A")
        design, repair = out["design"], out["repair"]
        enable_nets = [n for n in design.nets if n.upper().startswith("EN_")]
        assert enable_nets  # a buck was synthesized, so it has an enable net
        for net_id in enable_nets:
            assert len(design.nets[net_id].nodes) >= 2  # no longer floating
        assert any(p.rule_id == "ERC012" and "pull-up" in p.new_value for p in repair.patches)

    def test_non_enable_single_pin_net_is_left_for_human(self) -> None:
        # A buck's feedback net is single-pin too, but must NOT be auto-tied —
        # only enable nets are. FB needs a divider a human supplies.
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail at 1A")
        repair = out["repair"]
        assert any(v["rule_id"] == "ERC012" and "FB_VDD_3V3" in v["net_refs"] for v in repair.remaining)
        # the enable net, by contrast, was tied
        assert any(p.rule_id == "ERC012" and "EN_VDD_3V3" in p.new_value for p in repair.patches)

    def test_enable_tie_is_marked_a_default_choice(self) -> None:
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail at 1A")
        en_patch = next(p for p in out["repair"].patches if p.rule_id == "ERC012")
        assert en_patch.confidence < 1.0  # always-on default, a human may want sequencing


class TestSynthesizeAndRepair:
    def test_converges_and_escalates_single_pin_nets(self) -> None:
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail at 1A, I2C, ethernet")
        repair = out["repair"]
        assert repair.converged
        assert repair.patches  # footprints were assigned
        # The only thing it cannot fix here is single-pin nets (need real connectors).
        assert all(v["rule_id"] == "ERC012" for v in repair.remaining)
        assert not repair.fully_clean  # honest: ERC012 still needs a human

    def test_no_footprint_violations_remain_after_repair(self) -> None:
        out = synthesize_and_repair("USB-C powered board, 3.3V rail, I2C sensor")
        design = out["design"]
        assert _erc020_count(design) == 0

    def test_result_to_dict_round_trips_shape(self) -> None:
        out = synthesize_and_repair("USB-C powered board, 3.3V rail, I2C sensor")
        data = out["repair"].to_dict()
        assert set(data) == {"converged", "fully_clean", "patch_count", "iterations", "patches", "remaining"}
        assert data["patch_count"] == len(data["patches"])
