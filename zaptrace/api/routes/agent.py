"""REST API routes for agent-runtime sandbox management and replay."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from zaptrace.security.replay import get_replay
from zaptrace.security.sandbox import (
    emergency_reset,
    emergency_stop,
    reset_sandbox,
    sandbox_status,
)

router = APIRouter()


@router.get("/sandbox/{session_id}/status")
def api_sandbox_status(session_id: str):
    """Get sandbox status for a session (call count, budget, emergency flag)."""
    try:
        return sandbox_status(session_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sandbox/{session_id}/stop")
def api_sandbox_stop(session_id: str, reason: str = ""):
    """Emergency-stop a session — no further tool calls allowed."""
    emergency_stop(session_id, reason)
    return {"session_id": session_id, "emergency_stopped": True}


@router.post("/sandbox/{session_id}/reset")
def api_sandbox_reset(session_id: str):
    """Reset emergency stop for a session."""
    emergency_reset(session_id)
    status = sandbox_status(session_id)
    return {"session_id": session_id, "emergency_stopped": status["emergency_stopped"]}


@router.post("/sandbox/{session_id}/clear")
def api_sandbox_clear(session_id: str):
    """Full sandbox reset — clear counters and budgets."""
    reset_sandbox(session_id)
    return {"session_id": session_id, "reset": True}


@router.get("/replay/{session_id}")
def api_replay_log(session_id: str):
    """Get the replayable session log for a session."""
    log = get_replay(session_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"No replay log for session '{session_id}'")
    return {
        "session_id": log.session_id,
        "entry_count": log.entry_count,
        "total_duration_ms": round(log.total_duration_ms, 1),
        "digest": log.digest,
    }
