"""Peripheral synthesis: place real sensors and hang them on the MCU's bus.

Functional-core synthesis (:mod:`zaptrace.synthesis.mcu`) gives the board a brain
and an I2C bus, but nothing to talk to. This adds the peripherals the intent asks
for: it picks a real sensor part for the requested measurement, places it, ties
its power pins to the rail, and drops it onto the existing I2C bus (the same SDA/
SCL nets the MCU and pull-ups are on). The result fulfils the intent — an "I2C
temperature sensor board" gets an actual temperature sensor, not an empty bus.

Deterministic: sensor selection is keyword-driven with a fixed rule order, and
parts mount in that order. Honest: a measurement with no library part, or an
intent with no I2C bus to hang a sensor on, is reported, never faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.core.models import Component, Net, NetNode, Pin, PinType
from zaptrace.library.loader import LibraryLoader

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.requirements import Requirements

# Keyword sets -> the I2C sensor part to place, in priority order. First rule a
# token hits wins for that measurement; several rules can match one intent.
_SENSOR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("humidity", "climate", "rht"), "sht31-dis", "temperature/humidity"),
    (("temperature", "temp ", "thermo"), "sht31-dis", "temperature/humidity"),
    (("pressure", "barometer", "altitude", "baro"), "bmp390", "pressure/altitude"),
    (("accelerom", "imu", "motion", "accel", "tilt", "vibration"), "lis3dh", "accelerometer"),
    (("adc", "analog input", "analog-to-digital"), "ads1115", "ADC"),
    (("air quality", "gas", "voc", "co2"), "bme688", "air-quality/gas"),
]
# A bare "sensor" mention with an I2C bus but no specific measurement.
_DEFAULT_I2C_SENSOR = ("bme280", "environmental")

_SUPPLY_NAMES = {"VDD", "VCC"}
_GROUND_NAMES = {"GND", "VSS"}
_I2C_DATA_NAMES = {"SDA", "SDI"}
_I2C_CLK_NAMES = {"SCL", "SCK"}
_I2C_ADDR_NAMES = {"ADDR", "SA0"}  # tie to GND for the default I2C address


@dataclass(frozen=True)
class SensorChoice:
    """A sensor the planner decided to place, and why."""

    part_id: str
    function: str
    realized: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"part_id": self.part_id, "function": self.function, "realized": self.realized, "reason": self.reason}


@dataclass
class PeripheralResult:
    """Outcome of peripheral synthesis."""

    sensors: list[SensorChoice] = field(default_factory=list)
    placed_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensors": [s.to_dict() for s in self.sensors],
            "placed_refs": self.placed_refs,
            "notes": self.notes,
        }


def plan_sensors(requirements: Requirements) -> list[SensorChoice]:
    """Pick the I2C sensors an intent calls for (deduplicated, deterministic).

    Returns an empty list when there is no I2C bus to hang a sensor on, so a
    sensor is never placed with nowhere to connect.
    """
    if "i2c" not in requirements.interfaces:
        return []
    text = requirements.raw_intent.lower()
    chosen: list[SensorChoice] = []
    seen: set[str] = set()
    for keywords, part_id, function in _SENSOR_RULES:
        if any(kw in text for kw in keywords) and part_id not in seen:
            seen.add(part_id)
            chosen.append(SensorChoice(part_id=part_id, function=function, realized=_part_exists(part_id)))
    if not chosen and "sensor" in text:
        part_id, function = _DEFAULT_I2C_SENSOR
        chosen.append(SensorChoice(part_id=part_id, function=function, realized=_part_exists(part_id)))
    return chosen


def _part_exists(part_id: str) -> bool:
    return part_id in LibraryLoader().load_all()


def _pin_type(raw: dict[str, str]) -> PinType:
    try:
        return PinType(raw.get("type", "bidirectional"))
    except ValueError:
        return PinType.BIDIRECTIONAL


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _connect(design: Design, net_name: str, ref: str, pin: str) -> None:
    if net_name not in design.nets:
        design.nets[net_name] = Net(id=net_name, name=net_name)
    design.nets[net_name].nodes.append(NetNode(component_ref=ref, pin_name=pin))


def _find_pin(spec_pins: dict[str, dict[str, str]], names: set[str]) -> str | None:
    for name in spec_pins:
        if name.upper() in names:
            return name
    return None


def instantiate_sensor(
    design: Design,
    part_id: str,
    *,
    rail_net: str,
    gnd_net: str = "GND",
    sda_net: str = "SDA",
    scl_net: str = "SCL",
) -> str | None:
    """Place one I2C sensor and wire its power and bus pins. Returns its ref.

    Power pins tie to ``rail_net``/``gnd_net``; the data/clock pins (whatever the
    part names them — SDA/SDI, SCL/SCK) join the board's I2C bus nets; an address
    pin is tied to GND for the default address. A 100 nF bypass is added on the
    rail. Mode/chip-select pins are left for a human (part-specific).
    """
    spec = LibraryLoader().get(part_id)
    supply_pin = _find_pin(spec.pins, _SUPPLY_NAMES)
    ground_pin = _find_pin(spec.pins, _GROUND_NAMES)
    data_pin = _find_pin(spec.pins, _I2C_DATA_NAMES)
    clock_pin = _find_pin(spec.pins, _I2C_CLK_NAMES)
    if not all((supply_pin, ground_pin, data_pin, clock_pin)):
        return None  # not an I2C part we can wire confidently

    ref = _next_ref(design, "U")
    design.components[ref] = Component(
        id=ref,
        ref=ref,
        type="sensor",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
    )
    _connect(design, rail_net, ref, supply_pin)
    _connect(design, gnd_net, ref, ground_pin)
    _connect(design, sda_net, ref, data_pin)
    _connect(design, scl_net, ref, clock_pin)
    addr_pin = _find_pin(spec.pins, _I2C_ADDR_NAMES)
    if addr_pin is not None:
        _connect(design, gnd_net, ref, addr_pin)

    # 100 nF decoupling cap on the sensor's rail (footprint assigned by repair).
    cap_ref = _next_ref(design, "C")
    design.components[cap_ref] = Component(id=cap_ref, ref=cap_ref, type="capacitor", value="100nF")
    _connect(design, rail_net, cap_ref, "1")
    _connect(design, gnd_net, cap_ref, "2")
    return ref


def instantiate_peripherals(
    design: Design,
    requirements: Requirements,
    *,
    rail_net: str,
    gnd_net: str = "GND",
) -> PeripheralResult:
    """Place every sensor :func:`plan_sensors` selects and wire it to the I2C bus."""
    result = PeripheralResult(sensors=plan_sensors(requirements))
    for choice in result.sensors:
        if not choice.realized:
            result.notes.append(f"sensor '{choice.part_id}' ({choice.function}) has no library part")
            continue
        ref = instantiate_sensor(design, choice.part_id, rail_net=rail_net, gnd_net=gnd_net)
        if ref is None:
            result.notes.append(f"sensor '{choice.part_id}' could not be wired as I2C (missing SDA/SCL/power pins)")
        else:
            result.placed_refs.append(ref)
    return result
