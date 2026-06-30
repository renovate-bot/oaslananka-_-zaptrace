"""Verified vendored land patterns for packages with no parametric generator.

Module / DFN / LGA / aQFN / magjack packages cannot be produced by the IPC-7351
generators in :mod:`zaptrace.ee.footprints`, so their geometry is sourced from
peer-reviewed, datasheet-derived KiCad land patterns vendored under
``data/footprints/vendor/`` (see that directory's ``ATTRIBUTION.md`` for license
and provenance). Sourcing verified files — rather than transcribing pad
coordinates from a datasheet by hand — is what keeps this safe: a single wrong
coordinate would be a fabrication hazard.

:data:`VENDOR_FOOTPRINTS` is the only trusted-by-name surface: a synthesis
footprint name resolves to a vendored file only via an explicit entry here.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from zaptrace.kicad.importer import load_kicad_footprint

if TYPE_CHECKING:
    from zaptrace.core.models import FootprintDef

_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "footprints" / "vendor"

# Synthesis footprint name -> vendored .kicad_mod file. Each entry pairs a
# library part's footprint name with the verified land pattern for its package.
VENDOR_FOOTPRINTS: dict[str, str] = {
    "BME280-LGA8": "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod",
    "SHT31-DIS-DFN8": "Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod",
    "nRF52840-QIAA": "Nordic_AQFN-73-1EP_7x7mm_P0.5mm.kicad_mod",
    "RJ45-8P8C-SHIELDED": "RJ45_Hanrun_HR911105A_Horizontal.kicad_mod",
    "ESP32-C3-MINI-1": "ESP32-C3-MINI-1.kicad_mod",
}


@cache
def _load_cached(filename: str) -> FootprintDef | None:
    path = _VENDOR_DIR / filename
    if not path.exists():
        return None
    return load_kicad_footprint(path)


def resolve_vendored_footprint(name: str) -> FootprintDef | None:
    """Return the verified land pattern registered for *name*, or ``None``.

    A fresh copy is returned each call so callers may attach and mutate it on a
    component without disturbing the cached parse.
    """
    filename = VENDOR_FOOTPRINTS.get(name)
    if filename is None:
        return None
    footprint = _load_cached(filename)
    return footprint.model_copy(deep=True) if footprint is not None else None
