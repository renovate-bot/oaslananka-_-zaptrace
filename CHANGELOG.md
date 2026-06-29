# Changelog

## [Unreleased]

### Agent tools

- **Simulation gate MCP tool** — `simulation_gate` runs the DC operating-point gate on a stored design and returns a blocking verdict. Rail references are derived from the design's power-rail net names. When ngspice is unavailable the gate is `skipped` (recorded as evidence, never a silent pass); `strict=True` makes a skip blocking. Tool catalog → 82.
- **Self-correcting synthesis MCP tool** — `synthesize_board_repair` runs the convergent ERC → patch → re-verify loop after synthesis: it assigns standard footprints to fix `ERC020` violations, re-runs ERC each round until a fixed point, and reports both what it patched and what it cannot fix (e.g. single-pin nets needing a real connector). Tool catalog → 81.
- **Board-level synthesis MCP tools** — `board_plan` composes a justified board block graph (power + interface support) from an intent; `synthesize_board` emits the full board netlist via block composition and stores it in the session; `synthesize_board_and_check` runs ERC on the result in one step. Each regulator block *provides* a rail, each interface support block *requires* one, and unrealized/unmet items are reported instead of silently dropped. Tool catalog → 80.
- **Requirements & compliance MCP tools** — `requirements_parse` extracts structured machine-readable requirements (rails, current, interfaces, MCU, USB-C, battery) from a design intent; `compliance_checklist` turns those into a product-class compliance pre-check (RoHS/REACH, USB-C, battery, etc.) flagged as evidence-ready, not certified. Tool catalog → 69.

### Analysis / verification

- **DC operating-point simulation gate** — `zaptrace/analysis/sim_gate.py` wraps the SPICE orchestrator as a blocking gate with two disciplines from the design note: an explicit skip (ngspice absent) is recorded as `skipped`, never a silent pass, and in `strict` mode it blocks; a run with no expected voltages is `no_reference`, distinct from a verified `pass`. `expected_rail_voltages()` derives references from the synthesis rail-net convention (`VDD_3V3` → 3.3 V). ngspice is now bundled in the container image so a skip in CI signals an environment fault, not an accepted gap. (Device models for the synthesized ICs are still pending, so rail checks currently skip even with ngspice present.)

### Synthesis / requirements

- **Peripheral (sensor) synthesis** — `zaptrace/synthesis/peripherals.py` places the real I2C sensor an intent asks for and hangs it on the MCU's bus, so the board fulfils the intent instead of leaving an empty bus. `plan_sensors()` maps measurement keywords to library parts (temperature/humidity → SHT31-DIS, pressure → BMP390, accelerometer → LIS3DH, ADC → ADS1115, air-quality → BME688, bare "sensor" → BME280), deterministically and only when an I2C bus exists. `instantiate_sensor()` ties power, joins the data/clock pins (named SDA/SDI, SCL/SCK across parts) to the SDA/SCL bus nets, ties an address pin to GND, and adds decoupling. `architecture.py` adds each as a realized `SENS_*` block (provides `sensor:<fn>`, requires the rail + `iface:i2c`). A measurement with no part, or an intent with no I2C bus, is reported, never faked. A synthesized "I2C temperature sensor board" now has an actual SHT31 talking to the MCU.
- **IPC-7351 footprint geometry resolution** — `zaptrace/synthesis/footprint_resolver.py` attaches real pad geometry (`Component.footprint_def`) to every synthesized part from its footprint name, via the IPC-7351 generators in `ee/footprints.py`. The manufacturing exporters (Gerber, Excellon, DSN) emit no copper without it, so this is what makes a synthesized board fabricable. `synthesize_and_repair()` now runs it after the repair loop; a package with no generator yet (e.g. an MCU module land pattern) is reported as `unresolved`, never given invented pads. Also added the `SOT-23-3` package (the synthesized LDO) to the SOT generator.
- **Functional-core synthesis** — `zaptrace/synthesis/mcu.py` instantiates the real MCU for the requested family from the library (`esp32` → ESP32-C3-MINI-1, `stm32`, `rp2040`, `nrf52`, `atmega`, `ch32`), places it, ties its power/ground/enable pins to the logic rail, and assigns GPIOs (natural-sorted, deterministic) to the interface support nets already on the board — so I2C SDA/SCL, RS-485 control, and CAN TXD/RXD reach the MCU instead of dangling at a pull-up. `architecture.py` adds it as the realized `CORE_MCU` block (provides `core`, requires the rail), emitted last so the support nets exist. A family with no library part (e.g. `samd`), or an interface with no support net (SPI/UART), is reported honestly, never faked. First time a synthesized board is a connected system rather than support scaffolding.
- **Convergent self-correction loop** — `zaptrace/synthesis/repair.py` closes the second half of the synthesis loop: `repair_design()` maps auto-fixable ERC violations to typed `Patch`es, re-runs ERC each round, and stops at a fixed point or a hard iteration cap. Two handlers so far: `ERC020` standard-footprint assignment, and `ERC012` floating-enable tie (a 100 kΩ pull-up to the board input for an `EN_<rail>` net, so a synthesized regulator turns on). It records measured per-iteration progress (violation count before/after), never invents a footprint for an unknown part or ties a non-enable single-pin net (USB-C CC, data lines, feedback stay for a human), and escalates whatever it cannot fix as `remaining`. `synthesize_and_repair()` ties it to architecture synthesis end to end.
- **RS-485 & CAN transceiver blocks** — `instantiate_rs485_transceiver` (MAX3485, half-duplex, 120 Ω termination) and `instantiate_can_transceiver` (SN65HVD230, 3.3 V, 120 Ω termination) are now parametric blocks; `plan_architecture()` realizes the `rs485`/`can` interfaces with them instead of deferring, and the repair loop knows their SOIC-8 footprint. RF interfaces (BLE/Wi-Fi/LoRa) remain honest gaps.
- **Block-composition architecture synthesis** — `zaptrace/synthesis/architecture.py` generalizes the power-tree planner to the whole board: `plan_architecture()` builds a typed block graph where every block declares what it `provides` (rails, interface support) and `requires` (a rail to run from), composes by satisfying requires-with-provides, and reports `UnmetRequirement`s rather than emitting them silently. `build_architecture_design()` emits a deterministic netlist plus a `SynthesisDecisionLog`, with interfaces lacking a parametric block recorded as honest gaps instead of skipped. First step from template selection toward from-scratch synthesis.
- **Requirements → constraints derivation** — `requirements_to_constraints()` maps parsed `Requirements` onto the constraint-DSL `ConstraintSet` (voltage domains per rail, a 90 Ω USB differential-pair routing intent + edge-placed connector for USB-C, an I2C bus routing intent). Every emitted constraint records the requirement it came from (traceability), and a bare intent invents nothing. Surfaced in the `requirements_parse` tool output.
- **Requirements/constraints artifact emitter** — `write_requirements_artifacts()` and a new `zaptrace requirements <intent> [-o DIR]` CLI command emit deterministic, reviewable `requirements.json` + `constraints.yaml` design-contract artifacts (or print them as JSON).
- **Requirement→constraint coverage matrix** — `requirements_coverage()` traces which stated requirements produced constraints (`covered`) and which are not yet handled (`uncovered`, e.g. battery charge/protection, current budget, unmapped buses), with a `fully_covered` flag. Surfaced in the `requirements_parse` tool and `zaptrace requirements` output — a coverage matrix, not a silent pass.
- **Unspecified-assumption register** — `requirements_assumptions()` records the facts a design needs that the intent did *not* state (supply rail, current budget, MCU, USB-C power role, battery chemistry), so every downstream assumption is explicit and reviewable. Surfaced in the `requirements_parse` tool and `zaptrace requirements` output.
- **Requirement freeze gate + version diff** — `freeze_requirements()` content-addresses the extracted design contract (SHA-256 over the contract fields, excluding raw prose) so downstream synthesis can record which requirements version it ran against and detect drift; `diff_requirements()` reports field-level changes between two versions with their before/after freeze hashes. Reworded-but-equivalent intent keeps the same hash; a real requirement change always moves it. Surfaced as `freeze` in the `requirements_parse` tool and `zaptrace requirements` output.
- **Assumption approval workflow** — `review_assumptions()` turns the unspecified-assumption register into a gate: each open assumption must carry a recorded reviewer decision before the requirements are review-complete (`approved` is True only when none remain pending). Approvals are bound to the requirements freeze hash, so a later requirement change re-opens the gate. Reachable via the new `requirements_review` MCP tool (intent + an `approvals` map) and surfaced as `assumption_review` in `requirements_parse` and `zaptrace requirements` output. Tool catalog → 70.
- **Product use-case & risk classifier** — `classify_risk()` classifies a design into the risk classes that drive downstream rule-pack/standards selection (battery, wireless, high_voltage, safety_critical), each with the evidence that triggered it; a class is emitted only on concrete evidence. Surfaced as `risk` in `requirements_parse` and `zaptrace requirements`.
- **Environmental / cost / regulatory / mechanical extractors** — `parse_requirements()` now also extracts operating temperature range (Celsius-anchored so a voltage range is never misread), IP ingress rating, board dimensions (mm), the tightest stated BOM/unit cost target (USD), and regulatory targets (CE/FCC/UL/RoHS/REACH/CISPR/ATEX/EN55032/IEC61000, matched only via unambiguous forms).
- **Requirement conflict detector** — `requirements_conflicts()` flags stated requirements that cannot all hold as written: battery + a ≥60 V rail, USB-C (non-PD) + a current budget above 3 A, and Li-ion + a sub-zero operating temperature. Each conflict cites both sides and the physical/spec reason. Surfaced as `conflicts` in `requirements_parse` and `zaptrace requirements`. **Completes the requirements epic.**
- **USB-C CC termination calculator** — `usb_c_cc_termination()` resolves the CC-pin resistor for a port role: a sink (UFP) presents Rd = 5.1 kΩ to GND; a source (DFP) presents Rp advertising its 5 V current (56 kΩ default / 22 kΩ for 1.5 A / 10 kΩ for 3.0 A; above 3 A requires USB-PD). Reachable via the new `calc_usb_c_cc` MCP tool. Datasheet-grounded value for the USB-C CC resistors named in the acceptance example. Tool catalog → 71.
- **Decoupling/bypass planner** — `decoupling_plan()` plans an IC rail's decoupling: one 100 nF high-frequency cap per power pin plus bulk capacitance (≥ 10 µF), with the ceramic voltage rating derated to ≥ 2× the rail for DC-bias loss. Reachable via the new `calc_decoupling` MCP tool. Tool catalog → 72.
- **Li-ion charger sizing** — `lipo_charge_resistor()` sizes the PROG resistor for a Microchip MCP73831/2 Li-ion/Li-Po linear charger from a target charge current (`I_chg = 1000 / R_prog`, 100–500 mA), rounding the resistor up so actual current never exceeds target. Reachable via the new `calc_lipo_charge` MCP tool. Tool catalog → 73.
- **Buck converter L/C calculator** — `buck_inductor_capacitor()` sizes a synchronous buck's inductor and output capacitor in CCM from Vin/Vout/Iout/Fsw (`L = Vout·(Vin−Vout)/(Vin·fsw·ΔIL)`, `Cout = ΔIL/(8·fsw·ΔVout)`), reporting duty cycle, ripple/peak current, and E-series-snapped values (cap rounded up to hold the ripple target). Reachable via the new `calc_buck_lc` MCP tool. Tool catalog → 74.
- **Block-level power-tree planner** — `plan_power_tree()` turns parsed requirements into a justified power architecture: input sources (USB-C VBUS, Li-ion cell), battery charger + power-path, and a regulator per rail with the LDO-vs-buck choice decided by dropout dissipation (≤ 0.5 W → LDO, else buck; rail above the system rail → boost). Every source/stage carries a rationale and points at the calculator that sizes it. Reachable via the new `power_tree_plan` MCP tool. The architecture layer of real synthesis — what stages a design needs and why, before netlisting. Tool catalog → 75.
- **Power-tree netlist emission** — `build_power_tree_design()` turns the power-tree plan into a real `Design` (components + nets) via the parametric blocks: a USB-C CC termination, a regulator per rail (a computed-L/C buck via `buck_inductor_capacitor`, or a new generic LDO block), and I2C pull-ups. Deterministic; boost stages are honestly left unrealized. Reachable via the new `synthesize_power_tree` MCP tool, which stores the design in the session. Adds the `instantiate_ldo` parametric block. Tool catalog → 76.
- **Closed-loop synthesize + ERC** — the new `synthesize_and_check` MCP tool builds an intent's power-tree netlist and runs the full ERC rule set on it in one call, closing the intent → netlist → verification loop so an agent can immediately see (and later auto-repair) what its own synthesis produced. Tool catalog → 77.
- **Design-analysis MCP tools** — expose the standalone analyses as agent-reachable tools: `mechanical_review`, `security_review`, `testability_report` (test-point coverage + debug/reset access + bring-up checklist), and `electrical_analysis` (heuristic SI/PI/thermal pre-check). Brings the agent tool catalog to 67.

### Manufacturing / DRC

- **Fab-profile-aware DRC** — `DRCEngine` accepts an optional `fab_profile`; when set, a DRC run also reports the selected manufacturer's profile-specific violations (min trace/space/drill/annular-ring, via and board limits) by folding the existing `DFMChecker` results into the `DRCResult`. Without a profile, DRC behaves exactly as before (generic geometric checks only). The `drc_run` MCP/agent tool gains a `fab_profile` parameter (e.g. `"jlcpcb-2layer"`) so the profile-aware run is reachable end-to-end.

### Domain analysis

- **Mechanical / enclosure review** — `mechanical_review()` flags missing mounting holes, too few holes on a large (>50 mm) board, and holes that sit off-board or too close to the edge to be usable. Returns serializable `MechanicalFinding`s.

### Verification

- **ERC014 voltage-domain check generalised** — now flags any two distinct declared supply voltages on a power net (1.8/3.3, 3.3/5, 5/12, …) instead of only the hardcoded 3.3 V vs 5 V pair. A shared `_parse_supply_voltage()` understands `"3.3"`, `"5"`, `"5.0"`, `"3V3"`, `"5V"` and `"3.3V"`, so `"5"`/`"5.0"` are treated as the same domain and blanks are ignored.
- **ERC023 — no-connect intent** — new rule flags a `no_connect` pin that is wired to other pins (it must be left floating per the part's datasheet). Brings the ERC pack to 23 rules.
- **ERC008 series-resistor check is now connectivity-precise** — the LED current-limit rule counted a series resistor only if a resistor is *directly connected* to the LED (shares one of its nets), via the electrical graph. Previously it passed whenever any resistor existed anywhere in the design (e.g. an unrelated I2C pull-up), masking real missing-current-limit faults.
- **ERC011 USB ESD check is now connectivity-precise** — USB ESD protection counts only when an ESD/TVS part shares a net with the USB device (and the protection part itself is no longer mis-flagged as an unprotected connector). Previously any ESD part anywhere in the design satisfied the check.
- **ERC016 reset-hold check is now connectivity-precise** — a reset pin is satisfied when its net is a power rail (tied high directly) or a resistor on that net bridges to a rail (pull-up to power, via `ElectricalGraph`). The old check counted any resistor sharing the net regardless of where it led, missed direct-to-rail resets (false positives), and only matched the exact type string `"RES"` (not `"R"`/`"Resistor"`). `has_resistor_to_power()` now accepts `allowed_values=None` to mean any resistor value.
- **ERC coverage reporting** — `ERCResult` now records every check that ran (`checks_run`: rule id, title, category, violation count) and a code-owned list of known `coverage_gaps`. `coverage_summary()` reports "N checks run across M categories … K coverage gaps noted" so a passing ERC advertises its scope and limits instead of an unqualified "passed". Surfaced in the design report, `erc_validate`, and `erc_get_result`.

### Honesty / no-overclaim

- **Synthesis self-describes as template selection** — `synthesize_with_provenance()` returns a `TemplateSelection` (template id, name, match score, `method="template_selection"`); `synthesize_design` (MCP/CLI) now reports which template was loaded and notes that this is keyword-based template selection, not from-scratch circuit synthesis. Tool/CLI descriptions and the README status table no longer overclaim "schematic synthesis".

### Governance and Release Readiness

- Added v0.2.3 verification-gate matrix and blocker policy documentation for release-critical evidence.
- Added release-gate CI summary script/test coverage and workflow artifact upload for gate PASS/FAIL/SKIP evidence.
- Reconciled README, roadmap, FAQ, and current-state audit status around the 0.2.2 baseline and M0/M1/M2/M3 GitHub milestone model.
- Added standardized issue templates and triage policy for epics, release gates, research tasks, bugs, and features.

## [0.2.2] - 2026-06-17 — Verification Foundation and Safety Hardening

### Proof & Evidence

- **Proof Pack v1 validation** — `validate_proof_pack()` with field coverage for version, name, design_path, artifacts (path + sha256), check_records, and limitations. CLI `zaptrace proof validate` with strict mode. 64 proof tests.
- **KiCad Oracle** — `KiCadOracle` module runs external KiCad ERC/DRC, captures results with `error`/`warning`/`violation_count` properties, integrates with Proof Pack checker. 1 new CLI command.
- **Fab profiles** — `zaptrace/fab/profile.py` with `FabProfile` model, 4 built-in profiles (JLCPCB 2/4-layer, OSH Park, PCBWay), DFM validation (`zaptrace/fab/dfm.py`) against profile constraints. Proof Pack integration.

### Library Reference Parts

- **12 seismic/IoT reference components** — W5500, WS2812B, CN3058E, TLV62569, TPS3839, TPS7A2033, USBLC6-2SC6, SX1262, ATECC608B, ADXL355, MAX-M10S, DS3231SN, RV-3032-C7. Library test coverage.

### CI & Automation

- **Export regression corpus** — Golden-file comparison test framework under `tests/corpus/goldens/` with 6 golden artifacts (BOM CSV/JSON, KiCad PCB/SCH, pick-and-place, report, schematic SVG). 1 test module.
- **Dedicated hardware CI** — `.github/workflows/hardware.yml` workflow runs hardware-level integration checks on dedicated runners.

### Agent & API Safety

- **MCP transaction safety** — Design snapshot/rollback/commit primitives in agent tools (`_snapshot_design`, `_rollback_design`, `_commit_design`). MCP `design_snapshot`, `design_rollback`, `design_commit` tools. Test coverage for agent tool lifecycle and MCP server integration.
- **REST API hardening** — Per-session rate limiting (token bucket), security headers (X-Content-Type-Options, X-Frame-Options, CSP, HSTS), session isolation via session-scoped design stores, request body size limits, robust Content-Length handling.

### Documentation & Positioning

- **Plugin runtime safety design** — Comprehensive design document (`docs/design/plugin-runtime.md`) covering manifest schema, capability permissions, read/write separation, sandbox model (3-phase), version negotiation, dependency policy, network access policy, signing/trust model, failure isolation, MCP transaction integration, Proof Pack attestation, and test strategy.
- **Verification-first positioning** — Clarified project positioning: added Verification Model section with evidence-layer table and non-claims, strengthened "What ZapTrace Is Not" with 6 new entries, removed fabrication-ready/production-ready language from FAQ, ROADMAP, and specs. Explicit Pre-1.0 banner.

### Non-Claims

This release does not claim:
- Fabrication-ready output
- Production-ready hardware generation
- Manufacturer approval
- Guaranteed correctness
- Fully automatic manufacturing

All outputs require human engineering review before fabrication.

## 0.2.1 (2026-06-10)

### Fixes

- Fixed DRC rule listing and footprint lookup tools that raised runtime errors.
- Fixed ERC component resolution by supporting both component IDs and reference designators.
- Fixed voltage-domain ERC checks and schematic SVG net rendering.
- Fixed KiCad copper-pour export when a design has no routing result.
- Added source type checking and regression coverage for the repaired paths.

### Release

- Restored deleted GitHub quality and security workflows under new workflow paths.
- Added release quality gates, immutable action pins, artifact attestations, and GHCR container publishing.
- Fixed the Docker image build and included server/MCP optional dependencies.

## 0.2.0 (2026-06-08)

### Features

- **KiCad PCB export** — Full `.kicad_pcb` output with layers (2/4-layer),
  board outline, footprints with pads, trace segments, vias, copper pours
  (zones), and mounting holes. Layer name mapping: `layer_0` → `F.Cu`,
  `layer_1` → `B.Cu` (or `In1.Cu` for 4-layer).
- **Component body blocking** — GridRouter reserves space occupied by
  component bodies via footprint courtyard dimensions, preventing traces
  from overlapping components (`_block_components`).
- **Layer-aware routing** — GridRouter assigns nets to layers based on
  their `NetClass` (power on top, analog on top, high-speed on inner
  layers for 4-layer boards, signal on bottom).
- **Excellon drill file export** — NC drill file output with plated and
  non-plated holes, tool size optimization, mounting hole support.
- **Copper pour engine** — Flood-fill based copper pour generation with
  mounting hole and trace obstacle blocking.

### CI & Quality

- **GitHub Actions** — All workflows upgraded to Node 24 compatible
  actions (`checkout@v6`, `upload-artifact@v6`, `download-artifact@v8`,
  `codecov@v6`, `codeql@v4`, `setup-uv@v8.1.0`).
- **Semgrep SAST** — Replaced archived `semgrep-action@v1` with native
  CLI (`pip install semgrep` + `semgrep scan`). SARIF upload integrated.
- **Ruff lint** — 113 auto-fixed + 23 unsafe-fixed issues across 59 files.
  Line length 100→120. 92 files reformatted. All checks passing.
- **Type checking** — Zero type errors in `grid_router.py` (down from 5).
- **Dependency groups** — `ruff`, `pytest-cov`, `maturin`, `pyright`
  added to dev/lint/test/typecheck groups.

### Documentation

- **README** — Comprehensive project README with feature matrix, quickstart,
  CLI/SDK/MCP/REST usage, architecture diagram, roadmap, limitations.
- **Community health** — `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md` added. GitHub issue/PR templates created.
- **Architecture docs** — `docs/ARCHITECTURE.md` with layer diagram,
  `docs/GETTING_STARTED.md`, `docs/ROADMAP.md`, `docs/FAQ.md`,
  `docs/SAFETY.md`.
- **Strategy docs** — `docs/strategy/` with MCP strategy, community growth,
  docs strategy, proof pack spec.
- **MCP docs** — `docs/mcp/` with quickstart, tools reference, examples.
- **Manufacturing docs** — `docs/manufacturing/` with Gerber and BOM guides.
- **Plugin development guide** — `docs/plugins/development-guide.md`.
- **Example designs** — 5 example projects in `examples/` (ESP32 I2C sensor,
  RP2040 USB HID, USB-C LiPo charger, STM32 RS-485, nRF52840 BLE sensor).

### Proof Pack System

- **`zaptrace/proof/`** — New module for self-verifying design validation bundles.
  - `manifest.py` — Pydantic models for `ProofManifest`, `CheckDefinition`,
    `ManifestModel` with categories and severity levels.
  - `checker.py` — `ProofRunner` with 6 built-in check types: DRC, ERC,
    routed, clearance, footprint_exists, net_connected. Custom check registry.
  - `pack.py` — `ProofPack` class (load, run, summary, report_json).
    `run_proof()` convenience function.
  - `__init__.py` — Clean public API.
- **CLI** — `zaptrace proof run|list|info` commands for proof pack management.
- **MCP tools** — `proof_run`, `proof_run_design`, `proof_list_checks` tools
  registered in TOOL_REGISTRY and exposed via FastMCP.
- **Proof pack example** — `.proof/` directory in the ESP32 example with 8 checks.
- **Tests** — 35 proof module tests (manifest, checker, YAML round-trip, pack
  loading, CLI integration).

### Fixes (post-release)

- **README links fixed** — `docs/MCP.md` → `docs/mcp/quickstart.md`,
  `docs/REST_API.md` → `docs/GETTING_STARTED.md`,
  `docs/PROOF_PACK.md` → `docs/strategy/proof-pack-spec.md`,
  `examples/README.md` → `examples/`.
- **Version strings** — API server (`0.1.0→0.2.0`), agent shell, test assertions.
- **Entry point** — Added `zaptrace-api` script pointing to `zaptrace.api.server:run`.
- **Ruff cleanup** — Removed unused imports, trailing whitespace in `cli/proof.py`.
- **Formatting** — `cli/proof.py` reformatted.

### Tests

- Test suite passing under CI; exact counts are enforced by automation rather than hard-coded here.
- Test count includes 43 proof module tests + 500 existing tests.
