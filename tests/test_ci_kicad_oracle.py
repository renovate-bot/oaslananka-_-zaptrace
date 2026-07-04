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
    assert data["kicad_oracle"] == "skip-unapproved"
    assert data["raw_status"] == "skipped"
    assert data["skip_approval_id"] == ""
    assert data["skip_reason"] == "kicad-cli not found on PATH"
    assert data["checks"][0]["status"] == "skipped"


def test_oracle_summary_marks_skip_approved_when_approval_id_present(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check("detect", "skipped", "kicad-cli not found on PATH")

    ci_kicad_oracle._write_summary(str(output), status="skipped", skip_approval_id="APPROVAL-42")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kicad_oracle"] == "skip-approved"
    assert data["raw_status"] == "skipped"
    assert data["skip_approval_id"] == "APPROVAL-42"


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


def test_oracle_summary_includes_commands_and_hashes(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    artifact = tmp_path / "oracle.txt"
    artifact.write_text("oracle evidence", encoding="utf-8")
    ci_kicad_oracle._CHECKS.clear()
    ci_kicad_oracle._SKIP_REASONS.clear()
    ci_kicad_oracle._record_check(
        "pcb_drc",
        "passed",
        "DRC report generated",
        command=["kicad-cli", "pcb", "drc"],
        report_path=str(artifact),
        report_sha256=ci_kicad_oracle._sha256_file(artifact),
    )

    ci_kicad_oracle._write_summary(str(output), status="passed", version="9.0.0", cli_path="/usr/bin/kicad-cli")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["commands"] == [["kicad-cli", "pcb", "drc"]]
    assert data["artifact_hashes"][str(artifact)] == ci_kicad_oracle._sha256_file(artifact)
    assert data["skip_policy"].startswith("skips are explicit")
