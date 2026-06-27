# Agent Runtime Threat Model

Status: v0.2.3 M0 release-gate hardening  
Scope: MCP server, REST API, in-memory sessions, file-export surfaces, and proof/audit evidence

ZapTrace is an agent-facing EDA runtime. Agent clients can create or mutate hardware designs, place and route boards, export manufacturing artifacts, and run verification workflows. This document treats MCP and REST as controlled capability surfaces rather than trusted local helper APIs.

## Security objectives

1. Deny mutating operations unless an explicit capability grant is present.
2. Keep all file I/O inside the configured workspace sandbox.
3. Record who/what/when/why audit evidence for mutating or release-export operations.
4. Make blocked operations observable through structured errors and audit events.
5. Avoid implying that generated manufacturing output is safe without engineering review.

## Trust boundaries

| Boundary | Trusted? | Notes |
|---|---:|---|
| Core Python process | Yes | In-process policy enforcement and session store. |
| MCP client / LLM agent | No | May be prompt-injected, confused, or over-scoped. |
| REST caller | No | Must provide session and capability headers for writes. |
| Workspace files | Partially | Paths must resolve under the workspace root. |
| External tools / plugins | No | Must be treated as separate capability subjects in later issues. |
| Manufacturing artifacts | No | Must be checked and human-reviewed before use. |

## Capability model

ZapTrace uses an ordered capability ladder:

| Capability | Intended operations | Examples |
|---|---|---|
| `read` | Inspection only | library search, ERC rules, design inspect, audit read |
| `preview-write` | In-memory candidate creation | parse design, synthesize, run pipeline candidate |
| `sandbox-write` | In-memory mutation or sandbox file preview | component add/remove, board update, place, route, report/SVG write |
| `approved-commit` | Explicit confirmation of a design state | design commit |
| `release-export` | Manufacturing or release artifact generation | KiCad, Gerber, Excellon, manufacturing bundle |

Read-only operations are public by process policy. Every non-read operation is deny-by-default unless the caller presents a capability at the required level or higher. Release-export tools additionally require a non-empty `approval_id` and fresh passing validation evidence for the current design state before artifacts are emitted.

## Threats and controls

| Threat | Impact | Current control |
|---|---|---|
| Confused deputy agent calls write/export tool after prompt injection | Design mutation or unsafe release artifacts | Capability-gated write/export operations; audit event with actor/tool/reason. |
| Missing or fixed session on mutating REST call | Cross-client state confusion | Mutating REST endpoints require `X-ZapTrace-Session-Id`. |
| Token/capability misuse | Over-scoped operations | Capability headers are explicit and recorded in audit metadata. Future work should replace headers with signed grants. |
| Workspace escape / path traversal | Arbitrary file read/write | Shared path validation rejects resolved paths outside workspace. |
| Unsafe manufacturing export | False confidence or accidental fab submission | `release-export` capability required; export tools also require fresh passing validation evidence plus a non-empty `approval_id`. |
| MCP session overreach | LLM writes without explicit grant | MCP session capabilities default to empty; write tools are denied and audited. |
| REST unauthorized write | Remote mutation | REST dependency denies missing session or missing capability before tool execution. |
| Missing evidence for decisions | Cannot reconstruct incident | Audit events include timestamp, surface, session, actor, tool, capability, decision, reason. |
| SSRF-like URL access | Remote data exfiltration | Current agent tools do not accept arbitrary remote URLs; future network tools must declare separate capability. |
| Unsafe subprocess/tool execution | Host compromise | Current MCP wrapper does not expose generic shell execution; future plugins require signed manifests and deny-by-default admission. |

## Required runtime evidence

For each mutating or release-export operation, ZapTrace records an audit event in the session:

```json
{
  "surface": "rest",
  "session_id": "api-allowed-session",
  "actor": "pytest",
  "tool": "design_parse_str",
  "capability": "preview-write",
  "decision": "allow",
  "reason": "audit allow example"
}
```

Denied requests are also recorded:

```json
{
  "surface": "mcp",
  "tool": "design_parse_str",
  "capability": "preview-write",
  "decision": "deny",
  "reason": "missing required capability: preview-write"
}
```

REST audit events are available at:

```text
GET /api/v1/audit/events
X-ZapTrace-Session-Id: <session-id>
```

MCP audit evidence is available through:

```text
zaptrace://audit/events
```

## Current limitations

- Capability grants are explicit runtime headers/session values, not cryptographically signed grants.
- Audit storage is in-memory and process-local.
- Plugin/tool admission, signed manifests, and persistent audit logs are tracked separately.
- This policy does not certify generated hardware output; it only controls agent/runtime authority.
