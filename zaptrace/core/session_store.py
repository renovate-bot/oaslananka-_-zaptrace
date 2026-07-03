"""Optional filesystem-backed session design persistence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from zaptrace.core.models import Design
from zaptrace.core.state import design_state_hash

_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def session_store_root() -> Path | None:
    raw = os.environ.get("ZAPTRACE_SESSION_STORE_ROOT", "").strip()
    return Path(raw).resolve() if raw else None


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_RE.sub("-", value.strip()).strip(".-_")
    return cleaned[:128] or fallback


class SessionDesignStore:
    """Filesystem store for versioned design state per session."""

    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root
        self.session_id = session_id
        self.session_dir = self.root / _safe_segment(session_id, fallback="session") / "designs"

    def load_designs(self) -> dict[str, Design]:
        designs: dict[str, Design] = {}
        for current_path in sorted(self.session_dir.glob("*/current.json")):
            try:
                design = Design.model_validate_json(current_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            designs[design.meta.name] = design
        return designs

    def write_design(self, design_name: str, design: Design) -> dict[str, Any]:
        safe_name = _safe_segment(design_name, fallback="design")
        design_dir = self.session_dir / safe_name
        versions_dir = design_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        payload = design.model_dump_json(indent=2) + "\n"
        state_hash = design_state_hash(design)
        version_path = versions_dir / f"{state_hash}.json"
        version_path.write_text(payload, encoding="utf-8")
        current_path = design_dir / "current.json"
        current_path.write_text(payload, encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "design_name": design_name,
            "state_hash": state_hash,
            "current_path": str(current_path.relative_to(self.root)),
            "version_path": str(version_path.relative_to(self.root)),
        }
        (design_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
