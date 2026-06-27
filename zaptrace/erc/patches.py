from __future__ import annotations

import contextlib
import re

from zaptrace.core.models import Design
from zaptrace.erc.models import ERCResult
from zaptrace.synthesis.calculators import i2c_pullup, led_series_resistor

# Assumptions used when the design does not pin these down. They are echoed in
# the patch so a reviewer can see (and override) what the value was based on.
_DEFAULT_LED_VF = 2.0
_DEFAULT_LED_CURRENT_MA = 10.0
_DEFAULT_I2C_BUS_PF = 100.0
_DEFAULT_I2C_SPEED_HZ = 100_000
_DEFAULT_I2C_RAIL_V = 3.3


def _infer_rail_voltage(design: Design, net_id: str) -> float | None:
    """Best-effort rail voltage for a net: connected supplies first, then the name."""
    net = design.nets.get(net_id) or next((n for n in design.nets.values() if n.id == net_id), None)
    if net is None:
        return None
    voltages: list[float] = []
    for node in net.nodes:
        comp = design.get_component(node.component_ref)
        if comp and comp.voltage_supply:
            with contextlib.suppress(ValueError):
                voltages.append(float(comp.voltage_supply))
    if voltages:
        return max(voltages)
    name = net.name
    # "3.3V" / "1.8V"
    m = re.search(r"(\d+\.\d+)\s*V", name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # "3V3" / "1V8" (European notation)
    m = re.search(r"\b(\d+)V(\d+)\b", name, re.IGNORECASE)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    # "5V" / "12V"
    m = re.search(r"\b(\d+)\s*V\b", name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _format_ohms(ohms: float) -> str:
    if ohms >= 1e6:
        return f"{ohms / 1e6:g}M"
    if ohms >= 1e3:
        return f"{ohms / 1e3:g}k"
    return f"{ohms:g}"


def _led_supply_voltage(design: Design, led_ref: str) -> float | None:
    """Rail voltage feeding an LED, inferred from its anode net."""
    net = design.get_net_for_pin(led_ref, "ANODE")
    if net is None:
        return None
    return _infer_rail_voltage(design, net.id)


def suggest_patches(design: Design, erc_result: ERCResult) -> list[dict[str, str]]:
    """Generate auto-patch suggestions for fixable ERC violations.

    Where possible the patch carries a *computed* component value (LED series
    resistor, I2C pull-up) rather than generic prose, with the assumptions it
    was based on. When a value cannot be derived it falls back to the rule's
    textual ``patch_suggestion``.

    Returns a list of patches that can be applied programmatically.
    """
    patches: list[dict[str, str]] = []
    for v in erc_result.violations:
        if v.rule_id == "ERC012" and len(v.net_refs) == 1:
            patches.append({"op": "remove_net", "net_id": v.net_refs[0], "reason": v.message})

        elif v.rule_id == "ERC001" and v.patch_suggestion:
            patches.append(
                {
                    "op": "add_note",
                    "ref": v.component_refs[0] if v.component_refs else "",
                    "note": v.patch_suggestion,
                }
            )

        elif v.rule_id == "ERC008" and v.component_refs:
            led_ref = v.component_refs[0]
            supply = _led_supply_voltage(design, led_ref)
            if supply is not None and supply > _DEFAULT_LED_VF:
                res = led_series_resistor(supply, _DEFAULT_LED_VF, _DEFAULT_LED_CURRENT_MA)
                patches.append(
                    {
                        "op": "add_series_resistor",
                        "ref": led_ref,
                        "value": _format_ohms(res.chosen_ohms),
                        "reason": v.message,
                        "assumptions": (
                            f"Vsupply={supply:g}V, Vf={_DEFAULT_LED_VF:g}V, I={_DEFAULT_LED_CURRENT_MA:g}mA"
                        ),
                    }
                )
            elif v.patch_suggestion:
                patches.append({"op": "add_note", "ref": led_ref, "note": v.patch_suggestion})

        elif v.rule_id == "ERC005" and v.net_refs:
            net_id = v.net_refs[0]
            supply = _infer_rail_voltage(design, net_id) or _DEFAULT_I2C_RAIL_V
            try:
                pull = i2c_pullup(supply, _DEFAULT_I2C_BUS_PF, bus_speed_hz=_DEFAULT_I2C_SPEED_HZ)
            except ValueError:
                if v.patch_suggestion:
                    patches.append({"op": "add_note", "net_id": net_id, "note": v.patch_suggestion})
                continue
            patches.append(
                {
                    "op": "add_pullup",
                    "net_id": net_id,
                    "value": _format_ohms(pull.recommended_ohms),
                    "reason": v.message,
                    "assumptions": (
                        f"Vdd={supply:g}V, Cbus={_DEFAULT_I2C_BUS_PF:g}pF, speed={_DEFAULT_I2C_SPEED_HZ}Hz"
                    ),
                }
            )

    return patches
