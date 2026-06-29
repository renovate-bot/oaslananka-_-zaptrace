# ZapTrace Roadmap

## Vision

ZapTrace is an AI-native, verification-first EDA kernel that turns design intent
into reviewable schematic, PCB, manufacturing, and proof artifacts — usable
entirely from an agent or a terminal, with **no GUI and no EDA tool as a runtime
dependency**.

The long-range goal is an engine where an agent can carry a professional board
**from intent to fabrication-grade output end to end** — synthesize the
topology, size every value, place, route, verify, and package — and hand a human
reviewer an auditable evidence pack instead of an unexplained file dump.

"Flawless" and "fully autonomous" are an asymptote, not a shipping claim. The
engineering target is concrete: the agent produces a *complete candidate* that
passes simulation and rule checks in a closed loop, with every decision
justified, so the only remaining step is human sign-off — not human authoring.
ZapTrace is not a fabrication guarantee, not a substitute for engineering
judgment, and every output requires human review before fabrication.

## Current State — 2026-06-29

ZapTrace already spans the full pipeline; the gap is **maturity and loop
closure**, not missing stages. What exists today, characterized honestly:

| Stage | What is real today | Honest limitation |
|-------|--------------------|-------------------|
| Intent → requirements | Structured requirements extraction, assumption register, conflict detector, freeze gate | Heuristic NL parsing; not a planner |
| Synthesis | **Template selection** + parametric blocks (power-tree, decoupling, USB-C CC, buck L/C, LDO) and a calculator library | No from-scratch topology synthesis; closes only the power-tree path |
| ERC | 29 connectivity-precise rules over an electrical graph, coverage reporting | Rules catch known faults only; no functional/timing proof |
| Placement / routing | Constraint-aware placement, grid + net-aware routing, copper pour | Grid router; no push-and-shove, length-match, or controlled-impedance routing in the loop |
| DRC | 16 geometric rules, fab-profile-aware | Geometry only; not a manufacturability guarantee |
| Analysis | Deterministic textbook SI timing, thermal, impedance (IPC-2141), DfT, mechanical, EMC pre-check | Estimates, not field solvers or CFD |
| Simulation | ngspice **DC operating-point**, skip-aware orchestrator | No transient/AC; device models absent; optional, not a gate |
| Supply | BOM intelligence provider interface; DigiKey/Mouser/TME/Farnell adapters | Fixture-backed, not live API |
| Export | Gerber, Excellon, BOM, PnP, KiCad, SVG, IPC-2581/ODB++ foundation | KiCad export one-way |
| Verification evidence | Proof-pack runner + manifest, KiCad Oracle (optional), fab profiles | Proof pack experimental; oracle skippable |
| Surfaces | Python SDK, CLI, REST API, MCP server (77 tools) | — |
| Library | ~82 parts | Far short of professional breadth |

The README status table and this section are the source of truth; no claim of
fabrication or production readiness is made.

## The Gap to the Vision

Seven gaps separate "broad pipeline that runs" from "agent completes a
professional board end to end." The milestones below are organized around
closing them. Detailed technical design lives in
[docs/design/autonomous-synthesis.md](design/autonomous-synthesis.md).

1. **From-scratch synthesis** — replace template selection with requirement-driven
   parametric block composition (topology + values), beyond the power path.
2. **Simulation as a gate** — make DC/transient SPICE a bundled, blocking check,
   not an optional skip; add the device models the orchestrator lacks.
3. **Professional routing** — differential pairs, length matching, controlled
   impedance, and push-and-shove inside the routing loop.
4. **Convergent self-correction** — ERC/DRC/sim failure → automatic patch →
   re-verify, with measured convergence, not just a diagram.
5. **Authoritative internal engines** — internal ERC/DRC/sim become the
   authority so KiCad is an optional second opinion, removing the dependency.
6. **Library depth + live supply** — thousands of IPC-7351-compliant parts and
   live distributor data behind the existing provider interface.
7. **A benchmark that measures "flawless"** — a release-blocking harness scoring
   pass-rate against real, fabricable reference designs.

## Milestones

### M1 — Synthesis & Simulation Loop (closes gaps 1, 2, 4)

**Goal:** an agent states an intent and gets a *complete, simulated* candidate
design back, not a template.

- Requirement-driven block-composition synthesis beyond the power tree
  (signal-chain, MCU support circuitry, interface blocks).
- Bundled ngspice path (container) with a curated device-model set; DC + transient
  operating checks promoted to a **blocking** evidence gate.
- Closed synthesize → ERC → sim → patch → re-verify loop with a measured
  convergence rate and a hard iteration/termination policy.

**Exit:** for a bounded class of boards, the loop produces a candidate that
passes internal ERC and DC/transient sim without human edits, with a decision
log explaining every value and stage.

### M2 — Routing & Manufacturing Fidelity (closes gaps 3, 5)

**Goal:** layouts and outputs are professional-grade and self-authoritative.

- Routing upgrades: differential-pair routing, length matching, controlled
  impedance fed from the IPC-2141 engine, and push-and-shove or rip-up-and-retry.
- Internal ERC/DRC/sim declared the authority; KiCad Oracle reframed as an
  optional cross-check, with fidelity scorecards instead of a dependency.
- IPC-2581 / ODB++ evidence exports hardened from foundation to release-ready.

**Exit:** a routed board passes internal DRC and a controlled-impedance check;
KiCad Oracle, when present, agrees within a recorded tolerance.

### M3 — Library, Supply & Benchmark (closes gaps 6, 7)

**Goal:** breadth and proof that the engine is actually good.

- Library scaled toward professional breadth with IPC-7351-compliant footprints
  and provenance.
- Live distributor adapters behind the existing provider interface, with
  lifecycle/alternates/cache and a BOM risk gate.
- A release-blocking benchmark harness scoring complete designs against
  fabricable reference projects (pass-rate, not a single smoke test).

**Exit:** the benchmark runs in CI as a release gate; regressions in synthesis,
routing, or verification quality block a release.

### M4 — Autonomy & Sign-off Discipline

**Goal:** multiple candidates, bounded permissions, enterprise-grade evidence.

- Specialist-agent orchestration generating and scoring multiple candidates on
  verifiable evidence.
- Long-running workflow checkpoint/resume/rollback; deny-by-default signed plugin
  admission with an audit trail.
- Sign-off policy separating pass/fail evidence, warnings, skipped checks, and
  mandatory human-review items.

**Exit:** an agent produces scored candidates under bounded permissions, and the
proof pack cleanly separates what was verified from what still needs a human.

## Non-Goals

ZapTrace will not claim to be:

- A full replacement for an interactive PCB editor (KiCad, Altium, Eagle) — it is
  a backend engine, not a GUI.
- A fully autonomous production sign-off authority.
- A field solver or a substitute for lab compliance testing.
- A substitute for human engineering review.
- A manufacturer approval system.

## Milestone Table

| Milestone | Status | Theme | Closes gaps |
|-----------|--------|-------|-------------|
| Foundation | ✅ Shipped | Full pipeline, exports, MCP/REST/CLI, proof-pack scaffold | — |
| M1 | ▶ Active | Synthesis & simulation loop | 1, 2, 4 |
| M2 | Planned | Routing & manufacturing fidelity | 3, 5 |
| M3 | Planned | Library, supply & benchmark | 6, 7 |
| M4 | Planned | Autonomy & sign-off discipline | — |

## How to Contribute

See [CONTRIBUTING.md](../CONTRIBUTING.md) and
[docs/strategy/triage-policy.md](strategy/triage-policy.md). For the technical
design behind the milestones, see
[docs/design/autonomous-synthesis.md](design/autonomous-synthesis.md).
