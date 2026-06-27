# ZapTrace AI-Native EDA Engine — Design Specification

**Date:** 2026-06-08
**Status:** Draft
**Author:** AI Agent (approved by user)

---

## 1. Executive Summary

ZapTrace is an **AI-native electronics design engine** that produces professional-grade
schematics and PCB layouts without depending on any commercial EDA tool (KiCad, Altium,
Eagle, etc.). It embeds electrical engineering knowledge — component selection, pin
assignment, routing rules, manufacturing constraints — directly into its design pipeline,
so an AI agent can describe what it wants and get back verified Gerber files. **All outputs require human engineering review before fabrication.**

**Key differentiator:** Every other "AI for EDA" tool is a wrapper around an existing EDA
(KiCad MCP Server, Circuit-Synth, ALT TAB Circuit Copilot). ZapTrace *is the EDA*,
designed from the ground up for AI agent consumption.

---

## 2. Core Principles

| # | Principle | Explanation |
|---|-----------|-------------|
| 1 | **No EDA dependency** | Output standard formats (Gerber, Excellon, IPC-2581, PDF). Input YAML. Zero license cost. |
| 2 | **EE knowledge built-in** | Default routing rules, clearance tables, stackup presets, DFM rules. Agent doesn't restate them. |
| 3 | **Agent-native first** | MCP (27+ tools), REST API, CLI — all equal citizens. Design steps are composable. |
| 4 | **Progressive override** | Sensible defaults for everything. Agent overrides only what's special about *this* design. |
| 5 | **Deterministic + verifiable** | Same input → same output. ERC + DRC + simulation gates on every path. |
| 6 | **Review-grade manufacturing artifacts** | Gerber, drill, BOM, and pick-and-place outputs for validation; production use requires external checks and human approval. |

---

## 3. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AI Agent Layer                             │
│  (Any LLM: Claude, GPT, Gemini, Llama, DeepSeek, etc.)           │
│  MCP Tools │ REST API │ CLI                                      │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                    ZapTrace Engine (Python)                        │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │   Design     │  │   Library    │  │    EE Knowledge Base     │ │
│  │   Model      │──│   Manager    │──│  (rules, constraints,    │ │
│  │   (Pydantic) │  │   (YAML)     │  │   defaults, presets)     │ │
│  └──────┬───────┘  └──────────────┘  └────────────┬─────────────┘ │
│         │                                          │              │
│         ▼                                          ▼              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Schematic   │  │    ERC       │  │    Netlist Classifier    │ │
│  │  Engine      │──│  (18 rules)  │──│  (power, signal, bus,   │ │
│  │              │  │              │  │   differential, RF...)   │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                 │                        │              │
│         ▼                 ▼                        ▼              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Placement   │  │    DRC       │  │    Autorouter            │ │
│  │  Engine      │──│  (40+ rules) │──│  (Freerouting backend)   │ │
│  │  (Rust + Py) │  │              │  │  + ZapTrace rule adapter │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                 │                        │              │
│         ▼                 ▼                        ▼              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  SPICE/Sim   │  │   BOM +      │  │    Manufacturing Export  │ │
│  │  (ngspice)   │  │  PnP Gen     │  │  (Gerber, Excellon,      │ │
│  │              │  │              │  │   IPC-2581, ODB++)       │ │
│  └─────────────┘  └──────────────┘  └──────────────────────────┘ │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │              Integration Adapters (optional)                  │ │
│  │  KiCad │ Altium │ JLCPCB │ LCSC │ PCBWay                     │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Data Flow — Full Design Cycle

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: SPECIFY                                                   │
│                                                                     │
│  Agent: "ESP32-S3 + 16MB PSRAM + ST7789 display + BME280 +         │
│          USB-C + LiPo charger + 3.3V LDO"                           │
│                                                                     │
│  ↓ parse_design() / synthesize() → Design(Pydantic)                 │
│    - Resolve components from library (70+ YAML)                     │
│    - Auto-assign pins (I2C, SPI, UART, GPIO, power)                │
│    - Generate netlist                                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│  PHASE 2: VERIFY                                                    │
│                                                                     │
│  ↓ run_erc() → ERCResult (18 rules)                                 │
│    - Missing pull-ups on I2C/open-drain busses                      │
│    - Unconnected power/ground pins                                  │
│    - Short circuits, duplicate net names                            │
│    - Mixed voltage domains without level shifters                   │
│    - Decoupling capacitor missing on IC power pins                  │
│    - Missing bypass caps per IC                                     │
│                                                                     │
│  ↓ run_simulation() → SimulationResult (optional)                   │
│    - ngspice transient analysis                                     │
│    - DC sweep for voltage regulators                                │
│    - AC analysis for filters                                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│  PHASE 3: LAYOUT                                                    │
│                                                                     │
│  ↓ place_components() → Positions (Rust MST + force-directed)      │
│    - Group by function (PSU near input, MCU center, connectors edge)│
│    - Thermal-aware placement (regulators away from sensors)        │
│    - Decoupling caps → within 3mm of IC power pins                 │
│                                                                     │
│  ↓ route_board(design, positions) → RouterResult                   │
│    - Stackup-aware layer assignment                                 │
│    - Signal integrity: 45°/arc routing, no 90° corners             │
│    - Differential pairs (USB, HDMI): length-matched, coupled        │
│    - Power nets: wider traces (default: 0.3mm signal, 0.5mm power) │
│    - Clearance: 0.15mm default, 0.2mm for high-voltage             │
│    - Via parameters: 0.3/0.15mm default pad/hole                   │
│    - No floating copper islands (orphans)                           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│  PHASE 4: CHECK                                                     │
│                                                                     │
│  ↓ run_drc(design, layout) → DRCResult (40+ rules)                 │
│    - Electrical: clearance, creepage, via annular ring              │
│    - Manufacturing: min trace, min hole, solder mask sliver         │
│    - Signal integrity: stub length, parallel run length             │
│    - Thermal: copper coverage %, thermal vias per component         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│  PHASE 5: EXPORT                                                    │
│                                                                     │
│  ↓ export_gerber(design, layout, output_dir) → FileList             │
│    - .GTL (Top Layer) / .GBL (Bottom Layer)                         │
│    - .GTS (Top Solder) / .GBS (Bottom Solder)                       │
│    - .GTO (Top Silkscreen) / .GBO (Bottom Silkscreen)               │
│    - .GTP (Top Paste) / .GBP (Bottom Paste)                         │
│    - .GKO (Keepout) / .GM1 (Board Outline)                          │
│    - .TXT (Excellon Drill)                                          │
│                                                                     │
│  ↓ export_bom(design) → CSV + JSON                                  │
│  ↓ export_pnp(design, positions) → CSV (pick-and-place)             │
│  ↓ export_schematic_pdf(design) → PDF                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Detailed Module Specifications

### 4.1 Design Model (`zaptrace/core/models.py`) — Extend

Current Pydantic models need extensions for PCB-level data.

**New/Extended fields:**

```python
# In Component
class Component(BaseModel):
    # Existing: id, ref, type, value, footprint, mpn, manufacturer, lifecycle, datasheet, pins
    # New:
    symbol: SymbolDef | None          # Schematic symbol geometry
    footprint: FootprintDef | None    # PCB footprint geometry
    thermal: ThermalSpec              # Thermal requirements (power dissipation, need for vias)
    voltage_rating: float | None      # For clearance calculations
    current_rating: float | None      # For trace width calculations
    frequency_rating: float | None    # For signal integrity

class SymbolDef(BaseModel):
    """Vector symbol definition for schematic rendering."""
    pins: list[SymbolPin]            # Pin positions on symbol
    body: list[DrawCommand]          # Lines, arcs, rectangles, text
    origin: tuple[float, float]      # Center point

class FootprintDef(BaseModel):
    """PCB land pattern definition."""
    pads: list[Pad]                  # SMD pads or THT holes
    outline: list[DrawCommand]       # Component outline on silkscreen
    courtyard: tuple[float, float]   # Courtyard width/height
    assembly: tuple[float, float]    # Assembly layer info
    height: float                    # 3D height for clearance
    thermal_pads: list[str] | None   # Pad IDs that are thermal

class Pad(BaseModel):
    id: str
    layer: LayerSet                  # Top/Bottom/All
    shape: PadShape                  # Rect, Circle, Oval, Custom
    position: tuple[float, float]    # Center position relative to footprint origin
    size: tuple[float, float]        # Width x height
    drill: float | None              # Through-hole drill diameter
    plated: bool = True
    solder_paste: bool = True        # Include in paste layer

# New Board-level model
class BoardDefinition(BaseModel):
    width: float                     # Board dimensions (mm)
    height: float
    layers: int                      # 2, 4, 6, 8...
    layer_stack: list[LayerSpec]     # Each layer: name, type (signal/power/ground), thickness, material
    outline: list[tuple[float, float]]  # Board outline polygon
    cutouts: list[list[tuple[float, float]]]  # Internal cutouts
    mounting_holes: list[MountingHole]
    constraints: BoardConstraints

class BoardConstraints(BaseModel):
    min_trace: float = 0.15          # mm
    min_trace_power: float = 0.3     # mm
    min_clearance: float = 0.15      # mm
    min_clearance_high_voltage: float = 0.3  # >50V
    min_hole: float = 0.15           # mm
    min_annular_ring: float = 0.13   # mm
    min_solder_mask_sliver: float = 0.1
    via_pad: float = 0.45            # mm (default via pad diameter)
    via_hole: float = 0.2            # mm (default via hole)
    default_trace_signal: float = 0.2
    default_trace_power: float = 0.5
    default_trace_high_current: Callable[[float], float]  # A → mm (IPC-2221 lookup)

# In Design
class Design(BaseModel):
    meta: DesignMeta
    components: dict[str, Component]
    nets: dict[str, Net]
    board: BoardDefinition | None    # NEW: PCB board definition
    placement: dict[str, tuple[float, float]] | None  # NEW: component positions
    routing: RouteResult | None      # NEW: routed traces
```

### 4.2 EE Knowledge Base (`zaptrace/ee/`)

**New package** — the brain of the system.

```
zaptrace/ee/
├── __init__.py
├── knowledge.py        # Central KB loader, version, metadata
├── routing/
│   ├── __init__.py
│   ├── defaults.py     # Default trace widths by net class
│   ├── clearance.py    # Clearance tables (IPC-2221, IPC-7351)
│   ├── stackup.py      # Layer stackup presets
│   └── dfm.py          # Manufacturing constraints by fab house
├── placement/
│   ├── __init__.py
│   ├── grouping.py     # Functional grouping rules
│   ├── decoupling.py   # Decap placement rules
│   └── thermal.py      # Thermal management rules
├── constraints/
│   ├── __init__.py
│   ├── net_classes.py  # Net class definitions
│   └── differential.py # Differential pair rules
└── presets/
    ├── 2layer_standard.yaml
    ├── 4layer_standard.yaml
    ├── 4layer_rf.yaml
    └── 6layer_ddr.yaml
```

#### 4.2.1 Net Classes

Every net is auto-classified. Each class carries routing rules:

| Class | Trace Width | Clearance | Via Count | Notes |
|-------|-------------|-----------|-----------|-------|
| `signal_low` | 0.2mm | 0.15mm | 2 max | GPIO, SPI, I2C, UART |
| `signal_high` | 0.25mm | 0.2mm | 2 max | High-speed, >10MHz |
| `signal_analog` | 0.3mm | 0.25mm | 1 max | Guard ring, no vias under |
| `power_low` | 0.3mm | 0.2mm | 4 max | <100mA rails |
| `power_med` | 0.5mm | 0.2mm | 4 max | 100mA-500mA |
| `power_high` | IPC-2221 calc | 0.3mm | unlimited | >500mA |
| `ground` | 0.5mm min | 0.15mm | unlimited | Star/flood |
| `differential` | 0.2mm | 0.15mm (within pair) | matched | USB, HDMI, Ethernet |
| `rf` | 50Ω impedance | 0.3mm | none in path | Antenna, RF |

#### 4.2.2 Clearance Tables

Default clearance matrix (from IPC-2221B):

| | Signal | Power | Ground | High-V (>50V) |
|---|---|---|---|---|
| Signal | 0.15 | 0.2 | 0.15 | 0.3 |
| Power | 0.2 | 0.2 | 0.2 | 0.4 |
| Ground | 0.15 | 0.2 | 0.15 | 0.3 |
| High-V | 0.3 | 0.4 | 0.3 | 0.6 |

#### 4.2.3 Routing Rules (EE Knowledge)

1. **No 90° corners** — traces route at 45° or arcs for high-speed
2. **Avoid right angles** — acid traps, impedance discontinuity
3. **Via count** — signal nets ≤ 2 vias, power nets generous
4. **Decoupling caps** — within 3mm of IC power pins, shortest path to via
5. **Differential pairs** — coupled routing (gap = 2× trace width), length matched (±0.5mm)
6. **Crystal/oscillator** — short traces, guard ring, no other traces under
7. **Analog separation** — no digital traces through analog zone
8. **Thermal relief** — 4-spoke for through-hole, 2-4 spoke for SMD pads
9. **Copper pour** — ground flood preferred on outer layers, stitching vias every 5mm
10. **Star ground** — single-point ground for mixed-signal designs

---

### 4.3 Schematic Engine (`zaptrace/schematic/`)

**Purpose:** Generate professional-looking schematic diagrams as SVG/PDF.

```
zaptrace/schematic/
├── __init__.py
├── engine.py             # Main orchestrator
├── symbol_library.py     # Built-in symbol definitions
├── placement.py          # Auto-placement on schematic canvas
├── routing.py            # Connection routing on schematic (bus, wire, junction)
├── annotation.py         # Text, labels, title block, BOM table
├── renderers/
│   ├── __init__.py
│   ├── svg.py            # SVG renderer
│   ├── pdf.py            # PDF via SVG → cairo/weasyprint
│   └── png.py            # PNG rasterization
└── presets/
    ├── default.yaml       # Page size, grid, font, styles
    ├── a4.yaml
    └── letter.yaml
```

#### 4.3.1 Symbol Library

YAML-based symbols with vector geometry:

```yaml
# zaptrace/schematic/symbols/resistor.yaml
symbol:
  name: resistor_h
  pins:
    - id: "1"
      position: [0.0, 0.0]
      orientation: left
      length: 5.0
    - id: "2"
      position: [30.0, 0.0]
      orientation: right
      length: 5.0
  body:
    - type: rect
      x: 5, y: -8, w: 20, h: 16
      fill: none, stroke: black
    - type: text
      x: 15, y: 0
      text: "{value}"
      anchor: center
      size: 8
    - type: text
      x: 15, y: -14
      text: "{ref}"
      anchor: center
      size: 10
  origin: [15.0, 0.0]
```

Supported symbols: resistor, capacitor (polarized/non), inductor, diode, LED, transistor
(NPN/PNP/MOSFET), IC (multi-pin configurable), connector, crystal, fuse, bead, transformer,
op-amp, regulator, header, jumper, test point, ground, power, net label, off-page.

#### 4.3.2 Schematic Auto-Placement

The schematic engine places components on the canvas:

1. **Left-to-right flow:** Inputs/connectors left, MCU center, outputs right
2. **Power top-down:** VCC top, GND bottom
3. **Functional grouping:** I2C devices near each other, SPI devices near each other
4. **Bus routing:** Thicker lines for bus connections, labels for clarity
5. **Hierarchical sheets:** Complex designs → sub-sheets (power, MCU, I/O, sensors)
6. **Title block:** Design name, author, date, revision, sheet count, page number

#### 4.3.3 Schematic Quality Standards

- Grid alignment (2.54mm / 100mil grid)
- No overlapping components
- No crossing wires (use net labels or jumper dots)
- Proper junction dots at T-connections
- Power/ground symbols explicit (not hidden)
- Decoupling caps shown near IC (not in power section)
- All unused pins labelled "NC" or terminated per datasheet

---

### 4.4 PCB Engine (`zaptrace/pcb/`)

**Purpose:** Generate professional PCB layouts.

```
zaptrace/pcb/
├── __init__.py
├── board.py                # Board definition and stackup
├── footprint_library.py    # Land pattern generator (IPC-7351B)
├── layers.py               # Layer management and assignment
├── exporters/
│   ├── __init__.py
│   ├── gerber.py           # RS-274X Gerber output
│   ├── excellon.py         # Excellon drill output
│   ├── ipc2581.py          # IPC-2581 output (future)
│   ├── kicad_pcb.py        # .kicad_pcb output (optional integration)
│   └── step.py             # 3D STEP export (future)
└── presets/
    ├── 2layer_default.yaml
    ├── 4layer_default.yaml
    └── 4layer_iot.yaml     # Common for IoT: SIG/GND/PWR/SIG
```

#### 4.4.1 Footprint Library

IPC-7351B parametric footprint generator. Footprints defined by package family + dimensions:

```yaml
# zaptrace/pcb/footprints/resistors.yaml
- family: chip
  variants:
    - code: 0402
      body: [1.0, 0.5]
      height: 0.35
      pad_size: [0.5, 0.6]
      pad_pitch: 0.5
      courtyard: [1.6, 1.0]
    - code: 0603
      body: [1.6, 0.8]
      height: 0.45
      pad_size: [0.8, 0.9]
      pad_pitch: 1.0
      courtyard: [2.4, 1.4]
    - code: 0805
      body: [2.0, 1.25]
      height: 0.5
      pad_size: [1.0, 1.3]
      pad_pitch: 1.5
      courtyard: [3.0, 2.0]
```

Supported families: chip (R/C), SOT-23/89/223, SOIC, TSSOP, QFN, QFP, BGA, DIP,
SOD, SMA/B/C-DO214, TO-252/263, USB, HDMI, RJ45, JST, pin headers (2.54mm/2.0mm/1.27mm).

#### 4.4.2 Force-Directed Placement (Rust)

Current MST-based placement (Rust) is extended with:

1. **Component grouping:** Components on same bus → placed together
2. **Decoupling priority:** Caps placed first, nearest to IC
3. **Connector edge placement:** USB, power, audio → board edge
4. **Thermal zoning:** Regulators spaced from temperature sensors
5. **Keepout zones:** Antenna keepout, connector copper clearance
6. **Board outline compliance:** Components inside board boundary

#### 4.4.3 Autorouter Integration (Freerouting)

Freerouting (open-source, Java) is called as a subprocess:

```python
def route_board(design, positions):
    # 1. Export design to Freerouting format (DSN/SES or native JSON)
    dsn = render_specctra_dsn(design, positions)
    
    # 2. Apply ZapTrace routing rules as Freerouting constraints
    dsn = inject_constraints(dsn, design.board.constraints, net_classes)
    
    # 3. Run Freerouting headless
    result = subprocess.run(
        ["java", "-jar", "freerouting.jar", "-de", dsn_path, "-do", output_dir],
        capture_output=True, timeout=120
    )
    
    # 4. Parse result back to ZapTrace RouteResult
    routes = parse_freerouting_ses(output_dir / "output.ses")
    
    # 5. Post-process: arc fillet, via optimization
    routes = optimize_routes(routes)
    
    # 6. DRC check
    drc = run_drc(design, routes)
    
    return RouteResult(routes=routes, drc=drc)
```

**Fallback:** If Freerouting not available, use ZapTrace's built-in MST + push-aside router
(current Rust implementation) for basic connectivity.

---

### 4.5 DRC Engine (`zaptrace/drc/`)

**Purpose:** Catch real PCB manufacturing and electrical issues.

```
zaptrace/drc/
├── __init__.py
├── engine.py               # DRC orchestrator, rule registry
├── rules/
│   ├── __init__.py
│   ├── electrical.py       # Clearance, creepage, net connectivity
│   ├── manufacturing.py    # Min trace, min hole, annular ring, slivers
│   ├── signal_integrity.py # Stub length, parallel run, impedance
│   ├── thermal.py          # Copper coverage, thermal vias
│   ├── dfm.py              # Solder mask, silkscreen, paste coverage
│   └── placement.py        # Component overlap, board edge clearance
├── models.py               # DRCResult, DRCViolation, DRCSeverity
└── presets/
    ├── standard.yaml        # Standard PCB fabrication
    ├── prototype.yaml       # Relaxed for prototype runs
    └── automotive.yaml      # Strict for automotive/industrial
```

#### 4.5.1 DRC Rules (40+)

| ID | Rule | Severity | Threshold |
|----|------|----------|-----------|
| DRC-001 | Trace-to-trace clearance | Error | <0.15mm |
| DRC-002 | Trace-to-pad clearance | Error | <0.15mm |
| DRC-003 | Pad-to-pad clearance | Error | <0.15mm |
| DRC-004 | Min trace width | Error | <0.15mm (signal) |
| DRC-005 | Min trace width (power) | Error | IPC-2221 calc |
| DRC-006 | Min annular ring | Error | <0.13mm |
| DRC-007 | Min drill hole | Error | <0.15mm |
| DRC-008 | Solder mask sliver | Warning | <0.1mm |
| DRC-009 | Silkscreen over pad | Warning | Any overlap |
| DRC-010 | Unconnected net | Error | Any |
| DRC-011 | Single-node net | Warning | Any |
| DRC-012 | Starved thermal | Error | Any |
| DRC-013 | Copper island/orphan | Warning | Any |
| DRC-014 | Via-in-pad (non-plugged) | Warning | Any |
| DRC-015 | Component overlap | Error | Any |
| DRC-016 | Component off-board | Error | Any |
| DRC-017 | Board edge clearance (<0.5mm) | Warning | <0.5mm |
| DRC-018 | Trace length mismatch (diff pair) | Error | >0.5mm |
| DRC-019 | Stub length > 5mm | Warning | >5mm |
| DRC-020 | Parallel run > 20mm (high-speed) | Warning | >20mm |
| DRC-021 | Right-angle trace | Warning | 90° without chamfer |
| DRC-022 | Thermal via count insufficient | Warning | Per component |
| DRC-023 | Copper coverage < 30% (outer) | Info | <30% |
| DRC-024 | Copper coverage > 90% (inner) | Info | >90% |
| DRC-025 | Missing solder paste on SMD | Warning | Any SMD pad |
| DRC-026 | Incorrect pad shape | Warning | Per footprint spec |
| DRC-027 | Plated slot aspect ratio | Error | >8:1 |
| DRC-028 | Neck-down < 50% trace width | Warning | <50% |
| DRC-029 | Acute angle < 45° | Warning | Any |
| DRC-030 | Acid trap | Warning | <90° internal |

---

### 4.6 Netlist Classifier (`zaptrace/algo/net_classifier.py`)

**New module.** Automatically classifies every net in the design.

```python
class NetClass(Enum):
    SIGNAL_LOW = "signal_low"          # GPIO, control, <10MHz
    SIGNAL_HIGH = "signal_high"        # >10MHz digital
    SIGNAL_ANALOG = "signal_analog"    # ADC, sensor, op-amp
    POWER_LOW = "power_low"            # <100mA
    POWER_MED = "power_med"            # 100mA-500mA
    POWER_HIGH = "power_high"          # >500mA
    GROUND = "ground"                  # GND, ground plane
    DIFFERENTIAL = "differential"      # USB, HDMI, Ethernet
    RF = "rf"                          # Antenna, RF matching
    BUS = "bus"                        # Multi-drop (I2C, SPI, etc.)

def classify_net(net: Net, components: dict[str, Component]) -> NetClass:
    """Classify net based on connected pins and their types."""
    ...

def classify_design(design: Design) -> dict[str, NetClass]:
    """Classify all nets in a design."""
    ...
```

**Classification heuristics:**
- Net named "VCC"/"VDD"/"3V3"/"5V" → POWER_*
- Net named "GND"/"GNDA"/"VSS" → GROUND
- Net connected to USB_DP/DM pins → DIFFERENTIAL
- Net connected to ADC_IN pins → SIGNAL_ANALOG
- Net connected to antenna pin → RF
- Net with multiple drivers → BUS
- Net named I2C_SCL/SDA → BUS (with open-drain tag)
- Otherwise → SIGNAL_LOW (or SIGNAL_HIGH if >10MHz component)

---

### 4.7 Manufacturing Export (`zaptrace/export/`)

**Extend existing export module.**

#### 4.7.1 Gerber RS-274X

```python
def export_gerber(design: Design, output_dir: Path) -> dict[str, Path]:
    """Generate Gerber files for all layers."""
```

Gerber files generated:
| File | Layer | Extension |
|------|-------|-----------|
| Top copper | F.Cu | .GTL |
| Bottom copper | B.Cu | .GBL |
| Top solder mask | F.Mask | .GTS |
| Bottom solder mask | B.Mask | .GBS |
| Top silkscreen | F.Silkscreen | .GTO |
| Bottom silkscreen | B.Silkscreen | .GBO |
| Top paste | F.Paste | .GTP |
| Bottom paste | B.Paste | .GBP |
| Board outline | Edge.Cuts | .GM1 |
| Keepout | Keepout | .GKO |
| Inner layers (4+ layer) | In1.Cu ... | .G2, .G3... |
| Inner planes (4+ layer) | In1.Cu (plane) | .G2P, .G3P... |

#### 4.7.2 Excellon Drill

```python
def export_excellon(design: Design, output_dir: Path) -> Path:
    """Generate Excellon drill file(s) — plated and non-plated."""
```

#### 4.7.3 Pick-and-Place

```python
def export_pnp(design: Design, positions: dict[str, tuple[float, float]], output_dir: Path) -> Path:
    """Generate pick-and-place CSV for assembly."""
```

Format: Designator, Footprint, X, Y, Rotation, Layer, Value, MPN

#### 4.7.4 BOM Enhancement

Current BOM export extended with:
- Manufacturer MPN (already in component model)
- LCSC part number (via library or API)
- Quantity per board
- Reference designators grouped
- Lifecycle status
- Alternate part numbers

#### 4.7.5 PDF Schematic

```python
def export_schematic_pdf(design: Design, output_dir: Path) -> Path:
    """Render schematic as PDF via SVG -> WeasyPrint/cairo."""
```

---

### 4.8 Integration Layer (`zaptrace/integrations/`)

**Optional adapters** — not dependencies, just optional reach.

```
zaptrace/integrations/
├── __init__.py
├── kicad/
│   ├── __init__.py
│   ├── import_sch.py      # Read .kicad_sch → Design
│   ├── export_sch.py      # Design → .kicad_sch
│   ├── import_pcb.py      # Read .kicad_pcb → Design
│   └── export_pcb.py      # Design → .kicad_pcb (for KiCAD GUI editing)
├── jlcpcb/
│   ├── __init__.py
│   ├── parts_search.py    # LCSC API: search by MPN/parameters
│   ├── pricing.py         # Get pricing and stock
│   ├── order_bom.py       # Submit BOM for assembly
│   └── pcb_order.py       # Submit Gerber for fabrication
├── altium/
│   └── import.py          # Altium ASCII import (future)
└── symbol_server/
    └── snap_eda.py         # SnapEDA/UltraLibrarian import (future)
```

---

### 4.9 Simulation Integration (`zaptrace/simulation/`)

```
zaptrace/simulation/
├── __init__.py
├── netlist.py              # Design → SPICE netlist
├── ngspice.py              # Run ngspice, parse results
├── models.py               # SimulationResult, Waveform
└── analysis/
    ├── __init__.py
    ├── transient.py         # Transient analysis setup
    ├── dc_sweep.py          # DC sweep
    └── ac.py                # AC analysis
```

**Integration pattern:**
```python
def run_simulation(design: Design, analysis: AnalysisType) -> SimulationResult:
    # 1. Extract relevant subcircuit (or full design)
    # 2. Generate SPICE netlist with .model cards
    # 3. Write .cir file
    # 4. Run: subprocess.run(["ngspice", "-b", netlist_path])
    # 5. Parse .raw output → SimulationResult
    # 6. Generate SVG waveforms
    # 7. Compare against expected values (ERC-style checks)
```

---

## 5. Built-in EE Knowledge: Expert Rules

Beyond basic routing, ZapTrace embeds professional EE practices:

### 5.1 Power Distribution

- **Star topology** for mixed-signal (analog VCCA separate from digital VCC)
- **Ferrite bead** between analog/digital power domains
- **Bulk capacitance**: 10µF per IC minimum, 47-100µF per board
- **Decoupling**: 100nF per power pin pair, within 3mm, shortest GND return
- **Power trace width**: IPC-2221 external: `W = (I / (k × T^0.44))^(1/0.725)` where k=0.048 (external), 0.024 (internal)

### 5.2 Signal Integrity

- **USB 2.0**: 90Ω differential, 4-layer recommended, GND trace between D+/D-
- **USB 3.0**: 90Ω diff, length match ±100µm, no vias on high-speed pairs
- **I2C**: short traces (<50cm), pull-up resistor calculation: `Rp = (VCC - 0.4) / 3mA`
- **SPI**: trace length match for >20MHz, series resistor (22-33Ω) near source
- **Ethernet**: 100Ω diff, magnetics close to RJ45, no vias under magnetics
- **SDIO**: length match ±1mm, no 90° corners, keepout from noisy traces
- **Crystal**: 15pF-30pF load caps (per crystal datasheet), parallel feedback R

### 5.3 Thermal Management

- **Regulator junction temp**: `TJ = TA + (RθJA × PD)` — warn if >85°C
- **Thermal vias**: 9-via array under QFN power pad, 0.3mm holes
- **Copper pour**: at least 30% copper on outer layers for thermal dissipation
- **Component spacing**: keep high-power parts >5mm from sensors

### 5.4 EMC/EMI

- **Guard traces**: Analog signals get GND guard trace on both sides
- **Via stitching**: GND vias every λ/20 (max 5mm) along RF edges
- **Ferrite on cables**: I/O connectors get ferrite bead + 100nF cap
- **Chassis GND**: mounting holes → chassis ground with 1MΩ || 1nF to GND
- **Split planes**: don't route signals over split plane boundaries

### 5.5 DFM (Design for Manufacturing)

- **Panelization**: keep board rectangular, min 50×50mm, mouse bites for depanel
- **Silkscreen**: 0.15mm min line width, 0.8mm min text height
- **Solder mask**: 0.1mm minimum sliver, 0.05mm misregistration tolerance
- **Paste**: 80-100% coverage for fine-pitch, 70-80% for standard
- **V-score**: allow 5mm from board edge for V-groove
- **Fiducials**: 1mm circle, one at diagonal corners, solder mask opening

---

## 6. MCP Tools — Revised and Extended

Current: 27 tools. Target: 45+ tools.

### 6.1 New MCP Tools

| Tool | Description |
|------|-------------|
| `design_set_board` | Set board dimensions, layer count, stackup |
| `design_import_kicad_sch` | Import KiCad schematic → ZapTrace Design |
| `design_import_kicad_pcb` | Import KiCad PCB → ZapTrace Design |
| `place_components_auto` | Auto-place components with force-directed algorithm |
| `place_set_position` | Manual override for a component position |
| `route_board` | Route all nets (Freerouting backend) |
| `route_net_manual` | Manual trace route for a single net |
| `run_drc` | Full DRC check, return violations |
| `run_drc_rule` | Run a single DRC rule |
| `export_gerber` | Generate Gerber files |
| `export_excellon` | Generate drill files |
| `export_pnp` | Generate pick-and-place CSV |
| `export_schematic_pdf` | Generate PDF schematic |
| `export_all` | Generate all manufacturing files |
| `simulate_netlist` | Export SPICE netlist |
| `simulate_run` | Run ngspice simulation |
| `library_search_footprint` | Search footprints by package |
| `library_get_footprint` | Get footprint geometry |
| `library_add_component` | Add component to user library |
| `drc_get_rules` | List all DRC rules with thresholds |
| `drc_set_rule` | Override a DRC rule threshold |
| `board_preview_3d` | Generate 3D preview (STL/STEP) |

### 6.2 Revised Existing Tools

| Tool | Change |
|------|--------|
| `design_parse` | Accept board definitions |
| `design_synthesize` | Use net classifier, auto-assign trace classes |
| `erc_run` | New rules: thermal, decap count, voltage domain |
| `export_bom` | Include LCSC part numbers, pricing |
| `export_svg` | Enhanced: proper symbols, grid, title block |

---

## 7. Implementation Phases

### Phase 1: Foundation (3 weeks)
**Priority: HIGHEST**

1. **Extend design model** — Add board, footprint, symbol models
2. **EE Knowledge Base** — Routing rules, clearance tables, net classes
3. **Netlist Classifier** — Auto-classify nets
4. **DRC Engine (core)** — DRC-001 to DRC-020 (electrical + manufacturing)
5. **Gerber exporter (basic)** — Top/bottom copper + solder mask + silkscreen
6. **Excellon exporter** — Drill files

**Goal:** `design_parse` → `run_erc` → `place_components` → `route_board` (basic) → `run_drc` → `export_gerber`

### Phase 2: Schematic Engine (2 weeks)
**Priority: HIGH**

1. **Symbol library** — 50+ vector symbols
2. **Schematic auto-placement** — Left-to-right, functional grouping
3. **SVG renderer (pro)** — Proper symbols, grids, title blocks
4. **PDF export** — Via weasyprint/cairo
5. **Schematic export (KiCad)** — Optional .kicad_sch output

### Phase 3: Professional Routing (3 weeks)
**Priority: HIGH**

1. **Freerouting integration** — DSN/SES protocol adapter
2. **Rule injection** — ZapTrace net classes → Freerouting constraints
3. **Post-processing** — Arc fillet, via reduction, 45° enforcement
4. **Differential pair routing** — Length matching, coupled traces
5. **Copper pour** — Ground flood, thermal reliefs, stitching vias

### Phase 4: Verification (2 weeks)
**Priority: MEDIUM**

1. **Simulation netlist** — Design → SPICE circuit
2. **ngspice runner** — Subprocess integration
3. **Waveform parser** — Transient/DC/AC results
4. **Sim-to-DRC bridge** — Compare simulation vs DRC

### Phase 5: Manufacturing Pipeline (2 weeks)
**Priority: MEDIUM**

1. **JLCPCB API** — Parts search, pricing, ordering
2. **Pick-and-place** — Rotation optimization, panelization
3. **BOM enhancement** — LCSC MPN, stock check, alternatives
4. **All Gerber layers** — Inner layers, paste, keepout

### Phase 6: Polish & docs (1 week)
**Priority: LOW (ongoing)**

1. **PDF documentation** — Generated PDF manual per design
2. **Example gallery** — 10 reference designs
3. **CLI improvement** — `zaptrace create`, `zaptrace board`, `zaptrace export`
4. **Web UI** — Basic schematic preview, DRC viewer (future)

---

## 8. Cross-Cutting Concerns

### 8.1 Error Handling

Every design step has well-defined error states:

```python
class DesignResult(BaseModel):
    success: bool
    design: Design | None
    errors: list[DesignError]
    warnings: list[DesignWarning]
```

Design steps are composable — a failed ERC blocks routing, a failed DRC blocks Gerber export, unless explicitly overridden (`force=True`).

### 8.2 Determinism

- Same input YAML → same output Gerber (seed-based placement)
- Random seed propagates through all algorithms
- Version pinning in EE Knowledge Base (semver)

### 8.3 Performance

- **Rust core**: Placement, MST routing (existing)
- **Freerouting**: Heavy routing (separate process, async)
- **ngspice**: Simulation (separate process, async)
- **Gerber**: Python I/O-bound, fast enough
- **100-component design**: <60s full pipeline

### 8.4 Extensibility

- Plugin system for custom DRC rules
- Plugin system for custom exporters (Altium, Eagle, Fusion 360)
- Custom footprint generators (parametric)
- Custom routing rules per design

---

## 9. Comparison Matrix

| Feature | ZapTrace (target) | KiCad MCP Server | Circuit-Synth | Flux.ai | Spicebridge |
|---------|-------------------|-----------------|---------------|---------|-------------|
| Self-contained EDA | ✅ Yes | ❌ Needs KiCad | ❌ Needs KiCad | ✅ Cloud | ❌ Needs KiCad |
| AI-native | ✅ MCP+API+CLI | ✅ MCP | ✅ Python | ❌ API-only | ✅ MCP |
| Gerber output | ✅ Native | ✅ Via KiCad | ✅ Via KiCad | ✅ Native | ❌ No |
| DRC | ✅ 40+ rules | ✅ Via KiCad | ❌ | ✅ | ❌ |
| Autorouter | ✅ Freerouting | ✅ Via KiCad | ❌ | ✅ | ❌ |
| SPICE sim | ✅ ngspice | ❌ | ❌ | ❌ | ✅ ngspice |
| BOM/assembly | ✅ JLCPCB API | ❌ | ✅ LCSC | ✅ | ❌ |
| Library (YAML) | ✅ 70+ components | ✅ KiCad lib | ❌ | ✅ 500k+ | ❌ |
| Footprint gen | ✅ IPC-7351B | ✅ KiCad | ❌ | ✅ | ❌ |
| RR/45° routing | ✅ Enforced | ❌ User sets | ❌ | ✅ | ❌ |
| Open source | ✅ MIT | ✅ MIT | ✅ MIT | ❌ | ✅ MIT |
| Offline | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes |
| PCB from scratch | ✅ Yes | ❌ Opens KiCad | ❌ Opens KiCad | ✅ Yes | ❌ No |

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Freerouting integration unstable | Can't route complex boards | Fallback to MST routing + push-aside; own simple router for <50 nets |
| Gerber output not fab-compatible | Boards don't pass DFM | Test against JLCPCB/PCBWay/OSH Park acceptance criteria; test suite with real fab outputs |
| Simulation accuracy limited | False confidence | Mark simulation as "approximate" in output; compare against known reference designs |
| Performance with 500+ component designs | Slow pipeline | Async stages, caching, Rust for critical paths, incremental design updates |
| IPC footprint generator edge cases | Wrong land patterns | Extensive test fixtures; allow manual override per component |

---

## 11. Success Criteria

By end of Phase 6:

1. ✅ AI agent can describe a design in natural language → get back production Gerber files
2. ✅ No KiCad dependency — output passes JLCPCB/PCBWay DFM check
3. ✅ No 90° traces in any output — all routing at 45° or arcs
4. ✅ DRC catches all standard manufacturing errors (proven by test suite)
5. ✅ BOM with manufacturer MPN + LCSC part number + pricing
6. ✅ SPICE simulation verifies power supply startup (transient analysis)
7. ✅ All 45+ MCP tools working end-to-end
8. ✅ Full test suite with >300 tests

---

## 12. Decisions (2026-06-08)

### 12.1 Freerouting (JVM)

**Decision:** Freerouting.
**Why:** Pro-level routing. Used by production tools for 20+ years. Supports differential pairs, length matching, multi-layer, blind/buried vias, push-and-shove. Our basic MST router remains as fallback when JVM is unavailable. Freerouting will be distributed as an optional dependency (`pip install zaptrace[pro]`).

### 12.2 Gerber Fab Test

**Decision:** Yes — a reference design will be fabricated at JLCPCB to validate Gerber output.
**Plan:** After Phase 1 (basic Gerber), pick a simple 2-layer design (e.g., ESP32-S3 breakout), generate Gerber, upload to JLCPCB for DFM check, fix issues, order test batch.

### 12.3 Simulation

**Decision:** Optional — on-demand only. Auto-run only for power supply subcircuits (regulator startup, stability). Full simulation (transient, AC, DC) is triggered explicitly by the user/agent. This keeps the pipeline fast for routine designs while enabling deep verification when needed.

### 12.4 Phase Order

**Decision:** Keep Phase 1→6 as specified. Phase 1 (Foundation) is the critical path — everything depends on the extended design model, DRC, and Gerber export. Phases 2-3 can partially overlap (schematic symbols while building Freerouting integration).
