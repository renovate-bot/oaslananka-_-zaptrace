"""Tests for SPICE netlist export."""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin
from zaptrace.export.spice import _spice_value, export_spice_netlist, write_spice_netlist


def _design() -> Design:
    d = Design(meta=DesignMeta(name="SpiceTest"))
    d.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="mcu",
        pins={
            "VCC": Pin(name="VCC", type="power"),
            "GND": Pin(name="GND", type="power"),
            "OUT": Pin(name="OUT", type="output"),
        },
    )
    d.components["r1"] = Component(
        id="r1",
        ref="R1",
        type="resistor",
        value="10k",
        pins={"p1": Pin(name="p1", type="passive"), "p2": Pin(name="p2", type="passive")},
    )
    d.components["c1"] = Component(
        id="c1",
        ref="C1",
        type="capacitor",
        value="100nF",
        pins={"p1": Pin(name="p1", type="passive"), "p2": Pin(name="p2", type="passive")},
    )
    d.components["d1"] = Component(
        id="d1",
        ref="D1",
        type="LED",
        value="red",
        pins={"ANODE": Pin(name="ANODE", type="passive"), "CATHODE": Pin(name="CATHODE", type="passive")},
    )
    d.nets["vcc"] = Net(
        id="vcc",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="U1", pin_name="VCC"), NetNode(component_ref="R1", pin_name="p1")],
    )
    d.nets["gnd"] = Net(
        id="gnd",
        name="GND",
        type=NetType.GROUND,
        nodes=[
            NetNode(component_ref="U1", pin_name="GND"),
            NetNode(component_ref="C1", pin_name="p2"),
            NetNode(component_ref="D1", pin_name="CATHODE"),
        ],
    )
    d.nets["sig"] = Net(
        id="sig",
        name="SIG",
        type=NetType.SIGNAL,
        nodes=[
            NetNode(component_ref="U1", pin_name="OUT"),
            NetNode(component_ref="R1", pin_name="p2"),
            NetNode(component_ref="C1", pin_name="p1"),
            NetNode(component_ref="D1", pin_name="ANODE"),
        ],
    )
    return d


def test_passives_emit_element_cards() -> None:
    netlist = export_spice_netlist(_design())
    assert "R1 VCC SIG 10k" in netlist
    assert "C1 SIG 0 100n" in netlist  # ground collapses to node 0


def test_value_units_are_normalized() -> None:
    assert _spice_value("100nF") == "100n"
    assert _spice_value("4.7uF") == "4.7u"
    assert _spice_value("10k") == "10k"
    assert _spice_value("10kΩ") == "10k"
    assert _spice_value("100uH") == "100u"
    assert _spice_value(None) == ""
    # the farad unit must not survive into the capacitor card
    assert "100nF" not in export_spice_netlist(_design())


def test_ground_collapses_to_node_zero() -> None:
    netlist = export_spice_netlist(_design())
    # C1 pin2 and the LED cathode are on GND -> node 0
    assert "C1 SIG 0" in netlist
    assert "D1 SIG 0 DGEN" in netlist


def test_diode_gets_generic_model() -> None:
    netlist = export_spice_netlist(_design())
    assert "D1 SIG 0 DGEN" in netlist
    assert ".model DGEN D()" in netlist


def test_active_device_without_model_is_commented() -> None:
    netlist = export_spice_netlist(_design())
    # the MCU has no SPICE model -> emitted as a comment, never as a live card
    assert "* Unsupported: U1 (mcu) [no SPICE model]" in netlist
    assert "\nU1 " not in netlist


def test_unsupported_token_is_present_for_proof_checker() -> None:
    # zaptrace/proof/checker.py._check_spice greps the netlist for "Unsupported"
    # to report devices it could not simulate. Guard that contract here.
    assert "Unsupported" in export_spice_netlist(_design())
    # a passives-only / empty design must NOT trip the token
    assert "Unsupported" not in export_spice_netlist(Design(meta=DesignMeta(name="clean")))


def test_netlist_structure() -> None:
    netlist = export_spice_netlist(_design(), title="My Board")
    assert netlist.startswith("* My Board")
    assert netlist.rstrip().endswith(".end")


def test_write_spice_netlist_creates_file(tmp_path: Path) -> None:
    out = write_spice_netlist(_design(), tmp_path / "nested" / "board.cir")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.rstrip().endswith(".end")
    assert "R1 VCC SIG 10k" in text


def test_empty_design_is_valid() -> None:
    netlist = export_spice_netlist(Design(meta=DesignMeta(name="empty")))
    assert netlist.startswith("* empty")
    assert ".end" in netlist
