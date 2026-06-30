"""Footprint proof schema and builders.

A footprint proof is machine-readable evidence that records where a land pattern
came from and what geometric/pin-mapping assumptions it carries. Validation of
those proofs is implemented by later gates; this module defines the contract.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zaptrace import __version__
from zaptrace.core.models import FootprintDef, Pad


class FootprintSourceType(StrEnum):
    GENERATED = "generated"
    VENDORED = "vendored"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


class FootprintSourceProvenance(BaseModel):
    """Source provenance for a footprint proof."""

    model_config = ConfigDict(strict=False)

    source_type: FootprintSourceType
    source_name: str = ""
    source_path: str = ""
    source_sha256: str = ""
    generator: str = ""
    generator_version: str = ""
    attribution: str = ""


class FootprintPadProof(BaseModel):
    """Pad geometry evidence captured from a FootprintDef."""

    model_config = ConfigDict(strict=False)

    pad_id: str
    layer: str
    shape: str
    position_mm: tuple[float, float]
    size_mm: tuple[float, float]
    drill_mm: float | None = None
    plated: bool = True
    solder_paste: bool = True
    solder_mask: bool = True


class FootprintPin1Evidence(BaseModel):
    """Evidence that identifies pin/pad 1 orientation in the footprint."""

    present: bool = False
    pad_id: str = ""
    method: str = ""
    message: str = ""


class FootprintProof(BaseModel):
    """Proof schema for generated/imported/vendored footprints."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    package_id: str
    footprint_name: str
    source: FootprintSourceProvenance
    pad_count: int = Field(ge=0)
    pin_count: int = Field(ge=0)
    pin_map: dict[str, str] = Field(description="Pin name/id -> pad id mapping")
    pads: list[FootprintPadProof]
    courtyard_mm: tuple[float, float]
    paste_enabled_pad_count: int = Field(ge=0)
    paste_disabled_pad_count: int = Field(ge=0)
    solder_mask_policy: str = "mask opening assumed for all pads unless explicitly modeled"
    thermal_pads: list[str] = Field(default_factory=list)
    pin1: FootprintPin1Evidence = Field(default_factory=FootprintPin1Evidence)
    notes: list[str] = Field(default_factory=list)


def file_sha256(path: str | Path) -> str:
    """Return SHA-256 for a footprint source file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pad_to_proof(pad: Pad) -> FootprintPadProof:
    return FootprintPadProof(
        pad_id=pad.id,
        layer=pad.layer.value,
        shape=pad.shape.value,
        position_mm=pad.position,
        size_mm=pad.size,
        drill_mm=pad.drill,
        plated=pad.plated,
        solder_paste=pad.solder_paste,
        solder_mask=True,
    )


def _pin1_evidence(pads: list[Pad]) -> FootprintPin1Evidence:
    ids = {pad.id for pad in pads}
    for candidate in ("1", "A1", "P1"):
        if candidate in ids:
            return FootprintPin1Evidence(
                present=True,
                pad_id=candidate,
                method="explicit-pad-id",
                message=f"Pin-1 evidence found via pad id {candidate}",
            )
    return FootprintPin1Evidence(
        present=False,
        method="not-found",
        message="No explicit pin-1 pad id found",
    )


def _default_source(
    source_type: FootprintSourceType, source_name: str, source_path: str = ""
) -> FootprintSourceProvenance:
    digest = file_sha256(source_path) if source_path and Path(source_path).exists() else ""
    return FootprintSourceProvenance(
        source_type=source_type,
        source_name=source_name,
        source_path=source_path,
        source_sha256=digest,
        generator="zaptrace.ee.footprints" if source_type == FootprintSourceType.GENERATED else "",
        generator_version=__version__ if source_type == FootprintSourceType.GENERATED else "",
    )


def build_footprint_proof(
    package_id: str,
    footprint: FootprintDef,
    *,
    footprint_name: str = "",
    source: FootprintSourceProvenance | None = None,
    source_type: FootprintSourceType = FootprintSourceType.GENERATED,
    source_path: str = "",
    expected_pin_count: int | None = None,
    pin_map: dict[str, str] | None = None,
) -> FootprintProof:
    """Build a footprint proof from a FootprintDef."""
    resolved_source = source or _default_source(source_type, footprint.source or package_id, source_path)
    mapping = pin_map or {pad.id: pad.id for pad in footprint.pads}
    pin_count = expected_pin_count if expected_pin_count is not None else len(mapping)
    paste_enabled = sum(1 for pad in footprint.pads if pad.solder_paste)
    paste_disabled = len(footprint.pads) - paste_enabled
    notes: list[str] = []
    if not footprint.courtyard or footprint.courtyard == (0.0, 0.0):
        notes.append("courtyard is missing or zero-sized")
    return FootprintProof(
        package_id=package_id,
        footprint_name=footprint_name or footprint.description or package_id,
        source=resolved_source,
        pad_count=len(footprint.pads),
        pin_count=pin_count,
        pin_map=mapping,
        pads=[_pad_to_proof(pad) for pad in footprint.pads],
        courtyard_mm=footprint.courtyard,
        paste_enabled_pad_count=paste_enabled,
        paste_disabled_pad_count=paste_disabled,
        thermal_pads=footprint.thermal_pads or [],
        pin1=_pin1_evidence(footprint.pads),
        notes=notes,
    )


def write_footprint_proof(proof: FootprintProof, output_path: str | Path) -> Path:
    """Write a footprint proof JSON artifact."""
    out = Path(output_path)
    if out.suffix.lower() != ".json":
        raise ValueError(f"unexpected footprint proof suffix: {out.suffix}")
    resolved = out.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.path-traversal.path-traversal-write
    resolved.write_text(proof.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return resolved
