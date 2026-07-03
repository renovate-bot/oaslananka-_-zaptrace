# Dependency Management

## Tooling

ZapTrace uses standard ecosystem tooling:

- Python project metadata and dependencies: `pyproject.toml`.
- Python lockfile: `uv.lock`.
- Rust dependencies: `zaptrace_core/Cargo.toml` and `zaptrace_core/Cargo.lock`.
- Container runtime: `Dockerfile` and `docker-compose.yml`.
- GitHub Actions: pinned workflow actions.
- Automation: Renovate for normal updates and Dependabot for GitHub-native security alerts/security updates.

## Update policy

- Patch/minor/digest updates may be automated when CI and stability checks pass.
- Major updates require manual review.
- Docker/base-runtime updates require extra caution even when CI passes.
- Security updates should be triaged before routine feature work.

## Review expectations

Dependency PRs should include:

- lockfile updates when applicable;
- CI results;
- release notes or changelog review for major/runtime changes;
- explicit risk if the update affects parser, export, MCP/API, plugin, CI, or release behavior.

## License awareness

The repository uses a permissive MIT license. New dependencies should be compatible with the project license and distribution model. A dedicated third-party license report/checker is recommended before claiming full REUSE or enterprise-grade legal maturity.

## OpenSSF evidence

This document supports OpenSSF/OSPS dependency selection, dependency ingest, and dependency tracking criteria. A concise policy version is available at [Dependency Policy](../supply-chain/dependency-policy.md).
