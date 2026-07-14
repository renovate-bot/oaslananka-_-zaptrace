"""REST artifact lifecycle routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from zaptrace.api.routes._session import authorize_tool, current_request_principal, resolve_session_id
from zaptrace.api.storage import ArtifactCreateRequest, ArtifactStore

router = APIRouter()


@router.get("/config")
def artifact_config() -> dict[str, Any]:
    """Return artifact storage configuration visible to API clients."""
    return ArtifactStore().config()


@router.get("")
def list_artifacts(session: str = Depends(resolve_session_id)) -> dict[str, Any]:
    """List stored artifacts for the current session."""
    records = ArtifactStore().list_artifacts(session)
    return {
        "session_id": session,
        "count": len(records),
        "artifacts": [record.model_dump(mode="json") for record in records],
    }


@router.post("")
def create_artifact(
    request: ArtifactCreateRequest,
    http_request: Request,
    session: str = Depends(authorize_tool("artifact_create")),
) -> dict[str, Any]:
    """Store a deterministic REST artifact and return its lifecycle metadata."""
    try:
        record = ArtifactStore().store_text(
            session,
            filename=request.filename,
            kind=request.kind,
            content=request.content,
            owner_principal=current_request_principal(http_request).principal_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail={"code": "ARTIFACT_TOO_LARGE", "message": str(exc)}) from exc
    return {"ok": True, "artifact": record.model_dump(mode="json")}


@router.delete("/expired")
def cleanup_expired_artifacts(session: str = Depends(authorize_tool("artifact_cleanup"))) -> dict[str, Any]:
    """Delete expired artifacts across the configured artifact root."""
    deleted = ArtifactStore().cleanup_expired(session_id=session)
    return {
        "ok": True,
        "session_id": session,
        "deleted_count": len(deleted),
        "deleted": [record.model_dump(mode="json") for record in deleted],
    }


@router.delete("/{artifact_id}")
def delete_artifact(
    artifact_id: str,
    session: str = Depends(authorize_tool("artifact_delete")),
) -> dict[str, Any]:
    """Delete one artifact for the current session."""
    record = ArtifactStore().delete_artifact(session, artifact_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": artifact_id})
    return {"ok": True, "deleted": record.model_dump(mode="json")}
