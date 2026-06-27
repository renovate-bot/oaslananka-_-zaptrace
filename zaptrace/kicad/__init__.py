"""KiCad integration — export, oracle, and validation support."""

from __future__ import annotations

from .importer import (
    KiCadFidelityReport,
    KiCadImportResult,
    KiCadUnsupportedRecord,
    import_kicad_pcb,
    score_kicad_roundtrip,
)
from .oracle import (
    KiCadDrcItem,
    KiCadDrcResult,
    KiCadErcItem,
    KiCadErcResult,
    KiCadOracle,
    KiCadResult,
    detect_kicad,
    get_kicad_version,
    run_drc,
    run_erc,
)

__all__ = [
    "KiCadImportResult",
    "KiCadUnsupportedRecord",
    "KiCadFidelityReport",
    "import_kicad_pcb",
    "score_kicad_roundtrip",
    "KiCadOracle",
    "KiCadResult",
    "KiCadErcResult",
    "KiCadErcItem",
    "KiCadDrcResult",
    "KiCadDrcItem",
    "detect_kicad",
    "get_kicad_version",
    "run_erc",
    "run_drc",
]
