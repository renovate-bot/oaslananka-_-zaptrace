from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_benchmark_001 import FAIL, PASS, build_report, load_spec, main, validate_spec


def test_benchmark_001_spec_contract_passes() -> None:
    spec = load_spec(Path("benchmarks/001-esp32-sensor/requirements.yaml"))
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["status"] == PASS
    assert report["blocked"] is False
    assert report["benchmark"]["id"] == "benchmark-001-esp32-sensor"
    assert report["benchmark"]["release_gate"]["milestone_readiness"] == "M1"
    assert {check["name"] for check in report["checks"]} >= {
        "metadata",
        "board-requirements",
        "acceptance-thresholds",
        "release-gate-link",
        "scoring-evidence",
    }


def test_main_writes_json_and_markdown(tmp_path) -> None:
    output = tmp_path / "benchmark-001-report.json"
    markdown = tmp_path / "benchmark-001-report.md"

    code = main(["--output", str(output), "--markdown", str(markdown), "--strict"])

    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == PASS
    assert "Benchmark 001 Release Gate Summary" in markdown.read_text(encoding="utf-8")


def test_missing_function_blocks_release(tmp_path) -> None:
    source = Path("benchmarks/001-esp32-sensor/requirements.yaml")
    spec_path = tmp_path / "requirements.yaml"
    text = source.read_text(encoding="utf-8")
    text = text.replace("    - id: i2c_sensor\n", "    - id: removed_i2c_sensor\n")
    spec_path.write_text(text, encoding="utf-8")

    spec = load_spec(spec_path)
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["status"] == FAIL
    assert "board-requirements" in report["blocking_checks"]


def test_scoring_evidence_requires_committed_proof_and_bom(tmp_path) -> None:
    source = Path("benchmarks/001-esp32-sensor/requirements.yaml")
    spec_path = tmp_path / "requirements.yaml"
    text = source.read_text(encoding="utf-8")
    text = text.replace(
        "  bom_risk_report: docs/reports/benchmark-001-bom-risk-sample.json\n",
        "  bom_risk_report: docs/reports/missing-bom-risk.json\n",
    )
    spec_path.write_text(text, encoding="utf-8")

    spec = load_spec(spec_path)
    checks = validate_spec(spec, root=Path.cwd())
    report = build_report(spec, checks)

    assert report["status"] == FAIL
    assert "scoring-evidence" in report["blocking_checks"]
