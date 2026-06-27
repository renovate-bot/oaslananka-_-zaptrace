# REST API production hardening

ZapTrace REST is designed for local, CI, and controlled team deployments. Production use should enable explicit session IDs, scoped capabilities, optional bearer-token authentication, bounded request sizes, and artifact lifecycle controls.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ZAPTRACE_API_TOKEN` | Optional bearer token. When set, `/api/*` requests require `Authorization: Bearer <token>`. | unset |
| `ZAPTRACE_CORS_ORIGINS` | Comma-separated allowed browser origins. | `http://localhost:5173,http://localhost:8080` |
| `ZAPTRACE_API_ARTIFACT_ROOT` | Filesystem root for REST artifact storage. | `.zaptrace/api-artifacts` |
| `ZAPTRACE_API_ARTIFACT_RETENTION_SECONDS` | Artifact retention before cleanup. | `86400` |
| `ZAPTRACE_API_MAX_ARTIFACT_BYTES` | Maximum stored artifact payload size. | `5242880` |

## Authorization model

Mutating routes require an explicit `X-ZapTrace-Session-Id` and capability header. Capability decisions are recorded in the session audit log.

Examples:

- `preview-write`: parse/synthesize/register deterministic artifacts;
- `sandbox-write`: layout mutation, transaction validation, artifact deletion/cleanup;
- `approved-commit`: transaction commit after approval;
- `release-export`: KiCad/manufacturing export gates.

## Artifact lifecycle

The `/api/v1/artifacts` routes provide deterministic artifact metadata for CI and review workflows:

- `POST /api/v1/artifacts`: store UTF-8 content under a deterministic hash-prefixed artifact ID;
- `GET /api/v1/artifacts`: list artifacts for the active session;
- `DELETE /api/v1/artifacts/{artifact_id}`: delete one session artifact;
- `DELETE /api/v1/artifacts/expired`: remove expired artifacts according to retention policy;
- `GET /api/v1/artifacts/config`: expose storage configuration for clients and smoke tests.

Artifact records include `sha256`, `size_bytes`, `created_at`, `retention_seconds`, and a root-relative path. The API does not claim cloud storage, multi-tenant isolation, or procurement/manufacturing approval.

## OpenAPI contract

`/openapi.json` is part of the CI surface. Tests assert that hardened routes and artifact lifecycle endpoints remain visible to clients.
