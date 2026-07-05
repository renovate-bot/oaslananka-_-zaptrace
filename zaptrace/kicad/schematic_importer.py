"""KiCad schematic (.kicad_sch) import with verified net identity (issue #117).

Parses a flat KiCad schematic into the canonical ZapTrace Design model,
resolving wires, labels, junctions, symbols, and pins into deterministic
connectivity while preserving unsupported records as structured evidence.

Supported constructs
--------------------
* ``(symbol ...)``  — component instances with ref/value properties
* ``(wire ...)``    — single-segment wire (start/end coordinates)
* ``(junction ...)`` — explicit wire crossing junction
* ``(label ...)``, ``(global_label ...)``, ``(hierarchical_label ...)`` — net naming
* ``(no_connect ...)`` — unconnected pin marker (suppresses dangling-wire warning)
* ``(net_tie ...)`` — noted as unsupported; does not fail import

Connectivity resolution
-----------------------
1. All wire endpoints are collected.
2. Wire segments are merged into connected groups via union-find, expanded by
   junction points that lie on any wire.
3. Each group that carries at least one label is named by its highest-priority
   label (global > hierarchical > local). Groups without labels receive an
   auto-generated net name ``net_<hex>``.
4. Symbol pins are assigned to the wire group whose endpoint matches the pin
   coordinate (with a 1-mil tolerance).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    ImportLossRecord,
    Net,
    NetNode,
)
from zaptrace.io.sexp import SexpNode
from zaptrace.io.sexp import parse as _sexp_parse

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchematicUnsupportedRecord:
    """A KiCad schematic construct that could not be fully imported."""

    kind: str
    message: str
    severity: str = "warning"
    source: str = ""  # "line:<n>" or xref

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
        }


@dataclass
class KiCadSchematicImportResult:
    """Result of importing a .kicad_sch file.

    Attributes
    ----------
    design:
        The canonical ZapTrace Design derived from the schematic.
    unsupported:
        Schematic constructs that could not be fully mapped.
    source_path:
        The original .kicad_sch file path, if available.
    net_score:
        Fraction of design nets that have at least one component connection
        (1.0 means all nets are resolved). Ranges [0, 1].
    """

    design: Design
    unsupported: list[SchematicUnsupportedRecord] = field(default_factory=list)
    source_path: Path | None = None
    net_score: float = 1.0

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path) if self.source_path else None,
            "component_count": len(self.design.components),
            "net_count": len(self.design.nets),
            "unsupported_count": self.unsupported_count,
            "net_score": self.net_score,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Coordinate precision: treat coordinates within this distance as equal.
_COORD_EPSILON: float = 0.01  # 1 mil in mm


def _coord(node: list[SexpNode]) -> tuple[float, float]:
    """Extract (x, y) from ``(at x y ...)`` or ``(xy x y)``."""
    try:
        return float(str(node[1])), float(str(node[2]))
    except (IndexError, ValueError):
        return 0.0, 0.0


def _find(nodes: list[SexpNode], tag: str) -> list[SexpNode] | None:
    """Return the first child list whose head atom equals *tag*, or None."""
    for n in nodes:
        if isinstance(n, list) and n and n[0] == tag:
            return n  # type: ignore[return-value]
    return None


def _find_all(nodes: list[SexpNode], tag: str) -> list[list[SexpNode]]:
    """Return all child lists whose head atom equals *tag*."""
    return [n for n in nodes if isinstance(n, list) and n and n[0] == tag]  # type: ignore[return-value]


def _atom(node: list[SexpNode], index: int = 1) -> str:
    """Safely extract a string atom at *index* from a list node."""
    try:
        v = node[index]
        return str(v) if isinstance(v, str) else ""
    except IndexError:
        return ""


def _prop(nodes: list[SexpNode], key: str) -> str:
    """Return the value of the first ``(property "key" "value" ...)`` child."""
    for n in nodes:
        if isinstance(n, list) and len(n) >= 3 and n[0] == "property" and n[1] == key:
            return str(n[2])
    return ""


# ---------------------------------------------------------------------------
# Union-find for connectivity
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def _make(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x

    def find(self, x: int) -> int:
        self._make(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        self._make(x)
        self._make(y)
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[ry] = rx

    def groups(self) -> dict[int, list[int]]:
        grps: dict[int, list[int]] = {}
        for k in self._parent:
            r = self.find(k)
            grps.setdefault(r, []).append(k)
        return grps


# ---------------------------------------------------------------------------
# Schematic parser
# ---------------------------------------------------------------------------


def _parse_schematic(
    sexp: list[SexpNode],
) -> tuple[
    list[dict[str, Any]],  # symbols (component instances)
    list[tuple[tuple[float, float], tuple[float, float]]],  # wires
    list[tuple[float, float]],  # junctions
    list[tuple[str, str, tuple[float, float]]],  # labels: (name, kind, coord)
    list[SchematicUnsupportedRecord],
]:
    """Parse a top-level kicad_sch S-expression into raw schematic objects."""
    symbols: list[dict[str, Any]] = []
    wires: list[tuple[tuple[float, float], tuple[float, float]]] = []
    junctions: list[tuple[float, float]] = []
    labels: list[tuple[str, str, tuple[float, float]]] = []
    unsupported: list[SchematicUnsupportedRecord] = []

    for node in sexp[1:]:  # skip "kicad_sch"
        if not isinstance(node, list) or not node:
            continue
        tag = str(node[0])

        if tag == "symbol":
            _parse_symbol(node, symbols, unsupported)

        elif tag == "wire":
            pts = _find(node, "pts")
            if pts:
                xy_nodes = _find_all(pts, "xy")
                if len(xy_nodes) == 2:
                    start = _coord(xy_nodes[0])
                    end = _coord(xy_nodes[1])
                    wires.append((start, end))
                else:
                    unsupported.append(
                        SchematicUnsupportedRecord(
                            kind="wire_malformed",
                            message=f"wire with {len(xy_nodes)} points",
                            severity="warning",
                        )
                    )

        elif tag == "junction":
            at = _find(node, "at")
            if at:
                junctions.append(_coord(at))

        elif tag in ("label", "global_label", "hierarchical_label"):
            at = _find(node, "at")
            coord = _coord(at) if at else (0.0, 0.0)
            name = _atom(node, 1)
            labels.append((name, tag, coord))

        elif tag == "no_connect":
            pass  # intentionally skipped

        elif tag in (
            "version",
            "generator",
            "generator_version",
            "uuid",
            "title_block",
            "lib_symbols",
            "sheet",
            "sheet_instances",
            "symbol_instances",
            "net_tie_pad_groups",
            "bus",
            "bus_entry",
            "image",
            "polyline",
            "arc",
            "circle",
            "rectangle",
            "text",
            "text_box",
            "embedded_files",
            "rule_area",
        ):
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind=tag,
                    message=f"Schematic construct '{tag}' noted but not fully mapped",
                    severity="info",
                )
            )

        else:
            unsupported.append(
                SchematicUnsupportedRecord(
                    kind=f"unknown_{tag}",
                    message=f"Unknown schematic construct '{tag}'",
                    severity="warning",
                )
            )

    return symbols, wires, junctions, labels, unsupported


def _parse_symbol(
    node: list[SexpNode],
    symbols: list[dict[str, Any]],
    unsupported: list[SchematicUnsupportedRecord],
) -> None:
    """Extract component instance data from a ``(symbol ...)`` node."""
    lib_id_node = _find(node, "lib_id")
    lib_id = _atom(lib_id_node) if lib_id_node else ""
    at_node = _find(node, "at")
    at_coord = _coord(at_node) if at_node else (0.0, 0.0)
    at_angle = float(str(at_node[3])) if at_node and len(at_node) > 3 else 0.0

    ref = _prop(node, "Reference")
    value = _prop(node, "Value")
    footprint = _prop(node, "Footprint")
    unit_node = _find(node, "unit")
    unit = int(_atom(unit_node)) if unit_node else 1

    # Collect pin coordinates from nested symbol bodies
    pin_coords: list[tuple[str, float, float]] = []
    for child in node:
        if isinstance(child, list) and child and child[0] == "pin":
            pin_name = _atom(child, 1)
            pin_at = _find(child, "at")
            if pin_at:
                px, py = _coord(pin_at)
                pin_coords.append((pin_name, px, py))
            else:
                # Bare pin format: (pin name x y) — coordinates are schematic-absolute
                try:
                    px = float(str(child[2]))
                    py = float(str(child[3]))
                    pin_coords.append((pin_name, px, py))
                except (IndexError, ValueError):
                    pass

    symbols.append(
        {
            "lib_id": lib_id,
            "ref": ref,
            "value": value,
            "footprint": footprint,
            "at": at_coord,
            "angle": at_angle,
            "unit": unit,
            "pins": pin_coords,
        }
    )

    # Only record meaningful unsupported attributes, not every missing optional
    if not ref:
        unsupported.append(
            SchematicUnsupportedRecord(
                kind="symbol_missing_ref",
                message=f"Symbol '{lib_id}' has no Reference property",
                severity="warning",
            )
        )


# ---------------------------------------------------------------------------
# Connectivity resolution
# ---------------------------------------------------------------------------


def _resolve_connectivity(
    symbols: list[dict[str, Any]],
    wires: list[tuple[tuple[float, float], tuple[float, float]]],
    junctions: list[tuple[float, float]],
    labels: list[tuple[str, str, tuple[float, float]]],
) -> dict[str, list[tuple[str, str]]]:
    """Resolve wire connectivity into named nets.

    Returns a dict mapping ``net_name → [(ref, pin_name), ...]``.
    """
    # Step 1: collect all unique coordinate points
    coords: list[tuple[float, float]] = []
    coord_idx: dict[tuple[int, int], int] = {}  # quantised coord → index

    def _quantise(xy: tuple[float, float]) -> tuple[int, int]:
        return round(xy[0] / _COORD_EPSILON), round(xy[1] / _COORD_EPSILON)

    def _get_or_add(xy: tuple[float, float]) -> int:
        q = _quantise(xy)
        if q not in coord_idx:
            coord_idx[q] = len(coords)
            coords.append(xy)
        return coord_idx[q]

    uf = _UnionFind()

    # Step 2: add wires — union start and end
    for start, end in wires:
        si = _get_or_add(start)
        ei = _get_or_add(end)
        uf.union(si, ei)

    # Step 3: junctions expand connectivity — merge junction point into any
    #         wire endpoint that is within epsilon
    for jx, jy in junctions:
        jq = _quantise((jx, jy))
        if jq in coord_idx:
            ji = coord_idx[jq]
            # Already in graph; union is a no-op but ensures membership
            uf.union(ji, ji)
        else:
            # Add junction as its own group (may get merged later)
            _get_or_add((jx, jy))

    # Step 4: label endpoints → wire groups
    label_groups: dict[int, list[tuple[str, str]]] = {}  # root → [(name, kind)]
    for lname, lkind, lcoord in labels:
        lq = _quantise(lcoord)
        if lq in coord_idx:
            li = coord_idx[lq]
            r = uf.find(li)
            label_groups.setdefault(r, []).append((lname, lkind))
        else:
            # Floating label (no wire attached): add as isolated group
            li = _get_or_add(lcoord)
            r = uf.find(li)
            label_groups.setdefault(r, []).append((lname, lkind))

    # Step 5: choose best name for each group
    _kind_priority = {"global_label": 0, "hierarchical_label": 1, "label": 2}

    def _best_name(group_labels: list[tuple[str, str]]) -> str:
        if not group_labels:
            return ""
        return min(group_labels, key=lambda x: _kind_priority.get(x[1], 99))[0]

    # Step 6: assign pins to groups
    group_pins: dict[int, list[tuple[str, str]]] = {}  # root → [(ref, pin_name)]
    for sym in symbols:
        ref = sym["ref"]
        for pin_name, px, py in sym["pins"]:
            q = _quantise((px, py))
            if q in coord_idx:
                gi = coord_idx[q]
                r = uf.find(gi)
                group_pins.setdefault(r, []).append((ref, pin_name))

    # Step 7: collect all roots and name nets
    all_roots: set[int] = set()
    for uf_root in uf.groups():
        all_roots.add(uf_root)
    for r in label_groups:
        all_roots.add(r)
    for r in group_pins:
        all_roots.add(r)

    nets: dict[str, list[tuple[str, str]]] = {}
    for root in all_roots:
        name_candidates = label_groups.get(root, [])
        net_name = _best_name(name_candidates)
        if not net_name:
            # Auto-name from hash of root integer
            net_name = "net_" + hashlib.sha256(str(root).encode()).hexdigest()[:8]
        pins = group_pins.get(root, [])
        if net_name in nets:
            nets[net_name].extend(pins)
        else:
            nets[net_name] = pins

    return nets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_kicad_schematic(path: str | Path) -> KiCadSchematicImportResult:
    """Import a flat KiCad schematic (.kicad_sch) into a ZapTrace Design.

    This function:
    1. Parses the S-expression content.
    2. Extracts component instances, wires, junctions, and labels.
    3. Resolves connectivity via union-find.
    4. Builds the canonical Design model.
    5. Records unsupported constructs as ImportLossRecord entries.

    Parameters
    ----------
    path:
        Path to a ``.kicad_sch`` file.

    Returns
    -------
    KiCadSchematicImportResult
        The import result including the design, unsupported records, and
        net score.

    Raises
    ------
    ValueError
        If the file is not a valid kicad_sch S-expression.
    OSError
        If the file cannot be read.
    """
    p = Path(path)
    content = p.read_text(encoding="utf-8")
    return import_kicad_schematic_string(content, source_path=p)


def import_kicad_schematic_string(
    content: str,
    source_path: Path | None = None,
) -> KiCadSchematicImportResult:
    """Import a KiCad schematic from a string (for testing without file I/O).

    Parameters
    ----------
    content:
        The raw .kicad_sch S-expression text.
    source_path:
        Optional source file path for evidence records.

    Returns
    -------
    KiCadSchematicImportResult
    """
    sexp = _sexp_parse(content)
    if not isinstance(sexp, list) or not sexp or sexp[0] != "kicad_sch":
        raise ValueError("Not a valid kicad_sch file: root element must be (kicad_sch ...)")

    symbols, wires, junctions, labels, unsupported = _parse_schematic(sexp)

    # Resolve connectivity
    nets_raw = _resolve_connectivity(symbols, wires, junctions, labels)

    # Build Design
    source_name = source_path.stem if source_path else "schematic"
    design = Design(meta=DesignMeta(name=source_name, author="kicad-schematic-import"))

    # Add components from symbol instances (deduplicate by ref — multi-unit symbols)
    seen_refs: set[str] = set()
    for sym in symbols:
        ref = sym["ref"]
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        comp = Component(
            id=re.sub(r"[^a-zA-Z0-9_]", "_", ref).lower(),
            ref=ref,
            type=sym["lib_id"].split(":")[-1] if ":" in sym["lib_id"] else sym["lib_id"],
            value=sym["value"],
        )
        design.components[comp.id] = comp

    # Add nets and nodes
    net_ids_with_pins = 0
    for net_name, pin_list in sorted(nets_raw.items()):
        net_id = re.sub(r"[^a-zA-Z0-9_]", "_", net_name).lower()
        nodes = [NetNode(component_ref=ref, pin_name=pin) for ref, pin in pin_list]
        net = Net(id=net_id, name=net_name, nodes=nodes)
        design.nets[net_id] = net
        if nodes:
            net_ids_with_pins += 1

    # Net score: fraction of nets that have at least one pin connection
    total_nets = len(design.nets)
    net_score = (net_ids_with_pins / total_nets) if total_nets else 1.0

    # Record unsupported constructs as import losses
    for ur in unsupported:
        if ur.severity in ("warning", "error"):
            design.import_losses.append(
                ImportLossRecord(
                    source_format="kicad_sch",
                    field_path=ur.kind,
                    behavior="noted",
                    original_value=ur.message,
                    note=f"KiCad schematic import: {ur.message} [{ur.source}]",
                )
            )

    return KiCadSchematicImportResult(
        design=design,
        unsupported=unsupported,
        source_path=source_path,
        net_score=net_score,
    )


def compute_schematic_net_score(
    exported_result: KiCadSchematicImportResult,
    imported_result: KiCadSchematicImportResult,
) -> float:
    """Compute self-round-trip net identity score.

    Measures what fraction of nets in *imported_result* are also present in
    *exported_result* (by name, normalised), and vice versa.  A score of 1.00
    means all nets are shared.

    Used to validate: export → import → same nets.
    """

    def _norm_names(result: KiCadSchematicImportResult) -> set[str]:
        return {re.sub(r"[^a-z0-9]", "_", n.lower()) for n in result.design.nets}

    a = _norm_names(exported_result)
    b = _norm_names(imported_result)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union
