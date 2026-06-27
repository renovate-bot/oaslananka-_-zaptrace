from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zaptrace.plugin import (
    PluginCapability,
    admit_plugin_manifest,
    discover_plugin_manifests,
    generate_plugin_manifest_schema,
    load_plugin_manifest,
)

VALID = Path("tests/fixtures/plugins/valid")
UNSIGNED = Path("tests/fixtures/plugins/unsigned")
OVERBROAD = Path("tests/fixtures/plugins/overbroad")
INCOMPATIBLE = Path("tests/fixtures/plugins/incompatible")
MALFORMED = Path("tests/fixtures/plugins/malformed")
SCHEMA = Path("schemas/plugin-manifest-v1.schema.json")


def test_valid_plugin_manifest_loads_and_generates_schema_contract() -> None:
    manifest = load_plugin_manifest(VALID)

    assert manifest.plugin_id == "dev.zaptrace.examples.hello-analyzer"
    assert manifest.entry.type == "python_module"
    assert [cap.value for cap in manifest.capabilities] == ["design:read", "proof:read", "host:log"]

    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert committed == generate_plugin_manifest_schema()


def test_plugin_discovery_is_deterministic_when_no_plugins_are_installed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert discover_plugin_manifests([]) == []
    assert discover_plugin_manifests([missing]) == []
    assert [item.plugin_id for item in discover_plugin_manifests([VALID])] == ["dev.zaptrace.examples.hello-analyzer"]


def test_signed_trusted_plugin_is_admitted_and_audited() -> None:
    session: dict[str, object] = {}
    manifest = load_plugin_manifest(VALID)

    result = admit_plugin_manifest(
        manifest,
        trusted_fingerprints={"sha256:dev-fixture"},
        audit_session=session,
        session_id="plugin-test-session",
        actor="pytest",
    )

    assert result.allowed is True
    assert result.code == "PLUGIN_ADMITTED"
    assert result.agent_capability == "read"
    assert result.audit_event is not None
    assert result.audit_event["decision"] == "allow"
    assert result.audit_event["metadata"]["plugin_id"] == manifest.plugin_id
    assert session["audit_events"][-1]["tool"] == "plugin_admission"


def test_unsigned_plugin_is_rejected_by_default_and_audited() -> None:
    session: dict[str, object] = {}
    manifest = load_plugin_manifest(UNSIGNED)

    result = admit_plugin_manifest(manifest, audit_session=session)

    assert result.allowed is False
    assert result.code == "PLUGIN_SIGNATURE_REQUIRED"
    assert result.audit_event is not None
    assert result.audit_event["decision"] == "deny"
    assert result.audit_event["metadata"]["code"] == "PLUGIN_SIGNATURE_REQUIRED"


def test_overbroad_permissions_are_rejected_with_actionable_error() -> None:
    manifest = load_plugin_manifest(OVERBROAD)

    result = admit_plugin_manifest(manifest, trusted_fingerprints={"sha256:dev-fixture"})

    assert result.allowed is False
    assert result.code == "PLUGIN_PERMISSION_MISMATCH"
    assert "filesystem write paths require filesystem:write" in result.message


def test_dangerous_capabilities_require_explicit_admission() -> None:
    manifest = load_plugin_manifest(VALID)
    patched = manifest.model_copy(
        update={"capabilities": [PluginCapability.DESIGN_READ, PluginCapability.SUBPROCESS_RUN]}
    )
    patched = type(manifest).model_validate(patched.model_dump(mode="json", by_alias=True))

    result = admit_plugin_manifest(patched, trusted_fingerprints={"sha256:dev-fixture"})

    assert result.allowed is False
    assert result.code == "PLUGIN_DANGEROUS_CAPABILITY_DENIED"
    assert "subprocess:run" in result.message


def test_incompatible_plugin_version_fails_with_current_version_message() -> None:
    manifest = load_plugin_manifest(INCOMPATIBLE)

    result = admit_plugin_manifest(manifest, trusted_fingerprints={"sha256:dev-fixture"})

    assert result.allowed is False
    assert result.code == "PLUGIN_VERSION_INCOMPATIBLE"
    assert "current version" in result.message


def test_malformed_plugin_manifest_is_rejected_before_admission() -> None:
    with pytest.raises(ValidationError):
        load_plugin_manifest(MALFORMED)
