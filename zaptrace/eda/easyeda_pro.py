"""EasyEDA Pro project reader with shared shape codec (issue #120).

Reads an EasyEDA Pro ZIP/JSONL project into the canonical ZapTrace model,
preserving unknown constructs as structured degradation records.

EasyEDA Pro project structure
-------------------------------
A ``.epro`` or ``.zip`` file contains:
* ``project.json``    — project metadata (name, version, source provenance)
* ``schematic.jsonl`` — one JSON object per line, schematic elements
* ``pcb.jsonl``       — one JSON object per line, PCB elements

Known record types (``"type"`` field)
--------------------------------------
Schematic:
  * ``HEADER``    — file format metadata (version, generator, docType)
  * ``CANVAS``    — canvas settings
  * ``COMPONENT`` — placed component with ref, value, package, mpn, x/y
  * ``NET``       — net with name and list of ``{component, pin}`` refs
  * ``WIRE``      — wire segment with net reference and coordinate list
  * ``LABEL``     — net label annotation

PCB:
  * ``HEADER``     — file format metadata
  * ``LAYER``      — layer definition (id, name, color)
  * ``FOOTPRINT``  — placed footprint (ref, package, x/y/rotation)
  * ``TRACK``      — routed copper track (net, x1/y1/x2/y2, width, layer)
  * ``VIA``        — via (x/y, outer/inner diameter)

Unknown records
---------------
Any record whose ``"type"`` is not in the supported set is preserved as an
:class:`EasyEdaDegradationRecord` with the document (file name) and 0-based
line index. Records are never silently dropped.

Security guards
---------------
* ZIP path traversal: rejects any entry whose resolved path escapes the
  extraction root.
* Oversized ZIP: rejects ZIPs with an uncompressed total exceeding
  ``MAX_UNCOMPRESSED_BYTES``.
* Oversized JSONL: rejects individual lines exceeding
  ``MAX_JSONL_LINE_BYTES``.
* Malformed JSONL: records a degradation entry instead of crashing.
* Unsupported version: warns but continues (version mismatch is non-fatal).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

# Safety limits
MAX_UNCOMPRESSED_BYTES: int = 50 * 1024 * 1024  # 50 MiB
MAX_JSONL_LINE_BYTES: int = 1 * 1024 * 1024  # 1 MiB per line

# Supported EasyEDA Pro version prefix
_SUPPORTED_VERSIONS = ("2.",)

# ---------------------------------------------------------------------------
# Shared codec: record type vocabularies
# ---------------------------------------------------------------------------

_SCH_KNOWN = frozenset({"HEADER", "CANVAS", "COMPONENT", "NET", "WIRE", "LABEL"})
_PCB_KNOWN = frozenset({"HEADER", "LAYER", "FOOTPRINT", "TRACK", "VIA", "DIMENSION_LINE", "CANVAS"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EasyEdaDegradationRecord:
    """An unknown or unsupported EasyEDA Pro record.

    Attributes
    ----------
    record_type:
        The ``"type"`` field from the JSON record, or ``"PARSE_ERROR"`` if the
        line could not be decoded as JSON.
    document:
        The file inside the ZIP where the record was encountered.
    line_index:
        0-based line index within the JSONL file.
    severity:
        ``"info"`` for known-unknown constructs; ``"error"`` for parse errors.
    raw:
        The raw line text (truncated to 200 chars for safety).
    """

    record_type: str
    document: str
    line_index: int
    severity: str = "info"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "document": self.document,
            "line_index": self.line_index,
            "severity": self.severity,
            "raw": self.raw[:200],
        }


@dataclass
class EasyEdaComponent:
    """A placed component from the EasyEDA Pro schematic."""

    id: str
    ref: str
    value: str = ""
    package: str = ""
    mpn: str = ""
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ref": self.ref,
            "value": self.value,
            "package": self.package,
            "mpn": self.mpn,
            "x": self.x,
            "y": self.y,
        }


@dataclass
class EasyEdaNet:
    """A net from the EasyEDA Pro schematic."""

    id: str
    name: str
    pins: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "pins": self.pins}


@dataclass
class EasyEdaLayer:
    """A PCB layer from the EasyEDA Pro document."""

    id: int
    name: str
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "color": self.color}


@dataclass
class EasyEdaTrack:
    """A routed track from the EasyEDA Pro PCB."""

    layer: int
    net: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "net": self.net,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "width": self.width,
        }


@dataclass
class EasyEdaVia:
    """A via from the EasyEDA Pro PCB."""

    x: float
    y: float
    outer_diameter: float = 0.8
    inner_diameter: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "outer_diameter": self.outer_diameter,
            "inner_diameter": self.inner_diameter,
        }


@dataclass
class EasyEdaFootprint:
    """A placed footprint from the EasyEDA Pro PCB."""

    ref: str
    package: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "package": self.package,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
        }


@dataclass
class EasyEdaProSchematic:
    """Extracted schematic data from an EasyEDA Pro project."""

    format_version: str = ""
    components: list[EasyEdaComponent] = field(default_factory=list)
    nets: list[EasyEdaNet] = field(default_factory=list)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "component_count": len(self.components),
            "net_count": len(self.nets),
            "degradation_count": len(self.degradation),
        }


@dataclass
class EasyEdaProPcb:
    """Extracted PCB data from an EasyEDA Pro project."""

    format_version: str = ""
    layers: list[EasyEdaLayer] = field(default_factory=list)
    footprints: list[EasyEdaFootprint] = field(default_factory=list)
    tracks: list[EasyEdaTrack] = field(default_factory=list)
    vias: list[EasyEdaVia] = field(default_factory=list)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "layer_count": len(self.layers),
            "footprint_count": len(self.footprints),
            "track_count": len(self.tracks),
            "via_count": len(self.vias),
            "degradation_count": len(self.degradation),
        }


@dataclass
class EasyEdaProProject:
    """The result of reading an EasyEDA Pro ZIP project.

    Attributes
    ----------
    project_name:
        The project name from ``project.json``.
    format_version:
        The EasyEDA Pro format version.
    source_provenance:
        The source provenance field from ``project.json``, if present.
    schematic:
        Extracted schematic data (may be empty if no schematic file found).
    pcb:
        Extracted PCB data (may be empty if no PCB file found).
    degradation:
        Top-level degradation records (project-level unknowns).
    """

    project_name: str = ""
    format_version: str = ""
    source_provenance: str = ""
    schematic: EasyEdaProSchematic = field(default_factory=EasyEdaProSchematic)
    pcb: EasyEdaProPcb = field(default_factory=EasyEdaProPcb)
    degradation: list[EasyEdaDegradationRecord] = field(default_factory=list)

    @property
    def total_degradation_count(self) -> int:
        return len(self.degradation) + len(self.schematic.degradation) + len(self.pcb.degradation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "format_version": self.format_version,
            "source_provenance": self.source_provenance,
            "schematic": self.schematic.to_dict(),
            "pcb": self.pcb.to_dict(),
            "total_degradation_count": self.total_degradation_count,
        }


# ---------------------------------------------------------------------------
# ZIP security helpers
# ---------------------------------------------------------------------------


def _is_safe_path(arcname: str) -> bool:
    """Return True if *arcname* does not attempt path traversal."""
    p = PurePosixPath(arcname)
    # Reject absolute paths or any path with ".." components
    if p.is_absolute():
        return False
    return all(part != ".." for part in p.parts)


def _check_zip_size(zf: zipfile.ZipFile) -> None:
    """Raise ValueError if uncompressed total exceeds MAX_UNCOMPRESSED_BYTES."""
    total = sum(info.file_size for info in zf.infolist())
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError(f"EasyEDA Pro ZIP uncompressed size {total} > {MAX_UNCOMPRESSED_BYTES} limit")


# ---------------------------------------------------------------------------
# Shared JSONL codec
# ---------------------------------------------------------------------------


def _parse_jsonl(
    text: str,
    document: str,
    known_types: frozenset[str],
) -> tuple[list[dict[str, Any]], list[EasyEdaDegradationRecord]]:
    """Parse JSONL text into (records, degradation_records).

    Each line is decoded as a JSON object. Unknown ``"type"`` values and lines
    that cannot be decoded are recorded as degradation records.
    """
    records: list[dict[str, Any]] = []
    degradation: list[EasyEdaDegradationRecord] = []

    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue

        if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="OVERSIZED_LINE",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=line[:200],
                )
            )
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="PARSE_ERROR",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=f"{exc}: {line[:200]}",
                )
            )
            continue

        if not isinstance(obj, dict):
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type="NON_OBJECT_LINE",
                    document=document,
                    line_index=i,
                    severity="error",
                    raw=line[:200],
                )
            )
            continue

        record_type = obj.get("type", "UNKNOWN")
        if record_type not in known_types:
            degradation.append(
                EasyEdaDegradationRecord(
                    record_type=record_type,
                    document=document,
                    line_index=i,
                    severity="info",
                    raw=line[:200],
                )
            )
        else:
            records.append(obj)

    return records, degradation


# ---------------------------------------------------------------------------
# Schematic extractor
# ---------------------------------------------------------------------------


def _extract_schematic(text: str, document: str) -> EasyEdaProSchematic:
    """Extract schematic data from JSONL content."""
    records, degradation = _parse_jsonl(text, document, _SCH_KNOWN)
    sch = EasyEdaProSchematic(degradation=degradation)

    for rec in records:
        rtype = rec.get("type")
        if rtype == "HEADER":
            sch.format_version = str(rec.get("version", ""))
        elif rtype == "COMPONENT":
            sch.components.append(
                EasyEdaComponent(
                    id=str(rec.get("id", "")),
                    ref=str(rec.get("ref", "")),
                    value=str(rec.get("value", "")),
                    package=str(rec.get("package", "")),
                    mpn=str(rec.get("mpn", "")),
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                )
            )
        elif rtype == "NET":
            pins_raw = rec.get("pins", [])
            pins = [
                {"component": str(p.get("component", "")), "pin": str(p.get("pin", ""))}
                for p in pins_raw
                if isinstance(p, dict)
            ]
            sch.nets.append(
                EasyEdaNet(
                    id=str(rec.get("id", "")),
                    name=str(rec.get("name", "")),
                    pins=pins,
                )
            )

    return sch


# ---------------------------------------------------------------------------
# PCB extractor
# ---------------------------------------------------------------------------


def _extract_pcb(text: str, document: str) -> EasyEdaProPcb:
    """Extract PCB data from JSONL content."""
    records, degradation = _parse_jsonl(text, document, _PCB_KNOWN)
    pcb = EasyEdaProPcb(degradation=degradation)

    for rec in records:
        rtype = rec.get("type")
        if rtype == "HEADER":
            pcb.format_version = str(rec.get("version", ""))
        elif rtype == "LAYER":
            pcb.layers.append(
                EasyEdaLayer(
                    id=int(rec.get("id", 0)),
                    name=str(rec.get("name", "")),
                    color=str(rec.get("color", "")),
                )
            )
        elif rtype == "FOOTPRINT":
            pcb.footprints.append(
                EasyEdaFootprint(
                    ref=str(rec.get("ref", "")),
                    package=str(rec.get("package", "")),
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                    rotation=float(rec.get("rotation", 0.0)),
                )
            )
        elif rtype == "TRACK":
            pcb.tracks.append(
                EasyEdaTrack(
                    layer=int(rec.get("layer", 1)),
                    net=str(rec.get("net", "")),
                    x1=float(rec.get("x1", 0.0)),
                    y1=float(rec.get("y1", 0.0)),
                    x2=float(rec.get("x2", 0.0)),
                    y2=float(rec.get("y2", 0.0)),
                    width=float(rec.get("width", 0.2)),
                )
            )
        elif rtype == "VIA":
            pcb.vias.append(
                EasyEdaVia(
                    x=float(rec.get("x", 0.0)),
                    y=float(rec.get("y", 0.0)),
                    outer_diameter=float(rec.get("outerDiameter", 0.8)),
                    inner_diameter=float(rec.get("innerDiameter", 0.4)),
                )
            )

    return pcb


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_easyeda_pro_zip(path_or_bytes: str | bytes) -> EasyEdaProProject:
    """Read an EasyEDA Pro ZIP project file.

    Parameters
    ----------
    path_or_bytes:
        A file path (str) to a ``.epro`` or ``.zip`` file, or raw ZIP bytes.

    Returns
    -------
    EasyEdaProProject
        The extracted project data with degradation records.

    Raises
    ------
    ValueError:
        If the ZIP is malformed, unsafe (path traversal), or too large.
    FileNotFoundError:
        If *path_or_bytes* is a path that does not exist.
    """
    if isinstance(path_or_bytes, str):
        from pathlib import Path

        p = Path(path_or_bytes)
        if not p.exists():
            raise FileNotFoundError(f"EasyEDA Pro project not found: {p}")
        raw = p.read_bytes()
    else:
        raw = path_or_bytes

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ZIP file: {exc}") from exc

    with zf:
        _check_zip_size(zf)

        # Security: reject unsafe entry names
        for info in zf.infolist():
            if not _is_safe_path(info.filename):
                raise ValueError(f"Unsafe ZIP entry path (path traversal): {info.filename!r}")

        return _parse_zip_contents(zf)


def _parse_zip_contents(zf: zipfile.ZipFile) -> EasyEdaProProject:
    """Internal: extract project from an already-opened, validated ZipFile."""
    project = EasyEdaProProject()
    names = zf.namelist()

    # Read project.json
    if "project.json" in names:
        try:
            meta = json.loads(zf.read("project.json").decode("utf-8", errors="replace"))
            project.project_name = str(meta.get("name", ""))
            project.format_version = str(meta.get("formatVersion", meta.get("version", "")))
            project.source_provenance = str(meta.get("sourceProvenance", ""))

            if project.format_version and not any(project.format_version.startswith(v) for v in _SUPPORTED_VERSIONS):
                project.degradation.append(
                    EasyEdaDegradationRecord(
                        record_type="UNSUPPORTED_VERSION",
                        document="project.json",
                        line_index=0,
                        severity="info",
                        raw=f"version={project.format_version}",
                    )
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            project.degradation.append(
                EasyEdaDegradationRecord(
                    record_type="PARSE_ERROR",
                    document="project.json",
                    line_index=0,
                    severity="error",
                    raw="project.json could not be decoded",
                )
            )
    else:
        project.degradation.append(
            EasyEdaDegradationRecord(
                record_type="MISSING_PROJECT_JSON",
                document="",
                line_index=0,
                severity="error",
                raw="project.json not found in ZIP",
            )
        )

    # Read schematic JSONL (any .jsonl file with 'schematic' in name or first one found)
    sch_names = [n for n in names if "schematic" in n.lower() and n.endswith(".jsonl")]
    if not sch_names:
        sch_names = [n for n in names if n.endswith(".jsonl") and "pcb" not in n.lower()]
    if sch_names:
        doc = sch_names[0]
        try:
            content = zf.read(doc).decode("utf-8", errors="replace")
            project.schematic = _extract_schematic(content, doc)
        except Exception as exc:  # pragma: no cover
            project.degradation.append(
                EasyEdaDegradationRecord(
                    record_type="SCHEMATIC_READ_ERROR",
                    document=doc,
                    line_index=0,
                    severity="error",
                    raw=str(exc)[:200],
                )
            )

    # Read PCB JSONL
    pcb_names = [n for n in names if "pcb" in n.lower() and n.endswith(".jsonl")]
    if pcb_names:
        doc = pcb_names[0]
        try:
            content = zf.read(doc).decode("utf-8", errors="replace")
            project.pcb = _extract_pcb(content, doc)
        except Exception as exc:  # pragma: no cover
            project.degradation.append(
                EasyEdaDegradationRecord(
                    record_type="PCB_READ_ERROR",
                    document=doc,
                    line_index=0,
                    severity="error",
                    raw=str(exc)[:200],
                )
            )

    return project
