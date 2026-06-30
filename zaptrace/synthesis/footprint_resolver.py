"""Attach real footprint geometry (IPC-7351 pads) to synthesized components.

Synthesis and the repair loop assign footprint *names* ("0402", "SOT-23-5"); the
manufacturing exporters (Gerber, Excellon, DSN) need actual pad geometry
(``Component.footprint_def``) or they emit no copper for that part. This walks a
design and fills in ``footprint_def`` from each component's footprint name via
the IPC-7351 generators in :mod:`zaptrace.ee.footprints`.

Honest: a package with no generator yet — a module land pattern like an ESP32
module, say — is reported as unresolved, not faked. A part with no real pads is a
fabrication blocker, and the report makes it visible instead of shipping empty
copper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.ee.footprint_vendor import resolve_vendored_footprint
from zaptrace.ee.footprints import generate_footprint_for_component

if TYPE_CHECKING:
    from zaptrace.core.models import Design


@dataclass
class FootprintResolution:
    """Which components got real pad geometry, and which could not."""

    resolved: list[str] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)

    @property
    def fully_resolved(self) -> bool:
        return not self.unresolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "fully_resolved": self.fully_resolved,
            "resolved_count": len(self.resolved),
            "unresolved_count": len(self.unresolved),
            "resolved": self.resolved,
            "unresolved": self.unresolved,
        }


def resolve_footprints(design: Design) -> FootprintResolution:
    """Fill ``footprint_def`` for every component from its footprint name, in place.

    A component that already has geometry is left as is. One with a name but no
    generator is recorded in ``unresolved`` (a real, visible fab blocker), never
    given invented pads.
    """
    package_by_mpn = _package_by_mpn()
    result = FootprintResolution()
    for comp in design.components.values():
        if comp.footprint_def is not None:
            result.resolved.append(comp.ref)
            continue
        if not comp.footprint:
            result.unresolved.append(
                {"ref": comp.ref, "footprint": "", "type": comp.type, "reason": "no footprint name to resolve from"}
            )
            continue
        # Try the part-specific footprint name first; fall back to its standard
        # package (e.g. "LQFP-48") when the custom name has no generator.
        footprint_def = generate_footprint_for_component(comp.footprint, comp.type)
        if footprint_def is None and comp.mpn:
            package = package_by_mpn.get(comp.mpn)
            if package:
                footprint_def = generate_footprint_for_component(package, comp.type)
        # Packages with no parametric generator (modules, DFN/LGA/aQFN, magjacks)
        # fall back to a verified vendored KiCad land pattern keyed by name.
        if footprint_def is None:
            footprint_def = resolve_vendored_footprint(comp.footprint)
        if footprint_def is not None:
            comp.footprint_def = footprint_def
            result.resolved.append(comp.ref)
        else:
            result.unresolved.append(
                {
                    "ref": comp.ref,
                    "footprint": comp.footprint,
                    "type": comp.type,
                    "reason": "no IPC-7351 generator for this package yet",
                }
            )
    return result


def _package_by_mpn() -> dict[str, str]:
    """Map each library part's MPN to its standard package name, for fallback."""
    from zaptrace.library.loader import LibraryLoader

    return {spec.mpn: spec.package for spec in LibraryLoader().load_all().values() if spec.mpn and spec.package}
