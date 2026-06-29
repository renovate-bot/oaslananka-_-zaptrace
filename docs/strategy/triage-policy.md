# GitHub Triage Policy

This document standardizes issue and pull-request triage for ZapTrace.

## Required Issue Structure

Every non-trivial issue should include:

1. Problem
2. Scope
3. Acceptance Criteria
4. Evidence Required
5. Dependencies / Blocking Work
6. Non-Goals

Release-blocking issues must also include a gate policy and artifact list.

## Label Taxonomy

| Group | Labels | Meaning |
|-------|--------|---------|
| Type | `type:epic`, `type:feature`, `type:hardening`, `type:research`, `type:benchmark`, `type:docs` | Work shape |
| Priority | `priority:P0`, `priority:P1`, `priority:P2`, `priority:P3` | Release urgency |
| Area | `area:architecture`, `area:agent-runtime`, `area:eda-interop`, `area:verification`, `area:manufacturing`, `area:supply-chain`, `area:security`, `area:ui`, `area:ci`, `area:docs`, `area:plugin` | Technical ownership |
| Status | `status:needs-audit`, `status:blocked`, `status:ready`, `status:validated` | Workflow state |

## Priority Rules

| Priority | Use When | Blocking Policy |
|----------|----------|-----------------|
| P0 | Incorrect claim, unsafe behavior, broken release gate, missing audit evidence | Blocks current milestone |
| P1 | Required for the next product milestone | Blocks next milestone, not necessarily patch release |
| P2 | Important capability for autonomy or ecosystem growth | Does not block current milestone |
| P3 | Future-facing research, cross-EDA expansion, advanced analysis | Does not block unless promoted |

## Milestone Rules

| Milestone | Theme | Default Priority Range |
|-----------|-------|------------------------|
| M0 / v0.2.3 | Verification gate stabilization | P0/P1 |
| M1 / v0.3 | Manufacturing intelligence and Review Studio | P1 |
| M2 / v0.4 | Autonomous candidate generation | P2 |
| M3 / v1.0 | Enterprise signoff and cross-EDA readiness | P2/P3 |

## Triage Flow

1. Confirm whether the issue describes implementation, evidence, docs, or research.
2. Add exactly one `type:*` label unless it is an epic.
3. Add one `priority:*` label.
4. Add one or more `area:*` labels.
5. Put the issue into the earliest milestone whose exit criteria require it.
6. Mark `status:blocked` only when a named dependency prevents work.
7. Mark `status:validated` only after evidence is attached or linked.
8. For old closed issues, use `status:needs-audit` when the title implies more than the current code proves.

## Pull Request Rules

Every PR must state:

- fixed issue(s)
- user-visible behavior change
- verification commands run
- evidence artifacts created or intentionally skipped
- whether docs/changelog were updated
- whether the change affects fabrication/manufacturing claims

## Release Board Conventions

For each milestone, maintain one epic issue with:

- goal
- required open issues
- historical closed issues
- release gate
- non-goals

The milestone is releasable only when:

- no P0 issue remains open
- all release-gate evidence is PASS or SKIP-APPROVED
- release notes include limitations and non-claims
