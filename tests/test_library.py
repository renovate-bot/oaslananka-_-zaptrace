"""Tests for component library loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from zaptrace.core.exceptions import LibraryError
from zaptrace.library.loader import ComponentSpec, LibraryLoader, LibraryLoadError


@pytest.fixture
def lib_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    return root


def _write_component(lib_root: Path, category: str, comp_id: str, **overrides: str) -> Path:
    path = lib_root / category / f"{comp_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "id": comp_id,
        "name": comp_id,
        "category": category,
        "manufacturer": "TestCorp",
        "mpn": f"{comp_id}-001",
        "description": f"A test {comp_id} component",
        "package": "SOT-23",
        "footprint": f"Footprint_{comp_id}",
        **overrides,
    }
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


class TestLibraryLoader:
    def test_empty_directory(self, lib_root: Path) -> None:
        loader = LibraryLoader(lib_root)
        assert loader.load_all() == {}

    def test_load_single(self, lib_root: Path) -> None:
        _write_component(lib_root, "passive", "res_10k")
        loader = LibraryLoader(lib_root)
        specs = loader.load_all()
        assert len(specs) == 1
        assert specs["res_10k"].name == "res_10k"
        assert specs["res_10k"].category == "passive"

    def test_load_multiple_categories(self, lib_root: Path) -> None:
        _write_component(lib_root, "passive", "res_10k")
        _write_component(lib_root, "mcu", "esp32")
        _write_component(lib_root, "sensor", "bme280")
        loader = LibraryLoader(lib_root)
        specs = loader.load_all()
        assert len(specs) == 3

    def test_invalid_yaml_skipped(self, lib_root: Path) -> None:
        path = lib_root / "passive" / "broken.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{invalid: yaml: broken", encoding="utf-8")
        loader = LibraryLoader(lib_root)
        assert loader.load_all() == {}

    def test_get_existing(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "stm32")
        loader = LibraryLoader(lib_root)
        spec = loader.get("stm32")
        assert spec.id == "stm32"
        assert spec.manufacturer == "TestCorp"

    def test_get_missing(self, lib_root: Path) -> None:
        loader = LibraryLoader(lib_root)
        with pytest.raises(LibraryError, match="not found"):
            loader.get("nonexistent")

    def test_search(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "esp32", manufacturer="Espressif")
        _write_component(lib_root, "sensor", "bme280", manufacturer="Bosch")
        _write_component(lib_root, "sensor", "mpu6050", manufacturer="TDK")
        loader = LibraryLoader(lib_root)
        results = loader.search("esp")
        assert len(results) > 0
        assert results[0].manufacturer == "Espressif"

    def test_search_no_match(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "esp32")
        loader = LibraryLoader(lib_root)
        results = loader.search("zzzznotfound")
        assert results == []

    def test_list_categories(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "esp32")
        _write_component(lib_root, "sensor", "bme280")
        loader = LibraryLoader(lib_root)
        cats = loader.list_categories()
        assert sorted(cats) == ["mcu", "sensor"]

    def test_cache_used(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "esp32")
        loader = LibraryLoader(lib_root)
        loader.load_all()  # populate cache
        _write_component(lib_root, "mcu", "stm32")  # add after cache
        specs = loader.load_all()  # should return cached (only esp32)
        assert len(specs) == 1


class TestLibraryLoadErrors:
    def test_clean_library_has_no_errors(self, lib_root: Path) -> None:
        _write_component(lib_root, "passive", "res_10k")
        _write_component(lib_root, "mcu", "esp32")
        loader = LibraryLoader(lib_root)
        assert loader.load_all()  # loads
        assert loader.load_errors() == []

    def test_broken_yaml_is_recorded_not_silent(self, lib_root: Path) -> None:
        path = lib_root / "passive" / "broken.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{invalid: yaml: broken", encoding="utf-8")
        loader = LibraryLoader(lib_root)
        assert loader.load_all() == {}  # broken part not included (still resilient)
        errors = loader.load_errors()
        assert len(errors) == 1
        assert isinstance(errors[0], LibraryLoadError)
        assert "broken.yaml" in errors[0].path
        assert "YAML" in errors[0].reason

    def test_missing_required_field_is_recorded(self, lib_root: Path) -> None:
        path = lib_root / "mcu" / "no_category.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump({"id": "x", "name": "X"}), encoding="utf-8")  # no category
        loader = LibraryLoader(lib_root)
        assert loader.load_all() == {}
        errors = loader.load_errors()
        assert len(errors) == 1
        assert "category" in errors[0].reason

    def test_one_bad_file_does_not_drop_the_good_ones(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "good")
        bad = lib_root / "mcu" / "bad.yaml"
        bad.write_text("{nope", encoding="utf-8")
        loader = LibraryLoader(lib_root)
        specs = loader.load_all()
        assert "good" in specs
        assert len(loader.load_errors()) == 1

    def test_duplicate_id_is_recorded_first_wins(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "dup")  # "mcu/dup.yaml" sorts first
        _write_component(lib_root, "sensor", "dup")  # same id, recorded as duplicate
        loader = LibraryLoader(lib_root)
        specs = loader.load_all()
        assert len(specs) == 1
        assert specs["dup"].category == "mcu"  # first occurrence kept
        assert any("duplicate" in e.reason for e in loader.load_errors())

    def test_non_mapping_yaml_is_recorded(self, lib_root: Path) -> None:
        path = lib_root / "passive" / "list.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- a\n- b\n", encoding="utf-8")  # valid YAML, but a list not a mapping
        loader = LibraryLoader(lib_root)
        assert loader.load_all() == {}
        assert any("not a component mapping" in e.reason for e in loader.load_errors())

    def test_real_shipped_library_loads_without_errors(self) -> None:
        # Guards both that the shipped library is clean AND that validation does
        # not reject any real part.
        loader = LibraryLoader()
        loader.load_all()
        assert loader.load_errors() == [], loader.load_errors()


class TestComponentSpec:
    def test_minimal_dataclass(self) -> None:
        spec = ComponentSpec(id="test", name="Test", category="mcu")
        assert spec.manufacturer == ""
        assert spec.pins == {}
        assert spec.properties == {}


class TestIoTExpansion:
    """Verify new seismic/IoT reference parts load from the real library."""

    _EXPECTED_PIN_COUNTS: dict[str, int] = {
        "adxl355": 14,
        "rv-3032-c7": 10,
        "ds3231sn": 12,
        "w5500": 22,
        "max-m10s": 16,
        "atecc608b": 8,
        "tlv62569": 5,
        "tps7a2033": 5,
        "tps3839": 3,
        "cn3058e": 8,
        "usblc6-2sc6": 6,
        "ws2812b-2020": 4,
    }

    def test_all_new_parts_load(self) -> None:
        loader = LibraryLoader()
        specs = loader.load_all()
        for part_id, expected_pins in self._EXPECTED_PIN_COUNTS.items():
            spec = specs.get(part_id)
            assert spec is not None, f"{part_id} not found"
            assert len(spec.pins) == expected_pins, f"{part_id}: expected {expected_pins} pins, got {len(spec.pins)}"

    def test_sx1262_extended(self) -> None:
        loader = LibraryLoader()
        spec = loader.get("sx1262-868m")
        assert spec is not None
        assert len(spec.pins) >= 19, f"sx1262-868m: expected >=19 pins, got {len(spec.pins)}"
        assert any("VBAT" in k for k in spec.pins), "sx1262-868m should have VBAT pins"


def _full_spec(**overrides: object) -> ComponentSpec:
    data: dict[str, object] = {
        "id": "x",
        "name": "X",
        "category": "mcu",
        "manufacturer": "Acme",
        "mpn": "ACME-1",
        "description": "a part",
        "datasheet": "https://example.com/ds.pdf",
        "package": "QFN-32",
        "footprint": "QFN-32_5x5",
        "pins": {"1": {"type": "power"}},
    }
    data.update(overrides)
    return ComponentSpec(**data)  # type: ignore[arg-type]


class TestLibraryConfidence:
    def test_full_metadata_scores_high(self) -> None:
        spec = _full_spec()
        assert spec.confidence_score == 1.0
        assert spec.confidence_grade == "high"
        assert spec.missing_metadata == []

    def test_minimal_spec_scores_low(self) -> None:
        spec = ComponentSpec(id="x", name="X", category="mcu")
        assert spec.confidence_score == 0.0
        assert spec.confidence_grade == "low"
        # every governance field is reported missing
        assert set(spec.missing_metadata) == {
            "mpn",
            "datasheet",
            "manufacturer",
            "footprint",
            "pins",
            "package",
            "description",
        }

    def test_missing_one_field_is_weighted(self) -> None:
        spec = _full_spec(datasheet="")  # datasheet weight is 0.20
        assert spec.confidence_score == 0.8
        assert spec.confidence_grade == "medium"
        assert spec.missing_metadata == ["datasheet"]

    def test_confidence_report_is_worst_first(self, lib_root: Path) -> None:
        # "rich" has datasheet + pins; "poor" (default _write_component) lacks both.
        _write_component(lib_root, "mcu", "poor")
        _write_component(
            lib_root,
            "mcu",
            "rich",
            datasheet="https://example.com/ds.pdf",
            pins={"1": {"type": "power"}},  # type: ignore[arg-type]
        )
        report = LibraryLoader(lib_root).confidence_report()
        assert [row["id"] for row in report] == ["poor", "rich"]
        assert report[0]["confidence_score"] <= report[1]["confidence_score"]
        assert "datasheet" in report[0]["missing_metadata"]

    def test_mean_confidence(self, lib_root: Path) -> None:
        _write_component(lib_root, "mcu", "a")
        _write_component(lib_root, "mcu", "b")
        loader = LibraryLoader(lib_root)
        mean = loader.mean_confidence()
        assert 0.0 < mean <= 1.0

    def test_mean_confidence_empty_library(self, lib_root: Path) -> None:
        assert LibraryLoader(lib_root).mean_confidence() == 0.0
