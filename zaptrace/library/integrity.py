"""Library integrity gate for governed component library (issue #129).

Validates that all committed library entries meet governance gates:
* provenance, classification, pin-map, naming, footprint-proof
* No ungoverned entries (confidence_score < threshold)
* Duplicates and alternates are linked without losing manufacturer identity
* Aggregate coverage report across packages and functions

Public surface
--------------
LibraryIntegrityConfig  – gate thresholds
LibraryPartRecord       – per-part integrity record
LibraryDuplicateGroup   – duplicate/alternate analysis
LibraryIntegrityReport  – aggregate report with coverage by package/function
run_library_integrity_gate – main entry point
build_coverage_report   – package and function coverage
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from zaptrace.library.loader import ComponentSpec, LibraryLoader

LIBRARY_ROOT = Path(__file__).parent.parent.parent / "data" / "library"

# Governance gate thresholds
_MIN_CONFIDENCE_SCORE = 0.5  # Below this is ungoverned
_MIN_HIGH_CONFIDENCE_PCT = 0.70  # At least 70% of library must be high/medium confidence
_MIN_PARTS_GATE = 500  # Minimum unique parts required


@dataclass(frozen=True)
class LibraryIntegrityConfig:
    """Thresholds for the library integrity gate.

    Attributes:
        min_confidence_score: Parts below this are flagged as ungoverned.
        min_library_size:     Minimum number of parts required to pass.
        min_high_confidence_pct: Fraction of parts that must be ≥ medium confidence.
    """

    min_confidence_score: float = _MIN_CONFIDENCE_SCORE
    min_library_size: int = _MIN_PARTS_GATE
    min_high_confidence_pct: float = _MIN_HIGH_CONFIDENCE_PCT

    def to_dict(self) -> dict[str, object]:
        return {
            "min_confidence_score": self.min_confidence_score,
            "min_library_size": self.min_library_size,
            "min_high_confidence_pct": self.min_high_confidence_pct,
        }


DEFAULT_INTEGRITY_CONFIG = LibraryIntegrityConfig()


@dataclass
class LibraryPartRecord:
    """Integrity record for one library part.

    Attributes:
        part_id:          Part identifier.
        category:         Category (e.g. "passive", "power").
        confidence_score: Governance confidence from 0..1.
        confidence_grade: "high", "medium", or "low".
        missing_metadata: Governance fields that are absent.
        is_ungoverned:    True if confidence_score < min_confidence_score.
        duplicate_of:     Part ID of canonical duplicate, or "".
        alternate_for:    Part IDs this part is an alternate for.
    """

    part_id: str
    category: str
    confidence_score: float
    confidence_grade: str
    missing_metadata: list[str]
    is_ungoverned: bool = False
    duplicate_of: str = ""
    alternate_for: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "part_id": self.part_id,
            "category": self.category,
            "confidence_score": self.confidence_score,
            "confidence_grade": self.confidence_grade,
            "missing_metadata": self.missing_metadata,
            "is_ungoverned": self.is_ungoverned,
            "duplicate_of": self.duplicate_of,
            "alternate_for": list(self.alternate_for),
        }


@dataclass
class LibraryDuplicateGroup:
    """A group of duplicate or alternate parts.

    Attributes:
        canonical_id:   The primary part in this group.
        alternate_ids:  Other parts that are alternates or duplicates.
        conflict:       True if the alternates have conflicting manufacturer identities.
    """

    canonical_id: str
    alternate_ids: list[str] = field(default_factory=list)
    conflict: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "alternate_ids": list(self.alternate_ids),
            "conflict": self.conflict,
        }


@dataclass
class LibraryIntegrityReport:
    """Aggregate integrity report for the library.

    Attributes:
        status:                   "pass" | "fail".
        total_parts:              Total unique parts in the library.
        ungoverned_count:         Parts below min_confidence_score.
        high_confidence_count:    Parts with confidence_grade == "high".
        medium_confidence_count:  Parts with confidence_grade == "medium".
        low_confidence_count:     Parts with confidence_grade == "low".
        parts:                    Per-part records (ungoverned parts first).
        duplicate_groups:         Detected duplicate/alternate groups.
        category_counts:          Part counts by category.
        package_coverage:         Packages present in the library.
        integrity_failures:       Blocking failures (non-empty → fail).
        warnings:                 Non-blocking findings.
        report_hash:              Deterministic SHA-256 of the report.
        config:                   Gate configuration.
    """

    status: str
    total_parts: int = 0
    ungoverned_count: int = 0
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0
    parts: list[LibraryPartRecord] = field(default_factory=list)
    duplicate_groups: list[LibraryDuplicateGroup] = field(default_factory=list)
    category_counts: dict[str, int] = field(default_factory=dict)
    package_coverage: list[str] = field(default_factory=list)
    integrity_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_hash: str = ""
    config: LibraryIntegrityConfig = field(default_factory=LibraryIntegrityConfig)

    @property
    def accepted(self) -> bool:
        return self.status == "pass"

    @property
    def high_confidence_pct(self) -> float:
        if self.total_parts == 0:
            return 0.0
        return (self.high_confidence_count + self.medium_confidence_count) / self.total_parts

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "accepted": self.accepted,
            "total_parts": self.total_parts,
            "ungoverned_count": self.ungoverned_count,
            "high_confidence_count": self.high_confidence_count,
            "medium_confidence_count": self.medium_confidence_count,
            "low_confidence_count": self.low_confidence_count,
            "high_confidence_pct": round(self.high_confidence_pct, 4),
            "category_counts": dict(sorted(self.category_counts.items())),
            "package_coverage": sorted(self.package_coverage),
            "integrity_failures": list(self.integrity_failures),
            "warnings": list(self.warnings),
            "duplicate_groups": [d.to_dict() for d in self.duplicate_groups],
            "report_hash": self.report_hash,
            "config": self.config.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_duplicates(specs: list[ComponentSpec]) -> list[LibraryDuplicateGroup]:
    """Detect potential duplicate entries by (mpn, manufacturer) key.

    Parts with identical MPN + manufacturer are candidates for deduplication.
    Parts with same MPN but different manufacturer are flagged as conflicting.
    """
    by_mpn: dict[str, list[ComponentSpec]] = {}
    for spec in specs:
        key = spec.mpn.strip().upper()
        if key:
            by_mpn.setdefault(key, []).append(spec)

    groups: list[LibraryDuplicateGroup] = []
    for _mpn, mpn_specs in by_mpn.items():
        if len(mpn_specs) < 2:
            continue
        # Check for conflicting manufacturer identity
        manufacturers = {s.manufacturer.strip().upper() for s in mpn_specs}
        conflict = len(manufacturers) > 1
        canonical = mpn_specs[0]
        alternates = [s.id for s in mpn_specs[1:]]
        groups.append(LibraryDuplicateGroup(canonical_id=canonical.id, alternate_ids=alternates, conflict=conflict))
    return groups


def _build_report_hash(total: int, ungoverned: int, category_counts: dict[str, int]) -> str:
    payload = {
        "total_parts": total,
        "ungoverned_count": ungoverned,
        "category_counts": dict(sorted(category_counts.items())),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_library_integrity_gate(
    library_root: Path | None = None,
    config: LibraryIntegrityConfig | None = None,
) -> LibraryIntegrityReport:
    """Run the library integrity gate against the committed library.

    Args:
        library_root:  Path to the library root directory.
        config:        Gate thresholds (defaults to DEFAULT_INTEGRITY_CONFIG).

    Returns:
        LibraryIntegrityReport with status "pass" if:
        - total_parts >= min_library_size
        - ungoverned_count == 0 (no entries below min_confidence_score)
        - high_confidence_pct >= min_high_confidence_pct
    """
    cfg = config or DEFAULT_INTEGRITY_CONFIG
    root = library_root or LIBRARY_ROOT

    loader = LibraryLoader(root)
    try:
        components_dict = loader.load_all()
        errors_list = loader._errors
    except Exception as exc:
        return LibraryIntegrityReport(
            status="fail",
            integrity_failures=[f"Library load failed: {exc}"],
            config=cfg,
        )

    specs: list[ComponentSpec] = list(components_dict.values())
    failures: list[str] = []
    warnings: list[str] = []
    part_records: list[LibraryPartRecord] = []
    category_counts: dict[str, int] = {}
    packages: set[str] = set()

    high_count = 0
    med_count = 0
    low_count = 0
    ungoverned_count = 0

    for spec in specs:
        is_ungoverned = spec.confidence_score < cfg.min_confidence_score
        if is_ungoverned:
            ungoverned_count += 1

        if spec.confidence_grade == "high":
            high_count += 1
        elif spec.confidence_grade == "medium":
            med_count += 1
        else:
            low_count += 1

        category_counts[spec.category] = category_counts.get(spec.category, 0) + 1
        if spec.package:
            packages.add(spec.package.strip())

        part_records.append(
            LibraryPartRecord(
                part_id=spec.id,
                category=spec.category,
                confidence_score=spec.confidence_score,
                confidence_grade=spec.confidence_grade,
                missing_metadata=spec.missing_metadata,
                is_ungoverned=is_ungoverned,
            )
        )

    # Sort: ungoverned first
    part_records.sort(key=lambda r: (not r.is_ungoverned, r.part_id))

    duplicate_groups = _detect_duplicates(specs)
    conflicting = [g for g in duplicate_groups if g.conflict]
    if conflicting:
        warnings.append(f"{len(conflicting)} duplicate group(s) with conflicting manufacturer identities")

    total = len(specs)

    # Evaluate gate
    if total < cfg.min_library_size:
        failures.append(f"Library has {total} parts; minimum {cfg.min_library_size} required")

    if ungoverned_count > 0:
        failures.append(f"{ungoverned_count} ungoverned part(s) with confidence < {cfg.min_confidence_score}")

    high_pct = (high_count + med_count) / total if total > 0 else 0.0
    if high_pct < cfg.min_high_confidence_pct:
        failures.append(f"High/medium confidence fraction {high_pct:.1%} < {cfg.min_high_confidence_pct:.1%}")

    # Note load errors as warnings
    for err in errors_list:
        warnings.append(f"Load error: {err.path}: {err.reason}")

    status = "pass" if not failures else "fail"
    report_hash = _build_report_hash(total, ungoverned_count, category_counts)

    return LibraryIntegrityReport(
        status=status,
        total_parts=total,
        ungoverned_count=ungoverned_count,
        high_confidence_count=high_count,
        medium_confidence_count=med_count,
        low_confidence_count=low_count,
        parts=part_records,
        duplicate_groups=duplicate_groups,
        category_counts=category_counts,
        package_coverage=sorted(packages),
        integrity_failures=failures,
        warnings=warnings,
        report_hash=report_hash,
        config=cfg,
    )


def build_coverage_report(
    library_root: Path | None = None,
) -> dict[str, object]:
    """Build a package and function coverage report for the library.

    Returns a dict with:
      - packages: {package_name: count}
      - categories: {category_name: count}
      - total_parts: int
      - packages_with_drc_dfn_lga: int (DFN/LGA/aQFN etc.)
      - has_rf_coverage: bool
      - has_power_coverage: bool
      - has_sensor_coverage: bool
    """
    root = library_root or LIBRARY_ROOT
    loader = LibraryLoader(root)
    try:
        components_dict = loader.load_all()
    except Exception:
        return {"error": "load failed"}

    specs = list(components_dict.values())
    packages: dict[str, int] = {}
    categories: dict[str, int] = {}
    for spec in specs:
        if spec.package:
            packages[spec.package.strip()] = packages.get(spec.package.strip(), 0) + 1
        categories[spec.category] = categories.get(spec.category, 0) + 1

    dfn_lga_count = sum(
        v
        for k, v in packages.items()
        if any(pkg in k.upper() for pkg in ("DFN", "LGA", "AQFN", "WLCSP", "WSON", "UDFN"))
    )

    return {
        "packages": dict(sorted(packages.items())),
        "categories": dict(sorted(categories.items())),
        "total_parts": len(specs),
        "packages_with_drc_dfn_lga": dfn_lga_count,
        "has_rf_coverage": "rf" in categories,
        "has_power_coverage": "power" in categories,
        "has_sensor_coverage": "sensor" in categories,
    }
