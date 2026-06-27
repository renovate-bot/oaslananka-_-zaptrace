"""Requirements → constraints extraction.

Turns a natural-language / keyword design intent into a structured, machine-
readable :class:`Requirements` object — voltage rails, current budget, buses,
MCU family, and USB-C / battery flags — so every later synthesis decision can
be traced back to an explicit requirement instead of a guess.

This is deliberately deterministic pattern extraction, not an LLM: the same
intent always yields the same requirements, which is what verification-first
synthesis needs. It captures what was clearly stated; it does not invent
defaults (a missing field stays empty/None for the caller to resolve).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Canonical interface -> the tokens that imply it.
_INTERFACES: dict[str, tuple[str, ...]] = {
    "i2c": ("i2c", "i²c", "iic"),
    "spi": ("spi",),
    "uart": ("uart",),
    "usb": ("usb", "usb-c", "type-c", "typec"),
    "can": ("can", "canbus", "can-bus"),
    "rs485": ("rs485", "rs-485", "modbus"),
    "ethernet": ("ethernet", "rj45", "rmii"),
    "ble": ("ble", "bluetooth"),
    "wifi": ("wifi", "wi-fi", "wlan"),
    "lora": ("lora", "lorawan"),
}

# Canonical MCU family -> tokens.
_MCU_FAMILIES: dict[str, tuple[str, ...]] = {
    "esp32": ("esp32", "esp32-s3", "esp32-c3", "esp32-c6"),
    "stm32": ("stm32",),
    "rp2040": ("rp2040", "pico"),
    "nrf52": ("nrf52", "nrf5"),
    "atmega": ("atmega",),
    "samd": ("samd21", "samd51", "samd"),
    "ch32": ("ch32",),
}

_USB_C_TOKENS = ("usb-c", "usb c", "type-c", "typec", "usbc")
_BATTERY_TOKENS = ("battery", "li-ion", "lithium", "lipo", "li-po", "lifepo4", "18650", "coin cell")

# Risk-classification token sets (matched against the raw intent, whole-token).
_WIRELESS_INTERFACES = frozenset({"ble", "wifi", "lora"})
_WIRELESS_TOKENS = (
    "rf",
    "antenna",
    "2.4ghz",
    "sub-ghz",
    "subghz",
    "zigbee",
    "nfc",
    "rfid",
    "gps",
    "gnss",
    "cellular",
    "lte",
    "nb-iot",
    "433mhz",
    "915mhz",
)
_MAINS_TOKENS = (
    "mains",
    "ac line",
    "ac-line",
    "line voltage",
    "110vac",
    "120vac",
    "220vac",
    "230vac",
    "240vac",
    "high voltage",
    "high-voltage",
    "offline smps",
)
_SAFETY_CRITICAL_TOKENS = (
    "medical",
    "automotive",
    "aerospace",
    "avionics",
    "iso 26262",
    "iso26262",
    "iec 62304",
    "do-178",
    "safety-critical",
    "safety critical",
    "life support",
    "implant",
    "defibrillator",
    "infusion pump",
    "functional safety",
)
# Below this rail voltage a design is SELV (Safety Extra-Low Voltage); at or
# above it the board carries a hazardous-voltage / high-voltage risk.
_HV_RAIL_THRESHOLD_V = 60.0

# Canonical regulatory target -> tokens. Only unambiguous forms are listed
# (no bare "ce"/"ul"/"reach", which collide with ordinary English) so the
# extractor keeps the module's "invents nothing" precision.
_REGULATORY: dict[str, tuple[str, ...]] = {
    "CE": ("ce mark", "ce-mark", "ce marking", "ce marked", "ce-marked"),
    "FCC": ("fcc",),
    "UL": ("ul listed", "ul-listed", "ul94", "ul 94"),
    "RoHS": ("rohs",),
    "REACH": ("reach svhc", "reach compliance"),
    "CISPR": ("cispr",),
    "ATEX": ("atex",),
    "EN55032": ("en 55032", "en55032"),
    "IEC61000": ("iec 61000", "iec61000"),
}


def _has_token(text: str, token: str) -> bool:
    """Whole-token match (non-alphanumeric boundaries, so 'can' != 'scanner')."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def _extract_rails(text: str) -> list[float]:
    rails: set[float] = set()
    # "3.3V", "5V", "12V" (a digit/decimal before V, not followed by a digit so
    # the European "3V3" form is left to the next pattern, not read as "3V").
    for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*v(?![a-z0-9])", text):
        rails.add(float(match.group(1)))
    # "3V3", "1V8" European notation
    for match in re.finditer(r"(?<![\w])(\d+)v(\d+)(?![\w])", text):
        rails.add(float(f"{match.group(1)}.{match.group(2)}"))
    return sorted(rails)


def _extract_max_current_a(text: str) -> float | None:
    currents: list[float] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(ma|a)\b", text):
        amount = float(match.group(1))
        currents.append(amount / 1000.0 if match.group(2) == "ma" else amount)
    return max(currents) if currents else None


def _extract_temp_range_c(text: str) -> list[float] | None:
    """Operating temperature range, e.g. "-40 to 85C" / "0-70°C" -> [min, max].

    Anchored on a trailing Celsius marker so a voltage range ("48v to 230v")
    cannot be misread as a temperature.
    """
    pattern = r"(-?\d+)\s*°?\s*c?\s*(?:to|–|—|\.\.|-)\s*\+?(-?\d+)\s*°?\s*c\b"
    match = re.search(pattern, text)
    if not match:
        return None
    lo, hi = float(match.group(1)), float(match.group(2))
    return [min(lo, hi), max(lo, hi)]


def _extract_ingress_rating(text: str) -> str | None:
    """IP ingress-protection code, e.g. "IP67" -> "IP67"."""
    match = re.search(r"\bip\s?(\d{2})\b", text)
    return f"IP{match.group(1)}" if match else None


def _extract_cost_target_usd(text: str) -> float | None:
    """Tightest stated BOM/unit cost target in USD ("under $5", "10 usd" -> min)."""
    amounts: list[float] = []
    for match in re.finditer(r"\$\s*(\d+(?:\.\d+)?)", text):
        amounts.append(float(match.group(1)))
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*usd\b", text):
        amounts.append(float(match.group(1)))
    return min(amounts) if amounts else None


def _extract_dimensions_mm(text: str) -> list[float] | None:
    """Board dimensions in mm, e.g. "50x30mm" / "50 mm x 30 mm" -> [50.0, 30.0]."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm\b", text)
    if not match:
        return None
    return [float(match.group(1)), float(match.group(2))]


def _extract_regulatory(text: str) -> list[str]:
    """Stated regulatory / compliance targets (CE, FCC, UL, RoHS, ...)."""
    return sorted(name for name, tokens in _REGULATORY.items() if any(_has_token(text, t) for t in tokens))


@dataclass
class Requirements:
    """Structured, machine-readable requirements extracted from a design intent."""

    raw_intent: str
    rails_v: list[float] = field(default_factory=list)
    max_current_a: float | None = None
    interfaces: list[str] = field(default_factory=list)
    mcu: str | None = None
    usb_c: bool = False
    battery: bool = False
    # Environmental / mechanical / cost / regulatory targets.
    temp_range_c: list[float] | None = None
    ingress_rating: str | None = None
    dimensions_mm: list[float] | None = None
    cost_target_usd: float | None = None
    regulatory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_requirements(intent: str) -> Requirements:
    """Extract structured :class:`Requirements` from a design *intent* string."""
    text = intent.lower()
    interfaces = sorted(name for name, tokens in _INTERFACES.items() if any(_has_token(text, t) for t in tokens))
    mcu = next(
        (family for family, tokens in _MCU_FAMILIES.items() if any(_has_token(text, t) for t in tokens)),
        None,
    )
    return Requirements(
        raw_intent=intent,
        rails_v=_extract_rails(text),
        max_current_a=_extract_max_current_a(text),
        interfaces=interfaces,
        mcu=mcu,
        usb_c=any(t in text for t in _USB_C_TOKENS),
        battery=any(t in text for t in _BATTERY_TOKENS),
        temp_range_c=_extract_temp_range_c(text),
        ingress_rating=_extract_ingress_rating(text),
        dimensions_mm=_extract_dimensions_mm(text),
        cost_target_usd=_extract_cost_target_usd(text),
        regulatory=_extract_regulatory(text),
    )


def _rail_id(rail_v: float) -> str:
    """Stable voltage-domain id, e.g. 3.3 -> VDD_3V3, 5.0 -> VDD_5."""
    return "VDD_" + f"{rail_v:g}".replace(".", "V")


def requirements_to_constraints(requirements: Requirements) -> Any:
    """Derive a constraint-DSL :class:`ConstraintSet` from parsed requirements.

    Each emitted constraint is traceable to the requirement that produced it
    (recorded in the constraint's ``reason``), satisfying the requirement →
    constraint half of the engine that this module's name promises. Only what
    the requirements actually state is emitted — nothing is invented.
    """
    from zaptrace.core.models import (
        ConstraintSet,
        PlacementIntent,
        RoutingIntent,
        VoltageDomainConstraint,
    )

    constraints = ConstraintSet()

    for rail in requirements.rails_v:
        constraints.voltage_domains.append(VoltageDomainConstraint(id=_rail_id(rail), nominal=f"{rail:g}V"))

    if requirements.usb_c or "usb" in requirements.interfaces:
        constraints.routing.append(
            RoutingIntent(
                net="USB_D*",
                differential_pair=True,
                impedance_ohm=90.0,
                length_match_mm=0.15,
                reason="USB high-speed differential pair (from usb_c/usb interface requirement)",
            )
        )
        constraints.placement.append(
            PlacementIntent(
                component="J*",
                edge="bottom",
                reason="USB connector on a board edge (from usb_c requirement)",
            )
        )

    if "i2c" in requirements.interfaces:
        constraints.routing.append(RoutingIntent(net="*SDA*", reason="I2C bus net (from i2c interface requirement)"))

    return constraints


def requirements_assumptions(requirements: Requirements) -> list[dict[str, str]]:
    """Register information a design needs that the intent did not state.

    Distinct from coverage (which maps *stated* requirements to constraints):
    this lists the *unstated* facts a downstream step would otherwise have to
    assume, so every assumption is explicit and reviewable instead of silently
    baked in. (#103 — unspecified-assumption register.)
    """
    assumptions: list[dict[str, str]] = []

    if not requirements.rails_v:
        assumptions.append(
            {
                "field": "rails_v",
                "assumption": "no supply voltage stated; downstream must choose a rail (commonly 3.3V)",
            }
        )
    if requirements.max_current_a is None:
        assumptions.append(
            {
                "field": "max_current_a",
                "assumption": "no current budget stated; regulator/thermal sizing cannot be verified",
            }
        )
    if requirements.mcu is None:
        assumptions.append({"field": "mcu", "assumption": "no controller/MCU stated"})
    if requirements.usb_c:
        assumptions.append(
            {"field": "usb_c", "assumption": "USB-C power role (UFP sink vs DFP source) not stated; assuming sink"}
        )
    if requirements.battery:
        assumptions.append(
            {"field": "battery", "assumption": "battery chemistry/voltage and charge current not stated"}
        )
    return assumptions


def _contract_fields(requirements: Requirements) -> dict[str, Any]:
    """The design-contract fields used for freezing/diffing.

    Excludes ``raw_intent`` deliberately: the freeze gate tracks the *extracted*
    contract (rails, current, interfaces, ...), so reworded-but-equivalent prose
    does not break the freeze, and a genuine requirement change always does.
    """
    data = requirements.to_dict()
    data.pop("raw_intent", None)
    return data


def freeze_requirements(requirements: Requirements) -> dict[str, Any]:
    """Freeze parsed requirements into a content-addressed snapshot.

    Returns ``{"hash": "<sha256>", "frozen": {<contract fields>}}``. The hash is
    a stable digest over the contract fields (not the raw prose), so downstream
    synthesis can record which requirements version it was built against and
    detect drift — the freeze gate of the requirements engine. (#103.)
    """
    import hashlib
    import json

    payload = _contract_fields(requirements)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"hash": hashlib.sha256(blob).hexdigest(), "frozen": payload}


def diff_requirements(old: Requirements, new: Requirements) -> dict[str, Any]:
    """Diff two requirement versions field-by-field for review and freeze gating.

    Returns ``{"changed": [{"field", "from", "to"}], "unchanged": bool,
    "from_hash", "to_hash"}``. A non-empty ``changed`` list means the frozen
    contract moved and any downstream artifacts built on the old freeze must be
    re-verified — the versioning/diff half of the freeze gate. (#103.)
    """
    old_fields = _contract_fields(old)
    new_fields = _contract_fields(new)
    changed = [
        {"field": key, "from": old_fields[key], "to": new_fields[key]}
        for key in old_fields
        if old_fields[key] != new_fields[key]
    ]
    return {
        "changed": changed,
        "unchanged": not changed,
        "from_hash": freeze_requirements(old)["hash"],
        "to_hash": freeze_requirements(new)["hash"],
    }


def review_assumptions(requirements: Requirements, approvals: dict[str, str] | None = None) -> dict[str, Any]:
    """Approval gate over the unspecified-assumption register.

    Every registered assumption must be explicitly resolved before the
    requirements are review-complete. ``approvals`` maps an assumption ``field``
    to the decision the reviewer recorded for it (e.g. ``{"rails_v": "3.3V"}``);
    a missing field stays *pending*. Approvals are bound to ``freeze_hash`` so a
    later requirement change (which moves the hash, see :func:`freeze_requirements`)
    invalidates them and the gate re-opens.

    Returns ``{"freeze_hash", "approved": bool, "reviewed": [...], "pending": [...]}``;
    ``approved`` is True only when no assumption is still pending. (#103 —
    assumption approval workflow.)
    """
    approvals = approvals or {}
    freeze_hash = freeze_requirements(requirements)["hash"]
    reviewed: list[dict[str, str]] = []
    pending: list[dict[str, str]] = []
    for item in requirements_assumptions(requirements):
        decision = approvals.get(item["field"])
        if decision:
            reviewed.append({**item, "decision": decision, "status": "approved"})
        else:
            pending.append({**item, "status": "pending"})
    return {
        "freeze_hash": freeze_hash,
        "approved": not pending,
        "reviewed": reviewed,
        "pending": pending,
    }


def classify_risk(requirements: Requirements) -> dict[str, Any]:
    """Classify a design's product use-case / risk profile from its requirements.

    Deterministic, evidence-bearing classification into the risk classes that
    drive downstream rule-pack and standards selection: ``battery``,
    ``wireless``, ``high_voltage``, and ``safety_critical``. Each hit records the
    evidence that triggered it (a flag, a wireless interface, a hazardous rail, or
    an intent token) so the classification is auditable, never a black box. A
    class is emitted only when there is concrete evidence — nothing is inferred.

    Returns ``{"risk_classes": [<names>], "classifications": [{"class",
    "rationale", "evidence"}]}``. (#103 — product use-case & risk classifier.)
    """
    text = requirements.raw_intent.lower()
    classifications: list[dict[str, str]] = []

    if requirements.battery:
        classifications.append(
            {
                "class": "battery",
                "rationale": "battery-powered: needs charge/protection, fuel-gauging, and low-power review",
                "evidence": "battery requirement",
            }
        )

    wireless_ifaces = sorted(_WIRELESS_INTERFACES.intersection(requirements.interfaces))
    wireless_tokens = [t for t in _WIRELESS_TOKENS if _has_token(text, t)]
    if wireless_ifaces or wireless_tokens:
        classifications.append(
            {
                "class": "wireless",
                "rationale": "radio present: antenna matching, keep-outs, and RF/EMC certification apply",
                "evidence": ", ".join(wireless_ifaces + wireless_tokens),
            }
        )

    hv_rails = [r for r in requirements.rails_v if r >= _HV_RAIL_THRESHOLD_V]
    hv_tokens = [t for t in _MAINS_TOKENS if _has_token(text, t)]
    if hv_rails or hv_tokens:
        evidence = [f"{r:g}V rail" for r in hv_rails] + hv_tokens
        classifications.append(
            {
                "class": "high_voltage",
                "rationale": (
                    f"hazardous voltage (>= {_HV_RAIL_THRESHOLD_V:g}V): creepage/clearance and isolation apply"
                ),
                "evidence": ", ".join(evidence),
            }
        )

    safety_tokens = [t for t in _SAFETY_CRITICAL_TOKENS if _has_token(text, t)]
    if safety_tokens:
        classifications.append(
            {
                "class": "safety_critical",
                "rationale": "safety-critical domain: redundancy, traceability, and domain standards apply",
                "evidence": ", ".join(safety_tokens),
            }
        )

    return {
        "risk_classes": [c["class"] for c in classifications],
        "classifications": classifications,
    }


# USB-C without Power Delivery negotiation supplies at most 3 A at 5 V (the
# default/BC1.2 ceiling); above this a design must negotiate USB-PD or use
# another supply.
_USB_C_NON_PD_MAX_A = 3.0


def requirements_conflicts(requirements: Requirements) -> list[dict[str, Any]]:
    """Detect contradictions between stated requirements.

    Distinct from the assumption register (*unstated* facts) and the coverage
    matrix (*unmapped* facts): this flags stated requirements that are mutually
    inconsistent and cannot all hold as written, so the contradiction is caught
    before any drawing happens. Each conflict cites the two sides and explains
    the physical/spec reason. Deterministic and conservative — only genuine,
    explainable contradictions are emitted. (#103 — requirement conflict detector.)
    """
    conflicts: list[dict[str, Any]] = []

    hv_rails = [r for r in requirements.rails_v if r >= _HV_RAIL_THRESHOLD_V]
    if requirements.battery and hv_rails:
        conflicts.append(
            {
                "conflict": "battery_vs_high_voltage",
                "between": ["battery", f"rail {hv_rails[0]:g}V"],
                "detail": (
                    "battery-powered design also specifies a hazardous-voltage rail "
                    f"(>= {_HV_RAIL_THRESHOLD_V:g}V); confirm an isolated boost/charger "
                    "stage rather than a contradictory power source"
                ),
            }
        )

    current_a = requirements.max_current_a
    if requirements.usb_c and current_a is not None and current_a > _USB_C_NON_PD_MAX_A:
        conflicts.append(
            {
                "conflict": "usb_c_current_over_budget",
                "between": ["usb_c", f"max_current_a {current_a:g}A"],
                "detail": (
                    f"current budget {current_a:g}A exceeds the USB-C default (non-PD) "
                    f"{_USB_C_NON_PD_MAX_A:g}A limit; requires USB-PD negotiation or an "
                    "alternate supply"
                ),
            }
        )

    if requirements.battery and requirements.temp_range_c and requirements.temp_range_c[0] < 0:
        conflicts.append(
            {
                "conflict": "battery_vs_subzero_temperature",
                "between": ["battery", f"temp_range_c min {requirements.temp_range_c[0]:g}C"],
                "detail": (
                    "Li-ion/Li-Po charging is unsafe below 0 C; the stated low operating "
                    "temperature conflicts with battery charging without a heater or charge "
                    "inhibit"
                ),
            }
        )

    return conflicts


def requirements_coverage(requirements: Requirements) -> dict[str, Any]:
    """Trace which requirements produced constraints and which are not yet covered.

    Returns ``{"covered": [...], "uncovered": [...], "fully_covered": bool}``.
    The ``uncovered`` list is the honest record of stated requirements that the
    constraint derivation does not yet handle (e.g. battery charge/protection,
    current budget) — a coverage matrix, not a silent pass. (#103.)
    """
    constraints = requirements_to_constraints(requirements)
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, str]] = []

    if requirements.rails_v:
        covered.append(
            {
                "aspect": "rails_v",
                "detail": f"{len(requirements.rails_v)} voltage rail(s)",
                "constraints": [d.id for d in constraints.voltage_domains],
            }
        )
    if requirements.usb_c or "usb" in requirements.interfaces:
        covered.append(
            {
                "aspect": "usb",
                "detail": "USB differential-pair routing + edge-placed connector",
                "constraints": [r.net for r in constraints.routing if "usb" in r.reason.lower()]
                + [p.component for p in constraints.placement],
            }
        )
    if "i2c" in requirements.interfaces:
        covered.append(
            {
                "aspect": "interface:i2c",
                "detail": "I2C bus routing intent",
                "constraints": [r.net for r in constraints.routing if "i2c" in r.reason.lower()],
            }
        )

    # Stated requirements with no constraint mapping yet — the coverage gaps.
    if requirements.battery:
        uncovered.append({"aspect": "battery", "reason": "charge/protection constraints not yet derived"})
    if requirements.max_current_a is not None:
        uncovered.append({"aspect": "max_current_a", "reason": "current-budget constraint not yet derived"})
    for iface in requirements.interfaces:
        if iface not in {"usb", "i2c"}:
            uncovered.append({"aspect": f"interface:{iface}", "reason": "no constraint mapping yet"})

    return {"covered": covered, "uncovered": uncovered, "fully_covered": not uncovered}


def write_requirements_artifacts(intent: str, output_dir: str | Path) -> dict[str, str]:
    """Emit machine-readable ``requirements.json`` and ``constraints.yaml``.

    Turns a design intent into the two reviewable, version-controllable design-
    contract artifacts the requirements engine promises, and returns the written
    paths. JSON/YAML are deterministic (stable key order) so they diff cleanly in
    review and CI.
    """
    import json

    import yaml

    requirements = parse_requirements(intent)
    constraints = requirements_to_constraints(requirements)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    req_path = out / "requirements.json"
    con_path = out / "constraints.yaml"

    req_path.write_text(json.dumps(requirements.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    con_path.write_text(
        yaml.safe_dump(constraints.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {"requirements": str(req_path), "constraints": str(con_path)}
