from __future__ import annotations

import json

import pytest

from scripts.ci_release_gate import (
    FAIL,
    PASS,
    SKIP_APPROVED,
    SKIP_UNAPPROVED,
    build_records,
    main,
    normalize_status,
    require_external_oracles,
)


def test_normalize_github_results() -> None:
    assert normalize_status("success") == PASS
    assert normalize_status("failure") == FAIL
    assert normalize_status("skipped") == SKIP_APPROVED
    assert normalize_status("neutral") == "warn"


def test_missing_skip_reason_becomes_unapproved() -> None:
    records = build_records(["kicad-oracle=skipped"], [])
    assert records[0].status == SKIP_UNAPPROVED
    assert records[0].blocks_release


def test_approved_skip_is_non_blocking() -> None:
    records = build_records(["kicad-oracle=skipped"], ["kicad-oracle=tool-unavailable"])
    assert records[0].status == SKIP_APPROVED
    assert not records[0].blocks_release


def test_strict_mode_returns_failure_for_blocker(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(["--gate", "tests=failure", "--output", str(output), "--strict"])
    assert code == 1
    summary = json.loads(output.read_text())
    assert summary["blocked"] is True
    assert summary["blocking_gates"] == ["tests"]


def test_main_writes_json_and_markdown(tmp_path) -> None:
    output = tmp_path / "summary.json"
    markdown = tmp_path / "summary.md"
    code = main(
        [
            "--gate",
            "lint=success",
            "--gate",
            "kicad-oracle=skipped",
            "--skip-reason",
            "kicad-oracle=tool-unavailable",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )
    assert code == 0
    summary = json.loads(output.read_text())
    assert summary["blocked"] is False
    assert "kicad-oracle" in markdown.read_text()


def test_required_external_oracle_missing_blocks_release() -> None:
    records = require_external_oracles(build_records(["lint=success"], []), ["kicad-oracle"], [])
    oracle = next(record for record in records if record.name == "kicad-oracle")
    assert oracle.status == SKIP_UNAPPROVED
    assert oracle.blocks_release
    assert oracle.raw_result == "missing"


def test_required_external_oracle_missing_with_approved_skip_is_non_blocking() -> None:
    records = require_external_oracles(
        build_records(["lint=success"], []),
        ["kicad-oracle"],
        ["kicad-oracle=tool unavailable with approval APPROVAL-1"],
    )
    oracle = next(record for record in records if record.name == "kicad-oracle")
    assert oracle.status == SKIP_APPROVED
    assert not oracle.blocks_release


def test_main_required_oracle_missing_fails_strict(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(["--gate", "lint=success", "--required-oracle", "kicad-oracle", "--output", str(output), "--strict"])
    assert code == 1
    data = json.loads(output.read_text())
    assert data["blocked"] is True
    assert "kicad-oracle" in data["blocking_gates"]


def test_main_required_oracle_with_approved_skip_passes_strict(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(
        [
            "--gate",
            "lint=success",
            "--required-oracle",
            "kicad-oracle",
            "--skip-reason",
            "kicad-oracle=APPROVAL-1 tool unavailable",
            "--output",
            str(output),
            "--strict",
        ]
    )
    assert code == 0
    data = json.loads(output.read_text())
    assert data["blocked"] is False


def test_help_documents_canonical_invocations(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "Examples:" in captured.out
    assert "--gate lint=success --gate tests=success" in captured.out
    assert "v0.3.0" in captured.out
