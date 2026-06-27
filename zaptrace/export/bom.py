from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from zaptrace.core.models import Design
from zaptrace.supply.client import SupplyClient


def generate_bom_csv(design: Design) -> str:
    """Generate Bill of Materials as CSV string."""
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Ref",
            "Type",
            "Value",
            "Footprint",
            "MPN",
            "Manufacturer",
            "Lifecycle",
            "Datasheet",
            "LCSC#",
            "Basic/Extended",
            "Populate/DNP",
            "Flags",
        ],
    )
    writer.writeheader()
    client = SupplyClient()
    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        lcsc_id = comp.lcsc_id
        basic_part = comp.basic_part
        stock = comp.stock

        if comp.mpn and not lcsc_id:
            result = client.resolve_mpn(comp.mpn)
            if result:
                lcsc_id = result.lcsc_id
                basic_part = result.basic_part
                stock = result.stock

        dnp_val = "DNP" if comp.dnp else "Populate"
        basic_val = "Basic" if basic_part is True else ("Extended" if basic_part is False else "")

        flags = []
        if not comp.dnp and not lcsc_id:
            flags.append("Missing LCSC#")
        if not comp.dnp and stock == 0:
            flags.append("Out of Stock")

        writer.writerow(
            {
                "Ref": comp.ref,
                "Type": comp.type,
                "Value": comp.value or "",
                "Footprint": comp.footprint,
                "MPN": comp.mpn or "",
                "Manufacturer": comp.manufacturer or "",
                "Lifecycle": comp.lifecycle.value,
                "Datasheet": comp.datasheet_url or "",
                "LCSC#": lcsc_id or "",
                "Basic/Extended": basic_val,
                "Populate/DNP": dnp_val,
                "Flags": ", ".join(flags),
            }
        )
    return output.getvalue()


def generate_bom_json(design: Design) -> str:
    """Generate BOM as JSON string."""
    items: list[dict[str, str | None]] = []
    client = SupplyClient()
    for comp in sorted(design.components.values(), key=lambda c: c.ref):
        lcsc_id = comp.lcsc_id
        basic_part = comp.basic_part
        stock = comp.stock

        if comp.mpn and not lcsc_id:
            result = client.resolve_mpn(comp.mpn)
            if result:
                lcsc_id = result.lcsc_id
                basic_part = result.basic_part
                stock = result.stock

        dnp_val = "DNP" if comp.dnp else "Populate"
        basic_val = "Basic" if basic_part is True else ("Extended" if basic_part is False else "")

        flags = []
        if not comp.dnp and not lcsc_id:
            flags.append("Missing LCSC#")
        if not comp.dnp and stock == 0:
            flags.append("Out of Stock")

        items.append(
            {
                "ref": comp.ref,
                "type": comp.type,
                "value": comp.value,
                "footprint": comp.footprint,
                "mpn": comp.mpn,
                "manufacturer": comp.manufacturer,
                "lifecycle": comp.lifecycle.value,
                "datasheet_url": comp.datasheet_url,
                "lcsc_id": lcsc_id,
                "basic_extended": basic_val,
                "populate_dnp": dnp_val,
                "flags": ", ".join(flags),
            }
        )
    return json.dumps(
        {"design": design.meta.name, "items": items, "count": len(items)},
        indent=2,
        ensure_ascii=False,
    )


def generate_hbom_cyclonedx(design: Design, *, timestamp: str | None = None) -> str:
    """Generate a CycloneDX 1.6 hardware BOM (HBOM) as a JSON string.

    Populated components are grouped by part identity (type, value, MPN,
    footprint) into one CycloneDX component each, carrying the reference
    designators, quantity, lifecycle and sourcing metadata as properties.

    The output is deterministic — no ``metadata.timestamp`` is emitted unless
    one is supplied — so it can be hashed for the proof pack and diffed in CI.
    """
    groups: dict[tuple[str, str, str, str], list[Any]] = {}
    for comp in design.components.values():
        if comp.dnp:
            continue
        key = (comp.type, comp.value or "", comp.mpn or "", comp.footprint or "")
        groups.setdefault(key, []).append(comp)

    components: list[dict[str, Any]] = []
    for (ctype, value, mpn, footprint), comps in sorted(groups.items()):
        refs = sorted(c.ref for c in comps)
        head = comps[0]
        properties: list[dict[str, str]] = [
            {"name": "zaptrace:reference-designators", "value": ",".join(refs)},
            {"name": "zaptrace:quantity", "value": str(len(comps))},
            {"name": "zaptrace:type", "value": ctype},
            {"name": "zaptrace:lifecycle", "value": head.lifecycle.value},
        ]
        if footprint:
            properties.append({"name": "zaptrace:footprint", "value": footprint})
        if mpn:
            properties.append({"name": "zaptrace:mpn", "value": mpn})
        if head.lcsc_id:
            properties.append({"name": "zaptrace:lcsc-id", "value": head.lcsc_id})

        component: dict[str, Any] = {"type": "device", "name": value or ctype, "properties": properties}
        if head.manufacturer:
            component["manufacturer"] = {"name": head.manufacturer}
        components.append(component)

    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": {"type": "device", "name": design.meta.name}},
        "components": components,
    }
    if timestamp:
        bom["metadata"]["timestamp"] = timestamp
    return json.dumps(bom, indent=2, ensure_ascii=False)
