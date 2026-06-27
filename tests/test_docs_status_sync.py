from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_docs_status_sync import (
    actual_drc_rule_count,
    actual_erc_rule_count,
    actual_tool_count,
    main,
    validate_docs,
)


def test_actual_erc_rule_count_matches_runner() -> None:
    from zaptrace.erc.runner import _ALL_RULES

    assert actual_erc_rule_count() == len(_ALL_RULES) >= 20


def test_actual_drc_rule_count_matches_engine() -> None:
    from zaptrace.ee.drc.engine import _ALL_CHECKS

    assert actual_drc_rule_count() == len(_ALL_CHECKS) >= 11


def test_actual_tool_count_matches_registry() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    assert actual_tool_count() == len(TOOL_REGISTRY) >= 50


def test_docs_status_sync_current_repo_passes() -> None:
    result = validate_docs()
    assert result["passed"], result["errors"]


def test_docs_status_sync_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "docs-status.json"
    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["erc_rule_count"] == actual_erc_rule_count()
    assert report["drc_rule_count"] == actual_drc_rule_count()
    assert report["tool_count"] == actual_tool_count()
