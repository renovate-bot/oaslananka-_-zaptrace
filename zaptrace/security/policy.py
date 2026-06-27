"""Deny-by-default capability policy and audit events.

The policy is intentionally small and dependency-free so it can be shared by
REST, MCP, tests, and proof-pack integrations.  Read-only tools are public by
process policy; mutating/exporting tools require explicit capability grants.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

CAPABILITY_LEVELS: tuple[str, ...] = (
    "read",
    "preview-write",
    "sandbox-write",
    "approved-commit",
    "release-export",
)

CAPABILITY_RANK = {name: idx for idx, name in enumerate(CAPABILITY_LEVELS)}


@dataclass(frozen=True)
class AuditEvent:
    """A structured audit record for a policy decision or mutating operation."""

    event_id: str
    timestamp: str
    surface: str
    session_id: str
    actor: str
    tool: str
    capability: str
    decision: str
    reason: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def granted_capabilities_from_header(raw: str | None) -> set[str]:
    """Parse a comma/space-separated capability header into a normalized set."""
    if not raw:
        return set()
    tokens = raw.replace(",", " ").split()
    return {token.strip().lower() for token in tokens if token.strip() in CAPABILITY_RANK}


def authorize_capability(required: str, granted: set[str]) -> tuple[bool, str]:
    """Return (allowed, reason) for a required capability and explicit grants.

    `read` is intentionally allowed without a grant because read-only inspection
    is not a mutating operation. All other capabilities are deny-by-default.
    Higher capability grants imply lower-risk write levels.
    """
    if required == "read":
        return True, "read-only operation"
    required_rank = CAPABILITY_RANK.get(required)
    if required_rank is None:
        return False, f"unknown required capability: {required}"
    if not granted:
        return False, f"missing required capability: {required}"
    if any(CAPABILITY_RANK.get(cap, -1) >= required_rank for cap in granted):
        return True, f"capability grant satisfies {required}"
    return False, f"requires {required}; granted {sorted(granted)}"


def record_audit_event(
    session: dict[str, Any],
    *,
    surface: str,
    session_id: str,
    actor: str,
    tool: str,
    capability: str,
    decision: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an audit event to a session and return it as a dict."""
    event = AuditEvent(
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC).isoformat(),
        surface=surface,
        session_id=session_id,
        actor=actor,
        tool=tool,
        capability=capability,
        decision=decision,
        reason=reason,
        metadata=metadata or {},
    ).to_dict()
    session.setdefault("audit_events", []).append(event)
    return event


# Required capability per registered tool. The mapping is injected into
# TOOL_REGISTRY at import time so the public registry declares each tool's
# runtime capability level.
TOOL_CAPABILITIES: dict[str, str] = {
    # Session/design creation or in-memory mutation.
    "design_parse_file": "preview-write",
    "design_parse_str": "preview-write",
    "synthesize_design": "preview-write",
    "pipeline_run": "preview-write",
    "pipeline_run_stage": "preview-write",
    # In-memory layout/design mutation.
    "place_components": "sandbox-write",
    "route_nets": "sandbox-write",
    "board_update": "sandbox-write",
    "component_add": "sandbox-write",
    "component_remove": "sandbox-write",
    "board_classify_nets": "sandbox-write",
    "design_route_smart": "sandbox-write",
    "design_classify_nets": "sandbox-write",
    "design_transaction_preview": "preview-write",
    "design_transaction_validate": "sandbox-write",
    "design_transaction_rollback": "sandbox-write",
    "design_transaction_commit": "approved-commit",
    "design_transaction_list": "read",
    "design_snapshot": "sandbox-write",
    "design_rollback": "sandbox-write",
    # Explicit commit/confirmation gates.
    "design_commit": "approved-commit",
    # File/manufacturing/release exports.
    "export_report": "sandbox-write",
    "export_svg": "sandbox-write",
    "export_kicad": "release-export",
    "export_gerber": "release-export",
    "export_excellon": "release-export",
    "export_manufacturing": "release-export",
    "export_pick_and_place": "release-export",
    # REST artifact lifecycle.
    "artifact_create": "preview-write",
    "artifact_delete": "sandbox-write",
    "artifact_cleanup": "sandbox-write",
    # Review Studio.
    "review_start": "sandbox-write",
    "review_approve": "sandbox-write",
    "review_reject": "sandbox-write",
    "review_waive": "preview-write",
    "review_decide": "approved-commit",
    # Read-only by default unless listed above.
}


def required_tool_capability(tool_name: str) -> str:
    """Return the capability required by a tool name."""
    return TOOL_CAPABILITIES.get(tool_name, "read")
