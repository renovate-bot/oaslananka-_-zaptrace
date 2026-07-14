"""Object-level authorization for session-scoped runtime resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4


class ObjectAccessDeniedError(PermissionError):
    """Raised when a principal cannot access a protected object."""


@dataclass(frozen=True)
class RequestPrincipal:
    """Resolved caller identity used for object authorization."""

    principal_id: str
    actor: str
    scopes: frozenset[str] = frozenset()
    authenticated: bool = False
    local_development: bool = False

    @property
    def is_admin(self) -> bool:
        return "object-admin" in self.scopes


@dataclass
class ObjectAccessRecord:
    """Ownership and delegation metadata for one protected object."""

    object_type: str
    object_id: str
    owner_principal: str
    delegates: set[str] = field(default_factory=set)
    parent_object_type: str = ""
    parent_object_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["delegates"] = sorted(self.delegates)
        return payload


_OBJECT_ACCESS: dict[tuple[str, str], ObjectAccessRecord] = {}
_OBJECT_AUTHORIZATION_EVENTS: list[dict[str, Any]] = []


def generate_secure_object_id(prefix: str) -> str:
    """Generate an opaque, cryptographically strong object identifier."""
    return f"{prefix}-{token_urlsafe(24)}"


def _key(object_type: str, object_id: str) -> tuple[str, str]:
    return object_type.strip().lower(), object_id.strip()


def get_object_access(object_type: str, object_id: str) -> ObjectAccessRecord | None:
    """Return access metadata without creating an object."""
    return _OBJECT_ACCESS.get(_key(object_type, object_id))


def _record_authorization_event(
    *,
    principal: RequestPrincipal,
    object_type: str,
    object_id: str,
    action: str,
    decision: str,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    access = _OBJECT_ACCESS.get(_key(object_type, object_id))
    event = {
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "surface": "object-authorization",
        "principal_id": principal.principal_id,
        "actor": principal.actor,
        "authenticated": principal.authenticated,
        "object_type": object_type,
        "object_id": object_id,
        "parent_object_type": access.parent_object_type if access is not None else "",
        "parent_object_id": access.parent_object_id if access is not None else "",
        "action": action,
        "decision": decision,
        "reason": reason,
        "request_id": request_id,
    }
    _OBJECT_AUTHORIZATION_EVENTS.append(event)
    return event


def object_authorization_events(
    *,
    object_type: str | None = None,
    object_id: str | None = None,
    parent_object_type: str | None = None,
    parent_object_id: str | None = None,
    principal_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent object-authorization decisions matching the filters."""
    events = _OBJECT_AUTHORIZATION_EVENTS
    if object_type is not None:
        events = [event for event in events if event["object_type"] == object_type]
    if object_id is not None:
        events = [event for event in events if event["object_id"] == object_id]
    if parent_object_type is not None:
        events = [event for event in events if event["parent_object_type"] == parent_object_type]
    if parent_object_id is not None:
        events = [event for event in events if event["parent_object_id"] == parent_object_id]
    if principal_id is not None:
        events = [event for event in events if event["principal_id"] == principal_id]
    return events[-max(1, limit) :]


def authorize_object(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    action: str,
    request_id: str,
    allow_claim: bool = False,
    parent_object_type: str = "",
    parent_object_id: str = "",
) -> ObjectAccessRecord:
    """Authorize access, optionally claiming an unowned object for the caller."""
    normalized_type, normalized_id = _key(object_type, object_id)
    if not normalized_id:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action=action,
            decision="deny",
            reason="empty object identifier",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("object identifier is required")

    record = _OBJECT_ACCESS.get((normalized_type, normalized_id))
    if record is None and allow_claim:
        record = ObjectAccessRecord(
            object_type=normalized_type,
            object_id=normalized_id,
            owner_principal=principal.principal_id,
            parent_object_type=parent_object_type.strip().lower(),
            parent_object_id=parent_object_id.strip(),
        )
        _OBJECT_ACCESS[(normalized_type, normalized_id)] = record
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action=action,
            decision="allow",
            reason="object claimed by principal",
            request_id=request_id,
        )
        return record

    if record is None:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action=action,
            decision="deny",
            reason="object is not registered for this principal",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("principal is not authorized for the target object")

    direct_allowed = (
        principal.is_admin
        or principal.principal_id == record.owner_principal
        or principal.principal_id in record.delegates
    )
    allowed = direct_allowed
    reason = (
        "administrator override"
        if principal.is_admin
        else "object owner"
        if principal.principal_id == record.owner_principal
        else "delegated object access"
        if principal.principal_id in record.delegates
        else "principal is not owner, delegate, or administrator"
    )

    if record.parent_object_type and record.parent_object_id:
        try:
            authorize_object(
                object_type=record.parent_object_type,
                object_id=record.parent_object_id,
                principal=principal,
                action=f"parent:{action}",
                request_id=request_id,
            )
            if not direct_allowed:
                allowed = True
                reason = "access inherited from authorized parent object"
        except ObjectAccessDeniedError:
            allowed = False
            reason = "principal is not authorized for the parent object"

    _record_authorization_event(
        principal=principal,
        object_type=normalized_type,
        object_id=normalized_id,
        action=action,
        decision="allow" if allowed else "deny",
        reason=reason,
        request_id=request_id,
    )
    if not allowed:
        raise ObjectAccessDeniedError("principal is not authorized for the target object")
    return record


def delegate_object_access(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    delegate_principal: str,
    request_id: str,
) -> ObjectAccessRecord:
    """Grant a principal access to an object; only owner/admin may delegate."""
    record = get_object_access(object_type, object_id)
    if record is None:
        authorize_object(
            object_type=object_type,
            object_id=object_id,
            principal=principal,
            action="delegate",
            request_id=request_id,
        )
        raise AssertionError("unreachable")
    if not principal.is_admin and principal.principal_id != record.owner_principal:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="delegate",
            decision="deny",
            reason="only owner or administrator may delegate access",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("only owner or administrator may delegate object access")
    normalized_delegate = delegate_principal.strip()
    if not normalized_delegate:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="delegate",
            decision="deny",
            reason="delegate principal is required",
            request_id=request_id,
        )
        raise ValueError("delegate principal is required")
    record.delegates.add(normalized_delegate)
    _record_authorization_event(
        principal=principal,
        object_type=record.object_type,
        object_id=record.object_id,
        action="delegate",
        decision="allow",
        reason=f"delegated access to {normalized_delegate}",
        request_id=request_id,
    )
    return record


def revoke_object_access(
    *,
    object_type: str,
    object_id: str,
    principal: RequestPrincipal,
    delegate_principal: str,
    request_id: str,
) -> ObjectAccessRecord:
    """Revoke delegated access; only owner/admin may revoke."""
    normalized_type, normalized_id = _key(object_type, object_id)
    record = get_object_access(normalized_type, normalized_id)
    if record is None:
        _record_authorization_event(
            principal=principal,
            object_type=normalized_type,
            object_id=normalized_id,
            action="revoke-delegate",
            decision="deny",
            reason="object is not registered for this principal",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("principal is not authorized for the target object")
    if not principal.is_admin and principal.principal_id != record.owner_principal:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="revoke-delegate",
            decision="deny",
            reason="only owner or administrator may revoke access",
            request_id=request_id,
        )
        raise ObjectAccessDeniedError("only owner or administrator may revoke object access")
    normalized_delegate = delegate_principal.strip()
    if not normalized_delegate:
        _record_authorization_event(
            principal=principal,
            object_type=record.object_type,
            object_id=record.object_id,
            action="revoke-delegate",
            decision="deny",
            reason="delegate principal is required",
            request_id=request_id,
        )
        raise ValueError("delegate principal is required")
    record.delegates.discard(normalized_delegate)
    _record_authorization_event(
        principal=principal,
        object_type=record.object_type,
        object_id=record.object_id,
        action="revoke-delegate",
        decision="allow",
        reason=f"revoked delegated access from {normalized_delegate}",
        request_id=request_id,
    )
    return record


def remove_object_access(object_type: str, object_id: str, *, cascade: bool = True) -> None:
    """Remove access metadata and optionally remove child object records."""
    normalized_type, normalized_id = _key(object_type, object_id)
    _OBJECT_ACCESS.pop((normalized_type, normalized_id), None)
    if cascade:
        child_keys = [
            key
            for key, record in _OBJECT_ACCESS.items()
            if record.parent_object_type == normalized_type and record.parent_object_id == normalized_id
        ]
        for child_type, child_id in child_keys:
            remove_object_access(child_type, child_id, cascade=True)


def reset_object_authorization_state() -> None:
    """Clear in-memory ACL and audit state for isolated tests."""
    _OBJECT_ACCESS.clear()
    _OBJECT_AUTHORIZATION_EVENTS.clear()
