"""Optional filesystem-backed session design persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from zaptrace.core.models import Design
from zaptrace.core.state import design_state_hash

_SESSIONS_DIR = "sessions"
_SESSION_MANIFEST = "session.json"
_DESIGNS_DIR = "designs"
_DESIGN_MANIFEST = "manifest.json"
_CURRENT_FILE = "current.json"
_VERSIONS_DIR = "versions"


def session_store_root() -> Path | None:
    raw = os.environ.get("ZAPTRACE_SESSION_STORE_ROOT", "").strip()
    return Path(raw).resolve() if raw else None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


class SessionDesignStore:
    """Filesystem store using opaque server-generated path components only."""

    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self.sessions_root = self.root / _SESSIONS_DIR
        self.session_root = self._locate_or_create_session_root()
        self.session_dir = self.session_root / _DESIGNS_DIR

    def _iter_session_manifests(self) -> list[Path]:
        if not self.sessions_root.is_dir():
            return []
        canonical_root = self.sessions_root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.sessions_root.glob(f"*/{_SESSION_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved.parent.parent != canonical_root:
                continue
            manifests.append(resolved)
        return manifests

    def _iter_legacy_design_manifests(self) -> list[Path]:
        """Discover manifests from the pre-opaque session/design layout."""
        if not self.root.is_dir():
            return []
        canonical_root = self.root.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.root.glob(f"*/{_DESIGNS_DIR}/*/{_DESIGN_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if len(relative.parts) != 4 or relative.parts[1] != _DESIGNS_DIR:
                continue
            manifests.append(resolved)
        return manifests

    def _locate_or_create_session_root(self) -> Path:
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        for manifest_path in self._iter_session_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("session_id") == self.session_id:
                return manifest_path.parent

        for manifest_path in self._iter_legacy_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("session_id") == self.session_id:
                return manifest_path.parents[2]

        for _attempt in range(8):
            storage_id = f"session-{token_urlsafe(24)}"
            session_root = self.sessions_root / storage_id
            try:
                session_root.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            (session_root / _SESSION_MANIFEST).write_text(
                json.dumps({"schema_version": "1.0", "session_id": self.session_id}, indent=2) + "\n",
                encoding="utf-8",
            )
            return session_root
        raise RuntimeError("could not allocate a unique session storage directory")

    def _iter_design_manifests(self) -> list[Path]:
        if not self.session_dir.is_dir():
            return []
        canonical_root = self.session_dir.resolve()
        manifests: list[Path] = []
        for candidate in sorted(self.session_dir.glob(f"*/{_DESIGN_MANIFEST}")):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(canonical_root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if resolved.parent.parent != canonical_root:
                continue
            manifests.append(resolved)
        return manifests

    def _locate_or_create_design_dir(self, design_name: str) -> Path:
        for manifest_path in self._iter_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is not None and manifest.get("design_name") == design_name:
                return manifest_path.parent

        self.session_dir.mkdir(parents=True, exist_ok=True)
        for _attempt in range(8):
            storage_id = f"design-{token_urlsafe(24)}"
            design_dir = self.session_dir / storage_id
            try:
                design_dir.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return design_dir
        raise RuntimeError("could not allocate a unique design storage directory")

    def load_designs(self) -> dict[str, Design]:
        designs: dict[str, Design] = {}
        for manifest_path in self._iter_design_manifests():
            manifest = _read_json_object(manifest_path)
            if manifest is None:
                continue
            design_name = manifest.get("design_name")
            if not isinstance(design_name, str) or not design_name:
                continue
            current_path = manifest_path.parent / _CURRENT_FILE
            try:
                design = Design.model_validate_json(current_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            designs[design_name] = design
        return designs

    def write_design(self, design_name: str, design: Design) -> dict[str, Any]:
        design_dir = self._locate_or_create_design_dir(design_name)
        versions_dir = design_dir / _VERSIONS_DIR
        versions_dir.mkdir(parents=True, exist_ok=True)
        payload = design.model_dump_json(indent=2) + "\n"
        state_hash = design_state_hash(design)
        version_path = versions_dir / f"version-{token_urlsafe(24)}.json"
        version_path.write_text(payload, encoding="utf-8")
        current_path = design_dir / _CURRENT_FILE
        current_path.write_text(payload, encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "design_name": design_name,
            "state_hash": state_hash,
            "current_path": str(current_path.relative_to(self.root)),
            "version_path": str(version_path.relative_to(self.root)),
        }
        (design_dir / _DESIGN_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest


class PersistentDesignDict(dict[str, Design]):
    """Dictionary that persists design assignments into ``SessionDesignStore``."""

    def __init__(self, store: SessionDesignStore, initial: dict[str, Design] | None = None) -> None:
        super().__init__(initial or {})
        self.store = store

    def __setitem__(self, key: str, value: Design) -> None:
        super().__setitem__(key, value)
        self.store.write_design(key, value)

    def persist(self, key: str) -> None:
        if key in self:
            self.store.write_design(key, self[key])


def make_design_mapping(session_id: str) -> dict[str, Design]:
    root = session_store_root()
    if root is None:
        return {}
    store = SessionDesignStore(root, session_id)
    return PersistentDesignDict(store, store.load_designs())
