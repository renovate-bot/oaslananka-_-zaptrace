# ZapTrace Release Plan — 2026-06-17

## Recommended Version

**v0.2.2 — Verification Foundation and Safety Hardening**

## Recommendation Rationale

v0.2.2 is preferred over v0.3.0 for the following reasons:

1. **Manufacturing evidence is not substantively complete.** While fab profiles (#38), KiCad Oracle (#37), and export regression corpus (#39) are merged, they remain evidence layers — not guarantees. The project intentionally avoids fabrication-ready claims.

2. **Plugin runtime is design-only.** Phase 9 produced a comprehensive design document (`docs/design/plugin-runtime.md`), but no runtime code. The plugin ecosystem is still `🚧 Experimental`.

3. **No public API stability guarantee.** Pre-1.0 APIs remain unstable. A minor release (v0.2.2) correctly signals incremental hardening without implying a milestone boundary.

4. **Verification-first theme fits v0.2.x.** The merged work is about building verification infrastructure, safety hardening, and positioning clarity. These are v0.2 (Foundation) tasks, not v0.3 (Manufacturing Evidence) tasks.

5. **v0.3.0 should be reserved** for when manufacturing evidence is stable enough that at least one reference board has been fabricated, tested, and documented.

## Merged Changes

### Proof and Evidence

| PR | Title | Files |
|----|-------|-------|
| #35 | Proof Pack v1 validation foundation | `zaptrace/proof/` — `validate_proof_pack()`, CLI validate subcommand, 64 tests |
| #37 | KiCadOracle — ERC/DRC, CLI, Proof Pack integration | `zaptrace/kicad/oracle.py`, Proof Pack checker integration, CLI |
| #43 | Plugin runtime safety design | `docs/design/plugin-runtime.md` — design only, no runtime code |

### Manufacturing Evidence

| PR | Title | Files |
|----|-------|-------|
| #36 | 12 seismic/IoT reference parts + SX1262 expansion | `data/library/` — 13 new YAML part definitions, library tests |
| #38 | Fabrication profiles with DFM validation | `zaptrace/fab/` — 4 built-in profiles, DFM validation engine, Proof Pack integration |
| #39 | Export regression corpus with golden-file comparison | `tests/corpus/goldens/` — 6 golden artifacts, regression test module |

### CI and Automation

| PR | Title | Files |
|----|-------|-------|
| #39 | Export regression corpus (CI integration) | Golden-file comparison in CI test suite |
| #40 | Dedicated hardware CI workflow | `.github/workflows/hardware.yml`, `scripts/ci_examples.py` |

### Agent/API Safety

| PR | Title | Files |
|----|-------|-------|
| #41 | MCP design snapshot/rollback/commit for transaction safety | `zaptrace/agent/_tool_impls.py`, `zaptrace/mcp/server.py`, 3 new MCP tools |
| #42 | REST API hardening — rate limiting, security headers, session isolation | `zaptrace/api/routes/`, `zaptrace/api/server.py`, `_session.py` |

### Documentation and Positioning

| PR | Title | Files |
|----|-------|-------|
| #43 | Plugin runtime safety design document | `docs/design/plugin-runtime.md` — 16 sections, 396 lines |
| #44 | Verification-first project positioning | `README.md`, `docs/FAQ.md`, `docs/ROADMAP.md`, specs — 65 lines changed |

## Verification

| Check | Result |
|-------|--------|
| `python -m pytest` | ✅ 725 passed, 7 skipped |
| `ruff check .` | ✅ All checks passed |
| `ruff format --check .` | ✅ 132 files already formatted |
| `pyright` | ✅ 0 errors, 0 warnings, 0 informations |
| `python -m build` | ✅ `zaptrace-0.2.2` |

## Non-Claims

This release does **not** claim:
- fabrication-ready output
- production-ready hardware generation
- manufacturer approval
- guaranteed correctness
- fully automatic manufacturing

## Remaining Risks

- Human engineering review still required before any fabrication.
- KiCad Oracle / fab profile checks are evidence, not guarantees.
- Plugin runtime is designed but not implemented.
- Real fabricated reference boards are still needed before stronger manufacturing claims can be made.
- Proof pack format is experimental and may change.
- No branch protection rules on `main`.

## Release Checklist

- [ ] final full verification passes
- [ ] changelog reviewed
- [x] version number approved (recommended: 0.2.2)
- [ ] tag approved by user
- [ ] release notes approved by user
- [x] version string updated in `pyproject.toml`
- [x] version string updated in `zaptrace/__init__.py`
- [ ] backup branches preserved (do not delete)
