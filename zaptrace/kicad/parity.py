"""KiCad netlist parity checks.

The current KiCad schematic exporter emits a machine-readable
``*.kicad_netlist_evidence.json`` contract alongside the schematic/PCB files.
This module compares that exported evidence back to the ZapTrace IR so missing
nets, extra nets, and pin mismatches are visible and release-gateable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from zaptrace.core.models import Design


class NetPinMismatch(BaseModel):
    """Pin-level mismatch for one net."""

    net_id: str
    missing_nodes: list[str] = Field(default_factory=list)
    extra_nodes: list[str] = Field(default_factory=list)


class KiCadNetlistParityReport(BaseModel):
    """IR ↔ KiCad netlist-evidence parity report."""

    schema_version: str = "1.0"
    check: str = "ir_to_kicad_schematic_netlist"
    passed: bool
    missing_nets: list[str] = Field(default_factory=list)
    extra_nets: list[str] = Field(default_factory=list)
    pin_mismatches: list[NetPinMismatch] = Field(default_factory=list)
    ir_net_count: int = 0
    kicad_net_count: int = 0
    message: str = ""

    @property
    def error_count(self) -> int:
        return len(self.missing_nets) + len(self.extra_nets) + len(self.pin_mismatches)


def _node_key(component_ref: str, pin_name: str) -> str:
    return f"{component_ref}.{pin_name}"


def ir_net_map(design: Design) -> dict[str, set[str]]:
    """Return ``net_id -> {component.pin}`` for ZapTrace IR connectivity."""
    return {
        net_id: {_node_key(node.component_ref, node.pin_name) for node in net.nodes}
        for net_id, net in design.nets.items()
    }


def kicad_evidence_net_map(evidence: dict[str, Any]) -> dict[str, set[str]]:
    """Return ``net_id -> {component.pin}`` from KiCad netlist evidence JSON."""
    result: dict[str, set[str]] = {}
    for net in evidence.get("nets", []):
        if not isinstance(net, dict):
            continue
        net_id = str(net.get("id", ""))
        if not net_id:
            continue
        nodes: set[str] = set()
        for node in net.get("nodes", []):
            if isinstance(node, dict):
                component_ref = str(node.get("component_ref", ""))
                pin_name = str(node.get("pin_name", ""))
                if component_ref and pin_name:
                    nodes.add(_node_key(component_ref, pin_name))
        result[net_id] = nodes
    return result


def compare_ir_to_kicad_netlist_evidence(design: Design, evidence: dict[str, Any]) -> KiCadNetlistParityReport:
    """Compare ZapTrace IR connectivity against exported KiCad netlist evidence."""
    ir = ir_net_map(design)
    kicad = kicad_evidence_net_map(evidence)
    missing_nets = sorted(set(ir) - set(kicad))
    extra_nets = sorted(set(kicad) - set(ir))
    mismatches: list[NetPinMismatch] = []
    for net_id in sorted(set(ir).intersection(kicad)):
        missing_nodes = sorted(ir[net_id] - kicad[net_id])
        extra_nodes = sorted(kicad[net_id] - ir[net_id])
        if missing_nodes or extra_nodes:
            mismatches.append(NetPinMismatch(net_id=net_id, missing_nodes=missing_nodes, extra_nodes=extra_nodes))
    passed = not missing_nets and not extra_nets and not mismatches
    return KiCadNetlistParityReport(
        passed=passed,
        missing_nets=missing_nets,
        extra_nets=extra_nets,
        pin_mismatches=mismatches,
        ir_net_count=len(ir),
        kicad_net_count=len(kicad),
        message="IR and KiCad netlist evidence match" if passed else "IR and KiCad netlist evidence differ",
    )


def compare_ir_to_kicad_netlist_evidence_file(
    design: Design,
    evidence_path: str | Path,
) -> KiCadNetlistParityReport:
    """Load a KiCad netlist evidence file and compare it to the IR."""
    data = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    return compare_ir_to_kicad_netlist_evidence(design, data)


def write_kicad_netlist_parity_report(
    design: Design,
    evidence_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Write the parity report JSON and return its path."""
    report = compare_ir_to_kicad_netlist_evidence_file(design, evidence_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return out
