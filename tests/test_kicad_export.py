"""Tests for KiCad export — pad-net mapping and via net IDs."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    NetNode,
    NetType,
    Pad,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.kicad import export_kicad, export_kicad_pcb, export_kicad_schematic


def _make_test_design() -> Design:
    c1 = Component(
        id="r1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint="0805",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE, net="vcc"),
            "2": Pin(name="2", type=PinType.PASSIVE, net="gnd"),
        },
    )
    c2 = Component(
        id="c1",
        ref="C1",
        type="capacitor",
        value="100nF",
        footprint="0805",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE, net="vcc"),
            "2": Pin(name="2", type=PinType.PASSIVE, net="gnd"),
        },
    )
    n_vcc = Net(
        id="vcc",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="r1", pin_name="1"), NetNode(component_ref="c1", pin_name="1")],
    )
    n_gnd = Net(
        id="gnd",
        name="GND",
        type=NetType.GROUND,
        nodes=[NetNode(component_ref="r1", pin_name="2"), NetNode(component_ref="c1", pin_name="2")],
    )
    c1.footprint_def = FootprintDef(pads=[Pad(id="1"), Pad(id="2")])
    c2.footprint_def = FootprintDef(pads=[Pad(id="1"), Pad(id="2")])
    return Design(
        meta=DesignMeta(name="KiCadTest", version="0.1.0"),
        components={"r1": c1, "c1": c2},
        nets={"vcc": n_vcc, "gnd": n_gnd},
    )


def _make_design_with_vias() -> Design:
    d = _make_test_design()
    d.routing = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(10.0, 0.0), width=0.2, net_id="vcc")],
        vias=[(5.0, 0.0, 0.45, 0.2, "vcc")],
    )
    return d


def test_pad_net_mapping(tmp_path: Path) -> None:
    d = _make_test_design()
    out = export_kicad_schematic(d, tmp_path)
    kicad_sch = Path(out["schematic"]).read_text(encoding="utf-8")
    assert "KiCadTest" in kicad_sch
    assert "kicad_sch" in kicad_sch


def test_pcb_pad_net_numbers(tmp_path: Path) -> None:
    d = _make_test_design()
    out = export_kicad_pcb(d, tmp_path)
    pcb_text = Path(out["pcb"]).read_text(encoding="utf-8")
    assert '(net 1 "VCC")' in pcb_text
    assert '(net 2 "GND")' in pcb_text


def test_via_net_id_present(tmp_path: Path) -> None:
    d = _make_design_with_vias()
    out = export_kicad_pcb(d, tmp_path)
    pcb_text = Path(out["pcb"]).read_text(encoding="utf-8")
    assert "(via" in pcb_text
    assert "(net 1)" in pcb_text


def test_kicad_export_writes_connected_netlist_evidence(tmp_path: Path) -> None:
    d = _make_design_with_vias()
    out = export_kicad(d, tmp_path)
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "1.0"
    assert evidence["net_count"] == 2
    assert evidence["missing_or_unmapped_node_count"] == 0
    vcc = next(net for net in evidence["nets"] if net["id"] == "vcc")
    assert vcc["name"] == "VCC"
    assert len(vcc["nodes"]) == 2
    assert vcc["routed_segment_count"] == 1
    assert vcc["routed_via_count"] == 1
    assert evidence["fidelity"]["has_routed_pcb_geometry"] is True


def test_kicad_netlist_evidence_reports_missing_footprint_pad(tmp_path: Path) -> None:
    d = _make_test_design()
    d.components["r1"].footprint_def = FootprintDef(pads=[Pad(id="1")])
    out = export_kicad(d, tmp_path)
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))
    assert evidence["missing_or_unmapped_node_count"] == 1
    gnd = next(net for net in evidence["nets"] if net["id"] == "gnd")
    assert "r1.2" in gnd["missing_or_unmapped_nodes"]
    assert evidence["fidelity"]["pcb_pad_coverage"] < 1.0
