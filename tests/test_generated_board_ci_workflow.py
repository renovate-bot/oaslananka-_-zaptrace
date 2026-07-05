from __future__ import annotations

from pathlib import Path


def test_quality_workflow_runs_generated_board_release_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "generated-board-release-gate:" in workflow
    assert "name: Generated board release gate" in workflow
    assert "scripts/ci_generated_board_release_gate.py" in workflow
    assert "--strict" in workflow
    assert "generated-board-release-gate.json" in workflow
    assert "name: generated-board-release-gate" in workflow


def test_release_summary_depends_on_generated_board_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "generated-board-release-gate" in workflow
    assert "needs.generated-board-release-gate.result" in workflow
    assert '--gate "generated-board-release-gate=${{ needs.generated-board-release-gate.result }}"' in workflow


def test_quality_workflow_runs_validation_environment_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "validation-environment:" in workflow
    assert "name: Validation environment parity" in workflow
    assert "scripts/ci_validation_environment.py" in workflow
    assert "--strict" in workflow
    assert "validation-environment.json" in workflow


def test_release_summary_depends_on_validation_environment_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "needs.validation-environment.result" in workflow
    assert '--gate "validation-environment=${{ needs.validation-environment.result }}"' in workflow


def test_hardware_smoke_uses_current_router_result_shape() -> None:
    workflow = Path(".github/workflows/hardware.yml").read_text(encoding="utf-8")

    assert "_, d.routing, _ = route_design_smart(d, positions)" in workflow
