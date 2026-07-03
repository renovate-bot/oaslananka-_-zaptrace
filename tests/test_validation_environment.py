from __future__ import annotations

from scripts import ci_validation_environment


def test_version_parser_reads_major_minor() -> None:
    assert ci_validation_environment._first_version_number("Python 3.12.7") == (3, 12)
    assert ci_validation_environment._first_version_number("KiCad CLI 9.0.1") == (9, 0)


def test_report_contains_release_commands_and_non_claims() -> None:
    report = ci_validation_environment.build_report()
    assert report["schema_version"] == "1.0"
    assert "uv run pytest --cov=zaptrace --cov-report=term-missing" in report["recommended_release_commands"]
    assert any("fabrication" in claim for claim in report["non_claims"])


def test_report_json_is_stable_json() -> None:
    report = {
        "schema_version": "1.0",
        "passed": True,
        "tools": [],
    }
    rendered = ci_validation_environment.report_json(report)
    assert rendered.endswith("\n")
    assert '"passed": true' in rendered
