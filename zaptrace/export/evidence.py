"""Manufacturing evidence adapters for generated fabrication artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.fab.dfm import DFMCheckResult


class ManufacturingArtifactKind(StrEnum):
    GERBER = "gerber"
    EXCELLON = "excellon"
    ODBPP = "odbpp"
    IPC2581 = "ipc2581"
    BOM = "bom"
    PICK_AND_PLACE = "pick_and_place"
    STACKUP = "stackup"
    MANIFEST = "manifest"
    BUNDLE = "bundle"
    OTHER = "other"


class ManufacturingValidationStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIPPED = "skipped"


class ManufacturingArtifactEvidence(BaseModel):
    """Hashed manufacturing artifact record."""

    model_config = ConfigDict(strict=False)

    path: str
    kind: ManufacturingArtifactKind
    size_bytes: int = Field(ge=0)
    sha256: str
    role: str = ""
    required: bool = True


class ManufacturingValidationEvidence(BaseModel):
    """Smoke/parser/profile validation result for manufacturing evidence."""

    model_config = ConfigDict(strict=False)

    name: str
    status: ManufacturingValidationStatus
    severity: str = "error"
    release_blocking: bool = True
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def blocks_release(self) -> bool:
        return self.release_blocking and self.status == ManufacturingValidationStatus.FAIL


class ManufacturingEvidenceBundle(BaseModel):
    """Machine-readable manufacturing evidence bundle."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    generated_at: str
    fab_profile: str
    blocked: bool
    artifacts: list[ManufacturingArtifactEvidence]
    validations: list[ManufacturingValidationEvidence]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "Manufacturing evidence is not manufacturer approval.",
            "External fabrication review is required before ordering boards.",
            "Smoke validation checks file shape, not full DFM correctness.",
        ]
    )


class ManufacturingEvidenceAdapter(Protocol):
    """Adapter interface for manufacturing evidence collection."""

    name: str

    def collect(self, root: Path, *, fab_profile: str = "") -> ManufacturingEvidenceBundle:
        """Collect evidence for artifacts under *root*."""
        ...


_GERBER_SUFFIXES = {".GTL", ".GBL", ".GTO", ".GTS", ".GBS", ".GKO", ".GPT", ".GTP", ".GBP"}
_EXCELLON_SUFFIXES = {".DRL", ".TXT", ".XLN"}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_manufacturing_artifact(path: Path) -> ManufacturingArtifactKind:
    suffix = path.suffix.upper()
    lower_name = path.name.lower()
    if suffix in _GERBER_SUFFIXES:
        return ManufacturingArtifactKind.GERBER
    if suffix in _EXCELLON_SUFFIXES:
        return ManufacturingArtifactKind.EXCELLON
    if suffix == ".CSV" and "pick" in lower_name:
        return ManufacturingArtifactKind.PICK_AND_PLACE
    if suffix == ".CSV" and "bom" in lower_name:
        return ManufacturingArtifactKind.BOM
    if suffix == ".JSON" and "manifest" in lower_name:
        return ManufacturingArtifactKind.MANIFEST
    if suffix == ".ZIP":
        return ManufacturingArtifactKind.BUNDLE
    if suffix in {".ODB", ".ODBPP", ".TGZ"} or "odb" in lower_name:
        return ManufacturingArtifactKind.ODBPP
    if suffix in {".IPC2581", ".XML"} and ("ipc" in lower_name or "2581" in lower_name):
        return ManufacturingArtifactKind.IPC2581
    if "stackup" in lower_name:
        return ManufacturingArtifactKind.STACKUP
    return ManufacturingArtifactKind.OTHER


def build_artifact_evidence(path: Path, *, root: Path) -> ManufacturingArtifactEvidence:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError:
        relative = resolved
    return ManufacturingArtifactEvidence(
        path=relative.as_posix(),
        kind=classify_manufacturing_artifact(path),
        size_bytes=path.stat().st_size,
        sha256=hash_file(path),
        role=path.suffix.lstrip(".").lower(),
    )


def smoke_validate_gerber(path: Path) -> ManufacturingValidationEvidence:
    text = path.read_text(encoding="utf-8", errors="replace")
    required_tokens = ["MOMM", "FSLAX", "M02*"]
    missing = [token for token in required_tokens if token not in text]
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"gerber-smoke:{path.name}",
        status=status,
        summary="Gerber smoke validation passed" if not missing else "Gerber file is missing required tokens",
        details={"missing_tokens": missing, "size_bytes": path.stat().st_size},
    )


def smoke_validate_excellon(path: Path) -> ManufacturingValidationEvidence:
    text = path.read_text(encoding="utf-8", errors="replace")
    required_tokens = ["M48", "M30"]
    missing = [token for token in required_tokens if token not in text]
    status = ManufacturingValidationStatus.FAIL if missing else ManufacturingValidationStatus.PASS
    return ManufacturingValidationEvidence(
        name=f"excellon-smoke:{path.name}",
        status=status,
        summary="Excellon smoke validation passed" if not missing else "Excellon file is missing required tokens",
        details={"missing_tokens": missing, "size_bytes": path.stat().st_size},
    )


def validation_from_dfm_result(result: DFMCheckResult) -> ManufacturingValidationEvidence:
    if result.errors:
        status = ManufacturingValidationStatus.FAIL
        summary = f"Fab profile {result.profile_name} has {result.errors} blocking error(s)"
    elif result.warnings:
        status = ManufacturingValidationStatus.WARNING
        summary = f"Fab profile {result.profile_name} has {result.warnings} warning(s)"
    else:
        status = ManufacturingValidationStatus.PASS
        summary = f"Fab profile {result.profile_name} passed"
    return ManufacturingValidationEvidence(
        name="fab-profile-dfm",
        status=status,
        severity="error" if result.errors else "warning",
        release_blocking=True,
        summary=summary,
        details=result.to_dict(),
    )


class DirectoryManufacturingEvidenceAdapter:
    """Collect evidence by scanning a manufacturing output directory."""

    name = "directory-manufacturing-evidence"

    def collect(
        self,
        root: Path,
        *,
        fab_profile: str = "",
        dfm_result: DFMCheckResult | None = None,
    ) -> ManufacturingEvidenceBundle:
        artifacts: list[ManufacturingArtifactEvidence] = []
        validations: list[ManufacturingValidationEvidence] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            artifact = build_artifact_evidence(path, root=root)
            artifacts.append(artifact)
            if artifact.kind == ManufacturingArtifactKind.GERBER:
                validations.append(smoke_validate_gerber(path))
            elif artifact.kind == ManufacturingArtifactKind.EXCELLON:
                validations.append(smoke_validate_excellon(path))
        if dfm_result is not None:
            validations.append(validation_from_dfm_result(dfm_result))
        blocked = any(validation.blocks_release for validation in validations)
        return ManufacturingEvidenceBundle(
            generated_at=datetime.now(UTC).isoformat(),
            fab_profile=fab_profile or (dfm_result.profile_name if dfm_result else ""),
            blocked=blocked,
            artifacts=artifacts,
            validations=validations,
        )


def collect_manufacturing_evidence(
    root: str | Path,
    *,
    fab_profile: str = "",
    dfm_result: DFMCheckResult | None = None,
) -> ManufacturingEvidenceBundle:
    adapter = DirectoryManufacturingEvidenceAdapter()
    return adapter.collect(Path(root), fab_profile=fab_profile, dfm_result=dfm_result)
