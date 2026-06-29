"""Tests for peripheral (sensor) synthesis and bus wiring."""

from __future__ import annotations

from zaptrace.core.models import Design, DesignMeta, Net
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.peripherals import instantiate_sensor, instantiate_spi_flash, plan_sensors, plan_storage
from zaptrace.synthesis.requirements import parse_requirements


def _plan(intent: str):
    return plan_sensors(parse_requirements(intent))


class TestSensorSelection:
    def test_temperature_picks_sht31(self) -> None:
        choices = _plan("ESP32 3.3V board, I2C temperature sensor")
        assert any(c.part_id == "sht31-dis" for c in choices)

    def test_accelerometer_picks_lis3dh(self) -> None:
        assert any(c.part_id == "lis3dh" for c in _plan("RP2040 board, I2C accelerometer"))

    def test_bare_sensor_falls_back_to_default(self) -> None:
        choices = _plan("STM32 3.3V board, I2C sensor")
        assert [c.part_id for c in choices] == ["bme280"]

    def test_multiple_measurements_pick_multiple_parts(self) -> None:
        part_ids = {c.part_id for c in _plan("board with I2C temperature and pressure sensors")}
        assert "sht31-dis" in part_ids
        assert "bmp390" in part_ids

    def test_no_i2c_bus_means_no_sensor(self) -> None:
        # Nowhere to hang a sensor without an I2C bus.
        assert _plan("SPI flash board, temperature sensor") == []

    def test_no_sensor_keyword_means_no_sensor(self) -> None:
        assert _plan("ESP32 3.3V board, I2C bus") == []


class TestStorageSelection:
    def test_spi_flash_intent_picks_w25q(self) -> None:
        choices = plan_storage(parse_requirements("ESP32 3.3V board, SPI flash storage"))
        assert [c.part_id for c in choices] == ["w25q128jv"]
        assert choices[0].bus == "spi"

    def test_no_spi_bus_means_no_flash(self) -> None:
        assert plan_storage(parse_requirements("I2C board with flash mention")) == []

    def test_no_flash_keyword_means_no_storage(self) -> None:
        assert plan_storage(parse_requirements("ESP32 3.3V board, SPI display")) == []


class TestInstantiateSpiFlash:
    def _spi_bus(self) -> Design:
        design = Design(meta=DesignMeta(name="spi_test"))
        for net in ("VDD_3V3", "GND", "SPI_SCK", "SPI_MOSI", "SPI_MISO", "SPI_CS"):
            design.nets[net] = Net(id=net, name=net)
        return design

    def test_wires_spi_bus_and_holds_wp_high(self) -> None:
        design = self._spi_bus()
        ref = instantiate_spi_flash(design, "w25q128jv", rail_net="VDD_3V3")
        assert ref is not None
        for net in ("SPI_SCK", "SPI_MOSI", "SPI_MISO", "SPI_CS"):
            assert any(n.component_ref == ref for n in design.nets[net].nodes)
        # WP# and HOLD# are tied to the rail for normal (non-quad) operation
        rail_pins = {n.pin_name for n in design.nets["VDD_3V3"].nodes if n.component_ref == ref}
        assert {"WP", "HOLD"} <= rail_pins


class TestInstantiateSensor:
    def _bus(self) -> Design:
        design = Design(meta=DesignMeta(name="periph_test"))
        for net in ("VDD_3V3", "GND", "SDA", "SCL"):
            design.nets[net] = Net(id=net, name=net)
        return design

    def test_wires_power_and_bus(self) -> None:
        design = self._bus()
        ref = instantiate_sensor(design, "sht31-dis", rail_net="VDD_3V3")
        assert ref is not None
        assert any(n.component_ref == ref for n in design.nets["SDA"].nodes)
        assert any(n.component_ref == ref for n in design.nets["SCL"].nodes)
        assert any(n.component_ref == ref for n in design.nets["VDD_3V3"].nodes)
        # a decoupling cap was added too
        assert any(c.type == "capacitor" for c in design.components.values())

    def test_clock_pin_named_sck_joins_scl_net(self) -> None:
        # bmp390 names its clock SCK; it must still land on the SCL bus net.
        design = self._bus()
        ref = instantiate_sensor(design, "bmp390", rail_net="VDD_3V3")
        assert any(n.component_ref == ref for n in design.nets["SCL"].nodes)

    def test_active_low_reset_is_tied_high(self) -> None:
        # sht31-dis has an active-low nRESET; it must be held high, not left floating.
        design = self._bus()
        ref = instantiate_sensor(design, "sht31-dis", rail_net="VDD_3V3")
        reset_on_rail = any(
            n.component_ref == ref and n.pin_name.upper() in {"NRESET", "NRST"} for n in design.nets["VDD_3V3"].nodes
        )
        assert reset_on_rail

    def test_ref_does_not_collide(self) -> None:
        design = self._bus()
        from zaptrace.core.models import Component

        design.components["U1"] = Component(id="U1", ref="U1", type="mcu", value="X")
        ref = instantiate_sensor(design, "sht31-dis", rail_net="VDD_3V3")
        assert ref != "U1"


class TestIntegration:
    def test_board_has_mcu_and_sensor_on_one_bus(self) -> None:
        design, plan, _log = build_architecture_design(
            parse_requirements("ESP32-C3 3.3V board, I2C temperature sensor")
        )
        mcu = next(c for c in design.components.values() if c.type == "mcu")
        sensor = next(c for c in design.components.values() if c.type == "sensor")
        sda_members = {n.component_ref for n in design.nets["SDA"].nodes}
        assert mcu.ref in sda_members and sensor.ref in sda_members
        # the sensor is a realized peripheral block in the graph
        block = next(b for b in plan.blocks if b.kind == "peripheral")
        assert block.realized and "iface:i2c" in block.contract.requires

    def test_no_sensor_block_without_a_sensor_intent(self) -> None:
        _design, plan, _log = build_architecture_design(parse_requirements("ESP32-C3 3.3V board, I2C bus"))
        assert not any(b.kind == "peripheral" for b in plan.blocks)

    def test_usb_c_i2c_sensor_board_has_clean_erc(self) -> None:
        # End-to-end: a complete I2C-sensor board should converge to a clean ERC
        # (connector terminates CC, sensor reset tied, footprints assigned).
        from zaptrace.synthesis.repair import synthesize_and_repair

        out = synthesize_and_repair("ESP32-C3 USB-C 3.3V board, I2C temperature sensor")
        assert out["repair"].fully_clean

    def test_spi_flash_joins_the_mcu_mastered_bus(self) -> None:
        design, _plan, _log = build_architecture_design(parse_requirements("ESP32-C3 3.3V board, SPI flash storage"))
        mcu = next(c for c in design.components.values() if c.type == "mcu")
        flash = next(c for c in design.components.values() if c.type == "memory")
        sck = {n.component_ref for n in design.nets["SPI_SCK"].nodes}
        assert mcu.ref in sck and flash.ref in sck
