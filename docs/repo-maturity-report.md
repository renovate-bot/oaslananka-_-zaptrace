# Repository Maturity Report

## Executive summary

ZapTrace is already beyond a basic open-source repository: it has a README, MIT license, contribution guide, code of conduct, security policy, issue and pull request templates, quality CI, security scanning, release workflow, pinned GitHub Actions, Dependabot security alerts, Renovate dependency automation, SBOM/provenance-oriented release steps, and extensive technical documentation.

This PR raises the repository toward **Professional OSS / Mature OSS** by adding explicit maturity evidence, governance, maintainers, support, development policies, release-integrity documentation, and advisory workflow coverage. It intentionally does not claim Gold/foundation-grade status because the project is still effectively solo-maintainer and lacks regular independent human review.

## Current maturity level

**Current classification:** Professional OSS candidate / mature pre-1.0 project.

The repository resembles a CNCF **Sandbox-like to Incubating-like** project: strong automation and technical evidence exist, but independent governance, multi-maintainer continuity, and regular human review are not yet established.

## Target maturity level

**Target:** Professional OSS / Mature OSS.

Gold/foundation-grade should remain a future target until these conditions are demonstrably true:

- multiple active maintainers;
- at least two significant independent contributors;
- regular non-author human PR review;
- required CODEOWNERS or maintainer review in branch protection;
- reproducible release evidence and sustained test coverage;
- documented continuity plan with backup access.

## GitHub Community Standards status

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| README | Passed | `README.md` describes scope, status, quickstart, CLI, SDK, MCP, safety non-claims. |
| LICENSE | Passed | `LICENSE` uses MIT. |
| CONTRIBUTING | Passed | `CONTRIBUTING.md` documents setup, workflow, testing, commits, DCO-style assertion, and review expectations. |
| CODE_OF_CONDUCT | Passed | `CODE_OF_CONDUCT.md` exists. |
| SECURITY | Passed | `SECURITY.md` documents private reporting, scope, safe usage, supported versions, and disclosure targets. |
| SUPPORT | Passed | `SUPPORT.md` added. |
| Issue templates | Passed | Structured bug and feature templates exist. |
| Pull request template | Passed | `.github/PULL_REQUEST_TEMPLATE.md` exists and now includes maturity/human-review checks. |

## OpenSSF Best Practices status

| Area | Status | Notes |
|------|--------|-------|
| Passing readiness | Partial | Most core files exist; remaining work is entering evidence/justifications in BadgeApp and closing interface/maintenance justification gaps. |
| Silver readiness | Partial | Governance, maintainers, DCO-style policy, roadmap, architecture, support, and security requirements are now documented. Some criteria still need human/access confirmation. |
| Gold feasibility | Missing | Solo-maintainer state blocks bus factor, two independent contributors, and regular non-author human review. |
| `.bestpractices.json` | Passed | Added as local evidence metadata, not an official BadgeApp substitute. |
| BadgeApp proposal links | Partial | `docs/openssf-proposal-links.md` added with proposal-link workflow guidance. |
| Evidence file | Passed | `docs/openssf-evidence.md` added. |

## Scorecard readiness

| Check area | Status | Evidence / gap |
|------------|--------|----------------|
| Branch protection | Passed | Main branch has required checks, no force pushes/deletions, linear history, and conversation resolution. Strict up-to-date and review requirement are intentionally disabled for solo flow. |
| Code review | Partial | PR template and CODEOWNERS exist, but independent required review is not enabled. |
| Maintained | Passed | Recent releases, CI, dependency updates, and roadmap indicate active maintenance. |
| Security policy | Passed | `SECURITY.md`. |
| License | Passed | `LICENSE`. |
| CI tests | Passed | `quality.yml` runs lint, typecheck, tests, Rust checks, package build, Docker smoke, benchmarks, release gate, and KiCad oracle. |
| Dependency update tool | Passed | Renovate plus Dependabot security alerts. |
| Pinned dependencies | Partial | GitHub Actions are pinned by SHA where practical. Runtime dependencies are lockfile-managed. |
| Token permissions | Passed | Workflows use explicit least-privilege `permissions` blocks. |
| Dangerous workflows | Partial | No `pull_request_target` workflow was observed; manual workflow inputs should continue to be sanitized. |
| SAST | Passed | CodeQL and Semgrep run in security workflow. |
| Fuzzing | Missing | No dedicated fuzzing harness observed; issue recommended. |

## Documentation maturity

Diátaxis status:

| Mode | Status | Evidence |
|------|--------|----------|
| Tutorial | Partial | `docs/tutorials/getting-started.md` added; existing quickstart docs exist. |
| How-to | Partial | `docs/how-to/index.md` added as a hub; existing manufacturing/MCP guides cover many tasks. |
| Reference | Partial | `docs/reference/index.md` added; existing API/MCP/reference-style docs exist. |
| Explanation | Partial | `docs/explanation/architecture.md` added and links to existing architecture docs. |

## Release maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Semantic versioning | Passed | Release tags and package version use `vX.Y.Z`/SemVer-style identifiers. |
| Changelog | Passed | `CHANGELOG.md` exists. |
| GitHub Releases | Passed | `release.yml` creates GitHub Releases. |
| Release notes | Passed | GitHub release notes plus changelog. |
| Checksums | Partial | Release artifacts are produced; explicit checksum manifest instructions should be enforced in a future release hardening issue. |
| Provenance/attestation | Passed | Release workflow uses GitHub artifact attestations. |
| SBOM | Passed | Release workflow generates an SPDX SBOM. |
| Release verification docs | Passed | `docs/security/release-integrity.md` added. |

## Quality maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Lint | Passed | Ruff in `quality.yml`. |
| Format | Passed | Ruff format check in `quality.yml`. |
| Typecheck | Passed | Pyright in `quality.yml`. |
| Unit tests | Passed | Pytest matrix in `quality.yml`. |
| Rust quality | Passed | Cargo fmt, clippy, test, maturin build. |
| Coverage threshold | Passed | `pyproject.toml` sets `coverage.report.fail_under = 75`; CI uses coverage. |
| Integration/evidence gates | Passed | Benchmark, generated-board release gate, KiCad oracle, Docker smoke. |
| Test policy | Passed | `docs/development/testing-policy.md` added. |
| Coding standards | Passed | `docs/development/coding-standards.md` added. |

## Governance maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Governance model | Passed | `GOVERNANCE.md`. |
| Maintainers/roles | Passed | `MAINTAINERS.md`. |
| CODEOWNERS | Passed | `.github/CODEOWNERS`. |
| Access continuity | Partial | Documented; true continuity requires a backup maintainer. |
| Bus factor | Missing | Solo-maintainer project. |
| Required human review | Missing | Not enabled because no independent reviewer is available. |

## Community maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Bug/feature process | Passed | Structured issue templates. |
| PR process | Passed | PR template plus contributing guide. |
| Time to first response | Partial | Best-effort support policy; no measured SLA. |
| Contributor activity | Needs human confirmation | Requires live contribution analytics. |
| Small tasks | Missing | Add `good first issue` / `help wanted` labels and seed small issues. |
| All Contributors | Not applicable | Useful later if community grows. |

## License/legal maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| FLOSS license | Passed | MIT. |
| License location | Passed | Top-level `LICENSE`. |
| SPDX/REUSE | Partial | License exists; per-file SPDX headers are not complete. |
| Third-party dependency license awareness | Partial | Dependency management policy added; automated license review is future work. |
| NOTICE | Not applicable | MIT project with no identified NOTICE requirement at this time. |

## Security/supply-chain maturity

| Criterion | Status | Evidence / gap |
|-----------|--------|----------------|
| Security policy | Passed | `SECURITY.md`. |
| Private vulnerability reporting | Needs human confirmation | Enable in GitHub repository settings. |
| CodeQL | Passed | Existing security workflow. |
| Semgrep | Passed | Existing security workflow. |
| Gitleaks | Passed | Advisory workflow added. |
| Dependency review | Passed | PR workflow added. |
| Renovate | Passed | `.github/renovate.json`. |
| Dependabot security | Passed | Dependabot alert/security surface retained. |
| SBOM | Passed | Release workflow. |
| SLSA/provenance | Partial | GitHub artifact attestation exists; SLSA level not claimed. |
| Minimal permissions | Passed | Workflows use explicit permissions. |

## Missing files

No critical GitHub community file remains missing after this PR. Remaining optional files/policies:

- `REUSE.toml` or full REUSE setup;
- dedicated fuzzing docs/harness;
- checksum manifest automation if required beyond artifact attestations;
- independent contributor list once available.

## Missing workflows

Not added intentionally to avoid duplicate or noisy checks:

- standalone `codeql.yml` because CodeQL already runs in `security-scan.yml`;
- heavy Docker vulnerability scan because it may require additional tuning and baseline triage;
- fuzzing workflow because no fuzz harness exists yet;
- release publishing to PyPI/GHCR because release workflow explicitly documents why automatic publishing is disabled.

## Risky changes not applied

- Required PR review was not enabled because the project is solo-maintainer.
- Admin-enforced branch protection was not enabled because it would slow solo emergency maintenance.
- Gold/foundation-grade claims were not added.
- Automatic package publishing credentials were not introduced.
- Heavy vulnerability scanners that might require repository-specific allowlists were not made required checks.

## Recommended issues

1. [#80](https://github.com/oaslananka/zaptrace/issues/80) Add backup maintainer and define emergency release continuity.
2. [#80](https://github.com/oaslananka/zaptrace/issues/80) Enable required non-author PR review once an independent reviewer exists.
3. [#86](https://github.com/oaslananka/zaptrace/issues/86) Add `good first issue` and `help wanted` labels and seed small contributor tasks.
4. [#82](https://github.com/oaslananka/zaptrace/issues/82) Add fuzz/property-based tests for parsers, YAML ingestion, KiCad export, and MCP/API boundary inputs.
5. [#81](https://github.com/oaslananka/zaptrace/issues/81) Add REUSE/SPDX header automation or a license-header checker.
6. [#85](https://github.com/oaslananka/zaptrace/issues/85) Add checksum manifest generation for release assets, or document why attestations/SBOM are sufficient.
7. [#83](https://github.com/oaslananka/zaptrace/issues/83) Replace approved KiCad-old-version oracle skips with a modern KiCad CI environment.
8. [#84](https://github.com/oaslananka/zaptrace/issues/84) Add Docker image vulnerability scanning with a documented triage/allowlist policy.
9. Measure CHAOSS metrics periodically: first response time, issue age, PR age, release cadence, contributor concentration.

## Next actions

1. Merge this PR after human review.
2. Enable or verify private vulnerability reporting, Dependabot alerts, secret scanning, and push protection in GitHub settings.
3. Use the OpenSSF BadgeApp proposal links and evidence files to complete Passing, then Silver justifications.
4. Create issues for Gold/Level 3 blockers instead of claiming them prematurely.
5. Add independent reviewers before tightening branch protection to require human approval.
