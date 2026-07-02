# OpenSSF Gap Analysis

## Recommended target

- Immediate: OpenSSF Passing readiness and Baseline Level 1.
- Professional target: OpenSSF Silver readiness and Baseline Level 2.
- Do not claim: Gold / foundation-grade until independent maintainers and regular human review exist.

## Passing gaps

| Gap | Classification | Action |
|-----|----------------|--------|
| BadgeApp justifications incomplete | Partial | Use `docs/openssf-evidence.md` and proposal links to submit criteria. |
| Interface documentation synchronization | Partial | Keep CLI/API/MCP reference docs generated or reviewed during release. |
| Maintained evidence | Passed | Recent CI/releases/dependency updates support the claim. |

## Silver gaps

| Gap | Classification | Action |
|-----|----------------|--------|
| Governance model | Passed | `GOVERNANCE.md` added. |
| Role documentation | Passed | `MAINTAINERS.md` added. |
| Access continuity | Partial | Add backup maintainer or document private continuity plan. |
| DCO/legal assertion | Passed | DCO-style sign-off policy added to `CONTRIBUTING.md`. |
| Security requirements | Passed | Security policy and assurance docs added. |
| Documentation currency | Partial | Continue requiring docs updates in PR template and CI. |
| Accessibility/i18n | Partial | CLI/library mostly applicable as-is; web/docs accessibility review is future work. |

## Gold/foundation-grade blockers

| Blocker | Classification | Why not claim |
|---------|----------------|---------------|
| Bus factor >= 2 | Missing | Current documented maintainer list has one maintainer. |
| Two unassociated significant contributors | Missing | Not demonstrated by repository evidence. |
| Non-author review | Missing | Branch protection does not require review; solo maintainer cannot review own work for Gold evidence. |
| Required CODEOWNERS review | Missing | CODEOWNERS exists, but enforcement should wait for an independent reviewer. |
| Per-file SPDX/copyright headers | Partial | Top-level license exists; per-file headers need automation. |

## Issues to create or track

1. [#80](https://github.com/oaslananka/zaptrace/issues/80) Add backup maintainer and access continuity plan.
2. [#80](https://github.com/oaslananka/zaptrace/issues/80) Enable required non-author review when independent reviewer exists.
3. [#86](https://github.com/oaslananka/zaptrace/issues/86) Seed `good first issue` tasks and contributor onboarding labels.
4. [#81](https://github.com/oaslananka/zaptrace/issues/81) Add REUSE/SPDX header enforcement.
5. [#82](https://github.com/oaslananka/zaptrace/issues/82) Add fuzz/property testing harnesses.
6. [#84](https://github.com/oaslananka/zaptrace/issues/84) Add Docker vulnerability scanning after baseline/allowlist policy is documented.
7. [#83](https://github.com/oaslananka/zaptrace/issues/83) Replace old-KiCad approved skip with modern KiCad CI validation.
8. [#85](https://github.com/oaslananka/zaptrace/issues/85) Generate release checksum manifests.
