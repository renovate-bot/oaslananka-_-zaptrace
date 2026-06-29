# ZapTrace Roadmap

## Vision

ZapTrace is an AI-native, verification-first EDA kernel for transforming design intent into reviewable schematic, PCB, manufacturing, and proof artifacts. It is not a fabrication guarantee, a SPICE simulator, or a replacement for human engineering judgment. All outputs require human review before fabrication.

## Current Baseline — 2026-06-19

**Released baseline:** `0.2.2` — verification foundation and safety hardening.

Implemented foundation:

- Design parsing, template synthesis, ERC, DRC, placement, routing, copper pour, Gerber/Excellon/BOM/PnP/KiCad/SVG exports.
- Manufacturing ZIP bundle, REST API, MCP server, design diff, and full autopilot pipeline.
- Proof-pack runner, manifest model, CLI/API/MCP entry points, and validation smoke checks.
- KiCad Oracle integration as an optional external evidence layer when `kicad-cli` is available.
- Fab-profile DFM foundation for manufacturer capability presets and profile-based checks.
- Export regression corpus and dedicated hardware CI workflow scaffolding.

Current limitations:

- Proof packs are still experimental until deterministic evidence, external-tool records, and release gates are enforced.
- KiCad Oracle and hardware CI can be skipped when external binaries are unavailable; skipped evidence must become explicit release evidence.
- KiCad export is still mostly one-way; round-trip fidelity is not yet measured.
- No Review Studio UI, no autonomous candidate scoring loop, no signed plugin admission, and no enterprise signoff policy.
- No claim of fabrication readiness, production readiness, manufacturer approval, or fully autonomous correctness.

## M0 / v0.2.3 — Verification Gate Stabilization

**Goal:** make the current feature set auditable and release-gated before expanding autonomy.

Primary issues:

- Reconcile README, ROADMAP, CHANGELOG, audit docs, and old issue status.
- Add GitHub issue templates, triage policy, and release-board conventions.
- Define the v0.2.3 verification gate matrix and blocker criteria.
- Add MCP and REST threat-model tests, scoped capability allowlists, and audit evidence.
- Make KiCad Oracle evidence mandatory-or-explicitly-skipped in CI and proof packs.
- Define canonical hardware IR and constraint graph.
- Add transaction-safe design state, diff, and rollback.
- Define agent permission model and capability levels.
- Define KiCad import and round-trip fidelity.

Exit criteria:

- Every release-critical check has an owner, command, expected evidence artifact, and blocking policy.
- Skipped external checks are explicit, visible, and not silently treated as pass.
- Open and closed issue status matches the actual code and documentation state.
- P0 issue templates and triage labels are used consistently.

## M1 / v0.3 — Manufacturing Intelligence and Review Studio

**Goal:** move from local generation to reviewable manufacturing evidence.

Primary issues:

- BOM intelligence provider interface.
- ODB++ / IPC-2581 manufacturing evidence exports.
- Review Studio product spec.
- ESP32 benchmark project 001 agent flow.
- KiCad round-trip fidelity scorecard corpus.
- External manufacturing evidence adapters.
- BOM provenance, alternates, cache, and lifecycle risk model.
- Release-blocking ESP32 benchmark harness.

Exit criteria:

- A bounded professional benchmark can produce schematic, PCB, BOM, manufacturing outputs, and proof-pack evidence.
- Manufacturing evidence is generated as evidence, not a guarantee.
- Review Studio has a clear evidence model and UX specification.

## M2 / v0.4 — Autonomous Candidate Generation

**Goal:** generate and compare multiple design candidates safely.

Primary issues:

- Specialist agent orchestration and candidate generation.
- Long-running agent workflow checkpoint, resume, and failure recovery.
- Signed plugin manifest, tool admission, and deny-by-default permissions.
- Plugin API and external integrations.

Exit criteria:

- Agents generate multiple candidates with bounded permissions, checkpointing, and rollback.
- Candidates are scored using verifiable evidence rather than opaque claims.
- Plugin/tool admission defaults to deny and records an audit trail.

## M3 / v1.0 — Enterprise Signoff and Cross-EDA Readiness

**Goal:** make ZapTrace usable in enterprise human-reviewed workflows.

Primary issues:

- Signal integrity and EMC heuristics.
- Enterprise signoff and cross-EDA readiness epic.
- Altium, Eagle, and EasyEDA import-export fidelity targets and degradation reports.

Exit criteria:

- Signoff policy separates pass/fail evidence, warnings, skipped checks, and human-review requirements.
- Cross-EDA conversions have fidelity metrics and known-degradation reports.
- Public messaging remains verification-first and avoids fabrication-ready or no-review claims.

## Non-Goals

ZapTrace will not claim to be:

- A full replacement for KiCad, Altium, or Eagle.
- A fully autonomous production signoff authority.
- A SPICE simulator.
- A substitute for human engineering review.
- A manufacturer approval system.

## Milestone Table

| Milestone | Status | Theme |
|-----------|--------|-------|
| v0.2.0 | ✅ Complete | Core EDA/export foundation |
| v0.2.1 | ✅ Complete | Proof-pack scaffold and CI hardening |
| v0.2.2 | ✅ Complete | Verification foundation and safety hardening |
| M0 / v0.2.3 | Active | Verification gate stabilization |
| M1 / v0.3 | Planned | Manufacturing intelligence and Review Studio |
| M2 / v0.4 | Planned | Autonomous candidate generation |
| M3 / v1.0 | Planned | Enterprise signoff and cross-EDA readiness |

## How to Contribute

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [docs/strategy/triage-policy.md](strategy/triage-policy.md). For release-blocking work, use [docs/releases/v0.2.3-verification-gate.md](releases/v0.2.3-verification-gate.md).
