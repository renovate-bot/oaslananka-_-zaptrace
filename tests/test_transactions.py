"""Tests for transaction-safe design state."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zaptrace.agent import _tool_impls as tools
from zaptrace.core.state import design_state_hash

_DESIGN_YAML = """meta:
  name: TxDesign
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
"""


def setup_function() -> None:
    tools._sessions.clear()


def _load_design(session_id: str = "tx-test") -> None:
    tools.tool_design_parse_str(_DESIGN_YAML, session_id=session_id)


def test_preview_transaction_returns_json_safe_semantic_diff_without_mutating_primary() -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)

    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        reason="try a wider board",
        session_id="tx-test",
    )

    assert preview["state"] == "previewed"
    assert preview["parent_state_hash"] == before_hash
    assert preview["preview_state_hash"] != before_hash
    assert preview["semantic_diff"][0]["type"] == "board_changed"
    assert preview["semantic_diff"][0]["ref"] == "board"
    json.dumps(preview)

    current = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert current.board.width_mm == 100.0
    assert design_state_hash(current) == before_hash


def test_validate_and_commit_transaction_requires_explicit_approval() -> None:
    _load_design()
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        session_id="tx-test",
    )
    validated = tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")
    assert validated["state"] == "validated"
    assert validated["validation"]["status"] == "passed"

    with pytest.raises(ValueError, match="approval_id is required"):
        tools.tool_design_transaction_commit(preview["transaction_id"], approval_id="", session_id="tx-test")

    committed = tools.tool_design_transaction_commit(
        preview["transaction_id"],
        approval_id="approval-123",
        session_id="tx-test",
    )
    assert committed["state"] == "committed"
    assert committed["approval_id"] == "approval-123"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert design.board.width_mm == 120.0
    assert committed["committed_state_hash"] == design_state_hash(design)
    assert tools._get_session("tx-test")["transaction_history"][-1]["state"] == "committed"


def test_rollback_rejects_preview_without_mutating_primary() -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "component_add",
        {"component_id": "c1", "ref": "C1", "type_name": "capacitor", "value": "100n", "footprint": "0603"},
        session_id="tx-test",
    )

    rolled_back = tools.tool_design_transaction_rollback(preview["transaction_id"], session_id="tx-test")

    assert rolled_back["state"] == "rolled_back"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert "c1" not in design.components
    assert design_state_hash(design) == before_hash


def test_failed_validation_rejects_transaction_and_keeps_primary_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _load_design()
    before = tools._get_session("tx-test")["designs"]["TxDesign"]
    before_hash = design_state_hash(before)
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"layers": 4},
        session_id="tx-test",
    )

    class FakeRunner:
        def run(self, _design):
            return SimpleNamespace(passed=False, total_errors=1, total_warnings=0, total_info=0)

    monkeypatch.setattr(tools, "ERCRunner", FakeRunner)
    validated = tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")

    assert validated["state"] == "rejected"
    assert validated["validation"]["status"] == "failed"
    design = tools._get_session("tx-test")["designs"]["TxDesign"]
    assert design.board.layers == 2
    assert design_state_hash(design) == before_hash


def test_primary_state_change_blocks_stale_transaction_commit() -> None:
    _load_design()
    preview = tools.tool_design_transaction_preview(
        "TxDesign",
        "board_update",
        {"width_mm": 120},
        session_id="tx-test",
    )
    tools.tool_design_transaction_validate(preview["transaction_id"], session_id="tx-test")
    # Mutate primary outside the transaction to simulate a stale preview.
    tools._get_session("tx-test")["designs"]["TxDesign"].board.width_mm = 130

    with pytest.raises(ValueError, match="Primary design state changed"):
        tools.tool_design_transaction_commit(
            preview["transaction_id"],
            approval_id="approval-123",
            session_id="tx-test",
        )
