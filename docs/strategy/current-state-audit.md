# ZapTrace Current State Audit

*Generated: 2026-06-09*
*Refreshed: 2026-07-03*

> This audit is a current-state snapshot. Historical pre-0.3.0 gaps are kept only where they remain accurate after the 0.3.0 evidence-hardening baseline.

## Repository Summary

| Attribute | Value |
|-----------|-------|
| **Repository** | github.com/oaslananka/zaptrace |
| **License** | MIT |
| **Version** | 0.3.0 |
| **Language** | Python 3.12+ (with optional Rust extension) |
| **Package manager** | uv (with uv.lock) |
| **Build system** | hatchling |
| **Tests** | Deterministic pytest/coverage gate; exact counts are CI-generated and must not be hard-coded |
| **Coverage target** | 75% |
| **CI** | GitHub Actions quality, security, and release workflows |
| **CLI** | 20+ commands via Click |
| **MCP** | 87 agent-facing tools generated from `TOOL_REGISTRY` |
| **API** | FastAPI-based REST server |

## Current Architecture

ZapTrace has a layered architecture:

1. **Interface layer**: CLI (Click), MCP server (FastMCP), REST API (FastAPI), Python SDK
2. **Agent layer**: Tool registry with 87 agent-facing tools, MCP session/resource surfaces, pipeline autopilot
3. **Core layer**: Pydantic models, YAML parser, diff engine
4. **Domain layer**: EE knowledge base, net classifier, footprint generator, constraints
5. **Verification layer**: ERC (29 rules), DRC (16 rules), auto-patch suggestions
6. **Algorithm layer**: Grid+force-directed placer, Manhattan MST router, grid A* router, copper pour engine
7. **Export layer**: Gerber RS-274X, Excellon drill, BOM CSV/JSON, SVG, KiCad, manufacturing ZIP, Markdown reports
8. **Extension layer**: Template-based synthesis, component library, plugin system (scaffold), Rust core (optional)

## Existing Implemented Capabilities

- Complete Pydantic design model (Component, Net, Pin, BoardDefinition, etc.)
- YAML design file parser with validation
- Design synthesis from natural language intent (template-based)
- 29 ERC rules (pin compatibility, unconnected nets, power, signal integrity, RS485 direction, SPI CS uniqueness, LiPo protection, power-tree completeness, regulator headroom, DNP-aware, etc.)
- 16 DRC rules (trace width, clearance, hole size, annular ring, IPC-2152 current capacity, hole-to-hole spacing, etc.)
- Grid + force-directed placement algorithm
- Manhattan MST router (simple, fast)
- Grid-based A* router (quality, with component blocking)
- Differential pair routing support
- Copper pour generation (flood-fill)
- Trace fillet/rounding
- Net classification using EE knowledge
- Gerber RS-274X export (F.Cu, B.Cu, mask, silk, paste)
- Excellon drill export
- BOM CSV and JSON generation
- Pick-and-place (centroid) CSV generation
- KiCad schematic export
- SVG schematic rendering
- Markdown design report generation
- Manufacturing ZIP bundle with manifest
- 87 agent-facing tools registered from `TOOL_REGISTRY`
- FastAPI-based REST API server
- Design diff between two designs
- Full pipeline autopilot (parse→ERC→place→route→export)
- Component library with YAML data files
- Session-based design store
- Proof pack runner, manifest model, CLI/API/MCP entry points, and smoke checks
- CI-backed pytest suites, hardware/golden smoke scripts, benchmark gates, and generated-board release gates
- CI with lint, typecheck, test matrix, Rust build, package build, security scan, and release automation

## Experimental Capabilities

- **Proof pack system**: Runner, manifest, CLI/API/MCP entry points, and validation smoke checks are implemented; deterministic evidence, external-tool records, and signed/reproducible bundles still need v1 hardening.
- **Plugin system**: Documentation and architecture exist; runtime discovery/loading, signed manifests, and deny-by-default tool admission are not implemented.
- **DFM/fab-profile foundation**: Fab profiles and profile-based DFM checks exist; external manufacturer evidence adapters and release-blocking manufacturing evidence are not implemented.
- **Manufacturing readiness scoring**: Concept documented

## Planned / Foundation-Only Capabilities

- **Proof Pack v1 hardening**: signed manifests, deterministic bundle layout, external-tool evidence, and release-blocking proof-pack policy need continued hardening.
- **Plugin runtime hardening**: manifest/admission policy exists; runtime discovery/loading, sandbox execution, and registry governance remain incomplete.
- **SPICE evidence**: netlist export and simulation-gate scaffolding exist; device-model coverage and release-blocking no-skip simulation evidence remain incomplete.
- **Advanced manufacturing evidence**: external DFM adapters, ODB++/IPC-2581 evidence depth, fab-house upload/acceptance records, and release-blocking manufacturing gates remain incomplete.
- **Multi-board/hierarchical design**
- **Web-based PCB viewer**: static review viewer exists; interactive 2D PCB/proof evidence workflows remain incomplete.
- **IPC-2581 export**: foundation exists; external validation and release-blocking fixture coverage remain incomplete.
- **KiCad import** (bidirectional): importer foundation exists; parity/round-trip coverage remains incomplete.
- **Push-and-shove interactive routing**: pad-aware escape routing foundation exists; rip-up/reroute, shove behavior, and quality scoring remain incomplete.
- **BOM supply-chain enrichment** (Octopart, distributor APIs)
- **Thermal simulation**: risk/foundation checks exist; solver-backed thermal simulation remains incomplete.
- **Signal integrity analysis**: risk/foundation checks exist; solver-backed SI/PI evidence remains incomplete.
- **RF/microwave awareness**: RF synthesis/foundation checks exist; RF/microwave-grade constraints remain incomplete.
- **ML-assisted placement**

## Documentation Gaps (Before This Agent)

- **README.md**: Was empty (0 lines) — now filled
- **LICENSE**: Was MIT in pyproject.toml but no LICENSE file — now added
- **No CONTRIBUTING.md**: Now added
- **No CODE_OF_CONDUCT.md**: Now added
- **No SECURITY.md**: Now added
- **No GETTING_STARTED.md**: Now added
- **No ARCHITECTURE.md**: Now added
- **No ROADMAP.md**: Now added
- **No FAQ.md**: Now added
- **No SAFETY.md**: Now added
- **No MCP.md**: Now added
- **No PROOF_PACK.md**: Now added
- **No PLUGIN_SYSTEM.md**: Now added
- **No MANUFACTURING.md**: Now added
- **No CLI.md**: Now added
- **No PYTHON_API.md**: Now added
- **No REST_API.md**: Now added
- **No GITHUB_ACTION.md**: Now added
- **No RELEASE_CHECKLIST.md**: Now added
- **No VERSIONING.md**: Now added
- **No strategy docs**: Now added (vision, competitive positioning, etc.)
- **No example gallery**: Now added (5 reference designs)

## Developer Experience Gaps

- `zaptrace doctor` command added for validation-environment parity evidence
- No `zaptrace init` command
- No `zaptrace examples` command
- Proof-pack CLI group exists; dedicated `zaptrace export proof-pack` alias remains optional/future
- No comprehensive CLI help text beyond Click autogeneration
- No type stubs for the Python SDK
- No pre-built wheels (requires maturin build)

## MCP Gaps (Before This Agent)

- Tool catalog was not documented
- Resources were limited (designs, library categories, templates, ERC rules)
- No prompt templates
- No security documentation for MCP usage
- No client setup guide
- Missing resources: `zaptrace://drc/rules`, `zaptrace://artifacts`, `zaptrace://proof-packs`

## Plugin Ecosystem Gaps

- Plugin system is not functional yet
- No plugin discovery mechanism
- No plugin sandboxing
- No plugin registry

## Manufacturing Trust Gaps

- Manufacturing outputs are not fabrication-proven
- Fab-profile DFM foundation exists, but external fab evidence is not release-blocking
- No supply-chain verification (BOM stock, lead times)
- No fab compatibility validation adapters or manufacturer upload/acceptance evidence (JLCPCB, PCBWay, etc.)

## Testing Gaps

- Limited external-tool E2E coverage: the KiCad oracle exists but is optional when `kicad-cli` is unavailable
- Integration tests exist for many components but not every API/MCP/export path
- Performance/benchmark tests exist; release-blocking performance budgets and sharded runtime policy still need hardening
- Export regression corpus exists; it still needs release-blocking scorecards and round-trip fidelity coverage
- No property-based testing (Hypothesis)

## CI/CD Gaps

- Quality workflow is Ubuntu-only; no Windows/macOS quality matrix yet
- `kicad-cli` oracle supports strict-skip evidence; repository policy still needs protected required-check enforcement on GitHub
- Codecov upload exists, but minimum coverage enforcement is local pytest config rather than a protected GitHub check
- Branch protection evidence is documented in maturity reports; machine-verifiable periodic capture is still future work
- No nightly builds
- No mandatory hardware CI with real EDA binaries installed
- Basic issue/PR templates exist; standardized governance templates and triage policy are documented but automation is still future work

## Security Gaps

- Plugin manifest/admission policy exists; runtime sandbox enforcement remains incomplete
- MCP capability policy exists; deployment-level auth/transport hardening remains required if exposed beyond stdio/local IPC
- REST capability authorization helpers exist; deployment-specific token/session configuration remains required
- REST request limits and security headers exist; MCP/REST threat-model tests and permission evidence are still thin
- Security workflow exists (`uv audit`, Semgrep, CodeQL), but MCP/REST threat-model tests are still thin

## 2026-06-16 External Research Snapshot

- KiCad is the right external oracle for automated validation: `kicad-cli` supports scripted schematic/PCB actions, PCB DRC reports, ERC reports, Gerber info/diff, and JSON output modes in current documentation ([KiCad CLI docs](https://docs.kicad.org/master/en/cli/cli.html)).
- KiCad automation should prefer CLI/jobset flows for headless CI and treat Python bindings carefully: the legacy `pcbnew` SWIG layer is documented as unstable across major versions, while the newer `kicad-python` IPC package requires KiCad 9+ with a running KiCad API server ([KiCad pcbnew docs](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/index.html), [kicad-python](https://pypi.org/project/kicad-python/)).
- External routing interoperability should stay DSN/SES-compatible: Freerouting imports Specctra/Electra `.dsn` and exports `.ses`, and its CLI is explicitly intended for scripts/build systems ([Freerouting README](https://github.com/freerouting/freerouting), [Freerouting CLI docs](https://github.com/freerouting/freerouting/blob/master/docs/command_line_arguments.md)).
- Agentic EDA is moving toward multi-agent tool orchestration, but reliability depends on constrained APIs, validation loops, and recovery from long tool chains; EDAid identifies long-chain tool-calling errors as a central risk for LLM EDA automation ([NAACL 2025 EDAid](https://aclanthology.org/2025.naacl-long.83/)).
- AI-for-EDA is credible but still verification-bound: NVIDIA publicly focuses on AI, reinforcement learning, generative methods, and LLMs for chip design; Google DeepMind reports AlphaChip-style RL layouts used in production chips, but these results are for IC floorplanning, not a complete substitute for PCB sign-off ([NVIDIA EDA research](https://research.nvidia.com/labs/electronic-design-automation/), [Google DeepMind AlphaChip](https://deepmind.google/blog/how-alphachip-transformed-computer-chip-design/)).
- OpenROAD proves the value of no-human-in-the-loop automation in adjacent silicon flows, but its lesson for ZapTrace is disciplined flow orchestration and hard quality gates, not blind autonomy ([OpenROAD Flow docs](https://openroad-flow-scripts.readthedocs.io/)).
- Commercial autonomous PCB tools are differentiating around physics validation, multiple layout candidates, ECAD round-trip, deployment model, and review scorecards; ZapTrace should not promise "100% no review" until it can produce proof packs with external DRC/DFM evidence and fabricated reference boards ([Quilter 2026 comparison](https://www.quilter.ai/blog/the-2026-guide-to-autonomous-pcb-design-quilter-vs-deeppcb-vs-flux-ai)).
- Fabrication confidence must be fab-profile based, not generic: JLCPCB exposes specific capability pages plus DFM tooling, so ZapTrace needs explicit manufacturer presets and generated evidence against those presets ([JLCPCB capabilities](https://jlcpcb.com/capabilities/pcb-capabilities)).

## 2026-06-19 Status Reconciliation

This audit now separates implemented foundation, experimental evidence, and missing release gates:

- `0.3.0` is the current package baseline in `pyproject.toml` and `CHANGELOG.md`.
- The M0-M4 evidence-hardening roadmap has been implemented; remaining work is benchmark depth and external validation hardening.
- KiCad Oracle, fab profiles, proof packs, REST hardening, and MCP transaction primitives exist as foundations, but the project must still make skipped external evidence explicit and release-blocking.
- DFM is no longer purely planned; the foundation exists, while external manufacturing adapters and evidence gates remain planned under M1.
- Several historical closed issues require audit labels because their titles may imply completeness beyond the current experimental/release-gated state.
- Public positioning should remain: agent generates, proof system records evidence, human engineer approves.

## Release/Publishing Gaps

- No versioning policy documented (now added)
- No release checklist (now added)
- No changelog tracking beyond current milestone
- No PyPI publishing workflow
- No release automation

## Top 20 Technical Risks

1. **Session state defaults to in-memory dict** — opt-in filesystem persistence exists, but scalable multi-user storage is still future work
2. **Persistent storage is opt-in** — design state can persist with `ZAPTRACE_SESSION_STORE_ROOT`, but DB-backed concurrency is not implemented
3. **Router doesn't handle high-density boards well** — A* grid router is slow for complex designs
4. **Rust extension is optional** — no guarantee of performance-critical path optimization
5. **No multi-threading** — all operations are single-threaded
6. **Limited caching of computation results** — deterministic synthesis benchmark is cached, broader compute caches remain future work
7. **Schematic synthesis is template-based** — doesn't use LLM for creative design
8. **Limited footprint library** — ~50 packages supported
9. **No 3D model generation** — no STEP/IGES export
10. **ERC rules are hardcoded** — not configurable by users
11. **DRC rules are hardcoded** — not configurable by users
12. **No design rule constraints from YAML** — limits user control
13. **External validation is uneven** — KiCad oracle is strict-capable, but Gerber/fab-specific cross-check depth remains incomplete
14. **No unit test for each ERC rule independently** — rules tested together
15. **No metric for routing quality** — no via count, length optimization scoring
16. **KiCad export is unidirectional** — no import capability
17. **No support for flex/rigid-flex designs**
18. **Copper pour doesn't support thermal relief optimization**
19. **No hierarchy in design model** — flat design only
20. **External sign-off is optional** — local checks can pass while KiCad/fab-specific checks are skipped

## Top 20 Product Risks

1. **Low discoverability** — new users don't know ZapTrace exists yet
2. **No community** — no users providing feedback yet
3. **Single maintainer risk** — bus factor of 1
4. **Pre-1.0 trust barrier** — engineers won't trust pre-1.0 EDA tools
5. **No reference designs** — can't prove quality without examples (now addressed)
6. **No fabrication validation** — no boards fabricated from ZapTrace output
7. **Competing with well-funded tools** — Altium, KiCad, Flux AI, CircuitMaker
8. **No GUI** — limits adoption among visual designers
9. **Hardware engineers prefer GUIs** — CLI-first is a hard sell
10. **AI-assisted EDA market is crowded** — many new entrants
11. **No integration with popular design tools** — no Altium/Eagle/OrCAD import
12. **Documentation in English only** — limits global reach
13. **No case studies** — no public success stories
14. **Plugin ecosystem is empty** — no plugins to attract users
15. **No SaaS offering** — CLI-only limits enterprise adoption
16. **Pydantic dependency** — version conflicts with other tools
17. **No Windows CI testing** — only GitHub Actions (Ubuntu)
18. **No corporate sponsorship** — project is free-time effort
19. **uv adoption is growing but not universal** — pip users may struggle
20. **Name confusion** — "ZapTrace" might be confused with other tools

## Top 20 Opportunities

1. **MCP-first agent integration** — unique positioning as an agent-native EDA tool
2. **Proof packs as differentiator** — no other EDA tool provides auditable proof packs
3. **Verification-first messaging** — resonates with engineering culture
4. **Plugin ecosystem** — community can extend capabilities
5. **GitHub-native hardware CI** — CI for hardware design is an emerging space
6. **Manufacturing validation** — bridge from design to fab is a pain point
7. **BOM supply-chain awareness** — real-time component pricing and availability
8. **Multi-board system design** — growing need for complex interconnected systems
9. **AI-assisted design review** — automated design review is valuable
10. **Educational use** — teach electronics design programmatically
11. **Open-source EDA is under-served** — KiCad is great but not AI-native
12. **Startup-friendly** — hardware startups need fast iteration
13. **Integration with AI coding tools** — Cursor, Copilot, Claude Code
14. **WebAssembly compilation** — run ZapTrace in browser
15. **Python-first EDA** — appeals to ML/software engineers entering hardware
16. **CI/CD for hardware** — GitOps for PCBs is a growing trend
17. **License compliance** — SPDX, OID for open-source hardware
18. **Sustainability** — BOM optimization for environmental impact
19. **Academic research** — EDA algorithm research platform
20. **Custom manufacturing rules** — fab-specific presets (JLCPCB, PCBWay, etc.)

## Recommended 30-Day Plan

1. **Make CI trustworthy** — keep quality/security/release green, add docs check to quality, and enforce the KiCad oracle where available
2. **Proof Pack v1 hardening** — artifact hashes, deterministic manifests, external DRC/DFM evidence, and signed/verifiable reports
3. **Fab profile system** — JLCPCB/PCBWay presets for trace, clearance, drill, annular ring, solder mask, silkscreen, stackup, and output naming
4. **KiCad oracle integration** — parse JSON DRC/ERC reports, attach evidence into proof packs, and fail on selected severities
5. **Agent transaction safety** — session snapshots, rollback, dry-run tools, and idempotent write operations
6. **Export regression corpus** — golden Gerber/Excellon/KiCad fixtures and strict diff gates
7. **Release v0.3.0** — M0-M4 evidence hardening, benchmark readiness, and review-studio proof visibility

## Recommended 60-Day Plan

1. **BOM enrichment** — distributor API integration for pricing, stock, lifecycle, alternates, and lead-time risk
2. **SPICE model coverage and no-skip simulation evidence**
3. **DFM checks** — annular ring, solder mask, copper balance, courtyard, silkscreen, board-edge, assembly orientation
4. **Web-based viewer** — interactive 2D PCB and proof-pack evidence preview
5. **Multi-board support** — hierarchical designs and board-to-board connector checks
6. **Supply-chain risk scoring** — BOM-level risk analysis
7. **Release v0.3.0** — manufacturing trust release

## Recommended 90-Day Plan

1. **Multi-layer routing** — full 4+ layer support with stacked/blind/buried via policies
2. **User-defined DRC/ERC rules** — YAML-configured rules with schema validation
3. **Hardware CI GitHub App** — PR comments for ERC/DRC/DFM/proof-pack deltas
4. **Plugin runtime** — signed plugin discovery, permissions, sandboxing, and registry metadata
5. **REST API hardening** — auth, rate limiting, persistent storage, audit logs
6. **MCAD export** — STEP/IGES 3D model generation
7. **Release v0.4.0** — interactive and cloud-native release
