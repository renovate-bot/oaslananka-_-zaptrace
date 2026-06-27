"""Datasheet intelligence pipeline. (#106)

Structured extraction schema and heuristic pipeline that turns raw datasheet
text (copy-pasted from a PDF or fetched from a URL) into a machine-readable
:class:`DatasheetExtract`. This is keyword/regex-based extraction — not an LLM
call — so the same intent always yields the same result (verification-first).

Downstream uses:
- Component library enrichment (fill in missing footprint/spec fields).
- ERC rule grounding (ERC024/ERC026 use keyword heuristics today; a parsed
  extract would let them cross-check against datasheet pin-function tables).
- Synthesis parameter validation (verify an LDO dropout voltage against
  the datasheet value).

The ``extract_datasheet()`` function is the public entry point. Every field it
fills in carries a ``confidence`` value in [0.0, 1.0].
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Extraction schema
# ---------------------------------------------------------------------------


@dataclass
class ExtractedField:
    """A single extracted field with a confidence score."""

    value: str | float | None
    confidence: float  # 0.0 (no evidence) → 1.0 (exact regex match)
    source_snippet: str = ""  # short excerpt that triggered the extraction

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasheetExtract:
    """Structured data extracted from a component datasheet.

    All fields are ``ExtractedField`` objects with a confidence score.
    Missing data fields have ``value=None, confidence=0.0``.
    """

    part_number: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    manufacturer: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    description: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    package: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    supply_voltage_min_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    supply_voltage_max_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    output_current_max_a: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    operating_temp_min_c: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    operating_temp_max_c: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    dropout_voltage_v: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    quiescent_current_ua: ExtractedField = field(default_factory=lambda: ExtractedField(None, 0.0))
    # Pin-function table: pin name → function string
    pin_functions: dict[str, str] = field(default_factory=dict)
    # Raw import losses: fields we could not extract
    import_losses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fill_rate(self) -> float:
        """Fraction of scalar fields that have a non-None value."""
        fields = [
            self.part_number,
            self.manufacturer,
            self.description,
            self.package,
            self.supply_voltage_min_v,
            self.supply_voltage_max_v,
            self.output_current_max_a,
            self.operating_temp_min_c,
            self.operating_temp_max_c,
            self.dropout_voltage_v,
            self.quiescent_current_ua,
        ]
        return sum(1 for f in fields if f.value is not None) / len(fields)


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

_PART_RE = re.compile(
    r"\b([A-Z]{1,4}\d{3,10}[A-Z0-9\-]*)\b",
    re.IGNORECASE,
)
_VOLTAGE_RANGE_RE = re.compile(
    r"(?:supply|input|vcc|vin|vdd)[^\n]{0,30}voltage[^\n]{0,30}?(\d+\.?\d*)\s*v\s+to\s+(\d+\.?\d*)\s*v",
    re.IGNORECASE,
)
_VOLTAGE_MAX_RE = re.compile(
    r"(?:supply|input|vcc|vin|vdd)\s+voltage[^.]*?(?:max(?:imum)?)?[^.]*?(\d+\.?\d*)\s*v\b",
    re.IGNORECASE,
)
_CURRENT_RE = re.compile(
    r"(?:output|max(?:imum)?\s+)?current[^.]*?(\d+\.?\d*)\s*(ma|a)\b",
    re.IGNORECASE,
)
_TEMP_RANGE_RE = re.compile(
    r"(?:operating|ambient)\s+temp(?:erature)?[^.]*?(-?\d+)\s*°?c.*?to\s*\+?(-?\d+)\s*°?c",
    re.IGNORECASE | re.DOTALL,
)
_DROPOUT_RE = re.compile(
    r"dropout\s+voltage[^.]*?(\d+\.?\d*)\s*(mv|v)\b",
    re.IGNORECASE,
)
_QUIESCENT_RE = re.compile(
    r"quiescent[^.]*?(\d+\.?\d*)\s*(ua|ma|µa|μa)\b",
    re.IGNORECASE,
)
_PACKAGE_RE = re.compile(
    r"\b(SOT-?\d{2,3}|SOIC-?\d+|TSSOP-?\d+|QFN-?\d+|BGA-?\d+|DFN-?\d+|"
    r"TO-?92|TO-?220|TO-?252|SOP-?\d+|WSON-?\d+|VQFN-?\d+|LFCSP-?\d+|"
    r"SC-?\d{2,3}|SOD-?\d{2,3}|DPAK|D2PAK)\b",
    re.IGNORECASE,
)
_MANUFACTURER_RE = re.compile(
    r"^(?:manufactured|produced|by|©|from)?\s*(Texas Instruments|Microchip|STMicroelectronics|NXP|"
    r"Analog Devices|Maxim|ON Semiconductor|Diodes Inc|Vishay|Bourns|Murata|TDK|Würth|ROHM|"
    r"Infineon|Renesas|Nordic Semiconductor|Espressif|Silicon Labs|Semtech)\b",
    re.IGNORECASE | re.MULTILINE,
)
_PIN_TABLE_RE = re.compile(
    r"(?:pin|pad)\s+(\d+|[A-Z]\d*)\s+([A-Z][A-Z0-9_/\-]{1,20})\s+([^\n]{5,60})",
    re.IGNORECASE,
)


def _first(text: str, pattern: re.Pattern[str]) -> tuple[str, str] | None:
    m = pattern.search(text)
    if m:
        return m.group(0), m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
    return None


def extract_datasheet(raw_text: str) -> DatasheetExtract:
    """Heuristically extract structured data from raw datasheet text.

    The ``confidence`` of each field reflects the quality of the match:
    - 0.9 — explicit label + value pair matched cleanly
    - 0.7 — approximate/partial match
    - 0.5 — inferred from context
    - 0.0 — not found

    Args:
        raw_text: Raw text content of the datasheet (UTF-8 string).

    Returns:
        A :class:`DatasheetExtract` with all extractable fields filled in.
    """
    extract = DatasheetExtract()
    losses: list[str] = []

    # Part number (look for the most prominent part number in first 500 chars)
    header = raw_text[:500]
    part_matches = _PART_RE.findall(header)
    if part_matches:
        pn = max(part_matches, key=len)
        extract.part_number = ExtractedField(pn, 0.8, pn)
    else:
        losses.append("part_number: no alphanumeric part number found in header")

    # Manufacturer
    mfr_m = _MANUFACTURER_RE.search(raw_text)
    if mfr_m:
        extract.manufacturer = ExtractedField(mfr_m.group(1), 0.9, mfr_m.group(0))
    else:
        losses.append("manufacturer: not recognized")

    # Package
    pkg_m = _PACKAGE_RE.search(raw_text)
    if pkg_m:
        extract.package = ExtractedField(pkg_m.group(0).upper(), 0.85, pkg_m.group(0))
    else:
        losses.append("package: not detected")

    # Supply voltage range
    vr_m = _VOLTAGE_RANGE_RE.search(raw_text)
    if vr_m:
        try:
            extract.supply_voltage_min_v = ExtractedField(float(vr_m.group(1)), 0.9, vr_m.group(0)[:50])
            extract.supply_voltage_max_v = ExtractedField(float(vr_m.group(2)), 0.9, vr_m.group(0)[:50])
        except ValueError:
            losses.append("supply_voltage: range parse failed")
    else:
        losses.append("supply_voltage_min_v/max_v: no range pattern found")

    # Output current
    cur_m = _CURRENT_RE.search(raw_text)
    if cur_m:
        try:
            val = float(cur_m.group(1))
            unit = cur_m.group(2).lower()
            if unit == "ma":
                val /= 1000.0
            extract.output_current_max_a = ExtractedField(val, 0.8, cur_m.group(0))
        except (ValueError, IndexError):
            losses.append("output_current: parse failed")
    else:
        losses.append("output_current_max_a: not found")

    # Operating temperature
    temp_m = _TEMP_RANGE_RE.search(raw_text)
    if temp_m:
        try:
            extract.operating_temp_min_c = ExtractedField(float(temp_m.group(1)), 0.85, temp_m.group(0)[:50])
            extract.operating_temp_max_c = ExtractedField(float(temp_m.group(2)), 0.85, temp_m.group(0)[:50])
        except (ValueError, IndexError):
            losses.append("operating_temp: range parse failed")
    else:
        losses.append("operating_temp_min_c/max_c: not found")

    # Dropout voltage (for LDOs)
    do_m = _DROPOUT_RE.search(raw_text)
    if do_m:
        try:
            val = float(do_m.group(1))
            if do_m.group(2).lower() == "mv":
                val /= 1000.0
            extract.dropout_voltage_v = ExtractedField(val, 0.9, do_m.group(0))
        except (ValueError, IndexError):
            losses.append("dropout_voltage: parse failed")
    else:
        losses.append("dropout_voltage_v: not detected (may not be applicable)")

    # Quiescent current
    qi_m = _QUIESCENT_RE.search(raw_text)
    if qi_m:
        try:
            val = float(qi_m.group(1))
            unit = qi_m.group(2).lower()
            if unit in ("ma",):
                val *= 1000.0
            extract.quiescent_current_ua = ExtractedField(val, 0.85, qi_m.group(0))
        except (ValueError, IndexError):
            losses.append("quiescent_current: parse failed")
    else:
        losses.append("quiescent_current_ua: not found")

    # Pin function table
    for pm in _PIN_TABLE_RE.finditer(raw_text):
        pin_id = pm.group(2).upper()
        func = pm.group(3).strip()[:80]
        extract.pin_functions[pin_id] = func

    if not extract.pin_functions:
        losses.append("pin_functions: no pin table detected")

    extract.import_losses = losses
    return extract
