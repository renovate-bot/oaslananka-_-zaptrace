"""Heuristic engineering analysis report APIs."""

from __future__ import annotations

from zaptrace.analysis.current_density import (
    CurrentDensityReport,
    build_current_density_report,
)
from zaptrace.analysis.diffpair import (
    DiffPairLengthReport,
    build_diffpair_length_report,
    write_diffpair_length_report,
)
from zaptrace.analysis.rail_current import (
    RailCurrentBudgetReport,
    build_rail_current_budget_report,
)
from zaptrace.analysis.regulator_margin import (
    RegulatorMarginReport,
    build_regulator_margin_report,
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
from zaptrace.analysis.sipi_risk import (
    SipiRiskReport,
    build_sipi_risk_report,
)

__all__ = [
    "CurrentDensityReport",
    "build_current_density_report",
    "DiffPairLengthReport",
    "build_diffpair_length_report",
    "write_diffpair_length_report",
    "RailCurrentBudgetReport",
    "build_rail_current_budget_report",
    "RegulatorMarginReport",
    "build_regulator_margin_report",
    "SipiRiskReport",
    "build_sipi_risk_report",
    "ImpedanceReturnPathReport",
    "build_impedance_return_path_report",
    "AnalysisFinding",
    "ElectricalAnalysisReport",
    "build_analysis_proof_artifacts",
    "generate_electrical_analysis_report",
    "render_analysis_markdown",
    "run_analysis",
]
