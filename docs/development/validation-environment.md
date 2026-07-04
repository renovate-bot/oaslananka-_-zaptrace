# Validation environment parity

ZapTrace release evidence must be reproducible from a clean host. A host that can merely read the repository is not sufficient for release triage: the release path also needs the Python, Rust, KiCad, and simulation tools used by CI and proof-pack evidence.

## Required baseline

Run the environment gate before attempting release validation:

```bash
python scripts/ci_validation_environment.py --strict --output validation-environment.json
```

The gate is intentionally stdlib-only so it can run before dependency sync. It checks for:

- Python 3.12 or newer;
- `uv` for dependency resolution and package builds;
- Rust compiler and Cargo for the optional accelerated core;
- KiCad CLI for external ERC/DRC oracle evidence;
- optional but recommended tools such as Ruff, Pyright, maturin, and ngspice.

Ruff, Pyright, and maturin may be provided by `uv run ...` after dependency sync; global binaries are useful but not required.

## Release validation command sequence

After the environment gate passes, run the release-quality command set:

```bash
uv sync --all-extras --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov=zaptrace --cov-report=term-missing
cargo fmt --manifest-path zaptrace_core/Cargo.toml --check
cargo clippy --manifest-path zaptrace_core/Cargo.toml -- -D warnings
cargo test --manifest-path zaptrace_core/Cargo.toml
uv run python scripts/ci_kicad_oracle.py --strict-skips --output kicad-oracle-summary.json
uv run python scripts/ci_generated_board_release_gate.py --strict --output generated-board-release-gate.json
uv run python scripts/ci_kicad_roundtrip_scorecard.py --strict --output kicad-roundtrip-scorecard.json
```

## Skip policy

Release validation must not treat missing external tools as a pass. The KiCad oracle may emit explicit skip evidence for development environments, but release validation should use `--strict-skips` so unapproved missing-tool evidence fails the gate.

KiCad oracle summaries now use explicit skip semantics:

- `skip-unapproved`: skip has no approval id and blocks strict release validation.
- `skip-approved`: skip includes `--skip-approval-id <ID>` evidence and may be allowed by policy.

Example approved skip run (for controlled exceptions only):

```bash
uv run python scripts/ci_kicad_oracle.py --strict-skips --skip-approval-id APPROVAL-123 --output kicad-oracle-summary.json
```

In CI, the quality workflow runs the KiCad oracle with `--strict-skips` so any skip remains release-blocking unless explicitly handled outside the default workflow.

## Non-claims

Passing this environment gate only proves that a machine can run ZapTrace validation. It does not prove that generated boards are electrically correct, fabrication-ready, manufacturer-approved, production-ready, or compliance-certified.
