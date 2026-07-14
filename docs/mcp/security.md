# MCP Security

## Workspace Sandboxing

ZapTrace MCP tools operate within a sandboxed workspace. All file I/O is
restricted to the workspace root directory to prevent path-traversal attacks.

### Allowed Directories

- The workspace root (typically the project directory)
- `ZAPTRACE_WORKSPACE` environment variable overrides the default workspace
- Subdirectories of the workspace root are accessible

### Path Validation

Every tool that accepts a file path enforces the following checks:

1. The resolved absolute path must start with the workspace root
2. Symlinks are not followed outside the workspace
3. `..` segments are rejected if they escape the workspace
4. Absolute paths outside the workspace are rejected

### Capability Restrictions

| Tool Category | Sandboxed? | Notes |
|---|---|---|
| Design I/O | Yes | File paths must be within workspace |
| Export | Yes | Output files must be within workspace |
| Library | No | Read-only, no file access |
| ERC/DRC | No | Operates on in-memory design only |
| Pipeline | No | Operates on in-memory data only |

## Input Validation

- All string parameters are length-limited to 10,000 characters
- `yaml_content` is parsed by a safe YAML loader (no arbitrary code execution)
- Integer/float parameters are range-checked where applicable

## Error Handling

Tools return structured JSON error envelopes. Error messages never include
internal paths, stack traces, or sensitive configuration values.


## Deny-by-Default Capability Policy

ZapTrace gates every mutating or release-export MCP/REST operation with an explicit capability level.

| Capability | Purpose |
|---|---|
| `read` | Inspection-only tools. |
| `preview-write` | In-memory candidate creation, such as parse/synthesize/pipeline candidate runs. |
| `sandbox-write` | In-memory mutation and sandboxed preview writes, such as placement, routing, board edits, report/SVG writes. |
| `approved-commit` | Explicit confirmation of a design state. |
| `release-export` | KiCad, Gerber, Excellon, and manufacturing artifact generation. |

MCP sessions default to no write capability. Session capability grants require an explicit loopback-development opt-in; trusted automation uses server-controlled capabilities. REST mutation uses authenticated token scopes or the separately enabled loopback-only capability-header mode. See [Network transport authentication](../security/network-transport-authentication.md).

`release-export` is a two-part gate: callers must have the `release-export` capability and must pass an `approval_id` for a design state that has fresh passing ERC validation. If DRC has been run for that state, it must also be passing. Exported responses include the `release_gate` evidence used for the decision.

Denied write/export calls return `OPERATION_NOT_AUTHORIZED` and write an audit event. Release gates that fail after authorization return a user-facing validation or approval error and do not emit artifacts.

## Audit Evidence

Every mutating or release-export policy decision records an event with timestamp, surface, session, actor, tool, required capability, decision, reason, and request metadata. REST events are exposed at `/api/v1/audit/events`; MCP events are exposed as `zaptrace://audit/events`.

The full runtime threat model is tracked in [`docs/security/agent-runtime-threat-model.md`](../security/agent-runtime-threat-model.md).
