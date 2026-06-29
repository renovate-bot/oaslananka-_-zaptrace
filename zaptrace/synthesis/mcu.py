"""Functional-core synthesis: instantiate the MCU and wire it to the board.

Block-composition synthesis (:mod:`zaptrace.synthesis.architecture`) emits the
*support* circuitry — regulators, pull-ups, transceivers, termination — but no
brain. This module adds the functional core: it loads the real MCU part for the
requested family from the library, places it, ties its power pins to the logic
rail, and assigns its GPIOs to the interface support nets already on the board
(I2C SDA/SCL, RS-485 control, CAN TXD/RXD).

That turns a pile of support blocks into a *connected system*: the data nets that
were single-pin (a pull-up with nothing on the other end) now reach the MCU.

Deterministic: GPIO pins are assigned in natural order to interfaces in a fixed
order, so the same requirements always produce the same pin map. Honest: a family
with no library part, or an interface with no support net, is reported, never
faked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.core.models import Component, Net, NetNode, Pin, PinType
from zaptrace.library.loader import LibraryLoader

if TYPE_CHECKING:
    from zaptrace.core.models import Design

# MCU family -> the default library part to instantiate for it.
_FAMILY_PART: dict[str, str] = {
    "esp32": "esp32-c3-mini-1",
    "stm32": "stm32f103c8t6",
    "rp2040": "rp2040",
    "nrf52": "nrf52840-qiaa",
    "atmega": "atmega328p-au",
    "ch32": "ch32v003f4p6",
    # "samd": no library part yet -> reported as unrealized
}

# Interface -> the signals the MCU must drive, paired with the support-block net
# each one connects to. For a bus with a support block (I2C, RS-485, CAN) the net
# is one architecture synthesis already emitted; for a point-to-point bus the MCU
# masters (SPI), the net is created here for a peripheral to join.
_INTERFACE_SIGNALS: dict[str, list[tuple[str, str]]] = {
    "i2c": [("SDA", "SDA"), ("SCL", "SCL")],
    "spi": [("SCK", "SPI_SCK"), ("MOSI", "SPI_MOSI"), ("MISO", "SPI_MISO"), ("CS", "SPI_CS")],
    "rs485": [("RO", "RS485_RO"), ("DI", "RS485_DI"), ("nRE", "RS485_nRE"), ("DE", "RS485_DE")],
    "can": [("TXD", "CAN_TXD"), ("RXD", "CAN_RXD")],
}
# Buses whose nets must already exist (their support block created them); other
# interfaces (SPI) have the MCU create the nets.
_REQUIRES_SUPPORT_NET = frozenset({"i2c", "rs485", "can"})
# Deterministic interface order for pin assignment.
_INTERFACE_ORDER = ("i2c", "spi", "uart", "rs485", "can")

_GROUND_NAMES = {"GND", "VSS", "VSSA", "AGND", "DGND"}
_ENABLE_NAMES = {"EN", "NRST", "RESET", "RST"}
_NON_GPIO_NAMES = {"USB_DP", "USB_DM", "USB_D+", "USB_D-"}

# Per-family boot/config straps so the part boots and runs: pin -> how to tie it.
# "pulldown"/"pullup" add a 10 kΩ resistor; "gnd"/"rail" tie directly.
_STRAPS: dict[str, dict[str, str]] = {
    "stm32": {"BOOT0": "pulldown"},  # boot from main flash
    "rp2040": {"RUN": "pullup", "TESTEN": "gnd"},  # run enabled, factory test off
}


@dataclass(frozen=True)
class PinAssignment:
    """One MCU pin tied to a board net, with why."""

    pin: str
    net: str
    function: str  # "power", "ground", "enable", or "<iface>:<signal>"

    def to_dict(self) -> dict[str, str]:
        return {"pin": self.pin, "net": self.net, "function": self.function}


@dataclass
class McuResult:
    """Outcome of functional-core synthesis."""

    realized: bool
    family: str | None
    part_id: str | None = None
    ref: str | None = None
    assignments: list[PinAssignment] = field(default_factory=list)
    unconnected_interfaces: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "realized": self.realized,
            "family": self.family,
            "part_id": self.part_id,
            "ref": self.ref,
            "assignments": [a.to_dict() for a in self.assignments],
            "unconnected_interfaces": self.unconnected_interfaces,
            "reason": self.reason,
        }


def _natural_key(name: str) -> tuple[str, int, str]:
    """Sort GPIO names so GPIO2 precedes GPIO10 (prefix, number, raw)."""
    match = re.match(r"^(.*?)(\d+)$", name)
    if match:
        return (match.group(1), int(match.group(2)), name)
    return (name, -1, name)


def _pin_type(raw: dict[str, str]) -> PinType:
    try:
        return PinType(raw.get("type", "bidirectional"))
    except ValueError:
        return PinType.BIDIRECTIONAL


def _connect(design: Design, net_name: str, ref: str, pin: str) -> None:
    if net_name not in design.nets:
        design.nets[net_name] = Net(id=net_name, name=net_name)
    design.nets[net_name].nodes.append(NetNode(component_ref=ref, pin_name=pin))


def _classify_pins(spec_pins: dict[str, dict[str, str]]) -> tuple[list[str], list[str], str | None, list[str]]:
    """Return (supply_pins, ground_pins, enable_pin, assignable_gpio_pins).

    *Every* power pin is collected, not just the first: an MCU with a floating
    VDDA/VBAT/USB_VDD does not work, so each must reach the rail or ground.
    """
    supply: list[str] = []
    ground: list[str] = []
    enable: str | None = None
    gpios: list[str] = []
    for name, raw in spec_pins.items():
        upper = name.upper()
        ptype = raw.get("type", "")
        if ptype == "power" and upper in _GROUND_NAMES:
            ground.append(name)
        elif ptype == "power":
            supply.append(name)  # VDD, VDDA, VBAT, USB_VDD, VREG_VIN, AVDD, ...
        elif upper in _ENABLE_NAMES:
            enable = enable or name
        elif ptype == "bidirectional" and upper not in _NON_GPIO_NAMES:
            gpios.append(name)
    gpios.sort(key=_natural_key)
    return supply, ground, enable, gpios


def has_mcu_part(family: str | None) -> bool:
    """True when *family* has a library part this module can instantiate."""
    return family in _FAMILY_PART


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _apply_straps(
    design: Design, ref: str, family: str, spec_pins: dict[str, dict[str, str]], *, rail_net: str, gnd_net: str
) -> list[PinAssignment]:
    """Tie the family's boot/config pins so the part boots and runs."""
    from zaptrace.core.models import Component

    assignments: list[PinAssignment] = []
    for pin, mode in _STRAPS.get(family, {}).items():
        if pin not in spec_pins:
            continue
        if mode in ("gnd", "rail"):
            target = gnd_net if mode == "gnd" else rail_net
            _connect(design, target, ref, pin)
            assignments.append(PinAssignment(pin, target, f"strap:{mode}"))
            continue
        # pull-up / pull-down: a 10k resistor from the pin's net to rail/gnd.
        r_ref = _next_ref(design, "R")
        design.components[r_ref] = Component(id=r_ref, ref=r_ref, type="resistor", value="10k", footprint="0402")
        pin_net = f"{ref}_{pin}"
        target = rail_net if mode == "pullup" else gnd_net
        _connect(design, pin_net, ref, pin)
        _connect(design, pin_net, r_ref, "2")
        _connect(design, target, r_ref, "1")
        assignments.append(PinAssignment(pin, pin_net, f"strap:{mode}"))
    return assignments


def instantiate_mcu(
    design: Design,
    family: str | None,
    interfaces: list[str],
    *,
    rail_net: str,
    gnd_net: str = "GND",
    ref: str | None = None,
) -> McuResult:
    """Place the MCU for *family* and wire its power and interface pins.

    Power pins tie to ``rail_net``/``gnd_net`` and the enable pin is held active
    (a human can add reset sequencing later). GPIOs are assigned to the interface
    support nets already present on *design*; an interface whose support net is
    missing is reported in ``unconnected_interfaces``. ``ref`` defaults to the
    next free ``U`` designator so the MCU never clobbers a regulator/transceiver.
    """
    if family is None:
        return McuResult(realized=False, family=None, reason="no MCU stated in requirements")
    part_id = _FAMILY_PART.get(family)
    if part_id is None:
        return McuResult(realized=False, family=family, reason=f"no library part for MCU family '{family}'")

    if ref is None:
        ref = _next_ref(design, "U")
    spec = LibraryLoader().get(part_id)
    supply_pins, ground_pins, enable_pin, gpios = _classify_pins(spec.pins)

    component = Component(
        id=ref,
        ref=ref,
        type="mcu",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
    )
    design.components[ref] = component

    assignments: list[PinAssignment] = []
    for pin in supply_pins:
        _connect(design, rail_net, ref, pin)
        assignments.append(PinAssignment(pin, rail_net, "power"))
    for pin in ground_pins:
        _connect(design, gnd_net, ref, pin)
        assignments.append(PinAssignment(pin, gnd_net, "ground"))
    if enable_pin is not None:
        _connect(design, rail_net, ref, enable_pin)
        assignments.append(PinAssignment(enable_pin, rail_net, "enable"))
    assignments.extend(_apply_straps(design, ref, family, spec.pins, rail_net=rail_net, gnd_net=gnd_net))

    unconnected: list[str] = []
    available = list(gpios)
    for iface in _INTERFACE_ORDER:
        if iface not in interfaces:
            continue
        signals = _INTERFACE_SIGNALS.get(iface)
        if signals is None:
            unconnected.append(iface)  # recognized but no peripheral block yet
            continue
        needs_existing = iface in _REQUIRES_SUPPORT_NET
        missing_support = needs_existing and any(net not in design.nets for _, net in signals)
        if missing_support or len(available) < len(signals):
            unconnected.append(iface)
            continue
        for signal, net in signals:
            pin = available.pop(0)
            _connect(design, net, ref, pin)
            assignments.append(PinAssignment(pin, net, f"{iface}:{signal}"))

    return McuResult(
        realized=True,
        family=family,
        part_id=part_id,
        ref=ref,
        assignments=assignments,
        unconnected_interfaces=unconnected,
    )
