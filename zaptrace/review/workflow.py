"""Human review workflow — checklist, approve/reject, waiver, rollback.

Review Studio uses a checklist-based approval workflow where each review
item must be explicitly acknowledged before a decision (approve/reject/waive)
can be recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChecklistStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WAIVED = "waived"


class DecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    WAIVE = "waive"
    ROLLBACK = "rollback"


class HumanChecklistItem(BaseModel):
    """One review checklist item — a gate that a human must explicitly address."""

    model_config = ConfigDict(strict=False)

    item_id: str
    panel_id: str
    label: str
    description: str = ""
    status: ChecklistStatus = ChecklistStatus.PENDING
    decided_by: str = ""
    decided_at: str = ""
    reason: str = ""
    is_blocking: bool = True


class ReviewDecision(BaseModel):
    """Record of a human review decision on an entire design review."""

    model_config = ConfigDict(strict=False)

    decision_id: str
    design_name: str
    transaction_id: str = ""
    decision: DecisionType
    decided_by: str
    decided_at: str = ""
    reason: str = ""
    waiver_notes: str = ""
    checklist_results: dict[str, ChecklistStatus] = Field(default_factory=dict)
    approval_id: str = ""


class ReviewSession(BaseModel):
    """A mutable review session in progress — tracks checklist and decisions."""

    model_config = ConfigDict(strict=False)

    session_id: str
    design_name: str
    design_state_hash: str = ""
    checklist: dict[str, HumanChecklistItem] = Field(default_factory=dict)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @property
    def all_approved(self) -> bool:
        """True when all blocking checklist items are approved or waived."""
        return all(
            item.status in (ChecklistStatus.APPROVED, ChecklistStatus.WAIVED)
            for item in self.checklist.values()
            if item.is_blocking
        )

    @property
    def any_rejected(self) -> bool:
        """True when any checklist item is rejected."""
        return any(item.status == ChecklistStatus.REJECTED for item in self.checklist.values())


# ---------------------------------------------------------------------------
# In-memory store (session-local, ephemeral)
# ---------------------------------------------------------------------------

_REVIEW_SESSIONS: dict[str, ReviewSession] = {}


def _utc_now_str() -> str:
    return datetime.now(UTC).isoformat()


def _generate_id(prefix: str = "rev") -> str:
    import secrets

    return f"{prefix}-{secrets.token_hex(8)}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_review_session(
    design_name: str,
    design_state_hash: str = "",
    *,
    panel_ids: list[str] | None = None,
) -> ReviewSession:
    """Create a new review session with a default checklist.

    Args:
        design_name: Name of the design under review.
        design_state_hash: Deterministic design state hash for provenance.
        panel_ids: Panel IDs to create checklist items for; ``None`` builds for all.

    Returns:
        A new :class:`ReviewSession` with checklist items for each panel.
    """
    session_id = _generate_id("session")
    now = _utc_now_str()
    checklist: dict[str, HumanChecklistItem] = {}
    ids = panel_ids or [
        "requirements",
        "erc",
        "drc",
        "dfm",
        "bom",
        "supply",
        "manufacturing",
        "simulation",
        "proof_pack",
        "decision_log",
    ]
    for pid in ids:
        item_id = f"{pid}-review"
        checklist[item_id] = HumanChecklistItem(
            item_id=item_id,
            panel_id=pid,
            label=f"Review {pid.replace('_', ' ').title()}",
            description=f"Human must inspect {pid} panel evidence and confirm acceptability.",
            is_blocking=(pid not in ("decision_log", "simulation")),
        )
    session = ReviewSession(
        session_id=session_id,
        design_name=design_name,
        design_state_hash=design_state_hash,
        checklist=checklist,
        created_at=now,
        updated_at=now,
    )
    _REVIEW_SESSIONS[session_id] = session
    return session


def get_review_session(session_id: str) -> ReviewSession | None:
    """Look up an in-memory review session by ID."""
    return _REVIEW_SESSIONS.get(session_id)


def approve_checklist_item(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
) -> HumanChecklistItem:
    """Mark a checklist item as approved.

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.APPROVED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    session.updated_at = _utc_now_str()
    return item


def reject_checklist_item(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
) -> HumanChecklistItem:
    """Mark a checklist item as rejected.

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.REJECTED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    session.updated_at = _utc_now_str()
    return item


def add_waiver(
    session: ReviewSession,
    item_id: str,
    *,
    decided_by: str = "",
    reason: str = "",
    waiver_notes: str = "",
) -> HumanChecklistItem:
    """Waive a checklist item (non-blocking override).

    Raises:
        KeyError: if *item_id* is not in the checklist.
    """
    item = session.checklist.get(item_id)
    if item is None:
        raise KeyError(f"Checklist item not found: {item_id}")
    item.status = ChecklistStatus.WAIVED
    item.decided_by = decided_by
    item.decided_at = _utc_now_str()
    item.reason = reason
    session.updated_at = _utc_now_str()
    return item


def resolve_decision(
    session: ReviewSession,
    decision: DecisionType,
    *,
    decided_by: str = "",
    reason: str = "",
    waiver_notes: str = "",
) -> ReviewDecision:
    """Finalize a review session with a global decision.

    Records the decision and returns it.  The session is *not* cleared —
    decisions are preserved for audit.

    Args:
        session: The review session to finalize.
        decision: ``APPROVE``, ``REJECT``, or ``ROLLBACK``.
        decided_by: Human actor identifier.
        reason: Human-readable justification.
        waiver_notes: Additional context for waivers.

    Returns:
        The recorded :class:`ReviewDecision`.
    """
    decision_id = _generate_id("decision")
    now = _utc_now_str()
    approval_id = _generate_id("approval") if decision == DecisionType.APPROVE else ""
    checklist_results = {
        item_id: item.status for item_id, item in session.checklist.items()
    }
    rec = ReviewDecision(
        decision_id=decision_id,
        design_name=session.design_name,
        decision=decision,
        decided_by=decided_by,
        decided_at=now,
        reason=reason,
        waiver_notes=waiver_notes,
        checklist_results=checklist_results,
        approval_id=approval_id,
    )
    session.decisions.append(rec)
    session.updated_at = now
    return rec
