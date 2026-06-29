"""Board-level architecture synthesis by block composition.

This is the generalization of :mod:`zaptrace.synthesis.power_tree` from "what
power stages" to "what functional blocks the whole board needs, and how they
connect" — the first step away from template selection toward from-scratch
synthesis (see ``docs/design/autonomous-synthesis.md``).

The model is a typed **block graph**: every planned block declares what it
``provides`` (rails, interface support) and what it ``requires`` (a rail to run
from). The planner composes by satisfying requires-with-provides, so a bare
intent never invents a block it was not asked for, and an unsatisfiable
requirement is reported rather than silently emitted.

Deterministic: the same frozen :class:`~zaptrace.synthesis.requirements.Requirements`
always yields the same plan and the same netlist, so a result is reproducible
and a diff is meaningful. Honest: interfaces with no parametric block yet are
recorded as ``unrealized`` instead of being skipped silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.synthesis.mcu import has_mcu_part
from zaptrace.synthesis.peripherals import plan_sensors, plan_storage
from zaptrace.synthesis.power_tree import _rail_net, plan_power_tree

if TYPE_CHECKING:
    from zaptrace.core.models import Design
    from zaptrace.synthesis.explain import SynthesisDecisionLog
    from zaptrace.synthesis.requirements import Requirements

# Default logic rail when an intent states no rails but needs interface support.
_DEFAULT_LOGIC_RAIL_V = 3.3


@dataclass(frozen=True)
class BlockContract:
    """What a planned block offers to and needs from the rest of the board.

    Tokens are namespaced strings so composition is a simple set match:
    ``"rail:3V3"`` (a power rail), ``"net:GND"`` (a global net every block may
    assume), ``"iface:i2c"`` (interface support present).
    """

    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedBlock:
    """One node in the board's block graph: a unit of circuitry with provenance.

    ``realized`` is False for a block the planner knows is needed but has no
    parametric implementation for yet (e.g. an RS-485 transceiver) — it is kept
    in the plan, with a reason, so the gap is visible rather than dropped.
    """

    block_id: str
    kind: str
    rationale: str
    contract: BlockContract
    realized: bool
    calculator: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kind": self.kind,
            "rationale": self.rationale,
            "provides": list(self.contract.provides),
            "requires": list(self.contract.requires),
            "realized": self.realized,
            "calculator": self.calculator,
        }


@dataclass(frozen=True)
class UnmetRequirement:
    """A block ``requires`` token that no other block ``provides``."""

    block_id: str
    token: str


@dataclass
class ArchitecturePlan:
    """The composed block graph plus what could not be satisfied or realized."""

    blocks: list[PlannedBlock] = field(default_factory=list)
    rails_v: list[float] = field(default_factory=list)
    unmet: list[UnmetRequirement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def realized_blocks(self) -> list[PlannedBlock]:
        return [b for b in self.blocks if b.realized]

    @property
    def unrealized_blocks(self) -> list[PlannedBlock]:
        return [b for b in self.blocks if not b.realized]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "rails_v": self.rails_v,
            "unmet_requirements": [{"block_id": u.block_id, "token": u.token} for u in self.unmet],
            "notes": self.notes,
        }


# Interface → how the board supports it. ``realized`` blocks have a parametric
# implementation in ``synthesis.blocks``; others are honestly deferred.
#
# ``support`` semantics:
#   "rail-pullups"  needs the logic rail (e.g. I2C SDA/SCL pull-ups)
#   "gnd-only"      needs only GND (e.g. USB-C CC Rd termination)
#   "transceiver"   needs the logic rail + a transceiver IC (e.g. RS-485, CAN)
#   "none"          a digital bus needing no passive support block
#   "deferred"      needs a block (transceiver/PHY) not yet implemented
_INTERFACE_SUPPORT: dict[str, dict[str, Any]] = {
    "i2c": {
        "support": "rail-pullups",
        "realized": True,
        "rationale": "I2C bus needs SDA/SCL pull-ups to the logic rail",
    },
    "usb": {"support": "gnd-only", "realized": True, "rationale": "USB-C port needs CC pin Rd termination to GND"},
    "ethernet": {"support": "gnd-only", "realized": True, "rationale": "Ethernet magnetics need Bob-Smith termination"},
    "spi": {
        "support": "none",
        "realized": True,
        "rationale": "SPI is point-to-point; no passive support block required",
    },
    "uart": {
        "support": "none",
        "realized": True,
        "rationale": "UART is point-to-point; no passive support block required",
    },
    "rs485": {
        "support": "transceiver",
        "realized": True,
        "rationale": "RS-485 needs a transceiver + 120Ω bus termination",
    },
    "can": {
        "support": "transceiver",
        "realized": True,
        "rationale": "CAN needs a transceiver + 120Ω bus termination",
    },
    "ble": {
        "support": "deferred",
        "realized": False,
        "rationale": "BLE needs an RF front-end/antenna block (not yet implemented)",
    },
    "wifi": {
        "support": "deferred",
        "realized": False,
        "rationale": "Wi-Fi needs an RF front-end/antenna block (not yet implemented)",
    },
    "lora": {
        "support": "deferred",
        "realized": False,
        "rationale": "LoRa needs an RF front-end/antenna block (not yet implemented)",
    },
}


def _logic_rail_v(requirements: Requirements) -> float:
    """The rail interface support hangs off — the lowest stated rail, or a default."""
    return min(requirements.rails_v) if requirements.rails_v else _DEFAULT_LOGIC_RAIL_V


def plan_architecture(requirements: Requirements) -> ArchitecturePlan:
    """Compose the board's block graph from requirements, with provenance.

    Power blocks come from :func:`plan_power_tree` (each regulator *provides* its
    rail); interface support blocks *require* the logic rail. After composing,
    every ``requires`` token is checked against the union of ``provides`` tokens
    plus the always-present global nets; unsatisfied ones become :class:`UnmetRequirement`.
    """
    plan = ArchitecturePlan(rails_v=sorted(requirements.rails_v))
    plan.notes.extend(plan_power_tree(requirements).get("notes", []))

    logic_rail_v = _logic_rail_v(requirements)
    logic_rail = _rail_net(logic_rail_v)

    # --- Power blocks: USB-C input termination + one regulator per rail. -----
    power = plan_power_tree(requirements)
    if requirements.usb_c:
        plan.blocks.append(
            PlannedBlock(
                block_id="PB_USB_C_CC",
                kind="power_input",
                rationale="USB-C VBUS input; CC pins need Rd termination",
                contract=BlockContract(provides=("net:VBUS",), requires=("net:GND",)),
                realized=True,
                calculator="usb_c_cc_termination",
            )
        )
    for stage in power["stages"]:
        if stage["stage"] != "regulator":
            continue
        rail_v = stage["to_rail_v"]
        rail_net = _rail_net(rail_v)
        topology = stage["topology"]
        realized = topology in ("buck", "ldo")  # boost has no block yet
        plan.blocks.append(
            PlannedBlock(
                block_id=f"PB_REG_{rail_net}",
                kind="regulator",
                rationale=stage["rationale"],
                contract=BlockContract(provides=(f"rail:{rail_net}",), requires=("net:GND",)),
                realized=realized,
                calculator=stage.get("calculator"),
                params={"rail_v": rail_v, "topology": topology, "from_v": stage["from_v"]},
            )
        )
        if not realized:
            plan.notes.append(f"{topology} stage for {rail_net} planned but has no parametric block yet")

    # --- Interface support blocks: each requires the logic rail. -------------
    for iface in sorted(requirements.interfaces):
        spec = _INTERFACE_SUPPORT.get(iface)
        if spec is None:
            plan.notes.append(f"interface '{iface}' recognized but has no support policy")
            continue
        support = spec["support"]
        if support == "none":
            # Realized-but-empty: no support block needed, recorded for honesty.
            plan.blocks.append(
                PlannedBlock(
                    block_id=f"IF_{iface.upper()}",
                    kind="interface",
                    rationale=spec["rationale"],
                    contract=BlockContract(provides=(f"iface:{iface}",)),
                    realized=True,
                )
            )
            continue
        requires = ("net:GND",) if support == "gnd-only" else (f"rail:{logic_rail}", "net:GND")
        plan.blocks.append(
            PlannedBlock(
                block_id=f"IF_{iface.upper()}",
                kind="interface",
                rationale=spec["rationale"],
                contract=BlockContract(provides=(f"iface:{iface}",), requires=requires),
                realized=bool(spec["realized"]),
                params={"logic_rail_v": logic_rail_v, "support": support},
            )
        )

    # --- Functional core: the MCU, wired to the rail and the interfaces. -----
    # Appended last so it emits after the support nets it connects to exist.
    if requirements.mcu:
        realized = has_mcu_part(requirements.mcu)
        plan.blocks.append(
            PlannedBlock(
                block_id="CORE_MCU",
                kind="mcu",
                rationale=f"{requirements.mcu} is the functional core; drives the board's interfaces",
                contract=BlockContract(provides=("core",), requires=(f"rail:{logic_rail}", "net:GND")),
                realized=realized,
                params={"family": requirements.mcu},
            )
        )
        if not realized:
            plan.notes.append(f"MCU family '{requirements.mcu}' has no library part yet")

    # --- Peripherals: the sensors and storage the intent asks for. -----------
    for periph in [*plan_sensors(requirements), *plan_storage(requirements)]:
        bus_iface = f"iface:{periph.bus}"
        plan.blocks.append(
            PlannedBlock(
                block_id=f"PERIPH_{periph.part_id.upper().replace('-', '_')}",
                kind="peripheral",
                rationale=f"{periph.function} ({periph.part_id}) on the {periph.bus.upper()} bus",
                contract=BlockContract(
                    provides=(f"peripheral:{periph.function}",),
                    requires=(f"rail:{logic_rail}", "net:GND", bus_iface),
                ),
                realized=periph.realized,
                params={"part_id": periph.part_id, "bus": periph.bus},
            )
        )
        if not periph.realized:
            plan.notes.append(f"peripheral '{periph.part_id}' ({periph.function}) has no library part")

    _check_composition(plan)
    return plan


# Global nets every block may assume exist without a provider declaring them.
_GLOBAL_NETS = ("net:GND",)


def _check_composition(plan: ArchitecturePlan) -> None:
    """Flag any ``requires`` token not satisfied by some block's ``provides``."""
    provided = set(_GLOBAL_NETS)
    for block in plan.blocks:
        provided.update(block.contract.provides)
    for block in plan.blocks:
        for token in block.contract.requires:
            if token not in provided:
                plan.unmet.append(UnmetRequirement(block_id=block.block_id, token=token))


def build_architecture_design(
    requirements: Requirements,
    *,
    name: str = "SynthesizedBoard",
) -> tuple[Design, ArchitecturePlan, SynthesisDecisionLog]:
    """Emit a :class:`~zaptrace.core.models.Design` from the composed block graph.

    Returns ``(design, plan, decision_log)``. Only ``realized`` blocks emit
    components; unrealized ones stay in the plan and the decision log as honest
    gaps. Every emitted block records a decision citing its rationale, so the
    netlist is explainable end to end.
    """
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.synthesis.blocks import (
        instantiate_can_transceiver,
        instantiate_i2c_pullups,
        instantiate_ldo,
        instantiate_rj45_bob_smith,
        instantiate_rs485_transceiver,
        instantiate_sync_buck_tlv62569,
        instantiate_usb_c_ufp_cc,
    )
    from zaptrace.synthesis.calculators import buck_inductor_capacitor
    from zaptrace.synthesis.explain import SynthesisDecisionLog
    from zaptrace.synthesis.power_tree import _DEFAULT_BUCK_FSW_HZ, _DEFAULT_LOAD_A

    plan = plan_architecture(requirements)
    log = SynthesisDecisionLog()
    design = Design(meta=DesignMeta(name=name, description=f"Board synthesized from: {requirements.raw_intent}"))

    input_net = "VBUS" if requirements.usb_c else ("VBAT" if requirements.battery else "VIN")
    load_a = requirements.max_current_a if requirements.max_current_a is not None else _DEFAULT_LOAD_A
    logic_rail = _rail_net(_logic_rail_v(requirements))

    for block in plan.blocks:
        if not block.realized:
            log.record(
                "gap",
                block.block_id,
                "unrealized",
                rationale=block.rationale,
                confidence=0.0,
            )
            continue

        if block.kind == "power_input":  # USB-C CC termination
            instantiate_usb_c_ufp_cc(design, block.block_id)
            log.record(
                "topology", block.block_id, "USB-C CC Rd", rationale=block.rationale, calculator="usb_c_cc_termination"
            )

        elif block.kind == "regulator":
            rail_v = block.params["rail_v"]
            rail_net = _rail_net(rail_v)
            if block.params["topology"] == "buck":
                bc = buck_inductor_capacitor(block.params["from_v"], rail_v, load_a, _DEFAULT_BUCK_FSW_HZ)
                instantiate_sync_buck_tlv62569(
                    design,
                    block.block_id,
                    vin_net=input_net,
                    vout_net=rail_net,
                    sw_net=f"SW_{rail_net}",
                    en_net=f"EN_{rail_net}",
                    fb_net=f"FB_{rail_net}",
                    inductor_val=f"{bc.inductor_chosen_uh:g}uH",
                    cout_val=f"{bc.output_cap_chosen_uf:g}uF",
                )
                log.record(
                    "value",
                    block.block_id,
                    f"buck {rail_v:g}V (L={bc.inductor_chosen_uh:g}uH, Cout={bc.output_cap_chosen_uf:g}uF)",
                    rationale=block.rationale,
                    calculator="buck_inductor_capacitor",
                )
            else:  # ldo
                instantiate_ldo(design, block.block_id, vin_net=input_net, vout_net=rail_net, output_v=rail_v)
                log.record("topology", block.block_id, f"LDO {rail_v:g}V", rationale=block.rationale)

        elif block.kind == "interface":
            support = block.params.get("support")
            if support == "rail-pullups":  # I2C
                supply_v = block.params["logic_rail_v"]
                instantiate_i2c_pullups(design, block.block_id, vdd_net=logic_rail, supply_v=supply_v)
                log.record("value", block.block_id, "I2C pull-ups", rationale=block.rationale, calculator="i2c_pullup")
            elif support == "gnd-only" and block.block_id == "IF_ETHERNET":
                instantiate_rj45_bob_smith(design, block.block_id)
                log.record("topology", block.block_id, "RJ45 Bob-Smith", rationale=block.rationale)
            elif support == "gnd-only" and block.block_id == "IF_USB":
                # USB-C CC already emitted as the power_input block; nothing extra.
                log.record("topology", block.block_id, "covered by USB-C input", rationale=block.rationale)
            elif support == "transceiver" and block.block_id == "IF_RS485":
                instantiate_rs485_transceiver(design, block.block_id, rail_net=logic_rail)
                log.record("topology", block.block_id, "RS-485 transceiver (MAX3485)", rationale=block.rationale)
            elif support == "transceiver" and block.block_id == "IF_CAN":
                instantiate_can_transceiver(design, block.block_id, rail_net=logic_rail)
                log.record("topology", block.block_id, "CAN transceiver (SN65HVD230)", rationale=block.rationale)
            else:  # support == "none" (SPI/UART): no components, recorded for scope
                log.record("note", block.block_id, "no support block required", rationale=block.rationale)

        elif block.kind == "mcu":
            from zaptrace.synthesis.mcu import instantiate_mcu

            result = instantiate_mcu(design, block.params["family"], requirements.interfaces, rail_net=logic_rail)
            log.record(
                "topology",
                block.block_id,
                f"{result.part_id} core, {len(result.assignments)} pins wired",
                rationale=block.rationale,
            )
            for iface in result.unconnected_interfaces:
                log.record(
                    "note",
                    block.block_id,
                    f"{iface} not wired (no support net / no spare GPIO)",
                    confidence=0.0,
                )

        elif block.kind == "peripheral":
            from zaptrace.synthesis.peripherals import instantiate_sensor, instantiate_spi_flash

            part_id = block.params["part_id"]
            bus = block.params["bus"]
            if bus == "spi":
                ref = instantiate_spi_flash(design, part_id, rail_net=logic_rail)
            else:
                ref = instantiate_sensor(design, part_id, rail_net=logic_rail)
            if ref is not None:
                log.record("topology", block.block_id, f"{part_id} on {bus.upper()} bus", rationale=block.rationale)
            else:
                log.record("note", block.block_id, f"{part_id} not wired as {bus.upper()}", confidence=0.0)

    return design, plan, log
