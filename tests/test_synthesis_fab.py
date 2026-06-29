"""Tests for the end-to-end intent → manufacturing + evidence flow."""

from __future__ import annotations

from pathlib import Path

from zaptrace.synthesis.fab import FabResult, synthesize_to_manufacturing


class TestFabFlow:
    def test_produces_manufacturing_artifacts(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V board, I2C temperature sensor", tmp_path)
        assert isinstance(result, FabResult)
        names = " ".join(result.artifacts)
        assert ".zip" in names  # bundle
        assert ".DRL" in names or ".drl" in names.lower()  # drill
        assert "bom" in names.lower()  # bill of materials
        assert any(a.upper().endswith((".GTL", ".GBL")) for a in result.artifacts)  # copper gerber
        # the files really exist on disk
        assert all((tmp_path / a).is_file() for a in result.artifacts)

    def test_carries_score_and_bias_evidence(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V board, I2C sensor", tmp_path)
        assert 0 <= result.scorecard["score"] <= 100
        assert "passed" in result.dc_bias

    def test_review_checklist_flags_unresolved_footprints_and_mandates_review(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V board, I2C temperature sensor", tmp_path)
        joined = "\n".join(result.review_checklist)
        # the MCU module has no land pattern yet → must be called out
        assert "no pad geometry" in joined
        assert "ESP32-C3-MINI-1" in joined
        # the mandatory human-review line is always present
        assert any("qualified engineer" in item for item in result.review_checklist)

    def test_undriven_rail_appears_in_checklist(self, tmp_path: Path) -> None:
        result = synthesize_to_manufacturing("ESP32-C3 battery board, single Li-ion cell, 5V rail", tmp_path)
        assert any("undriven rail" in item for item in result.review_checklist)

    def test_to_dict_shape(self, tmp_path: Path) -> None:
        data = synthesize_to_manufacturing("ESP32-C3 3.3V board, I2C sensor", tmp_path).to_dict()
        assert {
            "intent",
            "design_name",
            "component_count",
            "net_count",
            "scorecard",
            "dc_bias",
            "artifacts",
            "review_checklist",
            "output_dir",
        } == set(data)
