from __future__ import annotations

import re
from collections import Counter

from zaptrace.core.models import Component, Design, NetType
from zaptrace.erc.graph import ElectricalGraph
from zaptrace.erc.models import ERCSeverity, ERCViolation

INVALID_NET_NAME_RE = re.compile(r"[^a-zA-Z0-9_+\-\.]")

# Component-type keywords used to tell active ICs (which need decoupling and
# carry power pins) apart from passives and connectors. IC detection is
# structural — a power pin plus "not an obvious passive/connector" — rather than
# a hardcoded part-number whitelist, so it generalises to any IC in the library.
_PASSIVE_TYPE_KEYWORDS = (
    "res",
    "cap",
    "ind",
    "ferrite",
    "bead",
    "led",
    "diode",
    "zener",
    "tvs",
    "crystal",
    "xtal",
    "resonator",
    "oscillator",
    "fuse",
    "jumper",
    "testpoint",
    "antenna",
    "switch",
    "button",
    "relay",
)
_CONNECTOR_TYPE_KEYWORDS = ("conn", "header", "usb", "jack", "socket", "terminal", "receptacle")
_CAP_TYPES = {"CAP", "CAPACITOR", "C"}
_DECOUPLE_CAP_VALUES = {"100nf", "0.1uf", "10nf", "1uf", "4.7uf", "10uf", "22uf"}


def _has_power_pin(comp: Component) -> bool:
    return any(pin.type.value == "power" for pin in comp.pins.values())


def _is_ic(comp: Component) -> bool:
    """Heuristically decide whether a component is an active IC.

    An IC is a component that carries at least one power pin and whose type is
    not an obvious passive or connector. This replaces the previous hardcoded
    part-number whitelist so the rule covers any IC in the library.
    """
    if not _has_power_pin(comp):
        return False
    type_lower = comp.type.lower()
    return not any(kw in type_lower for kw in _PASSIVE_TYPE_KEYWORDS + _CONNECTOR_TYPE_KEYWORDS)


def _component_net_ids(design: Design, component_ref: str) -> set[str]:
    """Net ids that *component_ref* is wired to via net nodes (canonical connectivity)."""
    return {net.id for net in design.nets.values() if any(node.component_ref == component_ref for node in net.nodes)}


def _net_owns_decoupling(design: Design, power_net_id: str, ground_net_ids: set[str]) -> bool:
    """Return True if a capacitor bridges *power_net_id* to a ground net."""
    for comp in design.get_components_on_net(power_net_id):
        if comp.type.upper() not in _CAP_TYPES:
            continue
        other_nets = _component_net_ids(design, comp.ref)
        other_nets.discard(power_net_id)
        if other_nets & ground_net_ids:
            return True
    return False


def rule_ERC001(design: Design) -> list[ERCViolation]:
    """Detect power pins with no net assignment."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin.type.value == "power" and pin.net is None:
                net = design.get_net_for_pin(comp.ref, pin_name)
                if net is None:
                    violations.append(
                        ERCViolation(
                            rule_id="ERC001",
                            severity=ERCSeverity.ERROR,
                            message=f"{comp.ref}.{pin_name} (power pin) is not connected to any net",
                            component_refs=[comp.ref],
                            patch_suggestion=f"Connect {comp.ref}.{pin_name} to an appropriate power net",
                        )
                    )
    return violations


def rule_ERC002(design: Design) -> list[ERCViolation]:
    """Detect floating input pins with no net."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin.type.value == "input" and pin.net is None:
                net = design.get_net_for_pin(comp.ref, pin_name)
                if net is None:
                    violations.append(
                        ERCViolation(
                            rule_id="ERC002",
                            severity=ERCSeverity.WARNING,
                            message=f"{comp.ref}.{pin_name} (input pin) is not connected to any net",
                            component_refs=[comp.ref],
                            patch_suggestion=f"Connect {comp.ref}.{pin_name} or add a pull-up/pull-down resistor",
                        )
                    )
    return violations


def rule_ERC003(design: Design) -> list[ERCViolation]:
    """Check ICs on power nets have a decoupling capacitor.

    For each IC power pin wired to a POWER net, require a capacitor bridging that
    net to ground (net-ownership check) rather than just *any* 100nF capacitor
    somewhere in the design. When an IC's power pins are not yet wired into the
    netlist, fall back to a lenient design-wide check for at least one
    decoupling-value capacitor so under-specified designs still get the hint.
    """
    violations: list[ERCViolation] = []
    ground_net_ids = {nid for nid, n in design.nets.items() if n.type == NetType.GROUND}
    lenient_has_cap = any(
        (c.value or "").lower() in _DECOUPLE_CAP_VALUES and c.type.upper() in _CAP_TYPES
        for c in design.components.values()
    )

    for comp in design.components.values():
        if not _is_ic(comp):
            continue

        connected_power_nets: set[str] = set()
        has_unconnected_power_pin = False
        for pin_name, pin in comp.pins.items():
            if pin.type.value != "power":
                continue
            net = design.get_net_for_pin(comp.ref, pin_name)
            if net is not None and net.type == NetType.POWER:
                connected_power_nets.add(net.id)
            elif net is None:
                has_unconnected_power_pin = True

        if connected_power_nets:
            missing = sorted(
                nid for nid in connected_power_nets if not _net_owns_decoupling(design, nid, ground_net_ids)
            )
            if missing:
                net_names = [design.nets[nid].name for nid in missing]
                violations.append(
                    ERCViolation(
                        rule_id="ERC003",
                        severity=ERCSeverity.WARNING,
                        message=f"{comp.ref} ({comp.type}) power net(s) {net_names} have no decoupling capacitor to ground",  # noqa: E501
                        component_refs=[comp.ref],
                        net_refs=missing,
                        patch_suggestion="Add a 100nF ceramic capacitor between each power pin and GND",
                    )
                )
        elif has_unconnected_power_pin and not lenient_has_cap:
            violations.append(
                ERCViolation(
                    rule_id="ERC003",
                    severity=ERCSeverity.WARNING,
                    message=f"{comp.ref} ({comp.type}) may be missing a decoupling capacitor",
                    component_refs=[comp.ref],
                    patch_suggestion="Add a 100nF ceramic capacitor near each power pin",
                )
            )
    return violations


def rule_ERC004(design: Design) -> list[ERCViolation]:
    """Detect duplicate net names."""
    violations: list[ERCViolation] = []
    name_counts = Counter(n.name for n in design.nets.values())
    for name, count in name_counts.items():
        if count > 1:
            nets = [n.id for n in design.nets.values() if n.name == name]
            violations.append(
                ERCViolation(
                    rule_id="ERC004",
                    severity=ERCSeverity.ERROR,
                    message=f"Net name '{name}' is used {count} times (IDs: {nets})",
                    net_refs=nets,
                    patch_suggestion="Rename duplicate nets with unique names",
                )
            )
    return violations


def rule_ERC005(design: Design) -> list[ERCViolation]:
    """Check I2C nets for pull-up resistors connected to a power rail."""
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    pullup_values = {"4.7k", "10k", "2.2k", "1k"}
    for net in design.nets.values():
        if net.name in ("I2C_SDA", "I2C_SCL") or "i2c" in net.name.lower():
            has_pullup = graph.has_resistor_to_power(net.id, pullup_values)
            if not has_pullup:
                violations.append(
                    ERCViolation(
                        rule_id="ERC005",
                        severity=ERCSeverity.WARNING,
                        message=f"I2C net '{net.name}' has no pull-up resistor tied to a power rail",
                        net_refs=[net.id],
                        patch_suggestion="Add 4.7k-10k pull-up resistors from SDA/SCL to the I2C voltage rail",
                    )
                )
    return violations


def rule_ERC006(design: Design) -> list[ERCViolation]:
    """Detect SPI MOSI-MOSI connection (should be MOSI-MISO)."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if "mosi" in net.name.lower():
            pins_on_net = [(n.component_ref, n.pin_name) for n in net.nodes]
            mosi_count = sum(1 for _, p in pins_on_net if "mosi" in p.lower())
            miso_count = sum(1 for _, p in pins_on_net if "miso" in p.lower())
            if mosi_count > 1 and miso_count == 0:
                violations.append(
                    ERCViolation(
                        rule_id="ERC006",
                        severity=ERCSeverity.ERROR,
                        message=f"MOSI connected to MOSI (should connect to MISO) on net '{net.name}'",
                        net_refs=[net.id],
                        patch_suggestion="Verify SPI wiring: master MOSI -> slave MOSI, master MISO <- slave MISO",
                    )
                )
    return violations


def rule_ERC007(design: Design) -> list[ERCViolation]:
    """Check power nets have at least one driving source.

    A power net is driven if it has an output pin, a regulator/power-source
    component, or an input connector on it — the same sources ERC027 recognizes,
    so a rail fed directly by a DC connector is not falsely flagged. Power-sink-
    only nets (e.g. an MCU VCC with nothing feeding it) are reported.
    """
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        if not _power_net_has_source(design, net.id):
            violations.append(
                ERCViolation(
                    rule_id="ERC007",
                    severity=ERCSeverity.WARNING,
                    message=f"Power net '{net.name}' has no driving source (output pin)",
                    net_refs=[net.id],
                    patch_suggestion=f"Connect a regulator or power source to {net.name}",
                )
            )
    return violations


_RES_TYPES = {"RES", "R", "RESISTOR"}


def rule_ERC008(design: Design) -> list[ERCViolation]:
    """Detect LEDs on power nets with no series resistor.

    A series resistor is only counted if a resistor is *directly connected* to
    the LED (shares one of the LED's nets) -- the previous global check passed
    whenever any resistor existed anywhere in the design (e.g. an unrelated I2C
    pull-up), masking real missing-current-limit faults. (graph/pin
    connectivity, not global heuristics.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        if comp.type not in ("LED", "LED-0603", "LED-0805", "LED-0402"):
            continue
        anode_pin = comp.pins.get("ANODE")
        if not (anode_pin and anode_pin.net):
            continue
        node_net = design.get_net_for_pin(comp.ref, "ANODE")
        if not (node_net and node_net.type in (NetType.POWER,)):
            continue
        led_net_ids = graph.nets_for_component(comp.ref) | graph.nets_for_component(comp.id)
        has_series_r = any(
            (other := design.get_component(ep.component_ref)) is not None
            and other.ref not in (comp.ref, comp.id)
            and other.type.upper() in _RES_TYPES
            for net_id in led_net_ids
            for ep in graph.endpoints(net_id)
        )
        if not has_series_r:
            violations.append(
                ERCViolation(
                    rule_id="ERC008",
                    severity=ERCSeverity.ERROR,
                    message=f"{comp.ref} LED anode on power net without series resistor",
                    component_refs=[comp.ref],
                    patch_suggestion="Add a current-limiting resistor (220-470 ohms) in series with the LED",
                )
            )
    return violations


def rule_ERC009(design: Design) -> list[ERCViolation]:
    """Detect UART TX-TX connection (should be TX-RX)."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if "uart" in net.name.lower() or "tx" in net.name.lower():
            pins_on_net = [(n.component_ref, n.pin_name) for n in net.nodes]
            tx_count = sum(1 for _, p in pins_on_net if p.upper() in ("TX", "TXD", "TX1", "TX0"))
            rx_count = sum(1 for _, p in pins_on_net if p.upper() in ("RX", "RXD", "RX1", "RX0"))
            if tx_count >= 2 and rx_count == 0:
                violations.append(
                    ERCViolation(
                        rule_id="ERC009",
                        severity=ERCSeverity.ERROR,
                        message=f"TX connected to TX on net '{net.name}' (should connect TX to RX)",
                        net_refs=[net.id],
                        patch_suggestion="Connect UART TX to RX, not TX to TX",
                    )
                )
    return violations


def rule_ERC010(design: Design) -> list[ERCViolation]:
    """Check crystal components have load capacitors."""
    violations: list[ERCViolation] = []
    crystal_keywords = {"xtal", "crystal", "32khz", "32.768khz"}
    for comp in design.components.values():
        if any(kw in comp.type.lower() for kw in crystal_keywords) or "crystal" in comp.type.lower():
            nearby_caps = 0
            for net in design.nets.values():
                for node in net.nodes:
                    if node.component_ref == comp.ref:
                        for other_node in net.nodes:
                            if other_node.component_ref != comp.ref:
                                other = design.get_component(other_node.component_ref)
                                if other and other.type.lower() in ("cap", "capacitor"):
                                    nearby_caps += 1
            if nearby_caps < 2:
                violations.append(
                    ERCViolation(
                        rule_id="ERC010",
                        severity=ERCSeverity.WARNING,
                        message=f"{comp.ref} ({comp.type}) may be missing load capacitors",
                        component_refs=[comp.ref],
                        patch_suggestion="Add 12-22pF load capacitors between crystal pins and ground",
                    )
                )
    return violations


_ESD_TYPES = {"ESD", "TVS", "ESD_PROTECTION"}


def _is_esd(comp: Component) -> bool:
    type_upper = comp.type.upper()
    return type_upper in _ESD_TYPES or "USBLC" in type_upper or "ESD" in type_upper or "TVS" in type_upper


def rule_ERC011(design: Design) -> list[ERCViolation]:
    """Check USB connectors for ESD protection on their own lines (info-level).

    The ESD/TVS device must share a net with the USB connector to count -- the
    previous check passed if any ESD part existed anywhere in the design, even
    one protecting an unrelated net. (graph/pin connectivity, not global
    heuristics.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        # Match USB connectors/devices, but not the ESD parts themselves (e.g. a
        # USBLC6 has "usb" in its type yet *is* the protection).
        if "usb" not in comp.type.lower() or _is_esd(comp):
            continue
        usb_net_ids = graph.nets_for_component(comp.ref) | graph.nets_for_component(comp.id)
        has_esd = any(
            (other := design.get_component(ep.component_ref)) is not None
            and other.ref not in (comp.ref, comp.id)
            and _is_esd(other)
            for net_id in usb_net_ids
            for ep in graph.endpoints(net_id)
        )
        if not has_esd:
            violations.append(
                ERCViolation(
                    rule_id="ERC011",
                    severity=ERCSeverity.INFO,
                    message=f"{comp.ref} ({comp.type}) has no ESD protection on its lines",
                    component_refs=[comp.ref],
                    patch_suggestion="Add ESD protection diodes (e.g., USBLC6-2) on D+/D- lines",
                )
            )
    return violations


def rule_ERC012(design: Design) -> list[ERCViolation]:
    """Detect nets with only one connected pin."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if len(net.nodes) < 2:
            violations.append(
                ERCViolation(
                    rule_id="ERC012",
                    severity=ERCSeverity.WARNING,
                    message=f"Net '{net.name}' has only {len(net.nodes)} connected pin(s)",
                    net_refs=[net.id],
                    patch_suggestion=f"Connect more components to '{net.name}' or remove unused net",
                )
            )
    return violations


def rule_ERC013(design: Design) -> list[ERCViolation]:
    """Hint at polarized component polarity concerns."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        if comp.type in ("CAP-ELEC", "cap-electrolytic-5mm") or "electrolytic" in comp.type.lower():
            violations.append(
                ERCViolation(
                    rule_id="ERC013",
                    severity=ERCSeverity.WARNING,
                    message=f"{comp.ref} is a polarized capacitor — verify correct polarity",
                    component_refs=[comp.ref],
                    patch_suggestion="Ensure positive pin connects to higher potential and negative to GND",
                )
            )
    return violations


def _parse_supply_voltage(raw: str) -> float | None:
    """Parse a declared supply voltage string to volts.

    Handles ``"3.3"``, ``"5"``, ``"5.0"``, ``"3V3"``, ``"5V"`` and ``"3.3V"``;
    returns ``None`` for blank/unparseable values so they never trigger a
    mismatch.
    """
    if not raw:
        return None
    # "3V3" style: a 'v' between digits is the decimal separator.
    s = re.sub(r"(?<=\d)[vV](?=\d)", ".", raw.strip())
    # Strip a trailing unit suffix ("5V" -> "5").
    s = re.sub(r"[vV]\s*$", "", s).strip()
    try:
        return round(float(s), 3)
    except ValueError:
        return None


def rule_ERC014(design: Design) -> list[ERCViolation]:
    """Detect components declaring different supply voltages on the same net.

    Generalised from a hardcoded 3.3 V vs 5 V check to any two distinct declared
    supply voltages (1.8/3.3, 3.3/5, 5/12, …), so cross-domain shorts are caught
    for every rail — not just the one hardcoded pair. (voltage-domain.)
    """
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        voltages: dict[float, set[str]] = {}
        for node in net.nodes:
            comp = design.get_component(node.component_ref)
            if comp is None:
                continue
            volts = _parse_supply_voltage(comp.voltage_supply)
            if volts is not None:
                voltages.setdefault(volts, set()).add(comp.ref)
        if len(voltages) >= 2:
            listed = ", ".join(f"{v:g}V" for v in sorted(voltages))
            violations.append(
                ERCViolation(
                    rule_id="ERC014",
                    severity=ERCSeverity.ERROR,
                    message=f"Net '{net.name}' connects components of different supply voltages ({listed}) — voltage mismatch",  # noqa: E501
                    net_refs=[net.id],
                    component_refs=sorted({ref for refs in voltages.values() for ref in refs}),
                    patch_suggestion="Use a level shifter or separate power nets for each voltage domain",
                )
            )
    return violations


def rule_ERC015(design: Design) -> list[ERCViolation]:
    """Detect multiple GND nets not joined."""
    violations: list[ERCViolation] = []
    gnd_nets = [n for n in design.nets.values() if n.type == NetType.GROUND]
    if len(gnd_nets) > 1:
        names = [n.name for n in gnd_nets]
        violations.append(
            ERCViolation(
                rule_id="ERC015",
                severity=ERCSeverity.ERROR,
                message=f"Multiple ground nets found: {names}. All grounds must be connected.",
                net_refs=[n.id for n in gnd_nets],
                patch_suggestion="Join all ground nets into a single GND net or use a 0-ohm jumper",
            )
        )
    return violations


def rule_ERC016(design: Design) -> list[ERCViolation]:
    """Check reset pins are held high — tied to a power rail or pulled up to one.

    A reset pin is satisfied if its net *is* a power rail (tied high directly)
    or a resistor on that net bridges to a power/ground rail (pull-up). The
    previous check counted any resistor sharing the net regardless of where it
    went, and missed direct-to-rail resets and "R"/"Resistor"-typed parts.
    (graph/pin connectivity, not loose heuristics.)
    """
    violations: list[ERCViolation] = []
    reset_pin_names = {"NRST", "RESET", "RST", "nRESET", "RSTB", "RUN"}
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin_name not in reset_pin_names or not pin.net:
                continue
            net = design.nets.get(pin.net) or next((n for n in design.nets.values() if n.name == pin.net), None)
            if net is None:
                continue
            # Tied directly to a positive rail needs no pull-up resistor.
            if net.type == NetType.POWER:
                continue
            if not graph.has_resistor_to_power(net.id):
                violations.append(
                    ERCViolation(
                        rule_id="ERC016",
                        severity=ERCSeverity.INFO,
                        message=f"{comp.ref}.{pin_name} reset pin is not held high (no pull-up or rail tie)",
                        component_refs=[comp.ref],
                        patch_suggestion=f"Add a 10k pull-up resistor from {pin_name} to VCC",
                    )
                )
    return violations


def rule_ERC017(design: Design) -> list[ERCViolation]:
    """Detect duplicate component references."""
    violations: list[ERCViolation] = []
    ref_counts = Counter(c.ref for c in design.components.values())
    for ref, count in ref_counts.items():
        if count > 1:
            ids = [c.id for c in design.components.values() if c.ref == ref]
            violations.append(
                ERCViolation(
                    rule_id="ERC017",
                    severity=ERCSeverity.ERROR,
                    message=f"Reference '{ref}' is used {count} times (IDs: {ids})",
                    component_refs=ids,
                    patch_suggestion=f"Rename duplicate references to unique values (e.g., {ref}_A, {ref}_B)",
                )
            )
    return violations


def rule_ERC018(design: Design) -> list[ERCViolation]:
    """Check for test points on debug/protocol nets."""
    violations: list[ERCViolation] = []
    protocol_keywords = {"uart", "i2c", "swd", "spi"}
    for net in design.nets.values():
        if any(kw in net.name.lower() for kw in protocol_keywords):
            has_test_point = any(
                (candidate := design.get_component(n.component_ref)) is not None and "tp" in candidate.ref.lower()
                for n in net.nodes
            )
            if not has_test_point:
                violations.append(
                    ERCViolation(
                        rule_id="ERC018",
                        severity=ERCSeverity.INFO,
                        message=f"Net '{net.name}' ({net.type.value}) has no test point",
                        net_refs=[net.id],
                        patch_suggestion=f"Add a test point (TP) on {net.name} for debugging",
                    )
                )
    return violations


def rule_ERC019(design: Design) -> list[ERCViolation]:
    """Check for illegal characters in net names."""
    violations: list[ERCViolation] = []
    for net in design.nets.values():
        if INVALID_NET_NAME_RE.search(net.name):
            violations.append(
                ERCViolation(
                    rule_id="ERC019",
                    severity=ERCSeverity.INFO,
                    message=f"Net name '{net.name}' contains illegal characters",
                    net_refs=[net.id],
                    patch_suggestion="Use only letters, digits, underscores, and hyphens in net names",
                )
            )
    return violations


def rule_ERC020(design: Design) -> list[ERCViolation]:
    """Detect components with no footprint."""
    violations: list[ERCViolation] = []
    for comp in design.components.values():
        if not comp.footprint:
            violations.append(
                ERCViolation(
                    rule_id="ERC020",
                    severity=ERCSeverity.WARNING,
                    message=f"{comp.ref} ({comp.type}) has no footprint assigned",
                    component_refs=[comp.ref],
                    patch_suggestion=f"Assign a footprint to {comp.ref}",
                )
            )
    return violations


_USBC_TYPE_KEYWORDS = ("usb-c", "usbc", "usb_c", "type-c", "typec", "usb_type_c")
_USBC_CC_RD_VALUES = {"5.1k", "5k1", "5.1K", "5K1"}
# Underscore is a word char, so \b does not fire in names like "SPI_CS";
# use explicit non-alphanumeric boundaries instead.
_CS_NET_RE = re.compile(r"(?<![a-z0-9])(?:cs|ss|nss|csb|ssel|ncs)\d*(?![a-z0-9])", re.IGNORECASE)
_CS_PULLUP_VALUES = {"10k", "4.7k", "47k", "22k", "100k", "1k"}


def rule_ERC021(design: Design) -> list[ERCViolation]:
    """Check USB-C connectors have CC pin termination resistors.

    A USB-C sink (UFP) needs an Rd (5.1k) from each CC pin to GND, or it will
    never be detected by the host. Detection is structural: a USB-C component
    type plus CC/CC1/CC2 pins, then a CC-to-rail termination resistor.
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        type_lower = comp.type.lower()
        if not any(kw in type_lower for kw in _USBC_TYPE_KEYWORDS):
            continue
        for pin_name in comp.pins:
            if pin_name.upper() not in ("CC", "CC1", "CC2"):
                continue
            net = design.get_net_for_pin(comp.ref, pin_name)
            if net is None:
                continue
            if not graph.has_resistor_to_power(net.id, _USBC_CC_RD_VALUES):
                violations.append(
                    ERCViolation(
                        rule_id="ERC021",
                        severity=ERCSeverity.WARNING,
                        message=f"{comp.ref}.{pin_name} (USB-C CC) has no termination resistor",
                        component_refs=[comp.ref],
                        net_refs=[net.id],
                        patch_suggestion="Add a 5.1k resistor from each CC pin to GND (sink/UFP), or Rp for a source",
                    )
                )
    return violations


def rule_ERC022(design: Design) -> list[ERCViolation]:
    """Check SPI chip-select nets have an idle pull-up resistor.

    Without a pull-up, a peripheral's CS can float (and the device be spuriously
    selected) while the MCU is in reset or its GPIOs are high-impedance.
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for net in design.nets.values():
        if net.type in (NetType.POWER, NetType.GROUND):
            continue
        if not _CS_NET_RE.search(net.name):
            continue
        if not graph.has_resistor_to_power(net.id, _CS_PULLUP_VALUES):
            violations.append(
                ERCViolation(
                    rule_id="ERC022",
                    severity=ERCSeverity.INFO,
                    message=f"SPI chip-select net '{net.name}' has no idle pull-up resistor",
                    net_refs=[net.id],
                    patch_suggestion="Add a 10k-100k pull-up from the CS net to its logic rail",
                )
            )
    return violations


def rule_ERC023(design: Design) -> list[ERCViolation]:
    """Flag no-connect (NC) pins that are wired to other pins.

    A pin the part marks 'no connect' / 'do not connect' must be left floating;
    wiring it to a net shared with other pins can violate the datasheet and, for
    internally-used NC pins, damage the part. (no-connect intent.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        for pin_name, pin in comp.pins.items():
            if pin.type.value != "no_connect":
                continue
            net = None
            if pin.net:
                net = design.nets.get(pin.net) or next((n for n in design.nets.values() if n.name == pin.net), None)
            if net is None:
                net = design.get_net_for_pin(comp.ref, pin_name)
            if net is None:
                continue
            others = [
                ep
                for ep in graph.endpoints(net.id)
                if not (ep.component_ref in (comp.ref, comp.id) and ep.pin_name == pin_name)
            ]
            if others:
                other_refs = sorted({ep.component_ref for ep in others})
                violations.append(
                    ERCViolation(
                        rule_id="ERC023",
                        severity=ERCSeverity.WARNING,
                        message=f"{comp.ref}.{pin_name} is a no-connect pin but is wired to {', '.join(other_refs)}",
                        component_refs=[comp.ref],
                        net_refs=[net.id],
                        patch_suggestion=f"Leave {comp.ref}.{pin_name} unconnected unless the datasheet says otherwise",
                    )
                )
    return violations


# RS485 transceiver keywords and DE/RE pin patterns.
_RS485_TYPE_KEYWORDS = ("rs485", "rs-485", "sp3485", "max485", "sn75176", "lt1785", "max3485")
_RS485_DE_RE_RE = re.compile(r"^(?:de|re|oe|nre|de_re|driver_enable|receiver_enable)$", re.IGNORECASE)
_RS485_PULL_VALUES = {"1k", "4.7k", "10k", "22k", "47k", "100k"}


def rule_ERC024(design: Design) -> list[ERCViolation]:
    """Check RS485 transceivers have DE/RE direction control in a defined state.

    A floating DE pin enables the driver at power-up and will assert RS485 bus
    dominance even when idle. A floating RE pin (active-low) disables the receiver
    unintentionally. Both must be pulled to a defined level.
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for comp in design.components.values():
        type_lower = comp.type.lower()
        if not any(kw in type_lower for kw in _RS485_TYPE_KEYWORDS):
            continue
        for pin_name in comp.pins:
            if not _RS485_DE_RE_RE.match(pin_name):
                continue
            net = design.get_net_for_pin(comp.ref, pin_name)
            if net is None:
                violations.append(
                    ERCViolation(
                        rule_id="ERC024",
                        severity=ERCSeverity.ERROR,
                        message=f"{comp.ref}.{pin_name} (RS485 direction control) is unconnected and will float",
                        component_refs=[comp.ref],
                        patch_suggestion=f"Pull {comp.ref}.{pin_name} to a defined level via a 10k resistor",
                    )
                )
                continue
            if graph.is_power_net(net.id):
                continue
            if not graph.has_resistor_to_power(net.id, _RS485_PULL_VALUES):
                violations.append(
                    ERCViolation(
                        rule_id="ERC024",
                        severity=ERCSeverity.WARNING,
                        message=(
                            f"{comp.ref}.{pin_name} (RS485 direction control) has no pull resistor; "
                            "direction is undefined at power-up"
                        ),
                        component_refs=[comp.ref],
                        net_refs=[net.id],
                        patch_suggestion=f"Add a 10k pull-up or pull-down to fix the idle bus direction for {pin_name}",
                    )
                )
    return violations


_SPI_PERIPHERAL_KEYWORDS = (
    "adc",
    "dac",
    "flash",
    "eeprom",
    "sram",
    "spi",
    "accel",
    "gyro",
    "baro",
    "temp",
    "sensor",
    "display",
    "lcd",
    "oled",
    "eth",
    "enc28",
    "w5500",
    "mcp",
)


def rule_ERC025(design: Design) -> list[ERCViolation]:
    """Flag SPI chip-select nets shared by more than one peripheral.

    Every SPI slave must have its own dedicated chip-select net; sharing a CS
    between two peripherals selects them simultaneously and corrupts transfers.
    (SPI CS uniqueness.)
    """
    violations: list[ERCViolation] = []
    graph = ElectricalGraph.from_design(design)
    for net in design.nets.values():
        if net.type in (NetType.POWER, NetType.GROUND):
            continue
        if not _CS_NET_RE.search(net.name):
            continue
        endpoints = graph.endpoints(net.id)
        peripheral_refs: list[str] = []
        for ep in endpoints:
            comp = design.get_component(ep.component_ref)
            if comp is None:
                continue
            type_lower = comp.type.lower()
            if any(kw in type_lower for kw in _PASSIVE_TYPE_KEYWORDS):
                continue
            peripheral_refs.append(comp.ref)
        if len(peripheral_refs) > 2:
            violations.append(
                ERCViolation(
                    rule_id="ERC025",
                    severity=ERCSeverity.ERROR,
                    message=(
                        f"SPI chip-select net '{net.name}' connects to {len(peripheral_refs)} non-passive "
                        f"components ({', '.join(peripheral_refs)}); each SPI slave needs its own CS net"
                    ),
                    net_refs=[net.id],
                    component_refs=peripheral_refs,
                    patch_suggestion="Route separate CS nets — one per SPI peripheral — from the MCU",
                )
            )
    return violations


_LIPO_BATT_KEYWORDS = ("battery", "batt", "lipo", "li-ion", "liion", "cell")
_LIPO_PROT_KEYWORDS = ("dw01", "bq2", "ap9101", "s8261", "mcp73", "tc4056", "ip5306", "lp2771", "protection")


def rule_ERC026(design: Design) -> list[ERCViolation]:
    """Check Li-ion/LiPo batteries have an overdischarge/overcurrent protection IC.

    An unprotected LiPo can be discharged below 2.5 V, causing permanent damage
    or thermal runaway. A dedicated protection IC (or a charger IC with built-in
    protection, e.g. BQ24xxx) must be present on the same design.
    (charger/battery protection.)
    """
    violations: list[ERCViolation] = []
    battery_refs: list[str] = []
    for comp in design.components.values():
        type_lower = comp.type.lower()
        if any(kw in type_lower for kw in _LIPO_BATT_KEYWORDS):
            battery_refs.append(comp.ref)
    if not battery_refs:
        return violations
    has_protection = any(
        any(kw in comp.type.lower() for kw in _LIPO_PROT_KEYWORDS) for comp in design.components.values()
    )
    if not has_protection:
        violations.append(
            ERCViolation(
                rule_id="ERC026",
                severity=ERCSeverity.WARNING,
                message=(
                    f"Li-ion/LiPo battery ({', '.join(battery_refs)}) detected but no protection IC found; "
                    "overdischarge or overcurrent can permanently damage the cell"
                ),
                component_refs=battery_refs,
                patch_suggestion=(
                    "Add a protection IC (e.g. DW01A + FS8205A) or a charger with built-in protection "
                    "(e.g. BQ24xxx, MCP73xxx)"
                ),
            )
        )
    return violations


# ---------------------------------------------------------------------------
# ERC027: Power-tree completeness — every power net must have a driving source
# ---------------------------------------------------------------------------

_REGULATOR_TYPE_KEYWORDS = (
    "regulator",
    "ldo",
    "buck",
    "boost",
    "buck-boost",
    "dc-dc",
    "dcdc",
    "tlv",
    "tps",
    "max",
    "lt",
    "adp",
    "mic",
    "mcp",
)

# Magnetics that pass a switching-regulator output to its filter cap / load.
_INDUCTOR_KEYWORDS = ("inductor", "choke", "ferrite")


def _is_power_source_component(comp: Component, pin_name: str) -> bool:
    """True if *comp* can drive a power net through *pin_name*.

    A driver is an explicit output pin, a regulator/power-source component, or an
    input connector — the same notions ERC007 and ERC027 share.
    """
    pin = comp.pins.get(pin_name)
    if pin is not None and pin.type.value == "output":
        return True
    type_lower = comp.type.lower()
    if any(kw in type_lower for kw in _REGULATOR_TYPE_KEYWORDS):
        return True
    return any(kw in type_lower for kw in _CONNECTOR_TYPE_KEYWORDS)


def _power_net_has_source(design: Design, net_id: str) -> bool:
    """Whether a power net is driven by some source.

    Directly: an output pin, regulator, or connector on the net. Indirectly, for
    a switching-regulator output: through an inductor whose other terminal sits
    on the regulator's switch node (a net that is itself regulator-driven). The
    indirect case is why a buck's filtered output rail is not falsely flagged.
    """
    net = design.nets.get(net_id)
    if net is None:
        return False
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp is not None and _is_power_source_component(comp, node.pin_name):
            return True
    # Buck/boost output: follow an inductor to the regulator's switch node.
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp is None or not any(kw in comp.type.lower() for kw in _INDUCTOR_KEYWORDS):
            continue
        for other in design.nets.values():
            if other.id == net_id:
                continue
            if not any(nn.component_ref == node.component_ref for nn in other.nodes):
                continue
            for nn in other.nodes:
                neighbor = design.get_component(nn.component_ref)
                if neighbor is not None and any(kw in neighbor.type.lower() for kw in _REGULATOR_TYPE_KEYWORDS):
                    return True
    return False


def rule_ERC027(design: Design) -> list[ERCViolation]:
    """Check power-tree completeness: every power net needs a source.

    A power net is considered "fed" if:
    - It has at least one output pin (regulator or power-source output), OR
    - It is connected to an input connector/power-source component, OR
    - It is a ground net.

    Power nets with no identified source are flagged; they cannot supply
    current. (power-tree completeness.)
    """
    violations: list[ERCViolation] = []

    for net in design.nets.values():
        if net.type == NetType.GROUND:
            continue
        if net.type != NetType.POWER:
            continue

        if not _power_net_has_source(design, net.id):
            violations.append(
                ERCViolation(
                    rule_id="ERC027",
                    severity=ERCSeverity.WARNING,
                    message=f"Power net '{net.name}' has no identified driving source (no regulator, output pin, or connector on this net)",  # noqa: E501
                    net_refs=[net.id],
                    patch_suggestion=(
                        f"Verify that '{net.name}' is fed by a regulator, power-source output, or external connector"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# ERC028: Regulator headroom and current budget
# ---------------------------------------------------------------------------

# Common regulator output current keywords for value strings (amps).
_CURRENT_A_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*A", re.IGNORECASE)
_CURRENT_MA_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*m[Aa]", re.IGNORECASE)


def _parse_current(raw: str) -> float | None:
    """Parse a current value string to amperes."""
    if not raw:
        return None
    m = _CURRENT_A_PATTERN.search(raw)
    if m:
        return float(m.group(1))
    m = _CURRENT_MA_PATTERN.search(raw)
    if m:
        return float(m.group(1)) / 1000.0
    # Bare number with no unit — assume mA if > 1, else A.
    try:
        v = float(raw)
        return v / 1000.0 if v > 10 else v
    except ValueError:
        return None


def rule_ERC028(design: Design) -> list[ERCViolation]:
    """Check regulator headroom and current budget.

    For components whose type contains regulator keywords, verify:
    1. Headroom: if the component has a ``voltage_supply``, the regulator's
       output cannot exceed its input (for buck/linear) or must be above
       (for boost).
    2. Current budget: if the regulator has a ``current_rating`` and there
       are loads on its output net, flag when the total estimated load
       exceeds the rating.

    (current budget, regulator headroom.)
    """
    violations: list[ERCViolation] = []

    for comp in design.components.values():
        type_lower = comp.type.lower()
        is_buck = "buck" in type_lower
        is_boost = "boost" in type_lower
        is_ldo = "ldo" in type_lower or "linear" in type_lower
        if not (is_buck or is_boost or is_ldo):
            continue

        # Check headroom: regulator's output net vs supply
        output_nets: set[str] = set()
        input_nets: set[str] = set()
        for _pin_name, pin in comp.pins.items():
            if pin.type.value == "output" and pin.net:
                output_nets.add(pin.net)
            if pin.type.value == "power" and pin.net:
                input_nets.add(pin.net)

        if input_nets and output_nets and comp.voltage_supply:
            vin = _parse_supply_voltage(comp.voltage_supply)
            if vin is not None:
                for out_net_id in output_nets:
                    out_net = design.nets.get(out_net_id)
                    if out_net is None:
                        continue
                    if is_buck and vin <= 0.5:
                        violations.append(
                            ERCViolation(
                                rule_id="ERC028",
                                severity=ERCSeverity.WARNING,
                                message=f"{comp.ref} buck regulator input ({vin:g}V) may be too low to regulate",
                                component_refs=[comp.ref],
                                patch_suggestion=(
                                    f"Verify {comp.ref} input voltage is above its minimum operating voltage"
                                ),
                            )
                        )

        # Current budget check
        if comp.current_rating is not None and comp.current_rating > 0:
            max_current_a = comp.current_rating
            load_current_a = 0.0
            for out_net_id in output_nets:
                # Estimate load from value strings of components on this net
                out_net = design.nets.get(out_net_id)
                if out_net is None:
                    continue
                for node in out_net.nodes:
                    load_comp = design.get_component(node.component_ref)
                    if load_comp and load_comp.ref != comp.ref:
                        load_val = _parse_current(load_comp.value or "")
                        if load_val is not None:
                            load_current_a += load_val

            if load_current_a > max_current_a * 1.1:  # 10% margin
                violations.append(
                    ERCViolation(
                        rule_id="ERC028",
                        severity=ERCSeverity.WARNING,
                        message=(
                            f"{comp.ref} regulator rated for {max_current_a:g}A but loads on its output "
                            f"net total ~{load_current_a:g}A — current budget exceeded"
                        ),
                        component_refs=[comp.ref],
                        net_refs=list(output_nets),
                        patch_suggestion=f"Choose a regulator rated for at least {load_current_a:g}A, or reduce load",
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# ERC029: DNP/variant-aware ERC
# ---------------------------------------------------------------------------


def rule_ERC029(design: Design) -> list[ERCViolation]:
    """Check that DNP (Do Not Populate) components and variant-excluded parts
    are not wired into critical nets where their absence would cause issues.

    A DNP component that is the *only* path between a regulator and a load,
    or the only decoupling capacitor on a power net, is flagged for review
    so the designer confirms the intent.

    (DNP/variant ERC.)
    """
    violations: list[ERCViolation] = []
    dnp_refs = {comp.ref for comp in design.components.values() if comp.dnp}

    if not dnp_refs:
        return violations

    # Check power nets: if ALL decoupling caps on a net are DNP, flag it
    {nid for nid, n in design.nets.items() if n.type == NetType.GROUND}
    for net in design.nets.values():
        if net.type != NetType.POWER:
            continue
        caps_on_net = []
        for node in net.nodes:
            comp = design.get_component(node.component_ref)
            if comp is None:
                continue
            if comp.type.upper() in _CAP_TYPES:
                caps_on_net.append(comp)
        if caps_on_net and all(c.dnp for c in caps_on_net):
            violations.append(
                ERCViolation(
                    rule_id="ERC029",
                    severity=ERCSeverity.WARNING,
                    message=f"All decoupling capacitors on power net '{net.name}' are DNP — no decoupling in the populated variant",  # noqa: E501
                    net_refs=[net.id],
                    component_refs=[c.ref for c in caps_on_net],
                    patch_suggestion=(
                        "Review DNP assignments: at least one decoupling cap per power rail must be populated"
                    ),
                )
            )

    # Check pull-up resistors on I2C nets
    for net in design.nets.values():
        if not ("i2c" in net.name.lower() or net.name in ("I2C_SDA", "I2C_SCL")):
            continue
        pullups_on_net = []
        for node in net.nodes:
            comp = design.get_component(node.component_ref)
            if comp is None:
                continue
            if comp.type.upper() in _RES_TYPES:
                pullups_on_net.append(comp)
        if pullups_on_net and all(c.dnp for c in pullups_on_net):
            violations.append(
                ERCViolation(
                    rule_id="ERC029",
                    severity=ERCSeverity.ERROR,
                    message=f"I2C net '{net.name}' has all pull-up resistors DNP — bus will not work",
                    net_refs=[net.id],
                    component_refs=[c.ref for c in pullups_on_net],
                    patch_suggestion="Ensure at least one pull-up resistor per I2C line is populated in all variants",
                )
            )

    return violations
