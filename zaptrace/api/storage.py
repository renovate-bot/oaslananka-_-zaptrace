"""Configurable REST artifact storage and lifecycle helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("-", value.strip()).strip(".-_")
    return cleaned[:128] or fallback


def _artifact_root() -> Path:
    return Path(os.environ.get("ZAPTRACE_API_ARTIFACT_ROOT", ".zaptrace/api-artifacts")).resolve()


def _safe_session_segment(value: str) -> str:
    """Map a session selector to a collision-resistant filesystem segment."""
    raw = value.strip()
    cleaned = _safe_segment(raw, fallback="session")
    if raw == cleaned and len(raw) <= 128:
        return cleaned
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{cleaned[:111]}-{digest}"


def _retention_seconds() -> int:
    raw = os.environ.get("ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS", "86400")
    try:
        return max(0, int(raw))
    except ValueError:
        return 86400


def _max_artifact_bytes() -> int:
    raw = os.environ.get("ZAPTRACE_API_MAX_ARTIFACT_BYTES", str(5 * 1024 * 1024))
    try:
        return max(1, int(raw))
    except ValueError:
        return 5 * 1024 * 1024


class ArtifactRecord(BaseModel):
    """Stored REST artifact metadata with deterministic naming and provenance."""

    model_config = ConfigDict(strict=False)

    session_id: str
    owner_principal: str = ""
    artifact_id: str
    kind: str
    filename: str
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    created_at: str
    retention_seconds: int = Field(ge=0)


class ArtifactCreateRequest(BaseModel):
    """Request body for registering a REST artifact."""

    filename: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="generic", min_length=1, max_length=64)
    content: str = Field(default="", description="UTF-8 artifact content for deterministic REST storage tests")


class ArtifactStore:
    """Small filesystem-backed artifact store for REST/API lifecycle control."""

    def __init__(
        self, *, root: Path | None = None, retention_seconds: int | None = None, max_bytes: int | None = None
    ) -> None:
        self.root = root or _artifact_root()
        self.retention_seconds = _retention_seconds() if retention_seconds is None else retention_seconds
        self.max_bytes = _max_artifact_bytes() if max_bytes is None else max_bytes

    def _session_dir(self, session_id: str) -> Path:
        return self.root / _safe_session_segment(session_id)

    def store_text(
        self,
        session_id: str,
        *,
        filename: str,
        kind: str,
        content: str,
        owner_principal: str = "",
    ) -> ArtifactRecord:
        payload = content.encode("utf-8")
        if len(payload) > self.max_bytes:
            raise ValueError(f"artifact exceeds {self.max_bytes} byte limit")
        safe_filename = _safe_segment(filename, fallback="artifact.txt")
        safe_kind = _safe_segment(kind, fallback="generic")
        digest = hashlib.sha256(payload).hexdigest()
        artifact_id = f"{digest[:16]}-{safe_filename}"
        artifact_dir = self._session_dir(session_id) / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / safe_filename
        artifact_path.write_bytes(payload)
        record = ArtifactRecord(
            session_id=session_id,
            owner_principal=owner_principal,
            artifact_id=artifact_id,
            kind=safe_kind,
            filename=safe_filename,
            path=str(artifact_path.relative_to(self.root)),
            sha256=digest,
            size_bytes=len(payload),
            created_at=_utc_now().isoformat(),
            retention_seconds=self.retention_seconds,
        )
        (artifact_dir / "manifest.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return record

    def _read_manifest(self, manifest_path: Path) -> ArtifactRecord | None:
        try:
            return ArtifactRecord.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list_artifacts(self, session_id: str) -> list[ArtifactRecord]:
        session_dir = self._session_dir(session_id)
        records: list[ArtifactRecord] = []
        for manifest_path in sorted(session_dir.glob("*/manifest.json")):
            record = self._read_manifest(manifest_path)
            if record is not None and record.session_id == session_id:
                records.append(record)
        return records

    def delete_artifact(self, session_id: str, artifact_id: str) -> ArtifactRecord | None:
        safe_id = _safe_segment(artifact_id, fallback="artifact")
        artifact_dir = self._session_dir(session_id) / safe_id
        record = self._read_manifest(artifact_dir / "manifest.json")
        if record is None or record.session_id != session_id:
            return None
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        return record

    def cleanup_expired(self, *, session_id: str | None = None, now: datetime | None = None) -> list[ArtifactRecord]:
        current = now or _utc_now()
        deleted: list[ArtifactRecord] = []
        expected_session_segment = _safe_session_segment(session_id) if session_id is not None else None
        for manifest_path in sorted(self.root.glob("*/*/manifest.json")):
            if expected_session_segment is not None and manifest_path.parent.parent.name != expected_session_segment:
                continue
            record = self._read_manifest(manifest_path)
            if record is None or (session_id is not None and record.session_id != session_id):
                continue
            try:
                created = datetime.fromisoformat(record.created_at)
            except ValueError:
                created = current
            age = (current - created).total_seconds()
            if age >= record.retention_seconds:
                artifact_dir = manifest_path.parent
                shutil.rmtree(artifact_dir, ignore_errors=True)
                deleted.append(record)
        return deleted

    def config(self) -> dict[str, Any]:
        return {
            "artifact_root": str(self.root),
            "retention_seconds": self.retention_seconds,
            "max_artifact_bytes": self.max_bytes,
        }
