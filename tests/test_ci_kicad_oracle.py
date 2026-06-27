"""Tests for structured KiCad oracle CI evidence."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import ci_kicad_oracle


def test_oracle_summary_writes_explicit_skipped_status(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("detect", "skipped", "kicad-cli not found on PATH")

    ci_kicad_oracle._write_summary(str(output), status="skipped")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "skipped"
    assert data["skip_reason"] == "kicad-cli not found on PATH"
    assert data["checks"][0]["status"] == "skipped"


def test_oracle_summary_writes_failed_status(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_drc", "failed", "DRC reported violations", errors=1)

    ci_kicad_oracle._write_summary(str(output), status="failed", version="9.0.0", cli_path="/usr/bin/kicad-cli")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "failed"
    assert data["version"] == "9.0.0"
    assert data["checks"][0]["errors"] == 1


def test_oracle_overall_status_fails_if_any_check_failed() -> None:
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_export_svg", "passed", "ok")
    ci_kicad_oracle._record_check("pcb_drc", "failed", "DRC reported violations")
    assert ci_kicad_oracle._overall_status() == "failed"


def test_oracle_overall_status_requires_release_gate_skip_for_partial_skips() -> None:
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("pcb_export_svg", "passed", "ok")
    ci_kicad_oracle._record_check("pcb_drc", "skipped", "kicad-cli lacks pcb drc")
    assert ci_kicad_oracle._overall_status() == "skipped"
