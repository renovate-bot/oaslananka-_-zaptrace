"""Tests for datasheet intelligence extraction pipeline. (#106)"""

from __future__ import annotations

import pytest

from zaptrace.library.datasheet import ExtractedField, extract_datasheet

_LDO_DATASHEET = """
TS2940 Positive Voltage Regulator
Texas Instruments — Low-Dropout Linear Regulator

The TS2940 is a 1A low-dropout regulator.

Features:
  - Supply (Input) Voltage: 5V to 15V
  - Output Voltage: Fixed 5V / 3.3V / Adjustable
  - Output Current: 1 A maximum
  - Dropout Voltage: 500 mV at 1A
  - Quiescent Current: 55 uA typical
  - Operating Temperature: -40°C to +125°C
  - Package: SOT-223

Pin Table:
  Pin 1  IN    Input voltage
  Pin 2  GND   Ground
  Pin 3  OUT   Regulated output
"""


class TestExtractDatasheet:
    def test_part_number_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.part_number.value is not None
        assert "TS2940" in str(result.part_number.value)
        assert result.part_number.confidence > 0.5

    def test_manufacturer_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.manufacturer.value is not None
        assert "Texas Instruments" in str(result.manufacturer.value)

    def test_package_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.package.value is not None
        assert "SOT" in str(result.package.value).upper()

    def test_supply_voltage_range(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.supply_voltage_min_v.value == pytest.approx(5.0)
        assert result.supply_voltage_max_v.value == pytest.approx(15.0)

    def test_output_current_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.output_current_max_a.value == pytest.approx(1.0, rel=0.01)

    def test_temperature_range(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.operating_temp_min_c.value == pytest.approx(-40.0)
        assert result.operating_temp_max_c.value == pytest.approx(125.0)

    def test_dropout_voltage_mv(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.dropout_voltage_v.value == pytest.approx(0.5, rel=0.01)

    def test_quiescent_current_ua(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        assert result.quiescent_current_ua.value == pytest.approx(55.0, rel=0.01)

    def test_pin_functions_extracted(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        # At least GND and OUT should be detected
        assert len(result.pin_functions) >= 2

    def test_fill_rate(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        # Most fields should be filled for this well-structured text
        assert result.fill_rate > 0.5

    def test_serializable(self) -> None:
        result = extract_datasheet(_LDO_DATASHEET)
        d = result.to_dict()
        assert "part_number" in d
        assert "fill_rate" not in d  # property, not a field


class TestEmptyDatasheet:
    def test_empty_text_returns_defaults(self) -> None:
        result = extract_datasheet("")
        assert result.part_number.value is None
        assert result.part_number.confidence == 0.0
        assert result.fill_rate == 0.0

    def test_import_losses_populated(self) -> None:
        result = extract_datasheet("")
        assert len(result.import_losses) > 0


class TestExtractedField:
    def test_to_dict(self) -> None:
        f = ExtractedField(3.3, 0.9, "3.3V supply")
        d = f.to_dict()
        assert d["value"] == 3.3
        assert d["confidence"] == 0.9
        assert d["source_snippet"] == "3.3V supply"
