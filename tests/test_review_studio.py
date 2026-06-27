"""Review Studio tests — panel aggregation, workflow, and API routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zaptrace.api.server import app
from zaptrace.core.diff import DiffEntry, DiffType
from zaptrace.core.models import Component, DRCViolation, DRCResult, Design, DesignMeta, Net, NetNode
from zaptrace.erc.models import ERCViolation, ERCSeverity
from zaptrace.review.panels import (
    ReviewPanel,
    ReviewPanelBundle,
    collect_panels,
    collect_review_bundle,
)
from zaptrace.review.workflow import (
    ChecklistStatus,
    DecisionType,
    HumanChecklistItem,
    ReviewDecision,
    ReviewSession,
    add_waiver,
    approve_checklist_item,
    create_review_session,
    reject_checklist_item,
    resolve_decision,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def design() -> Design:
    d = Design(meta=DesignMeta(name="ReviewBoard"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0603")
    d.components["c1"] = Component(id="c1", ref="C1", type="capacitor", value="100nF", footprint="0603")
    d.nets["n1"] = Net(
        id="n1",
        name="VCC",
        nodes=[NetNode(component_ref="R1", pin_name="1"), NetNode(component_ref="C1", pin_name="1")],
    )
    return d


@pytest.fixture
def design_with_erc(design: Design) -> Design:
    from zaptrace.erc.models import ERCResult

    # Use object.__setattr__ since erc_result is not a declared Design field
    object.__setattr__(
        design,
        "erc_result",
        ERCResult.from_violations(
            violations=[
                ERCViolation(
                    rule_id="ERC001",
                    severity=ERCSeverity.WARNING,
                    message="Unconnected pin R1-2",
                )
            ],
            design_name="ReviewBoard",
        ),
    )
    return design


@pytest.fixture
def design_with_drc(design: Design) -> Design:
    design.drc_result = DRCResult(
        design_name="ReviewBoard",
        violations=[
            DRCViolation(
                rule_id="DRC001",
                severity="error",  # type: ignore[arg-type]
                message="Track too close to board edge",
            ),
        ],
    )
    return design


@pytest.fixture
def baseline() -> Design:
    d = Design(meta=DesignMeta(name="ReviewBoard_base"))
    d.components["r1"] = Component(id="r1", ref="R1", type="resistor", value="10k", footprint="0603")
    return d


# ---------------------------------------------------------------------------
# Panel aggregation tests
# ---------------------------------------------------------------------------


class TestCollectPanels:
    def test_erc_panel_empty(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["erc"])
        p = panels["erc"]
        assert p.panel_id == "erc"
        assert p.status == "pass"
        assert "No ERC violations" in p.summary

    def test_erc_panel_with_violations(self, design_with_erc: Design) -> None:
        panels = collect_panels(design_with_erc, panel_ids=["erc"])
        p = panels["erc"]
        assert p.status == "warning"
        assert len(p.items) == 1
        assert p.items[0]["rule_id"] == "ERC001"

    def test_drc_panel_with_violations(self, design_with_drc: Design) -> None:
        panels = collect_panels(design_with_drc, panel_ids=["drc"])
        p = panels["drc"]
        assert p.status == "fail"
        assert len(p.items) >= 1

    def test_bom_panel(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["bom"])
        p = panels["bom"]
        assert p.panel_id == "bom"
        assert p.summary.startswith("2 line items")  # R1 + C1
        assert "export_csv" in p.actions

    def test_supply_panel_empty(self, design: Design) -> None:
        panels = collect_panels(design, panel_ids=["supply"])
        p = panels["supply"]
        assert p.status == "info"

    def test_all_panels_returned(self, design: Design) -> None:
        panels = collect_panels(design)
        expected = {"requirements", "erc", "drc", "dfm", "bom", "supply", "manufacturing", "simulation", "proof_pack", "decision_log"}
        assert expected.issubset(set(panels.keys()))

    def test_review_bundle_overall_pass(self, design: Design) -> None:
        bundle = collect_review_bundle(design)
        assert bundle.design_name == "ReviewBoard"
        assert bundle.overall_status == "pass"
        assert len(bundle.non_claims) >= 2

    def test_review_bundle_overall_fail(self, design_with_drc: Design) -> None:
        bundle = collect_review_bundle(design_with_drc)
        assert bundle.overall_status == "fail"

    def test_state_hash_in_bundle(self, design: Design) -> None:
        bundle = collect_review_bundle(design)
        assert bundle.design_state_hash != ""


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------


class TestReviewWorkflow:
    def test_create_session(self) -> None:
        rs = create_review_session("MyDesign", "abc123")
        assert rs.session_id.startswith("session-")
        assert rs.design_name == "MyDesign"
        assert len(rs.checklist) >= 8
        assert all(item.status == ChecklistStatus.PENDING for item in rs.checklist.values())

    def test_approve_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = approve_checklist_item(rs, item_id, decided_by="alice", reason="Looks good")
        assert result.status == ChecklistStatus.APPROVED
        assert result.decided_by == "alice"
        assert rs.updated_at != rs.created_at

    def test_reject_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = reject_checklist_item(rs, item_id, decided_by="bob", reason="Missing evidence")
        assert result.status == ChecklistStatus.REJECTED

    def test_waive_item(self) -> None:
        rs = create_review_session("TestDesign")
        item_id = list(rs.checklist.keys())[0]
        result = add_waiver(rs, item_id, decided_by="carol", reason="Non-critical", waiver_notes="Accepting risk")
        assert result.status == ChecklistStatus.WAIVED

    def test_approve_all_approved(self) -> None:
        rs = create_review_session("TestDesign")
        assert not rs.all_approved
        for item_id in rs.checklist:
            approve_checklist_item(rs, item_id, decided_by="alice")
        assert rs.all_approved

    def test_any_rejected(self) -> None:
        rs = create_review_session("TestDesign")
        assert not rs.any_rejected
        item_id = list(rs.checklist.keys())[0]
        reject_checklist_item(rs, item_id, decided_by="bob")
        assert rs.any_rejected

    def test_approve_decision(self) -> None:
        rs = create_review_session("ProdDesign")
        for item_id in rs.checklist:
            approve_checklist_item(rs, item_id, decided_by="alice")
        rec = resolve_decision(rs, DecisionType.APPROVE, decided_by="alice", reason="All clear")
        assert rec.decision == DecisionType.APPROVE
        assert rec.approval_id.startswith("approval-")
        assert len(rs.decisions) == 1

    def test_reject_decision(self) -> None:
        rs = create_review_session("FailDesign")
        rec = resolve_decision(rs, DecisionType.REJECT, decided_by="bob", reason="Blocking violations")
        assert rec.decision == DecisionType.REJECT
        assert rec.approval_id == ""

    def test_rollback_decision(self) -> None:
        rs = create_review_session("RollbackDesign")
        rec = resolve_decision(rs, DecisionType.ROLLBACK, decided_by="carol", reason="Wrong assumptions")
        assert rec.decision == DecisionType.ROLLBACK

    def test_unknown_item_raises(self) -> None:
        rs = create_review_session("TestDesign")
        with pytest.raises(KeyError):
            approve_checklist_item(rs, "nonexistent")


# ---------------------------------------------------------------------------
# API route tests (via TestClient)
# ---------------------------------------------------------------------------


client = TestClient(app)
_SESSION_HEADERS = {
    "X-ZapTrace-Session-Id": "test-session",
    "X-ZapTrace-Capabilities": "preview-write, sandbox-write, approved-commit, release-export",
}


def _load_design_via_api(client: TestClient, name: str = "ApiDesign") -> None:
    yaml = f"""
meta:
  name: {name}
components:
  r1:
    ref: R1
    type: resistor
    value: 10k
    footprint: "0603"
  c1:
    ref: C1
    type: capacitor
    value: 100nF
    footprint: "0603"
nets:
  n1:
    name: VCC
    nodes:
      - component_ref: R1
        pin_name: "1"
      - component_ref: C1
        pin_name: "1"
"""
    resp = client.post("/api/v1/designs/parse/str", params={"yaml_content": yaml}, headers=_SESSION_HEADERS)
    assert resp.status_code == 200, resp.text


class TestReviewApi:
    def test_bundle_endpoint(self) -> None:
        _load_design_via_api(client)
        resp = client.get("/api/v1/review/bundle/ApiDesign", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        bundle = data["bundle"]
        assert bundle["design_name"] == "ApiDesign"
        assert "erc" in bundle["panels"]
        assert "bom" in bundle["panels"]

    def test_panels_endpoint_subset(self) -> None:
        _load_design_via_api(client)
        resp = client.get("/api/v1/review/bundle/ApiDesign/panels?panel_ids=erc,bom", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["panels"].keys()) == {"erc", "bom"}

    def test_start_review_session(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["session"]["session_id"].startswith("session-")
        assert len(data["session"]["checklist"]) >= 8

    def test_review_workflow_via_api(self) -> None:
        _load_design_via_api(client)
        # Start session
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        # Approve item
        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/approve",
            params={"decided_by": "test-user", "reason": "Looks good"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["item"]["status"] == "approved"

        # Get session
        resp = client.get(f"/api/v1/review/session/{session_id}", headers=_SESSION_HEADERS)
        assert resp.status_code == 200

    def test_reject_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/reject",
            params={"decided_by": "test-user", "reason": "Not acceptable"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "rejected"

    def test_waive_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]
        item_id = list(resp.json()["session"]["checklist"].keys())[0]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/checklist/{item_id}/waive",
            params={"decided_by": "test-user", "reason": "Low risk", "waiver_notes": "Accepting"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "waived"

    def test_decide_approve_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={"decision": "approve", "decided_by": "lead", "reason": "Release ready"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["decision"]["decision"] == "approve"
        assert data["decision"]["approval_id"].startswith("approval-")

    def test_decide_reject_via_api(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={"decision": "reject", "decided_by": "lead", "reason": "Unresolved violations"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["decision"]["decision"] == "reject"

    def test_decide_invalid_decision(self) -> None:
        _load_design_via_api(client)
        resp = client.post("/api/v1/review/session/ApiDesign", headers=_SESSION_HEADERS)
        session_id = resp.json()["session"]["session_id"]

        resp = client.post(
            f"/api/v1/review/session/{session_id}/decide",
            params={"decision": "invalid_decision"},
            headers=_SESSION_HEADERS,
        )
        assert resp.status_code == 400

    def test_session_not_found(self) -> None:
        resp = client.get("/api/v1/review/session/nonexistent", headers=_SESSION_HEADERS)
        assert resp.status_code == 404

    def test_diff_endpoint(self) -> None:
        _load_design_via_api(client, "DesignA")
        _load_design_via_api(client, "DesignB")
        resp = client.get("/api/v1/review/diff/DesignA/DesignB", headers=_SESSION_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert "changes" in data
