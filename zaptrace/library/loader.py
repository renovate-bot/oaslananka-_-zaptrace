from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from zaptrace.core.exceptions import LibraryError

LIBRARY_ROOT = Path(__file__).parent.parent.parent / "data" / "library"


# Governance-critical metadata fields and their weight in the confidence
# score. A part is only as trustworthy as the data ERC/BOM/DFM can rely on:
# an exact MPN + datasheet make it sourceable and verifiable; a footprint and
# pin map make it placeable and checkable. Weights sum to 1.0 so the score is a
# 0..1 fraction. (Source: "library confidence score".)
_GOVERNANCE_FIELDS: tuple[tuple[str, float], ...] = (
    ("mpn", 0.20),
    ("datasheet", 0.20),
    ("manufacturer", 0.15),
    ("footprint", 0.15),
    ("pins", 0.15),
    ("package", 0.10),
    ("description", 0.05),
)


@dataclass
class ComponentSpec:
    id: str
    name: str
    category: str
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    datasheet: str = ""
    package: str = ""
    footprint: str = ""
    lifecycle: str = "active"
    voltage_supply: str = ""
    pins: dict[str, dict[str, str]] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)

    def _has_field(self, name: str) -> bool:
        value = getattr(self, name)
        return bool(value)  # empty string / empty dict both count as absent

    @property
    def missing_metadata(self) -> list[str]:
        """Governance-critical fields that are absent, worst-first by weight."""
        return [name for name, _ in _GOVERNANCE_FIELDS if not self._has_field(name)]

    @property
    def confidence_score(self) -> float:
        """0..1 fraction of weighted governance metadata that is populated.

        1.0 means every field ERC/BOM/DFM needs is present; a low score flags a
        part that should not be trusted for sourcing or verification yet.
        """
        return round(sum(weight for name, weight in _GOVERNANCE_FIELDS if self._has_field(name)), 3)

    @property
    def confidence_grade(self) -> str:
        score = self.confidence_score
        if score >= 0.85:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"


@dataclass(frozen=True)
class LibraryLoadError:
    """A single component file that could not be loaded, and why."""

    path: str
    reason: str


_REQUIRED_FIELDS = ("id", "name", "category")


class LibraryLoader:
    def __init__(self, library_root: Path = LIBRARY_ROOT) -> None:
        self._root = library_root
        self._cache: dict[str, ComponentSpec] | None = None
        self._errors: list[LibraryLoadError] = []

    def load_all(self) -> dict[str, ComponentSpec]:
        if self._cache is not None:
            return self._cache
        result: dict[str, ComponentSpec] = {}
        errors: list[LibraryLoadError] = []
        if not self._root.exists():
            self._errors = errors
            return result
        valid_keys = set(ComponentSpec.__dataclass_fields__)
        # Sorted for deterministic ordering (reproducibility, stable duplicate
        # resolution). One bad file is recorded and skipped, never silently
        # dropped and never fatal to the rest of the library.
        for yaml_file in sorted(self._root.rglob("*.yaml")):
            rel = yaml_file.relative_to(self._root).as_posix()
            try:
                raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError) as exc:
                errors.append(LibraryLoadError(rel, f"could not parse YAML: {exc}"))
                continue
            if not isinstance(raw, dict):
                errors.append(LibraryLoadError(rel, "top-level YAML is not a component mapping"))
                continue
            missing = [name for name in _REQUIRED_FIELDS if not raw.get(name)]
            if missing:
                errors.append(LibraryLoadError(rel, f"missing required field(s): {', '.join(missing)}"))
                continue
            # Required fields are validated above and keys are filtered to the
            # dataclass fields, so construction cannot raise here.
            spec = ComponentSpec(**{k: v for k, v in raw.items() if k in valid_keys})
            if spec.id in result:
                errors.append(LibraryLoadError(rel, f"duplicate component id '{spec.id}' (keeping first occurrence)"))
                continue
            result[spec.id] = spec
        self._cache = result
        self._errors = errors
        return result

    def load_errors(self) -> list[LibraryLoadError]:
        """Per-file load failures from the most recent :meth:`load_all`.

        Surfacing these (instead of silently dropping malformed parts) is what
        makes the library loader verification-first: a part that fails to load
        is visible, not invisibly missing.
        """
        self.load_all()
        return list(self._errors)

    def get(self, component_id: str) -> ComponentSpec:
        specs = self.load_all()
        if component_id not in specs:
            available = sorted(specs.keys())[:10]
            raise LibraryError(f"Component '{component_id}' not found. Similar: {available}")
        return specs[component_id]

    def search(self, query: str, max_results: int = 10) -> list[ComponentSpec]:
        specs = self.load_all()
        query_words = query.lower().split()

        def score(spec: ComponentSpec) -> int:
            text = " ".join(
                [
                    spec.id,
                    spec.name,
                    spec.description,
                    spec.mpn,
                    spec.category,
                    spec.manufacturer,
                ]
            ).lower()
            return sum(1 for word in query_words if word in text)

        scored = [(score(s), s) for s in specs.values()]
        scored = [(sc, s) for sc, s in scored if sc > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:max_results]]

    def list_categories(self) -> list[str]:
        return sorted({s.category for s in self.load_all().values()})

    def confidence_report(self) -> list[dict[str, Any]]:
        """Per-component governance confidence, worst-documented parts first.

        Surfaces which library parts lack the metadata ERC/BOM/DFM depend on so
        governance gaps are visible and actionable rather than implicit.
        """
        specs = self.load_all()
        report = [
            {
                "id": spec.id,
                "confidence_score": spec.confidence_score,
                "confidence_grade": spec.confidence_grade,
                "missing_metadata": spec.missing_metadata,
            }
            for spec in specs.values()
        ]
        report.sort(key=lambda row: (row["confidence_score"], row["id"]))
        return report

    def mean_confidence(self) -> float:
        """Mean governance confidence across the library (0..1), 0.0 if empty."""
        specs = self.load_all()
        if not specs:
            return 0.0
        return round(sum(s.confidence_score for s in specs.values()) / len(specs), 3)
