"""Rail-level current budget evidence."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from zaptrace.core.models import Design, Net, PinType

_CURRENT_A_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*A", re.IGNORECASE)
_CURRENT_MA_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*m[Aa]", re.IGNORECASE)


class RailBudgetStatus(StrEnum):
    PASS = "pass"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    FAIL = "fail"


class RailLoadEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    component_ref: str
    component_type: str
    current_a: float | None = None
    source: str = "missing"


class RailCurrentBudgetEntry(BaseModel):
    model_config = ConfigDict(strict=False)

    rail_id: str
    rail_name: str
    source_refs: list[str]
    source_current_a: float | None = None
    loads: list[RailLoadEntry]
    missing_current_refs: list[str]
    total_load_current_a: float
    margin_a: float | None = None
    margin_pct: float | None = None
    status: RailBudgetStatus
    message: str


class RailCurrentBudgetReport(BaseModel):
    schema_version: str = "1.0"
    rail_count: int
    failure_count: int
    missing_metadata_count: int
    blocked: bool
    human_review_required: bool
    rails: list[RailCurrentBudgetEntry]


def _parse_current(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _CURRENT_A_PATTERN.search(raw)
    if match:
        return float(match.group(1))
    match = _CURRENT_MA_PATTERN.search(raw)
    if match:
        return float(match.group(1)) / 1000.0
    try:
        value = float(raw)
    except ValueError:
        return None
    return value / 1000.0 if value > 10 else value


def _property_current(properties: dict[str, Any]) -> tuple[float | None, str]:
    for key in ("operating_current_a", "current_a", "load_current_a", "max_current_a"):
        value = properties.get(key)
        if value is None:
            continue
        try:
            return float(value), f"properties.{key}"
        except (TypeError, ValueError):
            return None, f"invalid-properties.{key}"
    return None, "missing"


def _is_rail(net: Net) -> bool:
    name = net.name.upper()
    return net.type.value == "power" or name.startswith(("VDD", "VCC", "VBUS", "VBAT", "VIN", "+"))


def _regulator_output_rails(design: Design) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for comp in design.components.values():
        kind = comp.type.lower()
        if not any(token in kind for token in ("regulator", "ldo", "buck", "boost", "linear")):
            continue
        for pin in comp.pins.values():
            if pin.type == PinType.OUTPUT and pin.net:
                out.setdefault(pin.net, []).append(comp.ref)
    return out


def _component_load_current(component_ref: str, design: Design) -> RailLoadEntry:
    component = design.get_component(component_ref)
    if component is None:
        return RailLoadEntry(component_ref=component_ref, component_type="unknown")
    current, source = _property_current(component.properties)
    if current is None:
        current = _parse_current(component.value)
        source = "value" if current is not None else source
    return RailLoadEntry(
        component_ref=component.ref,
        component_type=component.type,
        current_a=current,
        source=source,
    )


def _source_current_a(refs: list[str], design: Design) -> float | None:
    ratings: list[float] = []
    for ref in refs:
        component = design.get_component(ref)
        if component is None:
            continue
        if component.current_rating is not None and component.current_rating > 0:
            ratings.append(component.current_rating)
            continue
        current, _source = _property_current(component.properties)
        if current is not None and current > 0:
            ratings.append(current)
    return max(ratings) if ratings else None


def build_rail_current_budget_report(design: Design) -> RailCurrentBudgetReport:
    sources_by_rail = _regulator_output_rails(design)
    entries: list[RailCurrentBudgetEntry] = []
    for rail_id, net in sorted(design.nets.items()):
        if not _is_rail(net):
            continue
        source_refs = sources_by_rail.get(rail_id, [])
        source_current = _source_current_a(source_refs, design)
        loads: list[RailLoadEntry] = []
        for node in net.nodes:
            ref = node.component_ref
            if ref in source_refs:
                continue
            load = _component_load_current(ref, design)
            if load.component_ref not in {item.component_ref for item in loads}:
                loads.append(load)
        missing = [load.component_ref for load in loads if load.current_a is None]
        total = round(sum(load.current_a or 0.0 for load in loads), 6)
        margin = round(source_current - total, 6) if source_current is not None else None
        margin_pct = round((margin / source_current) * 100, 3) if source_current and margin is not None else None
        status = RailBudgetStatus.PASS
        message = "rail current budget passes"
        if source_current is None or missing:
            status = RailBudgetStatus.HUMAN_REVIEW_REQUIRED
            message = "rail current budget has missing source/load current metadata"
        if source_current is not None and total > source_current:
            status = RailBudgetStatus.FAIL
            message = "rail load current exceeds source current rating"
        entries.append(
            RailCurrentBudgetEntry(
                rail_id=rail_id,
                rail_name=net.name,
                source_refs=source_refs,
                source_current_a=source_current,
                loads=loads,
                missing_current_refs=missing,
                total_load_current_a=total,
                margin_a=margin,
                margin_pct=margin_pct,
                status=status,
                message=message,
            )
        )
    failures = sum(1 for item in entries if item.status == RailBudgetStatus.FAIL)
    missing_count = sum(len(item.missing_current_refs) for item in entries)
    review = any(item.status == RailBudgetStatus.HUMAN_REVIEW_REQUIRED for item in entries)
    return RailCurrentBudgetReport(
        rail_count=len(entries),
        failure_count=failures,
        missing_metadata_count=missing_count,
        blocked=failures > 0,
        human_review_required=review,
        rails=entries,
    )
