# Issue 279 Capability Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 93 public agent tools explicitly classified, make unknown tools fail closed, enforce filesystem policy from registry metadata, and place `synthesize_board_manufacture` behind the standard release gate.

**Architecture:** Keep capability policy in `zaptrace.security.policy` as the single source of truth, validate exact registry-policy equality during `_tool_impls` import, and attach validated capability metadata to each registry entry. Move MCP path enforcement from parameter-name heuristics to explicit per-parameter `path_policy` metadata. Reuse the existing design-state hash and release gate for the synthesis-to-manufacturing path, ensuring the exact synthesized design is stored, validated, approved, and exported.

**Tech Stack:** Python 3.12, pytest, FastMCP wrapper integration, existing ZapTrace ERC/DRC/export pipeline, generated Markdown/JSON policy evidence.

## Global Constraints

- Preserve all 93 public tool names and existing non-security parameter contracts except adding `approval_id` to `synthesize_board_manufacture`.
- Unknown or newly added public tools must fail registration instead of inheriting `read`.
- Path enforcement must use explicit schema metadata, not parameter-name matching.
- User-selected paths must remain inside `ZAPTRACE_WORKSPACE` / the configured MCP export root.
- Manufacturing artifacts must not be written before capability, path, current-state validation, and approval checks pass.
- Broader fabrication evidence semantics tracked by #280 remain out of scope.

---

### Task 1: Explicit fail-closed capability inventory

**Files:** `tests/test_security_policy.py`, `zaptrace/security/policy.py`, `zaptrace/agent/_tool_impls.py`

- [ ] Add failing tests for exact registry-policy equality and unknown-tool rejection.
- [ ] Expand the capability inventory to all 93 public tools using least privilege.
- [ ] Validate exact set equality at import and remove all implicit `read` fallbacks.
- [ ] Run targeted tests and commit.

### Task 2: Explicit path-policy schema and enforcement

**Files:** `tests/test_mcp_server.py`, `tests/test_security_policy.py`, `zaptrace/agent/_tool_impls.py`, `zaptrace/mcp/server.py`

- [ ] Add failing tests for `output_dir` escape, safe output, and non-path `fab_profile`.
- [ ] Add per-parameter `path_policy` metadata for every current filesystem input/output.
- [ ] Replace the path/file substring heuristic with metadata-driven validation.
- [ ] Add registry policy-shape tests and commit.

### Task 3: Gate synthesis-to-manufacturing

**Files:** `tests/test_security_policy.py`, `tests/test_mcp_server.py`, `zaptrace/agent/_tool_impls.py`, `zaptrace/synthesis/fab.py`

- [ ] Add failing tests for missing approval, path escape, release-export capability, and no artifact creation for read-only callers.
- [ ] Export the exact synthesized/stored/validated design rather than synthesizing a second design.
- [ ] Require current ERC/DRC evidence and the standard release gate before artifact emission.
- [ ] Run targeted tests and commit.

### Task 4: Auditable policy documentation

**Files:** `scripts/generate_mcp_docs.py`, `scripts/generate_tool_policy_matrix.py`, `docs/mcp/tools-reference.md`, `docs/reports/tool-policy-matrix.json`, `tests/test_docs_status_sync.py`

- [ ] Add freshness/schema tests.
- [ ] Expose capability and path policy in generated Markdown.
- [ ] Generate deterministic JSON policy inventory.
- [ ] Regenerate evidence, test, and commit.

### Task 5: Verification and PR

- [ ] Run Ruff, targeted tests, full available tests, generated-doc checks, and `git diff --check`.
- [ ] Push branch and open a PR with `Closes #279` plus test/risk evidence.
