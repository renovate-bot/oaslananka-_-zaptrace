"""Datasheet intelligence pipeline.

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

import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Provenance/fact evidence schema v1
# ---------------------------------------------------------------------------


class DatasheetFactScope(StrEnum):
    """Datasheet fact category with explicit safety semantics."""

    ABSOLUTE_MAXIMUM = "absolute_maximum"
    RECOMMENDED_OPERATING = "recommended_operating"
    PIN_FUNCTION = "pin_function"
    PACKAGE = "package"
    ELECTRICAL_CHARACTERISTIC = "electrical_characteristic"
    THERMAL_CHARACTERISTIC = "thermal_characteristic"


class DatasheetSourceRef(BaseModel):
    """Source locator for a datasheet-derived fact."""

    model_config = ConfigDict(strict=False)

    datasheet_url: str = ""
    datasheet_sha256: str = Field(description="SHA-256 of the source datasheet text/PDF bytes")
    page: int | None = Field(default=None, ge=1)
    table: str = ""
    figure: str = ""
    section: str = ""
    source_snippet: str = ""


class DatasheetFact(BaseModel):
    """One datasheet-derived engineering fact with provenance."""

    model_config = ConfigDict(strict=False)

    component_id: str
    field: str
    value: str | float | int | bool
    unit: str = ""
    scope: DatasheetFactScope
    confidence: float = Field(ge=0, le=1)
    source: DatasheetSourceRef


class DatasheetFactReport(BaseModel):
    """Machine-readable datasheet provenance report for one component."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    component_id: str
    datasheet_url: str = ""
    datasheet_sha256: str
    absolute_maximum: list[DatasheetFact] = Field(default_factory=list)
    recommended_operating: list[DatasheetFact] = Field(default_factory=list)
    other_facts: list[DatasheetFact] = Field(default_factory=list)
    import_losses: list[str] = Field(default_factory=list)

    @property
    def facts(self) -> list[DatasheetFact]:
        return [*self.absolute_maximum, *self.recommended_operating, *self.other_facts]

    @property
    def fact_count(self) -> int:
        return len(self.facts)


def datasheet_sha256(raw: str | bytes) -> str:
    """Return a stable SHA-256 for datasheet text or bytes."""
    payload = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(payload).hexdigest()


def _source(
    *,
    datasheet_url: str,
    digest: str,
    snippet: str,
    section: str,
    page: int | None = None,
    table: str = "",
    figure: str = "",
) -> DatasheetSourceRef:
    return DatasheetSourceRef(
        datasheet_url=datasheet_url,
        datasheet_sha256=digest,
        page=page,
        table=table,
        figure=figure,
        section=section,
        source_snippet=snippet[:240],
    )


def _add_fact(
    facts: list[DatasheetFact],
    *,
    component_id: str,
    field: str,
    value: str | float | int | bool | None,
    unit: str,
    scope: DatasheetFactScope,
    confidence: float,
    source: DatasheetSourceRef,
) -> None:
    if value is None:
        return
    facts.append(
        DatasheetFact(
            component_id=component_id,
            field=field,
            value=value,
            unit=unit,
            scope=scope,
            confidence=confidence,
            source=source,
        )
    )


def build_datasheet_fact_report(
    component_id: str,
    raw_text: str,
    *,
    datasheet_url: str = "",
    page: int | None = None,
    extract: DatasheetExtract | None = None,
) -> DatasheetFactReport:
    """Build a provenance report from datasheet text and optional extraction."""
    parsed = extract or extract_datasheet(raw_text)
    digest = datasheet_sha256(raw_text)
    recommended: list[DatasheetFact] = []
    other: list[DatasheetFact] = []

    _add_fact(
        recommended,
        component_id=component_id,
        field="supply_voltage_min_v",
        value=parsed.supply_voltage_min_v.value,
        unit="V",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.supply_voltage_min_v.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Recommended Operating Conditions",
            section="recommended operating conditions",
            snippet=parsed.supply_voltage_min_v.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="supply_voltage_max_v",
        value=parsed.supply_voltage_max_v.value,
        unit="V",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.supply_voltage_max_v.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Recommended Operating Conditions",
            section="recommended operating conditions",
            snippet=parsed.supply_voltage_max_v.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="operating_temp_min_c",
        value=parsed.operating_temp_min_c.value,
        unit="C",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.operating_temp_min_c.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Recommended Operating Conditions",
            section="recommended operating conditions",
            snippet=parsed.operating_temp_min_c.source_snippet,
        ),
    )
    _add_fact(
        recommended,
        component_id=component_id,
        field="operating_temp_max_c",
        value=parsed.operating_temp_max_c.value,
        unit="C",
        scope=DatasheetFactScope.RECOMMENDED_OPERATING,
        confidence=parsed.operating_temp_max_c.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Recommended Operating Conditions",
            section="recommended operating conditions",
            snippet=parsed.operating_temp_max_c.source_snippet,
        ),
    )
    _add_fact(
        other,
        component_id=component_id,
        field="output_current_max_a",
        value=parsed.output_current_max_a.value,
        unit="A",
        scope=DatasheetFactScope.ELECTRICAL_CHARACTERISTIC,
        confidence=parsed.output_current_max_a.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            table="Electrical Characteristics",
            section="electrical characteristics",
            snippet=parsed.output_current_max_a.source_snippet,
        ),
    )
    _add_fact(
        other,
        component_id=component_id,
        field="package",
        value=parsed.package.value,
        unit="",
        scope=DatasheetFactScope.PACKAGE,
        confidence=parsed.package.confidence,
        source=_source(
            datasheet_url=datasheet_url,
            digest=digest,
            page=page,
            section="package information",
            snippet=parsed.package.source_snippet,
        ),
    )
    for pin_name, function in sorted(parsed.pin_functions.items()):
        _add_fact(
            other,
            component_id=component_id,
            field=f"pin_functions.{pin_name}",
            value=function,
            unit="",
            scope=DatasheetFactScope.PIN_FUNCTION,
            confidence=0.75,
            source=_source(
                datasheet_url=datasheet_url,
                digest=digest,
                page=page,
                table="Pin Functions",
                section="pin functions",
                snippet=function,
            ),
        )
    return DatasheetFactReport(
        component_id=component_id,
        datasheet_url=datasheet_url,
        datasheet_sha256=digest,
        recommended_operating=recommended,
        other_facts=other,
        import_losses=parsed.import_losses,
    )


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
