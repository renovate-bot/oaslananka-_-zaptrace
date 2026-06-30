"""Heuristic engineering analysis report APIs."""

from __future__ import annotations

from zaptrace.analysis.diffpair import (
    DiffPairLengthReport,
    build_diffpair_length_report,
    write_diffpair_length_report,
)
from zaptrace.analysis.reports import (
    AnalysisFinding,
    ElectricalAnalysisReport,
    build_analysis_proof_artifacts,
    generate_electrical_analysis_report,
    render_analysis_markdown,
    run_analysis,
)
from zaptrace.analysis.signal_integrity import (
    ImpedanceReturnPathReport,
    build_impedance_return_path_report,
)

__all__ = [
    "DiffPairLengthReport",
    "build_diffpair_length_report",
    "write_diffpair_length_report",
    "ImpedanceReturnPathReport",
    "build_impedance_return_path_report",
    "AnalysisFinding",
    "ElectricalAnalysisReport",
    "build_analysis_proof_artifacts",
    "generate_electrical_analysis_report",
    "render_analysis_markdown",
    "run_analysis",
]
