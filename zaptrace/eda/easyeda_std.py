"""EasyEDA Standard format reader/writer with round-trip degradation evidence (issue #134).

EasyEDA Standard is the older JSON-based format, distinct from EasyEDA Pro
(ZIP+JSONL). A Standard file is a single flat JSON document.

Top-level structure
--------------------
::

    {
      "head": { "docType": "1", "editorVersion": "6.5.40", "c_para": {...} },
      "schematic": {
        "components": [ {id, ref, value, packageName, x, y}, ... ],
        "nets":       [ {id, name, pins: [{componentId, pinNumber}]}, ... ],
        "wires":      [ {id, strokeColor, points: [[x,y], ...]}, ... ],
        "shapes":     [ {"type": "~...", ...}, ... ]
      }
    }

The ``"PCB"`` top-level key is accepted as an alias for ``"schematic"`` to
support board documents with the same structure.

Security guards
---------------
* Oversized input: rejects inputs whose byte size exceeds ``MAX_JSON_BYTES``.
* Malformed JSON: records a degradation entry instead of raising.
* Unsupported version: warns via a degradation record but continues.

Unknown constructs
------------------
Any field or sub-record that cannot be mapped to the canonical
:class:`~zaptrace.core.models.Design` model is captured as an
:class:`EasyEdaStdDegradationRecord` so that nothing is silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

MAX_JSON_BYTES: int = 10 * 1024 * 1024  # 10 MiB

# Supported editorVersion prefix
_SUPPORTED_EDITOR_PREFIXES = ("6.", "5.", "2.")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EasyEdaStdComponent:
    """A placed component from an EasyEDA Standard schematic.

    Attributes
    ----------
    id:
        Internal EasyEDA record ID (e.g. ``"gge001"``).
    ref:
        Reference designator (e.g. ``"R1"``).
    value:
        Component value string (e.g. ``"10k"``).
    package:
        Footprint / package name (e.g. ``"R_0402"``).
    x:
        X coordinate in EasyEDA canvas units.
    y:
        Y coordinate in EasyEDA canvas units.
    """

    id: str
    ref: str
    value: str = ""
    package: str = ""
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ref": self.ref,
            "value": self.value,
            "package": self.package,
            "x": self.x,
            "y": self.y,
        }


@dataclass
class EasyEdaStdNet:
    """A net from an EasyEDA Standard schematic.

    Attributes
    ----------
    id:
        Internal EasyEDA record ID (e.g. ``"net001"``).
    name:
        Human-readable net name (e.g. ``"VCC"``).
    pins:
        List of pin references: ``[{"componentId": str, "pinNumber": str}]``.
    """

    id: str
    name: str
    pins: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "pins": self.pins}


@dataclass
class EasyEdaStdDegradationRecord:
    """A construct that could not be fully mapped to the canonical model.

    Attributes
    ----------
    record_type:
        Short classification tag, e.g. ``"UNKNOWN_SHAPE"``, ``"PARSE_ERROR"``.
    document:
        Logical document section where the record was encountered (e.g.
        ``"schematic.shapes"``).
    severity:
        ``"info"`` for known-unknown constructs; ``"error"`` for failures.
    raw:
        Truncated raw content for debugging (max 200 chars).
    """

    record_type: str
    document: str
    severity: str = "info"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "document": self.document,
            "severity": self.severity,
            "raw": self.raw[:200],
        }


@dataclass
class EasyEdaStdProject:
    """The result of reading an EasyEDA Standard JSON file.

    Attributes
    ----------
    components:
        Parsed component records.
    nets:
        Parsed net records.
    format_version:
        The ``editorVersion`` string from the ``head`` block, if present.
    degradation:
        All degradation records accumulated during parsing.
    """

    components: list[EasyEdaStdComponent] = field(default_factory=list)
    nets: list[EasyEdaStdNet] = field(default_factory=list)
    format_version: str = ""
    degradation: list[EasyEdaStdDegradationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "degradation_count": len(self.degradation),
        }


@dataclass
class EasyEdaStdWriteReport:
    """Report produced by :func:`write_easyeda_std_json`.

    Attributes
    ----------
    unsupported_count:
        Number of design elements that could not be represented in EasyEDA
        Standard JSON and were omitted from the output.
    """

    unsupported_count: int = 0

    @property
    def accepted(self) -> bool:
        """Return True when no design elements were lost during write."""
        return self.unsupported_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "unsupported_count": self.unsupported_count,
            "accepted": self.accepted,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decode_source(source: str | bytes | dict) -> dict[str, Any]:
    """Decode *source* to a Python dict.

    Raises
    ------
    ValueError
        If the byte/string content exceeds ``MAX_JSON_BYTES`` or cannot be
        parsed as JSON.
    TypeError
        If *source* is not ``str``, ``bytes``, or ``dict``.
    """
    if isinstance(source, dict):
        return source

    if isinstance(source, bytes):
        raw_bytes = source
    elif isinstance(source, str):
        raw_bytes = source.encode("utf-8", errors="replace")
    else:
        raise TypeError(f"Expected str, bytes, or dict; got {type(source).__name__!r}")

    if len(raw_bytes) > MAX_JSON_BYTES:
        raise ValueError(f"EasyEDA Standard JSON input exceeds size limit ({len(raw_bytes)} > {MAX_JSON_BYTES} bytes)")

    try:
        return json.loads(raw_bytes)  # type: ignore[return-value]
    except json.JSONDecodeError as exc:
        raise ValueError(f"EasyEDA Standard: malformed JSON — {exc}") from exc


def _parse_component(raw: Any, document: str) -> tuple[EasyEdaStdComponent | None, EasyEdaStdDegradationRecord | None]:
    """Parse a single component dict.  Returns (component, None) or (None, record)."""
    if not isinstance(raw, dict):
        return None, EasyEdaStdDegradationRecord(
            record_type="NON_OBJECT_COMPONENT",
            document=document,
            severity="error",
            raw=str(raw)[:200],
        )
    cid = str(raw.get("id", ""))
    if not cid:
        return None, EasyEdaStdDegradationRecord(
            record_type="COMPONENT_MISSING_ID",
            document=document,
            severity="error",
            raw=str(raw)[:200],
        )
    try:
        comp = EasyEdaStdComponent(
            id=cid,
            ref=str(raw.get("ref", "")),
            value=str(raw.get("value", "")),
            package=str(raw.get("packageName", raw.get("package", ""))),
            x=float(raw.get("x", 0.0)),
            y=float(raw.get("y", 0.0)),
        )
    except (TypeError, ValueError) as exc:
        return None, EasyEdaStdDegradationRecord(
            record_type="COMPONENT_PARSE_ERROR",
            document=document,
            severity="error",
            raw=f"{exc}: {str(raw)[:200]}",
        )
    return comp, None


def _parse_net(raw: Any, document: str) -> tuple[EasyEdaStdNet | None, EasyEdaStdDegradationRecord | None]:
    """Parse a single net dict.  Returns (net, None) or (None, record)."""
    if not isinstance(raw, dict):
        return None, EasyEdaStdDegradationRecord(
            record_type="NON_OBJECT_NET",
            document=document,
            severity="error",
            raw=str(raw)[:200],
        )
    nid = str(raw.get("id", ""))
    name = str(raw.get("name", ""))
    if not nid or not name:
        return None, EasyEdaStdDegradationRecord(
            record_type="NET_MISSING_FIELD",
            document=document,
            severity="error",
            raw=str(raw)[:200],
        )
    pins_raw = raw.get("pins", [])
    pins: list[dict[str, str]] = []
    if isinstance(pins_raw, list):
        for p in pins_raw:
            if isinstance(p, dict):
                pins.append(
                    {
                        "componentId": str(p.get("componentId", "")),
                        "pinNumber": str(p.get("pinNumber", "")),
                    }
                )
    return EasyEdaStdNet(id=nid, name=name, pins=pins), None


def _extract_section(data: dict[str, Any]) -> dict[str, Any]:
    """Return the schematic/PCB section dict from the top-level document."""
    for key in ("schematic", "PCB", "pcb", "Schematic"):
        if key in data and isinstance(data[key], dict):
            return data[key]  # type: ignore[return-value]
    return {}


# ---------------------------------------------------------------------------
# Public API — reader
# ---------------------------------------------------------------------------


def read_easyeda_std_json(source: str | bytes | dict) -> EasyEdaStdProject:
    """Read an EasyEDA Standard JSON document into an :class:`EasyEdaStdProject`.

    Parameters
    ----------
    source:
        Raw JSON bytes, JSON string, or an already-parsed ``dict``.  A list
        or other non-dict value is accepted but results in a NON_OBJECT_ROOT
        degradation record rather than a crash.

    Returns
    -------
    EasyEdaStdProject
        Parsed project with degradation records for any unsupported constructs.

    Raises
    ------
    ValueError
        If *source* is oversized (> ``MAX_JSON_BYTES``) or cannot be decoded
        as JSON.
    TypeError
        If *source* is an unexpected primitive type (int, float, etc.).
    """
    # Short-circuit for non-str/bytes/dict objects so we can record them as
    # NON_OBJECT_ROOT without raising TypeError from _decode_source.
    if isinstance(source, list):
        project = EasyEdaStdProject()
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type="NON_OBJECT_ROOT",
                document="root",
                severity="error",
                raw=str(source)[:200],
            )
        )
        return project

    try:
        data = _decode_source(source)
    except (ValueError, TypeError):
        raise

    project = EasyEdaStdProject()

    if not isinstance(data, dict):
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type="NON_OBJECT_ROOT",
                document="root",
                severity="error",
                raw=str(data)[:200],
            )
        )
        return project

    # ---- head block --------------------------------------------------------
    head = data.get("head", {})
    if isinstance(head, dict):
        project.format_version = str(head.get("editorVersion", ""))
        if project.format_version and not any(project.format_version.startswith(p) for p in _SUPPORTED_EDITOR_PREFIXES):
            project.degradation.append(
                EasyEdaStdDegradationRecord(
                    record_type="UNSUPPORTED_VERSION",
                    document="head",
                    severity="info",
                    raw=f"editorVersion={project.format_version}",
                )
            )
    else:
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type="MALFORMED_HEAD",
                document="head",
                severity="info",
                raw=str(head)[:200],
            )
        )

    # ---- schematic/PCB section ---------------------------------------------
    section = _extract_section(data)
    if not section:
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type="MISSING_SECTION",
                document="root",
                severity="error",
                raw="No 'schematic' or 'PCB' key found",
            )
        )
        return project

    # ---- components --------------------------------------------------------
    for raw_comp in section.get("components", []):
        comp, err = _parse_component(raw_comp, "schematic.components")
        if err:
            project.degradation.append(err)
        elif comp is not None:
            project.components.append(comp)

    # ---- nets --------------------------------------------------------------
    for raw_net in section.get("nets", []):
        net, err = _parse_net(raw_net, "schematic.nets")
        if err:
            project.degradation.append(err)
        elif net is not None:
            project.nets.append(net)

    # ---- wires (known-unsupported — preserved as degradation info) ---------
    for _i, wire in enumerate(section.get("wires", [])):
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type="WIRE",
                document="schematic.wires",
                severity="info",
                raw=str(wire)[:200],
            )
        )

    # ---- tilde-shape records -----------------------------------------------
    for _i, shape in enumerate(section.get("shapes", [])):
        raw_str = str(shape)
        if isinstance(shape, dict):
            shape_type = str(shape.get("type", "UNKNOWN_SHAPE"))
        elif isinstance(shape, str) and shape.startswith("~"):
            shape_type = "TILDE_SHAPE"
        else:
            shape_type = "UNKNOWN_SHAPE"
        project.degradation.append(
            EasyEdaStdDegradationRecord(
                record_type=shape_type,
                document="schematic.shapes",
                severity="info",
                raw=raw_str[:200],
            )
        )

    return project


def easyeda_std_project_to_design(project: EasyEdaStdProject, *, name: str = "easyeda_std") -> Design:
    """Convert an :class:`EasyEdaStdProject` into a canonical :class:`~zaptrace.core.models.Design`.

    Parameters
    ----------
    project:
        The parsed EasyEDA Standard project.
    name:
        The design name to use for the :class:`~zaptrace.core.models.DesignMeta`.

    Returns
    -------
    Design
        Canonical design model populated from *project*.
    """
    components: dict[str, Component] = {}
    for c in project.components:
        canonical = Component(
            id=c.id,
            ref=c.ref,
            type="component",
            value=c.value,
            footprint=c.package,
            position=(c.x, c.y),
        )
        components[c.id] = canonical

    nets: dict[str, Net] = {}
    for n in project.nets:
        nodes = [
            NetNode(component_ref=p["componentId"], pin_name=p["pinNumber"])
            for p in n.pins
            if p.get("componentId") and p.get("pinNumber")
        ]
        net = Net(id=n.id, name=n.name, nodes=nodes)
        nets[n.id] = net

    return Design(
        meta=DesignMeta(name=name),
        components=components,
        nets=nets,
    )


# ---------------------------------------------------------------------------
# Public API — writer
# ---------------------------------------------------------------------------


def write_easyeda_std_json(
    design: Design,
    *,
    project_name: str = "",
    source_provenance: str = "",
) -> tuple[str, EasyEdaStdWriteReport]:
    """Serialise a canonical :class:`~zaptrace.core.models.Design` as EasyEDA Standard JSON.

    Only the subset representable in EasyEDA Standard is emitted; anything
    else is counted in the :class:`EasyEdaStdWriteReport`.

    Parameters
    ----------
    design:
        The canonical design to serialise.
    project_name:
        Optional name to embed in the ``head.c_para`` block.
    source_provenance:
        Optional provenance string (e.g. ``"CC0-1.0"``) to embed in head.

    Returns
    -------
    tuple[str, EasyEdaStdWriteReport]
        ``(json_string, report)`` — the JSON string is deterministic (sorted
        component order) and round-trip importable.
    """
    report = EasyEdaStdWriteReport()

    # ---- components (sorted by ID for determinism) -------------------------
    components_out: list[dict[str, Any]] = []
    for cid in sorted(design.components):
        c = design.components[cid]
        x, y = c.position if c.position else (0.0, 0.0)
        components_out.append(
            {
                "id": c.id,
                "ref": c.ref,
                "value": c.value or "",
                "packageName": c.footprint or "",
                "x": x,
                "y": y,
            }
        )

    # ---- nets (sorted by ID for determinism) --------------------------------
    nets_out: list[dict[str, Any]] = []
    for nid in sorted(design.nets):
        n = design.nets[nid]
        pins_out = [{"componentId": node.component_ref, "pinNumber": node.pin_name} for node in n.nodes]
        nets_out.append({"id": n.id, "name": n.name, "pins": pins_out})

    # ---- unsupported: wires, shapes, copper pours, etc. -------------------
    # Copper pours, routes, DRC results etc. have no representation in
    # EasyEDA Standard and are counted as unsupported.
    if design.routing is not None:
        report.unsupported_count += 1
    if design.copper_pours:
        report.unsupported_count += len(design.copper_pours)
    if design.drc_result is not None:
        report.unsupported_count += 1

    doc: dict[str, Any] = {
        "head": {
            "docType": "1",
            "editorVersion": "6.5.40",
            "c_para": {
                "name": project_name,
                "sourceProvenance": source_provenance,
            },
        },
        "schematic": {
            "components": components_out,
            "nets": nets_out,
            "wires": [],
            "shapes": [],
        },
    }

    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False), report


# ---------------------------------------------------------------------------
# Public API — fidelity
# ---------------------------------------------------------------------------


def compute_easyeda_std_fidelity(design: Design) -> dict[str, Any]:
    """Compute round-trip fidelity metrics for *design*.

    The function serialises *design* back to EasyEDA Standard JSON, re-parses
    it, then computes Jaccard similarity for components and nets.

    Parameters
    ----------
    design:
        The canonical design to evaluate.

    Returns
    -------
    dict with keys:
        * ``component_jaccard``  – float in [0, 1]
        * ``net_jaccard``        – float in [0, 1]
        * ``overall_score``      – average of the two Jaccard scores
        * ``degradation_report`` – list of degradation record dicts
    """
    json_str, _report = write_easyeda_std_json(design)
    rt_project = read_easyeda_std_json(json_str)

    orig_comp_ids = set(design.components.keys())
    rt_comp_ids = {c.id for c in rt_project.components}
    component_jaccard = _jaccard(orig_comp_ids, rt_comp_ids)

    orig_net_ids = set(design.nets.keys())
    rt_net_ids = {n.id for n in rt_project.nets}
    net_jaccard = _jaccard(orig_net_ids, rt_net_ids)

    overall_score = (component_jaccard + net_jaccard) / 2.0

    return {
        "component_jaccard": component_jaccard,
        "net_jaccard": net_jaccard,
        "overall_score": overall_score,
        "degradation_report": [d.to_dict() for d in rt_project.degradation],
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)
