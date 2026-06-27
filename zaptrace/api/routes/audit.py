"""Audit API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from zaptrace.api.routes._session import resolve_session_id, session_audit_events

router = APIRouter()


@router.get("/events")
def list_audit_events(
    limit: int = 50,
    session: str = Depends(resolve_session_id),
) -> dict[str, Any]:
    """List recent security/audit events for a session."""
    return session_audit_events(session, limit=limit)
