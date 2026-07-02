# Security and Quality Assurance Case

ZapTrace uses an evidence-based assurance model. The repository does not claim that absence of findings proves security or correctness.

## Claims supported today

| Claim | Evidence |
|-------|----------|
| The project is maintained | Recent CI, releases, dependency updates, roadmap. |
| Basic community health files exist | README, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, SUPPORT, issue/PR templates. |
| Quality gates run automatically | `quality.yml`, docs workflow, hardware/KiCad/proof workflows. |
| Static analysis runs | Semgrep and CodeQL in `security-scan.yml`. |
| Dependency security is monitored | Renovate, Dependabot alerts, uv audit, dependency review workflow. |
| Release artifacts have provenance support | Release workflow uses SBOM and artifact attestation. |

## Claims not supported today

| Claim | Reason |
|-------|--------|
| Gold/foundation-grade governance | Solo maintainer; no regular independent human review. |
| Generated hardware is safe/fabrication-ready | Requires qualified human engineering review and manufacturer validation. |
| Plugins are safe for arbitrary untrusted execution | Stronger sandboxing and signed admission are still roadmap items. |
| All vulnerabilities will be found by scanners | SAST/SCA are partial evidence only. |

## Assurance maintenance

Update this file when adding or removing material security, release, or quality controls.
