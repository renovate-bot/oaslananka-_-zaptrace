"""Secure-by-default network transport configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from ipaddress import ip_address

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NetworkAuthConfiguration:
    """Resolved authentication posture for a network-facing transport."""

    surface: str
    host: str
    loopback: bool
    authentication_configured: bool
    local_development: bool

    @property
    def mode(self) -> str:
        if self.authentication_configured:
            return "authenticated"
        if self.local_development:
            return "loopback-development"
        return "loopback-read-only"


def environment_flag(name: str) -> bool:
    """Return whether an environment flag is explicitly enabled."""
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def is_loopback_host(host: str) -> bool:
    """Return whether *host* is an explicit loopback bind target."""
    normalized = host.strip().lower().strip("[]")
    if normalized in {"localhost", "ip6-localhost"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_network_auth_configuration(
    *,
    surface: str,
    host: str,
    token: str,
    allow_local_development: bool = False,
) -> NetworkAuthConfiguration:
    """Validate a network bind/authentication combination.

    Non-loopback binds require an authentication token. Local-development
    bypasses are accepted only for explicit loopback targets.
    """
    if not host.strip():
        raise RuntimeError(f"{surface} bind host must not be empty")

    loopback = is_loopback_host(host)
    authentication_configured = bool(token)
    if not loopback and not authentication_configured:
        raise RuntimeError(
            f"{surface} refuses non-loopback bind {host!r} without authentication; "
            "configure the transport bearer token or bind to 127.0.0.1/::1"
        )
    if not loopback and allow_local_development:
        raise RuntimeError(
            f"{surface} local-development authorization is restricted to loopback binds; "
            f"disable the local-development override before binding to {host!r}"
        )

    return NetworkAuthConfiguration(
        surface=surface,
        host=host,
        loopback=loopback,
        authentication_configured=authentication_configured,
        local_development=loopback and allow_local_development,
    )
