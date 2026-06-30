"""Tests for vendored (verified KiCad) footprint resolution."""

from __future__ import annotations

from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint
from zaptrace.kicad.importer import load_kicad_footprint
from zaptrace.synthesis.footprint_resolver import resolve_footprints
from zaptrace.synthesis.repair import synthesize_and_repair


class TestVendorRegistry:
    def test_every_registered_file_exists_and_parses(self) -> None:
        # Each registry entry must resolve to a real, parseable land pattern with pads.
        for name in VENDOR_FOOTPRINTS:
            fp = resolve_vendored_footprint(name)
            assert fp is not None, f"{name} did not resolve"
            assert fp.pads, f"{name} has no pads"
            assert fp.courtyard != (0.0, 0.0), f"{name} has no courtyard extent"

    def test_unknown_name_returns_none(self) -> None:
        assert resolve_vendored_footprint("NOT-A-REAL-FOOTPRINT") is None

    def test_returns_fresh_copy_each_call(self) -> None:
        a = resolve_vendored_footprint("BME280-LGA8")
        b = resolve_vendored_footprint("BME280-LGA8")
        assert a is not None and b is not None
        assert a is not b  # distinct objects, safe to mutate independently
        a.pads.clear()
        assert b.pads, "mutating one copy must not affect another"

    def test_known_package_pad_counts(self) -> None:
        # Sanity-check the geometry actually came from the right package.
        assert len(resolve_vendored_footprint("BME280-LGA8").pads) == 8  # type: ignore[union-attr]
        assert len(resolve_vendored_footprint("SHT31-DIS-DFN8").pads) == 9  # 8 + thermal EP  # type: ignore[union-attr]


class TestFootprintImporter:
    def test_load_nonexistent_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        bogus = Path(str(tmp_path)) / "missing.kicad_mod"
        bogus.write_text("(module foo)", encoding="utf-8")
        assert load_kicad_footprint(bogus) is None  # not a footprint form


class TestResolverIntegration:
    def test_esp32_module_resolves_via_vendor(self) -> None:
        out = synthesize_and_repair("ESP32-C3 wifi board, I2C BME280")
        result = resolve_footprints(out["design"])
        assert result.fully_resolved, f"unresolved: {result.unresolved}"
        # The ESP32 module and the BME280 both come from vendored land patterns.
        u1 = next(c for c in out["design"].components.values() if c.footprint == "ESP32-C3-MINI-1")
        assert u1.footprint_def is not None
        assert u1.footprint_def.pads

    def test_ethernet_rj45_resolves_via_vendor(self) -> None:
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail, I2C, ethernet")
        result = resolve_footprints(out["design"])
        assert result.fully_resolved, f"unresolved: {result.unresolved}"
