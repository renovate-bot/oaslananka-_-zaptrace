# Testing Policy

## Required gates

Before merging non-trivial changes, run the relevant subset of:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
```

## CI coverage

The `Quality` workflow runs linting, type checking, Python tests across supported Python versions, Rust checks, package build, Docker smoke, benchmark acceptance, generated-board release gates, and KiCad oracle evidence.

## Coverage threshold

The Python coverage threshold is configured in `pyproject.toml` with `coverage.report.fail_under = 75`. Raising the threshold is encouraged only after the suite is stable enough to avoid blocking useful maintenance work.

## Evidence tests

For EDA behavior, tests should prefer observable evidence:

- ERC/DRC results;
- generated artifact snapshots;
- KiCad oracle evidence;
- benchmark reports;
- proof-pack records;
- manufacturing export manifests.

## Slow/external tests

Tests requiring external tools such as KiCad or ngspice must clearly distinguish pass, fail, and approved skip. A missing external tool must not be reported as a silent pass.

## OpenSSF evidence

This document supports criteria requiring public documentation of when and how tests are run. A concise quality policy version is available at [Testing and Quality Policy](../quality/testing-policy.md).
