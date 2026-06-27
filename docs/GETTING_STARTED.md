# Getting Started with ZapTrace

## Installation

### Prerequisites
- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install with uv

```bash
uv pip install zaptrace
```

The PyPI distribution is `zaptrace`; the Python import package and CLI commands remain `zaptrace`.

### Install from source

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
uv sync --all-extras
```

### Optional: Rust Extension

For faster core algorithms, build the Rust extension:

```bash
uv pip install maturin
uv run maturin develop --manifest-path zaptrace_core/Cargo.toml
```

## Verify Installation

```bash
zaptrace --version
zaptrace --help
```

If the MCP server is working:

```bash
zaptrace-mcp --help
```

## Your First Design

### 1. Create a design file

Create `my-board.yaml`:

```yaml
meta:
  name: my_board
  description: A simple LED blinker

board:
  width_mm: 50
  height_mm: 40
  layers: 2

components:
  u1:
    ref: U1
    type: mcu
    value: ESP32-C3
    footprint: QFN-32
    pins:
      VCC: power
      GND: ground
      IO2: output
  r1:
    ref: R1
    type: resistor
    value: 10k
    footprint: 0805
    pins:
      p1: passive
      p2: passive
  led1:
    ref: LED1
    type: led
    value: Red
    footprint: 0805
    pins:
      anode: passive
      cathode: passive

nets:
  VCC:
    nodes:
      - U1.VCC
      - R1.p1
  GND:
    nodes:
      - U1.GND
      - LED1.cathode
  LED_OUT:
    nodes:
      - U1.IO2
      - R1.p2
      - LED1.anode
```

### 2. Parse and inspect

```bash
zaptrace parse my-board.yaml
zaptrace inspect my_board
zaptrace nets my_board
```

### 3. Validate

```bash
zaptrace erc my_board
zaptrace erc-rules
```

### 4. Place and route

```bash
zaptrace place my_board
zaptrace route my_board
```

### 5. Generate outputs

```bash
# Schematic
zaptrace svg my_board --output schematic.svg

# Report
zaptrace report my_board --output report.md

# BOM
zaptrace bom my_board

# Manufacturing package
zaptrace export manufacturing my_board --output build/
```

### 6. Full pipeline

```bash
zaptrace pipeline --source my-board.yaml --output build/
```

## Next Steps

- Read the [Architecture Guide](ARCHITECTURE.md)
- Explore the [examples](../examples/)
- Set up the [MCP server](MCP.md) for AI agent integration
- Learn about [Proof Packs](PROOF_PACK.md)
- Review the [Roadmap](ROADMAP.md)
