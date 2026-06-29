# ZapTrace Review Studio Product Spec and UX Contract

Status: v0.2 product contract  
Primary goal: human-in-the-loop review of agentic EDA changes, not a full schematic or PCB editor.

## Product Positioning

Review Studio is the surface where a person reviews evidence before accepting a design mutation, release export, or manufacturing handoff. It should make hidden state impossible: every agent proposal must be connected to a semantic diff, validation result, proof-pack record, BOM risk finding, and explicit approval or rollback action.

Review Studio is deliberately narrower than KiCad, Altium, or a browser PCB editor. It is a verification and approval workbench for agent-generated work.

## Target Users

| User | Primary need | Review Studio job |
|---|---|---|
| Hardware engineer | Confirm proposed schematic, PCB, DFM, and BOM changes | Review semantic/visual diffs, inspect violations, approve or reject transactions |
| Firmware engineer | Confirm pinout, boot/debug, buses, and power assumptions | Inspect net-level changes, connector maps, generated docs, and validation evidence |
| Founder/prototyper | Understand readiness and risk without becoming an EDA expert | See release blockers, non-claims, estimated risk, and next actions |
| CI reviewer | Review pull request artifacts and release gates | Open a static bundle with scorecards, proof-pack hashes, and blocking failures |
| Enterprise reviewer | Audit provenance, approvals, and security boundaries | Trace decisions, approvals, tool outputs, and local/hosted data boundaries |

## Non-Goals for v0.1/v0.2

Review Studio must not try to be:

- a full interactive PCB editor;
- a manual routing environment;
- a full schematic capture replacement;
- a fabrication approval authority;
- a no-human-review autonomous signoff system;
- a clone of KiCad or Altium in the browser.

When editing is needed, Review Studio should send users back to the source EDA tool or to a controlled agent transaction rather than allowing free-form hidden mutation.

## Core UX Principles

1. **Evidence before approval.** Approval controls are disabled until required gates are visible.
2. **Diff-first review.** Every proposed write starts from “what changed?” rather than “what was generated?”.
3. **No hidden mutation.** UI state reflects committed transaction state, pending proposal state, and rollback targets separately.
4. **Risk is explicit.** Unsupported features, stale cache, skipped external tools, and non-claims are displayed as first-class review items.
5. **Static artifacts are first-class.** A CI reviewer should be able to open a static bundle without running ZapTrace services.

## Core Screens

### 1. Project Overview

Purpose: summarize current design state, release readiness, open blockers, and latest agent proposal.

Required widgets:

- project metadata and design hash;
- active branch/session/transaction id;
- release gate status;
- proof-pack status;
- latest ERC/DRC/DFM/BOM/KiCad oracle result;
- non-claims and required human-review warnings.

### 2. Agent Plan and Transaction Timeline

Purpose: show what the agent intended, what it changed, and where rollback is possible.

Required widgets:

- agent plan steps;
- transaction timeline with pending, validated, approved, committed, rejected, and rolled-back states;
- per-transaction state hash;
- approval id and approver metadata;
- rollback target selector.

Alignment with the canonical hardware-IR and agent-permission-model work:

- write operations appear as transactions;
- commit requires explicit approval id;
- release-export actions require permission-scoped capability and validation evidence;
- rejected or failed transactions remain visible as audit evidence.

### 3. Schematic / Design Semantic Diff

Purpose: make logical changes reviewable without requiring PCB-editor expertise.

Required widgets:

- added/removed/changed components;
- net connectivity changes;
- pin/function changes;
- constraints and variant changes;
- generated explanation from the agent;
- machine-readable diff artifact link.

### 4. PCB / Layer Visual Diff

Purpose: show board-level change evidence without building a full PCB editor.

Required widgets:

- board outline and layer preview;
- copper/layer change overlays where available;
- placement changes;
- routing changes;
- unsupported visual fidelity degradations;
- link to native KiCad artifacts.

### 5. ERC / DRC / DFM Panel

Purpose: show whether design correctness and manufacturing constraints block release.

Required widgets:

- ERC summary and violations;
- DRC summary and violations;
- DFM summary by fab profile;
- severity filter;
- blocker/warning classification;
- external tool skip reasons.

### 6. BOM and Supply-Chain Risk Panel

Purpose: prevent release confidence when required parts are unavailable, obsolete, stale, or risky.

Required widgets:

- BOM table with ref, MPN, manufacturer, distributor part number, lifecycle, stock, and price break data;
- provider and cache provenance;
- stale/offline/cache-miss indicators;
- alternates;
- risk score and release-blocking flags;
- compliance flags where available.

### 7. Fab Profile / Manufacturing Export Panel

Purpose: connect outputs to manufacturing evidence, not just file generation.

Required widgets:

- selected fab profile;
- Gerber/Excellon/BOM/pick-and-place/stackup/manifest artifacts;
- artifact hashes;
- Gerber/Excellon smoke validation;
- ODB++ and IPC-2581 evidence attachment status;
- manufacturing non-claims.

### 8. Proof-Pack Viewer

Purpose: present audit evidence as the release review source of truth.

Required widgets:

- manifest metadata;
- input record;
- environment/tool versions;
- artifact list with hashes;
- check records;
- KiCad oracle evidence;
- transaction history;
- BOM provenance;
- manufacturing evidence;
- limitations and non-claims.

### 9. Approve / Reject / Rollback / Commit Controls

Purpose: make human intent explicit.

Required controls:

- approve proposal;
- reject proposal with reason;
- rollback to selected transaction hash;
- commit approved transaction;
- export proof bundle;
- copy approval id.

Controls must show why they are disabled, such as missing validation evidence, failed blocker, missing approval id, or insufficient capability.

## UI Data Contract

Review Studio consumes generated artifacts and normalized JSON records. It should not infer release readiness from screenshots or raw EDA files alone.

| UI area | Source artifact / API record | Required fields |
|---|---|---|
| Project overview | release gate summary JSON | status, blocked, blocking gates, non-claims |
| Transaction timeline | transaction runtime records | transaction id, state hash, status, approval id, operation, timestamp |
| Semantic diff | design diff JSON | added, removed, changed, severity, path, summary |
| PCB visual diff | visual diff manifest | layers, previews, unsupported features, diff artifacts |
| ERC/DRC/DFM | validation reports | check name, source, severity, status, violation count, details path |
| BOM risk | BOM risk report | provider, cache policy, lifecycle, stock, alternates, risk score, flags |
| Manufacturing | manufacturing evidence JSON | artifact kind, path, size, sha256, smoke validation status, fab profile |
| Proof pack | proof manifest | inputs, environment, artifacts, checks, oracle evidence, transaction history, limitations |
| Approval controls | permission/capability context | actor, capability, approval id, required gates, disabled reason |

## Static Viewer Mode for CI Artifacts

The first implementation slice is a static review bundle. It should be generated by CI or CLI and opened as local files.

Minimum bundle contents:

```text
review-bundle/
  index.html
  data/
    release-gate-summary.json
    proof-manifest.json
    semantic-diff.json
    validation-summary.json
    bom-risk.json
    manufacturing-evidence.json
    kicad-roundtrip-scorecard.json
  artifacts/
    schematic.svg
    board-preview.svg
    gerbers.zip
    kicad-project.zip
```

Static viewer requirements:

- no backend service required;
- no network calls by default;
- all artifact paths are relative to the bundle;
- bundle displays hash mismatches and missing files as blockers;
- supports PR review and release candidate review;
- can be uploaded as a CI artifact.

## Local-First and Hosted Security Requirements

Local-first mode:

- no artifact upload unless explicitly requested;
- all EDA files remain on the user machine;
- no telemetry containing design files, BOM, or netlists;
- path traversal protections for bundle loading;
- readonly static mode by default.

Hosted mode:

- workspace and project-level access controls;
- signed artifact URLs with expiration;
- audit log for every approval, rejection, rollback, and export;
- server-side validation of capability and approval id;
- secrets redaction for provider/API credentials;
- strict separation between user-visible evidence and hidden agent scratch state.

## End-to-End Demo Scenario

Scenario: ESP32 sensor board release review.

1. Agent proposes USB-C, Li-ion charger, 3.3 V regulator, ESP32, I2C sensor, debug header, LED/button changes.
2. Review Studio opens the transaction timeline and highlights the pending proposal.
3. Hardware engineer checks the semantic diff: new power tree, new I2C nets, new BOM lines, and updated fab profile.
4. ERC/DRC/DFM panel shows no blocking electrical or manufacturing findings.
5. BOM panel flags the original BME280 as unavailable/obsolete and suggests BME688 as an alternate.
6. Engineer rejects the first proposal with reason: “replace obsolete sensor.”
7. Agent creates a new transaction replacing the part and updating constraints.
8. Review Studio shows reduced BOM risk and updated proof-pack evidence.
9. Engineer approves with an approval id.
10. Commit and release-export controls become enabled because permission scope, validation gates, and approval evidence are present.
11. CI publishes a static review bundle attached to the pull request.

## First Implementation Slice

Build static proof-pack/design review bundle generation before building an interactive app.

Milestone slice:

- CLI command or CI script writes a `review-bundle/` folder;
- bundle includes normalized JSON evidence and static HTML;
- proof-pack, semantic diff, validation, BOM risk, manufacturing evidence, and release gate summary are visible;
- approve/reject controls are shown as disabled/read-only in static mode;
- hosted/interactive approval remains out of scope until transaction and capability APIs are stable.

## Acceptance Checklist

- Review Studio is explicitly scoped as a review and approval workbench, not a full EDA editor.
- Data contract maps to proof-pack, transaction, diff, BOM, fab, validation, and release-gate artifacts.
- Static proof-pack/design review bundle is the first implementation slice.
- Approval, rollback, and commit UX depends on transaction-safe state and permission-scoped writes.
- End-to-end ESP32 benchmark review scenario is documented.
