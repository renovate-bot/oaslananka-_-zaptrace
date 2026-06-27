# Phase 1: Foundation — Implementation Plan

**Spec ref:** `docs/superpowers/specs/2026-06-08-zaptrace-ai-eda-engine-design.md`
**Duration:** ~3 weeks (target: 14 working days)
**Dependencies:** Current ZapTrace codebase (Design model, ERC, Rust placement/routing)

---

## Overview

Phase 1 builds the critical path from Design model → professional Gerber output. After this
phase, an AI agent can describe a circuit, and ZapTrace produces review-grade manufacturing artifacts for validation.

**End-to-end flow after Phase 1:**
```
design_parse → run_erc → place_components → route_board → run_drc → export_gerber
```

---

## Task Breakdown

### 1.1 Extend Design Model (2 days)

**Files to modify:**
- `zaptrace/core/models.py`

**Changes:**

```python
# New models to add:

class PadShape(str, Enum):
    RECT = "rect"
    CIRCLE = "circle"
    OVAL = "oval"
    CUSTOM = "custom"

class LayerSet(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    ALL = "all"
    INNER = "inner"

class Pad(BaseModel):
    id: str
    layer: LayerSet
    shape: PadShape
    position: tuple[float, float]
    size: tuple[float, float]
    drill: float | None = None
    plated: bool = True
    solder_paste: bool = True

class DrawCommand(BaseModel):
    type: str  # line, rect, arc, circle, text
    params: dict[str, Any]  # type-specific drawing parameters

class SymbolDef(BaseModel):
    pins: list[SymbolPin]  # SymbolPin already exists in models
    body: list[DrawCommand]
    origin: tuple[float, float] = (0.0, 0.0)

class FootprintDef(BaseModel):
    pads: list[Pad]
    outline: list[DrawCommand]
    courtyard: tuple[float, float] = (0.0, 0.0)
    height: float = 0.0
    thermal_pads: list[str] | None = None

class LayerSpec(BaseModel):
    name: str
    type: str  # signal, power, ground
    thickness: float  # mm
    material: str = "copper"

class MountingHole(BaseModel):
    position: tuple[float, float]
    diameter: float
    plated: bool = False

class BoardConstraints(BaseModel):
    min_trace: float = 0.15
    min_trace_power: float = 0.3
    min_clearance: float = 0.15
    min_clearance_high_voltage: float = 0.3
    min_hole: float = 0.15
    min_annular_ring: float = 0.13
    min_solder_mask_sliver: float = 0.1
    via_pad: float = 0.45
    via_hole: float = 0.2
    default_trace_signal: float = 0.2
    default_trace_power: float = 0.5

class BoardDefinition(BaseModel):
    width: float
    height: float
    layers: int = 2
    layer_stack: list[LayerSpec] = []
    outline: list[tuple[float, float]] = []
    cutouts: list[list[tuple[float, float]]] = []
    mounting_holes: list[MountingHole] = []
    constraints: BoardConstraints = BoardConstraints()
```

**Extend Component:**
```python
class Component(BaseModel):
    # ... existing fields ...
    symbol: SymbolDef | None = None
    footprint_def: FootprintDef | None = None
    voltage_rating: float | None = None
    current_rating: float | None = None
    frequency_rating: float | None = None
```

**Extend Design:**
```python
class Design(BaseModel):
    # ... existing fields ...
    board: BoardDefinition | None = None
    placement: dict[str, tuple[float, float]] | None = None
    routing: RouteResult | None = None  # new model
```

**New model:**
```python
class TraceSegment(BaseModel):
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    net_id: str
    via: bool = False

class RouteResult(BaseModel):
    traces: list[TraceSegment]
    vias: list[tuple[float, float, float, float]]  # x, y, pad_diam, hole_diam
    layers_used: list[str]
    drc_result: DRCResult | None = None
```

**Acceptance criteria:**
- ✅ All new models serialize/deserialize correctly
- ✅ Existing tests still pass (backward compatible)
- ✅ `Design(board=BoardDefinition(width=50, height=40))` works
- ✅ Migration: no required changes to existing code paths

---

### 1.2 EE Knowledge Base (2 days)

**New package:** `zaptrace/ee/`

**Files to create:**
- `zaptrace/ee/__init__.py` — Package init, exports
- `zaptrace/ee/knowledge.py` — KnowledgeBase class, preset loader
- `zaptrace/ee/routing/defaults.py` — Default trace widths, clearance tables
- `zaptrace/ee/routing/__init__.py`
- `zaptrace/ee/constraints/net_classes.py` — NetClass enum, rules per class
- `zaptrace/ee/constraints/__init__.py`
- `zaptrace/ee/presets/2layer_standard.yaml`
- `zaptrace/ee/presets/4layer_standard.yaml`

**`zaptrace/ee/__init__.py`:**
```python
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.constraints.net_classes import NetClass, NetClassRule

__all__ = ["KnowledgeBase", "NetClass", "NetClassRule"]
```

**`zaptrace/ee/knowledge.py`:**
```python
from pathlib import Path
import yaml
from zaptrace.ee.constraints.net_classes import NetClass, NetClassRule

class KnowledgeBase:
    """Central EE knowledge repository."""
    
    def __init__(self):
        self.net_class_rules: dict[NetClass, NetClassRule] = {}
        self.clearance_matrix: dict[tuple[str, str], float] = {}
        self.board_presets: dict[str, dict] = {}
        self._load_defaults()
        self._load_presets()
    
    def _load_defaults(self):
        # Hard-coded defaults for net classes
        ...
    
    def _load_presets(self):
        presets_dir = Path(__file__).parent / "presets"
        for f in presets_dir.glob("*.yaml"):
            with open(f) as fh:
                data = yaml.safe_load(fh)
            self.board_presets[data["name"]] = data
    
    def get_rule(self, net_class: NetClass) -> NetClassRule:
        return self.net_class_rules[net_class]
    
    def get_clearance(self, class_a: str, class_b: str) -> float:
        return self.clearance_matrix.get((class_a, class_b), 0.15)
    
    def get_preset(self, name: str) -> dict:
        return self.board_presets.get(name, self.board_presets["2layer_standard"])
```

**`zaptrace/ee/constraints/net_classes.py`:**
```python
from enum import Enum
from dataclasses import dataclass

class NetClass(str, Enum):
    SIGNAL_LOW = "signal_low"
    SIGNAL_HIGH = "signal_high"
    SIGNAL_ANALOG = "signal_analog"
    POWER_LOW = "power_low"
    POWER_MED = "power_med"
    POWER_HIGH = "power_high"
    GROUND = "ground"
    DIFFERENTIAL = "differential"
    RF = "rf"

@dataclass
class NetClassRule:
    trace_width: float
    clearance: float
    max_vias: int
    priority: int  # lower = higher priority for routing
    description: str

CLASS_RULES: dict[NetClass, NetClassRule] = {
    NetClass.SIGNAL_LOW: NetClassRule(0.20, 0.15, 2, 5, "GPIO, I2C, UART, SPI <10MHz"),
    NetClass.SIGNAL_HIGH: NetClassRule(0.25, 0.20, 2, 4, ">10MHz digital signals"),
    NetClass.SIGNAL_ANALOG: NetClassRule(0.30, 0.25, 1, 3, "ADC, sensor, op-amp"),
    NetClass.POWER_LOW: NetClassRule(0.30, 0.20, 4, 2, "<100mA power rails"),
    NetClass.POWER_MED: NetClassRule(0.50, 0.20, 4, 2, "100mA-500mA"),
    NetClass.POWER_HIGH: NetClassRule(1.00, 0.30, 8, 1, ">500mA — calc per IPC-2221"),
    NetClass.GROUND: NetClassRule(0.50, 0.15, 99, 0, "Ground — flood preferred"),
    NetClass.DIFFERENTIAL: NetClassRule(0.20, 0.15, 0, 3, "Differential pair — length matched"),
    NetClass.RF: NetClassRule(0.30, 0.30, 0, 3, "50Ω impedance — no vias in path"),
}
```

**`zaptrace/ee/presets/2layer_standard.yaml`:**
```yaml
name: 2layer_standard
description: Standard 2-layer PCB for simple IoT and breakout boards
layers: 2
layer_stack:
  - name: F.Cu
    type: signal
    thickness: 0.035
    material: copper
  - name: B.Cu
    type: signal
    thickness: 0.035
    material: copper
core_thickness: 1.6
constraints:
  min_trace: 0.15
  min_clearance: 0.15
  min_hole: 0.15
  min_annular_ring: 0.13
  via_pad: 0.45
  via_hole: 0.2
```

**Acceptance criteria:**
- ✅ `KnowledgeBase()` loads without errors
- ✅ `kb.get_rule(NetClass.SIGNAL_LOW).trace_width == 0.20`
- ✅ `kb.get_preset("2layer_standard")` returns valid dict
- ✅ All presets parse as valid YAML

---

### 1.3 Netlist Classifier (1 day)

**New file:** `zaptrace/algo/net_classifier.py`

**Logic:**
1. Map every `Net` in `Design` → `NetClass`
2. Heuristics-based: net name patterns, connected pin types, component types
3. Output: `dict[str, NetClass]` (net_id → class)

```python
from zaptrace.core.models import Design, Component, Net, Pin

# Net name patterns
_POWER_PATTERNS = re.compile(r"^(VCC|VDD|VEE|VSS|V[0-9]+|3V3|5V|1V8|2V5|3V0|12V|AVCC|AVDD)", re.IGNORECASE)
_GROUND_PATTERNS = re.compile(r"^(GND|GNDA|GNDD|VSS|AGND|DGND|PGND)", re.IGNORECASE)
_DIFFERENTIAL_PATTERNS = re.compile(r"(DP|DM|DP_P|DM_N|[+-]pair|P|N)$", re.IGNORECASE)

def classify_net(net: Net, design: Design) -> NetClass:
    ...

def classify_design(design: Design) -> dict[str, NetClass]:
    ...
```

**Pin type detection from component library:**
Each component YAML now includes optional `pin_type` per pin:
```yaml
pins:
  - id: "VDD"
    name: "VDD"
    type: power    # power, ground, input, output, bidirectional, analog, open_drain
```

**Acceptance criteria:**
- ✅ VCC/3V3/5V pins → `POWER_*`
- ✅ GND/VSS → `GROUND`
- ✅ USB_DP/DM → `DIFFERENTIAL`
- ✅ ADC_IN → `SIGNAL_ANALOG`
- ✅ I2C_SCL/SDA → `SIGNAL_LOW` (with open-drain metadata)
- ✅ SPI_MOSI/MISO/SCK/CS → `SIGNAL_LOW` (or HIGH if >10MHz)
- ✅ Unknown nets → `SIGNAL_LOW`

---

### 1.4 DRC Engine (4 days)

**New package:** `zaptrace/drc/`

**Files:**
- `zaptrace/drc/__init__.py`
- `zaptrace/drc/engine.py` — DRC orchestrator, `DRCRunner` class
- `zaptrace/drc/models.py` — `DRCResult`, `DRCViolation`, `DRCSeverity`, `DRCRule`
- `zaptrace/drc/rules/__init__.py`
- `zaptrace/drc/rules/electrical.py` — DRC-001 to DRC-003, DRC-010 to DRC-014
- `zaptrace/drc/rules/manufacturing.py` — DRC-004 to DRC-009, DRC-015 to DRC-017
- `zaptrace/drc/rules/signal_integrity.py` — DRC-018 to DRC-021
- `zaptrace/drc/rules/thermal.py` — DRC-022 to DRC-024
- `zaptrace/drc/rules/dfm.py` — DRC-025 to DRC-030
- `tests/test_drc.py` — Full test suite

**`zaptrace/drc/models.py`:**
```python
class DRCSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

class DRCRule(BaseModel):
    id: str  # DRC-001
    name: str
    description: str
    severity: DRCSeverity
    category: str  # electrical, manufacturing, signal_integrity, thermal, dfm
    enabled: bool = True
    threshold: dict[str, Any]  # Rule-specific parameters

class DRCViolation(BaseModel):
    rule_id: str
    severity: DRCSeverity
    message: str
    location: str | None  # "R1:pin2", "net:VCC", "x=10,y=20"
    net_id: str | None
    component_id: str | None

class DRCResult(BaseModel):
    design_name: str
    total_violations: int
    errors: int
    warnings: int
    info: int
    violations: list[DRCViolation]
    passed: bool  # True if zero errors
```

**`zaptrace/drc/engine.py`:**
```python
class DRCRunner:
    def __init__(self, design: Design, knowledge_base: KnowledgeBase | None = None):
        self.design = design
        self.kb = knowledge_base or KnowledgeBase()
        self.rules: list[DRCRule] = []
        self._register_rules()
    
    def _register_rules(self):
        from zaptrace.drc.rules.electrical import register as reg_electrical
        from zaptrace.drc.rules.manufacturing import register as reg_manufacturing
        from zaptrace.drc.rules.signal_integrity import register as reg_si
        reg_electrical(self)
        reg_manufacturing(self)
        reg_si(self)
    
    def add_rule(self, rule: DRCRule, checker: Callable):
        self.rules.append((rule, checker))
    
    def run(self) -> DRCResult:
        violations = []
        for rule, checker in self.rules:
            if not rule.enabled:
                continue
            try:
                result = checker(self.design)
                violations.extend(result)
            except Exception as e:
                violations.append(DRCViolation(
                    rule_id=rule.id,
                    severity=DRCSeverity.ERROR,
                    message=f"DRC rule {rule.id} crashed: {e}",
                ))
        errors = sum(1 for v in violations if v.severity == DRCSeverity.ERROR)
        warnings = sum(1 for v in violations if v.severity == DRCSeverity.WARNING)
        info = sum(1 for v in violations if v.severity == DRCSeverity.INFO)
        return DRCResult(
            design_name=self.design.meta.name,
            total_violations=len(violations),
            errors=errors, warnings=warnings, info=info,
            violations=violations,
            passed=errors == 0,
        )
    
    def run_single(self, rule_id: str) -> list[DRCViolation]:
        """Run a single DRC rule by ID."""
        ...
```

**Minimum rules to implement in Phase 1:**
- DRC-001: Trace-to-trace clearance
- DRC-002: Trace-to-pad clearance
- DRC-003: Pad-to-pad clearance
- DRC-004: Min trace width
- DRC-006: Min annular ring
- DRC-010: Unconnected net
- DRC-015: Component overlap
- DRC-016: Component off-board
- DRC-021: Right-angle trace
- DRC-025: Missing solder paste on SMD

**Acceptance criteria:**
- ✅ `DRCRunner(design).run()` returns `DRCResult` with violations
- ✅ `drc.passed == True` for a valid design
- ✅ `drc.passed == False` for a design with clearance violation
- ✅ DRC-010 catches unconnected nets
- ✅ DRC-021 catches right-angle traces
- ✅ 10+ tests for the DRC engine

---

### 1.5 Gerber Exporter (4 days)

**New file:** `zaptrace/export/gerber.py`

RS-274X Gerber format implementation. Core primitives:

```python
class GerberJob:
    """Builds a Gerber file layer by layer."""
    
    def __init__(self, layer_name: str, file_path: Path):
        self.path = file_path
        self.lines: list[str] = []
        self._init()
    
    def _init(self):
        # Gerber header: format, units, aperture definitions
        self.lines.append("%FSLAX36Y36*%")   # 6.6 format, trailing zero suppress
        self.lines.append("%MOMM*%")          # Units: mm
        self.lines.append("G04 ZapTrace Gerber Export*")  # Comment
    
    def add_aperture(self, code: int, shape: str, size: float):
        """Define aperture (e.g., circular, 0.3mm)."""
        self.lines.append(f"%ADD{code}{shape},{size}X*%")
    
    def move_to(self, x: float, y: float):
        ix, iy = self._to_integer(x), self._to_integer(y)
        self.lines.append(f"X{ix}Y{iy}D02*")  # D02 = move (with aperture off)
    
    def line_to(self, x: float, y: float, aperture: int):
        ix, iy = self._to_integer(x), self._to_integer(y)
        self.lines.append(f"D{aperture}*")
        self.lines.append(f"X{ix}Y{iy}D01*")  # D01 = expose
    
    def flash(self, x: float, y: float, aperture: int):
        ix, iy = self._to_integer(x), self._to_integer(y)
        self.lines.append(f"D{aperture}*")
        self.lines.append(f"X{ix}Y{iy}D03*")  # D03 = flash
    
    def close(self):
        self.lines.append("M02*")  # End of file
        self.path.write_text("\n".join(self.lines), encoding="ascii")
    
    def _to_integer(self, val: float) -> str:
        # Convert mm to 6.6 format integer (mm * 1_000_000)
        return f"{int(round(val * 1_000_000)):010d}"
```

**Export function:**
```python
def export_gerber(design: Design, output_dir: Path, 
                  board: BoardDefinition | None = None,
                  traces: RouteResult | None = None) -> dict[str, Path]:
    """Generate all Gerber layers for a design.
    
    Returns dict mapping layer name to file path.
    """
    b = board or design.board
    if b is None:
        raise ValueError("Board definition required for Gerber export")
    
    files = {}
    layers = b.layer_stack or [
        LayerSpec(name="F.Cu", type="signal", thickness=0.035),
        LayerSpec(name="B.Cu", type="signal", thickness=0.035),
    ]
    
    for layer in layers:
        job = GerberJob(layer.name, output_dir / _gerber_filename(layer.name))
        
        # Board outline
        if b.outline:
            _draw_outline(job, b.outline, b.constraints)
        
        # Pads on this layer
        for comp in design.components.values():
            if comp.footprint_def:
                for pad in comp.footprint_def.pads:
                    if pad.layer in (LayerSet.ALL, _layer_to_set(layer.name)):
                        pos = design.placement.get(comp.id, (0, 0))
                        _draw_pad(job, pad, pos, design, layer)
        
        # Traces on this layer
        if traces:
            for trace in traces.traces:
                if trace.layer == layer.name:
                    _draw_trace(job, trace, b.constraints)
        
        # Vias
        if traces:
            for via in traces.vias:
                _draw_via(job, via, layer.name, b.constraints)
        
        job.close()
        files[layer.name] = job.path
    
    # Always generate drill file
    drill_path = output_dir / "drill.txt"
    _export_excellon(design, board, traces, drill_path)
    files["drill"] = drill_path
    
    return files


def _gerber_filename(layer_name: str) -> str:
    """Map layer name to standard Gerber extension."""
    MAPPING = {
        "F.Cu": "F_Cu.gtl",
        "B.Cu": "B_Cu.gbl",
        "F.Mask": "F_Mask.gts",
        "B.Mask": "B_Mask.gbs",
        "F.Silkscreen": "F_Silkscreen.gto",
        "B.Silkscreen": "B_Silkscreen.gbo",
        "F.Paste": "F_Paste.gtp",
        "B.Paste": "B_Paste.gbp",
        "Edge.Cuts": "Edge_Cuts.gm1",
    }
    return MAPPING.get(layer_name, f"{layer_name}.gbr")
```

**Also implement Excellon drill export in the same PR:**
```python
def export_excellon(design: Design, output_dir: Path) -> Path:
    """Excellon format drill file."""
```

**File:** `zaptrace/export/excellon.py`

**Acceptance criteria:**
- ✅ Gerber file starts with `%FSLAX36Y36*%` and ends with `M02*`
- ✅ Gerber file parses with `gerber-parser` library (or at least `gerbv -p`)
- ✅ Board outline drawn as closed polygon
- ✅ SMD pads rendered as flashed apertures
- ✅ Traces rendered as drawn lines with correct aperture
- ✅ Drill file has correct Excellon header (`M48`, `M95`, etc.)
- ✅ No Gerber syntax errors (validated by regex patterns)
- ✅ Test with a real design: ESP32-S3 minimal (or similar)

---

### 1.6 Board Route Result — Extend Router (1 day)

**Files to modify:**
- `zaptrace/algo/router.py` — Extend `route_nets` to accept board constraints and return `RouteResult`

**Changes:**
```python
def route_nets(design: Design, positions: dict[str, tuple[float, float]],
               board: BoardDefinition | None = None,
               rules: dict[str, NetClassRule] | None = None) -> RouteResult:
    """Route all nets with EE rules awareness."""
    # 1. Get net classes
    net_classes = classify_design(design)
    
    # 2. For each net, determine trace width from class rules
    # 3. Route with MST + avoid obstacles
    # 4. Return RouteResult with traces, vias, layers_used
    
    traces = []
    vias = []
    
    for net_id, net in design.nets.items():
        nclass = net_classes.get(net_id, NetClass.SIGNAL_LOW)
        rule = CLASS_RULES.get(nclass, CLASS_RULES[NetClass.SIGNAL_LOW])
        
        # Get positions of connected components
        points = []
        for node in net.nodes:
            pos = positions.get(node.component_ref, (0, 0))
            points.append(pos)
        
        # MST routing with trace width = rule.trace_width
        net_traces = _route_mst(points, rule.trace_width, obstacles=traces)
        traces.extend(net_traces)
    
    layers_used = ["F.Cu", "B.Cu"] if any(t.via for t in traces) else ["F.Cu"]
    
    return RouteResult(traces=traces, vias=vias, layers_used=layers_used)
```

**Acceptance criteria:**
- ✅ `route_nets` accepts board constraints parameter (backward compatible)
- ✅ Returns `RouteResult` model (not raw list)
- ✅ Trace widths vary by net class
- ✅ Existing routing tests pass

---

### 1.7 MCP Tool Updates (1 day)

**Files to modify:**
- `zaptrace/mcp/design_tools.py` — Add board/symbol/footprint tools
- `zaptrace/mcp/tool_registry.py` — Register new tools
- `zaptrace/mcp/export_tools.py` — Add Gerber/drill tools
- `zaptrace/mcp/drc_tools.py` — **New file** for DRC tools
- `zaptrace/mcp/library_tools.py` — Add footprint search tools

**New tool registrations:**

```python
# In tool_registry.py, extend TOOLS list:

# Board tools
ToolDef(name="design_set_board", ...),
ToolDef(name="design_get_board", ...),

# DRC tools
ToolDef(name="run_drc", ...),
ToolDef(name="run_drc_rule", ...),
ToolDef(name="drc_get_rules", ...),
ToolDef(name="drc_set_rule", ...),

# Export tools
ToolDef(name="export_gerber", ...),
ToolDef(name="export_excellon", ...),

# Library tools
ToolDef(name="library_search_footprint", ...),
ToolDef(name="library_get_footprint", ...),
```

**Acceptance criteria:**
- ✅ All 12 new tools registered and callable via MCP
- ✅ Tool count increases from 27 to 39
- ✅ Existing MCP tests pass
- ✅ Tool input/output models validate correctly

---

### 1.8 Integration Test: End-to-End (1 day)

**New test file:** `tests/test_phase1_e2e.py`

Test the full Phase 1 pipeline:

```python
def test_full_pipeline(tmp_path):
    """Design → ERC → Place → Route → DRC → Gerber."""
    
    # 1. Parse design from YAML
    design = parse_str(SAMPLE_DESIGN_YAML)
    assert design is not None
    
    # 2. Set board
    board = BoardDefinition(width=50, height=40, layers=2)
    design.board = board
    
    # 3. Run ERC
    erc = ERCRunner(design).run()
    assert erc.passed
    
    # 4. Place components
    positions = place_components(design)
    design.placement = positions
    assert len(positions) == len(design.components)
    
    # 5. Route
    routing = route_nets(design, positions, board)
    design.routing = routing
    assert len(routing.traces) > 0
    
    # 6. DRC
    drc = DRCRunner(design).run()
    assert drc.passed, f"DRC failed: {drc.violations}"
    
    # 7. Export Gerber
    files = export_gerber(design, tmp_path)
    assert len(files) >= 3  # At least F.Cu, B.Cu, drill
    for path in files.values():
        assert path.exists()
        assert path.stat().st_size > 0
    
    # 8. Verify Gerber headers
    for name, path in files.items():
        content = path.read_text()
        if name != "drill":
            assert content.startswith("%FSLAX36Y36*%")
```

**Acceptance criteria:**
- ✅ Full pipeline test passes from scratch
- ✅ All intermediate artifacts (positions, routes, DRC) valid
- ✅ Gerber files pass basic format validation
- ✅ Pipeline runs in <30s for a 10-component design

---

### 1.9 CI/CD Updates (0.5 day)

**Files to modify:**
- `.github/workflows/ci.yml` — Add Gerber validation step

```yaml
- name: Validate Gerber output
  run: |
    python -m pytest tests/test_phase1_e2e.py -v
    python -c "
    from zaptrace.export.gerber import export_gerber
    # Validate generated Gerber for syntax
    import re
    for gbr in output_dir.glob('*.gt*'):
        content = gbr.read_text()
        assert re.match(r'^%FSLAX36Y36', content)
        assert content.endswith('M02*\n')
    "
```

**Acceptance criteria:**
- ✅ CI passes with all new tests
- ✅ Gerber validation step runs automatically

---

## Dependency Graph

```
1.1 Design Model Extensions
  ├── 1.2 EE Knowledge Base (needs model types but not full models)
  ├── 1.3 Netlist Classifier (needs extended Component model with pin_type)
  │     └── 1.6 Router extension (needs classifier output)
  ├── 1.4 DRC Engine (needs board/footprint models)
  ├── 1.5 Gerber Exporter (needs board, footprint, route models)
  │     └── 1.6 Router extension (needs RouteResult)
  └── 1.7 MCP Tools (needs all above)
        └── 1.8 E2E Test (needs everything)
              └── 1.9 CI Updates
```

**Recommended implementation order:**
1. 1.1 → 1.2 (parallel: 1.1 + 1.2)
2. 1.3 → 1.4 (parallel: 1.3 + 1.4 start after 1.1 done)
3. 1.5 → 1.6 (parallel: 1.5 + 1.6 after 1.1, 1.3, 1.4 complete)
4. 1.7 → 1.8 → 1.9

---

## Verification Gates

Every task in this plan must pass before declaring Phase 1 complete:

| Gate | Check |
|------|-------|
| ✅ | All 155 existing tests still pass |
| ✅ | All new DRC tests pass (10+) |
| ✅ | All new export tests pass |
| ✅ | E2E pipeline test passes end-to-end |
| ✅ | Gerber output validates (header, structure) |
| ✅ | MCP tools (39 total) register and respond |
| ✅ | No `TODO`/`FIXME`/`pass` in new code |
| ✅ | No deprecation warnings from touched code |
| ✅ | `ruff check .` passes on new code |
| ✅ | `mypy zaptrace/` passes on new code |

---

## Files Summary

### New files (20):
```
zaptrace/ee/__init__.py
zaptrace/ee/knowledge.py
zaptrace/ee/routing/__init__.py
zaptrace/ee/routing/defaults.py
zaptrace/ee/constraints/__init__.py
zaptrace/ee/constraints/net_classes.py
zaptrace/ee/presets/2layer_standard.yaml
zaptrace/ee/presets/4layer_standard.yaml
zaptrace/drc/__init__.py
zaptrace/drc/engine.py
zaptrace/drc/models.py
zaptrace/drc/rules/__init__.py
zaptrace/drc/rules/electrical.py
zaptrace/drc/rules/manufacturing.py
zaptrace/drc/rules/signal_integrity.py
zaptrace/export/gerber.py
zaptrace/export/excellon.py
zaptrace/algo/net_classifier.py
zaptrace/mcp/drc_tools.py
tests/test_phase1_e2e.py
```

### Modified files (6):
```
zaptrace/core/models.py       # Extend models
zaptrace/algo/router.py       # Return RouteResult
zaptrace/mcp/tool_registry.py # Register 12 new tools
zaptrace/mcp/design_tools.py  # Board tools
zaptrace/mcp/export_tools.py  # Gerber/drill tools
zaptrace/mcp/library_tools.py # Footprint tools
.github/workflows/ci.yml      # Gerber validation
```

---

## Effort Summary

| Task | Days | Dependencies |
|------|------|-------------|
| 1.1 Extend Design Model | 2 | None |
| 1.2 EE Knowledge Base | 2 | None (uses simple types) |
| 1.3 Netlist Classifier | 1 | 1.1 |
| 1.4 DRC Engine | 4 | 1.1 |
| 1.5 Gerber Exporter | 4 | 1.1, 1.4 |
| 1.6 Router Extension | 1 | 1.1, 1.3 |
| 1.7 MCP Updates | 1 | 1.1-1.6 |
| 1.8 E2E Tests | 1 | 1.1-1.7 |
| 1.9 CI Updates | 0.5 | 1.8 |
| **Total** | **14 working days** | |

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Gerber format edge cases | Medium | Write extensive test fixtures; validate against reference outputs from KiCad |
| DRC false positives | Medium | Conservative thresholds initially; relax based on real fab feedback |
| Freerouting integration delay | Low | Not in Phase 1; basic MST routing sufficient for simple boards |
| Export performance large designs | Low | Phase 1 targets <50 component designs; optimize later |
