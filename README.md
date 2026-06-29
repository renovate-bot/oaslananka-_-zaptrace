<p align="center">
  <a href="https://www.buymeacoffee.com/oaslananka">
    <img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=%E2%98%95&slug=oaslananka&button_colour=FFDD00&font_colour=000000&font_family=Arial&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" />
  </a>
</p>

# ⚡ ZapTrace — Prompt-to-Fab

**ZapTrace** is an AI-native, verification-first, open-source electronic design automation (EDA) kernel for agents and engineers.

> **Pre-1.0.** All outputs require human engineering review before fabrication or use.
> See [Safety Disclaimer](#safety-disclaimer).

> From intent → normalized design → schematic → ERC → placement → routing → DRC → BOM → manufacturing package → auditable proof pack.

```
Prompt-to-Fab, with proofs.
AI-native EDA kernel for agents.
Verification-first electronics design.
Deterministic core, AI-assisted workflow.
No EDA dependency required, excellent EDA interoperability.
```

> **Proof Pack = evidence layer, not a guarantee.** See [verification model](#verification-model).

---

## What ZapTrace Is

- **A Python SDK** for programmatic electronics design — parse, validate, place, route, export.
- **A CLI** (`zaptrace`) for quick design iteration from the terminal.
- **An MCP server** (`zaptrace-mcp`) that exposes 85 agent-facing tools to AI agents.
- **A REST API** for web-based design workflows.
- **A verification engine** — Electrical Rule Checking (ERC) + Design Rule Checking (DRC) baked in.
- **A manufacturing export pipeline** — Gerber RS-274X, Excellon drill, BOM, pick-and-place, KiCad.
- **A proof-pack generator** — auditable, reproducible artifact bundles for every design.

## What ZapTrace Is Not

- ❌ **Not a replacement for KiCad, Altium, or Eagle** — ZapTrace is a *backend engine*, not a full PCB editor GUI.
- ❌ **Not a SPICE simulator** — no analog simulation (yet).
- ❌ **Not a replacement for human engineering judgment** — all outputs require review before fabrication.
- ❌ **Not fabrication-proven** — ZapTrace is pre-1.0. Manufacturing outputs are experimental.
- ❌ **Not fabrication-ready or production-ready** — no claim of fitness for manufacturing is made.
- ❌ **Proof Pack is not a correctness guarantee** — it is an evidence layer that records what was checked and what passed/failed. Absence of errors does not mean the design is correct or manufacturable.
- ❌ **KiCad Oracle (ERC/DRC) is external validation, not absolute correctness** — it catches rule violations the rules know about. A passing KiCad Oracle check does not guarantee a working circuit.
- ❌ **Fab profiles are not manufacturer approvals** — built-in profiles match common manufacturer capabilities, but you must verify against your specific manufacturer's current specifications. Always obtain pre-fabrication approval.
- ❌ **GitHub hardware CI cannot catch all hardware errors** — CI runs on simulated or limited hardware; physical validation (probe, power-up, functional test) is irreplaceable.

---

## Status

| Area | Status |
|------|--------|
| Design parsing | ✅ Implemented |
| Schematic synthesis | ⚠️ Template selection (keyword-matches a pre-built template; not from-scratch synthesis) |
| ERC (Electrical Rule Checking) | ✅ Implemented |
| Component placement | ✅ Implemented |
| Grid-based routing | ✅ Implemented |
| Net-aware smart routing | ✅ Implemented |
| DRC (Design Rule Checking) | ✅ Implemented |
| Net classification (EE knowledge) | ✅ Implemented |
| Copper pour generation | ✅ Implemented |
| Gerber RS-274X export | ✅ Implemented |
| Excellon drill export | ✅ Implemented |
| BOM (CSV + JSON) export | ✅ Implemented |
| Pick-and-place export | ✅ Implemented |
| KiCad schematic export | ✅ Implemented |
| SVG schematic rendering | ✅ Implemented |
| Manufacturing ZIP bundle | ✅ Implemented |
| MCP server (85 tools) | ✅ Implemented |
| Power-tree architecture planner + netlist emit | ✅ Implemented |
| REST API server | ✅ Implemented |
| Design diff | ✅ Implemented |
| Full pipeline (autopilot) | ✅ Implemented |
| Proof-pack system | 🚧 Experimental — v1 evidence hardening in M0 |
| Plugin system | 🚧 Experimental — signed runtime planned in M2 |
| Web-based viewer | 🔮 Planned |
| SPICE netlist export | 🔮 Planned — M3+ |
| DFM (Design for Manufacturing) | 🧪 Implemented foundation — fab-profile evidence hardening in M1 |
| Multi-board design | 🔮 Planned — post-M3 |
| RF/microwave awareness | 🔮 Planned |

---

## Quickstart

```bash
# Install
uv pip install zaptrace
```

The PyPI distribution is `zaptrace`; the Python import package and CLI commands remain `zaptrace`.

```bash
# Or from source
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
uv sync --all-extras

# Run diagnostics
zaptrace doctor

# Parse and validate a design
zaptrace parse examples/esp32_i2c_sensor_node/design.yaml
zaptrace erc my_design

# Generate manufacturing outputs
zaptrace export manufacturing my_design --output build/board
```

---

## CLI Usage

```bash
# Parse a design YAML
zaptrace parse design.yaml

# Inspect a parsed design
zaptrace inspect my_design

# Run ERC validation
zaptrace erc my_design

# List ERC rules
zaptrace erc-rules

# Place components
zaptrace place my_design

# Route nets
zaptrace route my_design

# Generate BOM
zaptrace bom my_design
zaptrace bom my_design --format json

# Generate design report
zaptrace report my_design --output report.md

# Render schematic SVG
zaptrace svg my_design --output schematic.svg

# Export to KiCad
zaptrace kicad my_design output/kicad/

# Diff two designs
zaptrace diff design_a design_b

# Search library
zaptrace library search resistor
zaptrace library get 0402_10k

# Run full pipeline
zaptrace pipeline --source design.yaml --output build/
zaptrace pipeline --intent "ESP32 I2C sensor node"
```

---

## Python SDK Usage

```python
from zaptrace.core.parser import parse_file
from zaptrace.erc.runner import ERCRunner
from zaptrace.algo.placer import place_components
from zaptrace.algo.router import route_design_smart
from zaptrace.export.manufacturing import generate_manufacturing_bundle
from zaptrace.ee.classifier import classify_design

# Parse
design = parse_file("design.yaml")

# Validate
runner = ERCRunner()
erc_result = runner.run(design)

# Classify nets
classify_design(design)

# Place & route
positions = place_components(design)
routing, route_result = route_design_smart(design, positions)

# Export
bundle = generate_manufacturing_bundle(design, "build/")
print(f"Gerber layers: {list(bundle['gerber_layers'].keys())}")
```

---

## MCP Usage

ZapTrace exposes an MCP server for AI agent integration.

```bash
# Start MCP server (stdio mode)
zaptrace-mcp

# Start MCP server (HTTP mode)
zaptrace-mcp --http --port 8090
```

Configure in your AI client's MCP settings:

```json
{
  "mcpServers": {
    "zaptrace": {
      "command": "zaptrace-mcp"
    }
  }
}
```

See [docs/mcp/quickstart.md](docs/mcp/quickstart.md) for the full tool catalog and prompt templates.

---

## REST API Usage

```bash
# Start API server
zaptrace-api

# Parse design
curl -X POST -H "Content-Type: multipart/form-data" \
  -F "file=@design.yaml" http://localhost:8000/parse

# Run ERC
curl http://localhost:8000/erc/my_design
```

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for REST API setup and usage.

---

## Manufacturing Export

ZapTrace generates all files needed for PCB fabrication:

| Artifact | Format | Status |
|----------|--------|--------|
| Copper layers | Gerber RS-274X | ✅ |
| Drill file | Excellon | ✅ |
| Bill of Materials | CSV / JSON | ✅ |
| Pick-and-place | CSV | ✅ |
| Manufacturing bundle | ZIP | ✅ |
| KiCad project | .kicad_pcb, .kicad_sch | ✅ |
| Schematic | SVG | ✅ |
| Design report | Markdown | ✅ |

```bash
# Generate everything
zaptrace export manufacturing my_design --output build/board
```

---

## Proof Pack

A Proof Pack is an auditable, reproducible artifact bundle that explains what ZapTrace generated and why.

```bash
zaptrace proof-pack design.yaml --output build/proof-pack
```

Each proof pack contains:
- Design inputs and normalized model
- ERC results (what was checked and what passed/failed)
- DRC results
- BOM and supply-chain overview
- All manufacturing artifacts
- Decision log
- Reproducibility metadata
- Warnings and review checklist

See [docs/strategy/proof-pack-spec.md](docs/strategy/proof-pack-spec.md) for details.

---

## Verification Model

ZapTrace uses a layered verification model. Each layer produces evidence; none is a correctness guarantee.

### Evidence Layers

| Layer | What It Does | What It Does NOT Do |
|-------|-------------|---------------------|
| **Parser** | Validates design YAML structure and constraints | Does not verify circuit functionality |
| **ERC (29 rules)** | Checks electrical rules (net connectivity, pin compatibility, power, power-tree, DNP-aware) | Does not simulate the circuit or verify timing |
| **DRC (16 rules)** | Checks physical design rules (clearance, width, drill) | Does not guarantee manufacturability |
| **KiCad Oracle** | Exports to KiCad and runs KiCad's ERC/DRC as external validation | KiCad may have different rules; a pass does not mean the design is correct |
| **Proof Pack** | Records all verification results, artifact hashes, environment metadata, and decisions | Evidence of what was checked, not a guarantee of correctness |
| **Fab Profiles** | Documents manufacturer capabilities (min trace, min drill, layers) | Not a manufacturer approval; always verify with your fab house |
| **GitHub Hardware CI** | Runs hardware-level integration checks on available runners | Cannot reproduce all real-world hardware conditions; physical testing required |

### What "Verification-First" Means

- Verification is **built into the pipeline**, not bolted on after export.
- Every design artifact has an auditable chain: who checked what, with which tool, and what result.
- The design pipeline stops on hard errors (ERC/DRC failures) and requires explicit override.
- **Human engineering review is mandatory** before fabrication. No automated tool can replace domain expertise.

### Non-Claims

ZapTrace does **not** claim:

- **Fabrication-ready** — no automated verification pipeline can guarantee a board will fabricate correctly.
- **Production-ready** — pre-1.0; APIs and outputs may change.
- **Manufacturer-approved** — fab profiles are reference configurations, not approvals.
- **Guaranteed correctness** — all verification tools have blind spots.
- **Fully automatic manufacturing** — every manufacturing output requires human review and fab house approval.

---

## Architecture

```mermaid
graph TD
    A[YAML Design File] --> B[Parser]
    A1[Natural Language Intent] --> B1[Synthesis Engine]
    B1 --> B

    B --> C[Design Model<br/>Pydantic]
    C --> D[EE Knowledge<br/>Classifier]

    D --> E[ERC Engine]
    E --> F{RC Passed?}

    F -->|Yes| G[Placer]
    F -->|No| H[Suggest Patches]
    H --> C

    G --> I[Router]
    I --> J[DRC Engine]

    J --> K{DRC Passed?}
    K -->|Yes| L[Export Pipeline]
    K -->|No| I

    L --> M[Gerber]
    L --> N[Excellon]
    L --> O[BOM]
    L --> P[Pick-and-Place]
    L --> Q[KiCad]
    L --> R[SVG Schematic]

    L --> S[Proof Pack Generator]
    S --> T[manifest.json + artifacts]

    C --> U[MCP Server]
    C --> V[REST API]
    C --> W[CLI]
```

---

## Example Gallery

| Example | Description |
|---------|-------------|
| [ESP32 I2C Sensor Node](examples/esp32_i2c_sensor_node/) | ESP32-C3 reading temperature/humidity over I2C |
| [RP2040 USB HID](examples/rp2040_usb_hid/) | RP2040-based USB keyboard controller |
| [USB-C LiPo Charger](examples/usb_c_lipo_charger/) | USB-C powered LiPo charger with protection |
| [STM32 RS485 Node](examples/stm32_rs485_node/) | Industrial STM32 RS485 Modbus node |
| [nRF52840 BLE Sensor](examples/nrf52840_ble_sensor/) | BLE environmental sensor with nRF52840 |

See [examples/](examples/) for design YAML files and walkthroughs.

---

## Safety Disclaimer

> **⚠️ ELECTRONICS DESIGN IS INHERENTLY RISKY.**
>
> ZapTrace is pre-1.0 software. All outputs — schematics, layouts, manufacturing files — **must be reviewed by a qualified electrical engineer before fabrication or use**.
>
> Incorrect PCB designs can cause:
> - Fire or thermal damage
> - Equipment damage
> - Electrical shock
> - Radio interference (legal liability)
> - Complete system failure
>
> ZapTrace is provided as-is, without warranty of any kind. The maintainers assume no liability for damages arising from the use of this software or its outputs.
>
> **Verification tools are evidence layers, not correctness guarantees.**
> - A passing ERC/DRC/KiCad Oracle check does not mean the design is correct or manufacturable.
> - A valid Proof Pack attests what was checked, not that the design is safe.
> - GitHub hardware CI cannot replace physical testing.
> - Fab profiles are reference configurations, not manufacturer approvals.
>
> **If you are not an electrical engineer, consult one before fabricating any ZapTrace-generated design.**
>
> See [docs/SAFETY.md](docs/SAFETY.md) for the full safety policy.

---

## Roadmap

| Horizon | Focus |
|---------|-------|
| **Now (v0.2)** | Proof-pack system, plugin architecture, manufacturing validation |
| **Next (v0.3)** | SPICE netlist export, DFM checks, multi-board support |
| **Soon (v0.4)** | Web-based viewer, interactive routing GUI, cloud CI integration |
| **Future (v0.5+)** | RF/microwave awareness, thermal simulation, ML-assisted placement |

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full roadmap.

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- **Issue tracker**: [GitHub Issues](https://github.com/oaslananka/zaptrace/issues)
- **Discussions**: [GitHub Discussions](https://github.com/oaslananka/zaptrace/discussions)
- **Code of Conduct**: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## License

MIT License — see [LICENSE](LICENSE).  
ZapTrace is free for commercial and personal use.

---

## Current Limitations

- **Pre-1.0**: APIs are unstable and may change without notice.
- **No GUI**: All interaction is CLI/SDK/MCP-based.
- **No SPICE**: No analog or mixed-signal simulation.
- **No interactive routing editor**: Routing is algorithmic (grid-based).
- **Schematic synthesis is template-based**: Does not use LLM-generated designs.
- **Limited package library**: ~50 common packages supported.
- **No thermal analysis**: No thermal simulation or PDN analysis.
- **No signal integrity analysis**: No SI/PI/EMI analysis.
- **Not fabrication-ready**: No claim of manufacturing readiness is made.
- **Not production-ready**: Pre-1.0; APIs, formats, and outputs may change without notice.
- **Proof Pack is evidence, not guarantee**: A passing Proof Pack does not mean the design is correct, safe, or manufacturable.
- **KiCad Oracle is external validation**: KiCad's own ERC/DRC has limitations. A passing check does not guarantee circuit functionality.
- **Fab profiles are not manufacturer approval**: Always verify with your specific fab house.
- **GitHub hardware CI ≠ physical testing**: CI cannot reproduce all real-world conditions.
- **KiCad export is unidirectional**: No KiCad file import.
- **Plugin system is experimental**: Not yet stable. Runtime safety design in progress.
- **Proof-pack system is experimental**: Format may change.
