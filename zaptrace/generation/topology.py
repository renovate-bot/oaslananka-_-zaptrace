"""Architecture-derived schematic topology planning."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.core.models import Design, NetType
from zaptrace.generation.architecture import ArchitectureCompileStatus, ElectronicsArchitectureArtifact
from zaptrace.generation.compiler import CompiledDesignIR
from zaptrace.generation.intent import BoardGenerationIntent


class TopologySynthesisStatus(StrEnum):
    """Status emitted by topology-aware schematic planning."""

    SYNTHESIZED = "synthesized"
    BLOCKED = "blocked"


class SchematicTopologyBlock(BaseModel):
    """Architecture-derived functional schematic block."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    component_refs: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


type TopologyNetType = Literal["power", "ground", "signal", "data", "clock", "differential", "analog"]


class SchematicTopologyNet(BaseModel):
    """Topology-level net with requirement trace."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    net_type: TopologyNetType
    nodes: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_required: bool = True


class SchematicTopologyInterface(BaseModel):
    """Architecture interface mapped into schematic nets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    role: str = Field(default="unspecified")
    nets: list[str] = Field(default_factory=list)
    controlled_impedance: bool = False
    requirement_ids: list[str] = Field(default_factory=list)


class SchematicTopologyPlan(BaseModel):
    """Topology-aware schematic plan derived from architecture and Design IR."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: TopologySynthesisStatus
    design_name: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    method: Literal["architecture_topology_planning"] = "architecture_topology_planning"
    source_architecture_status: ArchitectureCompileStatus
    source_compiler_method: str
    blocks: list[SchematicTopologyBlock] = Field(default_factory=list)
    interfaces: list[SchematicTopologyInterface] = Field(default_factory=list)
    nets: list[SchematicTopologyNet] = Field(default_factory=list)
    requirement_trace_count: int = Field(default=0, ge=0)
    blocking_reasons: list[str] = Field(default_factory=list)
    non_claims: list[str] = Field(default_factory=list)

    @property
    def synthesized(self) -> bool:
        """Return whether topology planning succeeded."""
        return self.status == TopologySynthesisStatus.SYNTHESIZED

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return self.model_dump(mode="json")


def schematic_topology_plan_json(plan: SchematicTopologyPlan) -> str:
    """Serialize a schematic topology plan as stable JSON."""
    return json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


_COMPONENT_KIND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mcu": ("esp", "mcu", "microcontroller"),
    "sensor": ("sensor", "bme", "imu", "temperature"),
    "power": ("reg", "ldo", "ams", "buck", "charger"),
    "interface": ("usb", "connector", "j"),
}


def _component_refs_for_kind(design: Design, kind: str) -> list[str]:
    keywords = _COMPONENT_KIND_KEYWORDS.get(kind, ())
    matches: list[str] = []
    for ref, component in design.components.items():
        type_text = f"{component.type} {component.value or ''} {component.ref}".lower()
        if any(token in type_text for token in keywords):
            matches.append(ref)
    return sorted(matches)


def _block_for_subsystem(
    architecture: ElectronicsArchitectureArtifact,
    design: Design,
) -> list[SchematicTopologyBlock]:
    blocks: list[SchematicTopologyBlock] = []
    for subsystem in architecture.subsystems:
        refs = _component_refs_for_kind(design, subsystem.kind)
        blocks.append(
            SchematicTopologyBlock(
                id=subsystem.id,
                name=subsystem.name,
                kind=subsystem.kind,
                component_refs=refs,
                requirement_ids=subsystem.requirement_ids,
            )
        )
    return blocks


def _net_type(net_type: NetType) -> TopologyNetType:
    value = net_type.value
    if value in {"power", "ground", "data", "clock", "differential", "analog"}:
        return value
    return "signal"


def _requirement_ids_for_net(
    net_name: str,
    architecture: ElectronicsArchitectureArtifact,
) -> list[str]:
    ids: set[str] = set()
    for rail in architecture.power_tree:
        if rail.net_name == net_name:
            ids.update(rail.requirement_ids)
    for interface in architecture.interfaces:
        if net_name in interface.nets:
            ids.update(interface.requirement_ids)
    if net_name == "GND":
        ids.update(req.id for req in architecture.requirements if req.category.value == "power")
    return sorted(ids)


def _topology_nets(
    architecture: ElectronicsArchitectureArtifact,
    design: Design,
) -> list[SchematicTopologyNet]:
    nets: list[SchematicTopologyNet] = []
    for net in design.nets.values():
        nodes = [f"{node.component_ref}.{node.pin_name}" for node in net.nodes]
        nets.append(
            SchematicTopologyNet(
                name=net.name,
                net_type=_net_type(net.type),
                nodes=sorted(nodes),
                requirement_ids=_requirement_ids_for_net(net.name, architecture),
            )
        )
    return sorted(nets, key=lambda item: item.name)


def _topology_interfaces(
    architecture: ElectronicsArchitectureArtifact,
) -> list[SchematicTopologyInterface]:
    return [
        SchematicTopologyInterface(
            name=interface.name,
            protocol=interface.protocol,
            role=interface.role,
            nets=interface.nets,
            controlled_impedance=interface.controlled_impedance,
            requirement_ids=interface.requirement_ids,
        )
        for interface in architecture.interfaces
    ]


def synthesize_schematic_topology_plan(
    architecture: ElectronicsArchitectureArtifact,
    intent: BoardGenerationIntent,
    compiled: CompiledDesignIR,
) -> SchematicTopologyPlan:
    """Create a topology-aware schematic plan from architecture and compiled Design IR."""
    if architecture.status != ArchitectureCompileStatus.READY:
        return SchematicTopologyPlan(
            status=TopologySynthesisStatus.BLOCKED,
            design_name=compiled.design.meta.name,
            family_id=intent.family_id,
            source_architecture_status=architecture.status,
            source_compiler_method=compiled.report.method,
            requirement_trace_count=len(compiled.report.requirement_traces),
            blocking_reasons=architecture.blocking_reasons or [f"architecture status is {architecture.status.value}"],
            non_claims=compiled.report.non_claims,
        )

    blocks = _block_for_subsystem(architecture, compiled.design)
    interfaces = _topology_interfaces(architecture)
    nets = _topology_nets(architecture, compiled.design)
    reasons: list[str] = []
    if not blocks:
        reasons.append("architecture does not define schematic topology blocks")
    if not nets:
        reasons.append("compiled Design IR does not define topology nets")

    return SchematicTopologyPlan(
        status=TopologySynthesisStatus.BLOCKED if reasons else TopologySynthesisStatus.SYNTHESIZED,
        design_name=compiled.design.meta.name,
        family_id=intent.family_id,
        source_architecture_status=architecture.status,
        source_compiler_method=compiled.report.method,
        blocks=blocks,
        interfaces=interfaces,
        nets=nets,
        requirement_trace_count=len(compiled.report.requirement_traces),
        blocking_reasons=reasons,
        non_claims=compiled.report.non_claims,
    )
