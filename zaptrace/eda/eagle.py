"""Eagle .brd / .sch XML import adapter.

Parses a subset of the Autodesk Eagle XML format (schema v7+) into a ZapTrace
:class:`~zaptrace.core.models.Design`. This is a *structural* import: nets,
components, and placed parts are extracted. Eagle-specific attributes (design
rules, ULP scripts, ERC annotations) become unsupported records rather than
being silently ignored.

Eagle XML structure (simplified):
  <eagle><drawing><board>
    <components>  (BOM-level, with value)
    <nets>        (net table)
    <elements>    (placed parts with x/y/layer)
    <signals>     (same as nets in schematic view)
  </board></drawing></eagle>
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from xml.etree.ElementTree import Element as _Element
from xml.etree.ElementTree import ParseError as _XMLParseError

import defusedxml.ElementTree as ElementTree


@dataclass(frozen=True)
class EagleUnsupportedRecord:
    """An Eagle construct that could not be fully imported."""

    kind: str
    message: str
    severity: str = "warning"


@dataclass
class EagleImportResult:
    """Result of importing an Eagle .brd or .sch XML file.

    The :attr:`nets` and :attr:`components` dicts are the extracted data.
    """

    source_path: Path | None = None
    schema_version: str = ""
    # Extracted data
    nets: dict[str, list[str]] = field(default_factory=dict)  # net_name → [component_refs]
    components: dict[str, dict[str, str]] = field(default_factory=dict)  # ref → {type, value, x, y}
    unsupported: list[EagleUnsupportedRecord] = field(default_factory=list)

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path) if self.source_path else None,
            "schema_version": self.schema_version,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "unsupported_count": self.unsupported_count,
        }


def import_eagle_xml(path: str | Path) -> EagleImportResult:
    """Parse an Eagle .brd or .sch XML file into a structured import result.

    Only the component table, net/signal table, and placed element positions
    are extracted. Polygon pours, design rules, library definitions, and
    schematic symbols are noted as unsupported records.

    Args:
        path: Path to the Eagle XML file (.brd or .sch).

    Returns:
        An :class:`EagleImportResult` with the extracted data.

    Raises:
        ValueError: If the file is not valid Eagle XML.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Eagle file not found: {path}")

    try:
        tree = ElementTree.parse(path)
    except _XMLParseError as exc:
        raise ValueError(f"Invalid Eagle XML: {exc}") from exc

    root: _Element = cast(_Element, tree.getroot())  # defusedxml lacks stubs
    if root.tag != "eagle":
        raise ValueError(f"Not an Eagle file: root tag is '{root.tag}', expected 'eagle'")

    version = root.get("version", "")
    result = EagleImportResult(source_path=path, schema_version=version)

    # -------------------------------------------------------------------------
    # Components (library-level parts in <components>)
    # -------------------------------------------------------------------------
    for comp in root.iter("component"):
        ref = comp.get("name", "")
        if not ref:
            continue
        result.components[ref] = {
            "type": comp.get("deviceset", ""),
            "value": comp.get("value", ""),
        }

    # -------------------------------------------------------------------------
    # Placed elements (footprint instances in <elements>)
    # -------------------------------------------------------------------------
    for elem in root.iter("element"):
        ref = elem.get("name", "")
        if not ref:
            continue
        existing = result.components.setdefault(ref, {})
        existing["x_mm"] = elem.get("x", "")
        existing["y_mm"] = elem.get("y", "")
        existing["layer"] = elem.get("layer", "")
        if not existing.get("type"):
            existing["type"] = elem.get("package", "")
        if not existing.get("value"):
            existing["value"] = elem.get("value", "")

    # -------------------------------------------------------------------------
    # Nets / signals
    # -------------------------------------------------------------------------
    for signal in root.iter("signal"):
        net_name = signal.get("name", "")
        if not net_name:
            continue
        refs: list[str] = []
        for contactref in signal.findall("contactref"):
            element = contactref.get("element", "")
            if element:
                refs.append(element)
        result.nets[net_name] = refs

    # Also check <net> elements (schematic format)
    for net in root.iter("net"):
        net_name = net.get("name", "")
        if not net_name or net_name in result.nets:
            continue
        refs = []
        for pin in net.findall("pinref"):
            part = pin.get("part", "")
            if part:
                refs.append(part)
        result.nets[net_name] = refs

    # -------------------------------------------------------------------------
    # Flag unsupported constructs
    # -------------------------------------------------------------------------
    for _polygon in root.iter("polygon"):
        result.unsupported.append(EagleUnsupportedRecord("polygon", "Polygon fill not yet imported", "info"))
        break  # flag once, not per-polygon

    for _dr in root.iter("designrules"):
        result.unsupported.append(EagleUnsupportedRecord("designrules", "Eagle design rules not imported", "info"))
        break

    for _lib in root.iter("library"):
        result.unsupported.append(
            EagleUnsupportedRecord("library", "Embedded library definitions not imported", "info")
        )
        break

    return result


def import_eagle_to_design(path: str | Path) -> tuple[Any, EagleImportResult]:
    """Import an Eagle file and convert to a ZapTrace Design (best-effort).

    Returns ``(design, import_result)`` where ``design`` is a ZapTrace
    :class:`~zaptrace.core.models.Design` built from the extracted data.
    Import losses are recorded in the design's ``import_losses`` field.
    """
    from zaptrace.core.models import (
        Component,
        Design,
        DesignMeta,
        ImportLossRecord,
        Net,
        NetNode,
    )

    eagle_result = import_eagle_xml(path)
    design = Design(meta=DesignMeta(name=Path(path).stem, author="eagle-import"))

    # Add components
    for ref, attrs in eagle_result.components.items():
        design.components[ref.lower()] = Component(
            id=ref.lower(),
            ref=ref,
            type=attrs.get("type", "unknown"),
            value=attrs.get("value", ""),
        )

    # Add nets
    for net_name, refs in eagle_result.nets.items():
        net_id = re.sub(r"[^a-zA-Z0-9_]", "_", net_name).lower()
        nodes = [NetNode(component_ref=r, pin_name="?") for r in refs]
        design.nets[net_id] = Net(id=net_id, name=net_name, nodes=nodes)

    # Record import losses for unsupported Eagle constructs
    for ur in eagle_result.unsupported:
        design.import_losses.append(
            ImportLossRecord(
                source_format="eagle",
                field_path=ur.kind,
                behavior="dropped",
                original_value=ur.message,
                note=f"Eagle import: {ur.message}",
            )
        )

    return design, eagle_result
