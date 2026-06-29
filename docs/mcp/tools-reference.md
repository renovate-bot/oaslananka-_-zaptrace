# MCP Tools Reference

> **Auto-generated from `TOOL_REGISTRY`**
> Run `python scripts/generate_mcp_docs.py` to regenerate.
> Total tools: 80

---


## Board

### `board_update`

Update board configuration parameters

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `width_mm` | `number` | Board width in mm |
| `height_mm` | `number` | Board height in mm |
| `layers` | `integer` | Number of copper layers |

### `board_plan`

Plan a justified board block graph (power + interface support) from an intent

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |

### `board_classify_nets`

Classify all nets in a design using EE knowledge

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `board_summarize_nets`

Get a summary of all nets and their classifications

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `board_export`

Export the board definition for a design as a JSON description

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Component Operations

### `patch_suggest`

Suggest auto-patches for fixable ERC violations

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `component_add`

Add a new component to a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `component_id` | `string` | Component ID |
| `ref` | `string` | Reference designator (e.g. R1, U1) |
| `type_name` | `string` | Component type |
| `value` | `string` | Component value |
| `footprint` | `string` | Footprint name |

### `component_remove`

Remove a component from a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `component_id` | `string` | Component ID to remove |

---

## Design I/O

### `design_parse_file`

Parse a design YAML file into a Design object

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `path` | `string` | Path to design YAML file |

### `design_parse_str`

Parse a YAML string into a Design object

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `yaml_content` | `string` | YAML content string |

### `design_inspect`

Inspect a parsed design and return its full details

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `design_list_nets`

List all nets in a design with their connections

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `design_diff`

Diff two designs and report changes

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_a_name` | `string` | First design name |
| `design_b_name` | `string` | Second design name |

### `design_route_smart`

Route all nets with net-class-aware trace widths

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `layer` | `string` | Layer name (default: F.Cu) |

### `design_classify_nets`

Classify all nets in a design by name and pin type

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `design_snapshot`

Capture a point-in-time snapshot of a design for later rollback

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name to snapshot |
| `label` | `string` | Optional label for the snapshot (auto-generated if omitted) |

### `design_rollback`

Restore a design from a named snapshot (reverts all mutations)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name to rollback |
| `label` | `string` | Snapshot label to restore from |

### `design_list_snapshots`

List available snapshots for a design (or all designs in session)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Optional design name filter |

### `design_commit`

Confirm design changes by clearing snapshots for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name to commit |
| `label` | `string` | Optional snapshot label to commit (omitting clears all) |

### `design_transaction_preview`

Preview a design mutation as an isolated transaction without committing it

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `operation` | `string` | Operation: board_update, component_add, component_remove |
| `params` | `object` | Operation parameters |
| `reason` | `string` | Why this transaction is proposed |

### `design_transaction_validate`

Validate a preview transaction without mutating primary state

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `transaction_id` | `string` | Transaction identifier |

### `design_transaction_commit`

Commit a validated transaction after explicit approval

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `transaction_id` | `string` | Transaction identifier |
| `approval_id` | `string` | External approval or release gate identifier |

### `design_transaction_rollback`

Reject or roll back a preview transaction without changing primary state

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `transaction_id` | `string` | Transaction identifier |

### `design_transaction_list`

List transactions for a session

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |

---

## Design Rule Checking (DRC)

### `drc_run`

Run Design Rule Check on a design, optionally against a manufacturer fab profile

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `fab_profile` | `string` | Optional fab profile name (e.g. 'jlcpcb-2layer') for profile-specific DRC |

### `drc_get_result`

Get the latest DRC result for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `drc_list_rules`

List all DRC rules with descriptions

**Parameters:**

*No parameters*

---

## Electrical Rule Checking (ERC)

### `erc_validate`

Run all ERC rules on a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `erc_get_result`

Get the latest ERC result summary for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `erc_list_rules`

List all registered ERC rules with descriptions

**Parameters:**

*No parameters*

---

## Export

### `export_bom_csv`

Generate Bill of Materials as CSV

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `export_bom_json`

Generate Bill of Materials as JSON

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `export_report`

Generate a Markdown design report

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_path` | `string` | Optional output path |

### `export_svg`

Render a schematic overview as SVG

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_path` | `string` | Optional output path |

### `export_kicad`

Export design to KiCad-compatible files

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_dir` | `string` | Output directory |
| `approval_id` | `string` | External approval or release gate identifier |

### `export_gerber`

Generate Gerber RS-274X files for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_dir` | `string` | Optional output directory for Gerber files |
| `approval_id` | `string` | External approval or release gate identifier |

### `export_excellon`

Generate Excellon drill files for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_dir` | `string` | Optional output directory for drill files |
| `approval_id` | `string` | External approval or release gate identifier |

### `export_manufacturing`

Generate a complete manufacturing package (Gerber + drill + BOM + PnP ZIP)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `output_dir` | `string` | Output directory for manufacturing files |
| `approval_id` | `string` | External approval or release gate identifier |

### `export_pick_and_place`

Generate a pick-and-place (centroid) CSV for assembly

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |
| `approval_id` | `string` | External approval or release gate identifier |

### `export_spice`

Export a design as a SPICE netlist string (foundation for simulation)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Library & Footprints

### `library_search`

Search the component library by keyword

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `string` | Search query |
| `max_results` | `integer` | Max results |

### `library_get`

Get full details for a library component

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `component_id` | `string` | Component ID |

### `library_list_categories`

List all component library categories

**Parameters:**

*No parameters*

### `footprint_search`

Search for footprints in the library by keyword

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `string` | Search query |
| `max_results` | `integer` | Max results (default 10) |

### `footprint_get`

Get footprint details for a library component

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `component_id` | `string` | Component ID |

### `footprint_generate`

Generate a parametric footprint for a given package name

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `package` | `string` | Package name (e.g. 0603, SOIC-8, QFN-32) |
| `layer` | `string` | Layer (top or bottom, default top) |

### `footprint_list_packages`

List all supported package names for footprint generation

**Parameters:**

*No parameters*

---

## Other

### `mechanical_review`

Review mounting holes vs board size and edges (mechanical / enclosure)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `security_review`

Review hardware-security exposure (debug access, secure element, etc.)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `testability_report`

Assess test-point coverage, debug/reset access, and a bring-up checklist

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `electrical_analysis`

Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

### `requirements_parse`

Extract structured, machine-readable requirements from a design intent

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |

### `requirements_review`

Approve a design's unspecified assumptions and gate on any still pending

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |
| `approvals` | `object` | Map of assumption field -> reviewer decision, e.g. {"rails_v": "3.3V"} |

### `power_tree_plan`

Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |

### `compliance_checklist`

Produce a product-class compliance pre-check checklist for a design intent

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |

### `audit_list_events`

List recent security/audit events for a session

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `limit` | `integer` | Maximum number of events to return |

### `calc_led_resistor`

Size an LED current-limiting resistor (E-series; current stays at/under target)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `supply_v` | `number` | Supply voltage driving the LED + resistor |
| `forward_v` | `number` | LED forward voltage (Vf) |
| `current_ma` | `number` | Target forward current in mA |
| `series` | `integer` | E-series to snap to (12 or 24) |

### `calc_voltage_divider`

Choose a divider top resistor for a target output voltage (E-series)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `input_v` | `number` | Divider input voltage |
| `output_v` | `number` | Target output voltage |
| `r_bottom` | `number` | Fixed bottom resistor in ohms |
| `series` | `integer` | E-series to snap to (12 or 24) |

### `calc_rc_filter`

Compute the -3 dB cutoff frequency of a first-order RC filter

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `r_ohms` | `number` | Resistance in ohms |
| `c_farads` | `number` | Capacitance in farads |

### `calc_i2c_pullup`

Compute I2C pull-up range and a recommended value (NXP UM10204)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `supply_v` | `number` | Bus supply voltage (Vdd) |
| `bus_capacitance_pf` | `number` | Total bus capacitance in pF |
| `bus_speed_hz` | `integer` | Bus speed: 100000, 400000, or 1000000 |
| `series` | `integer` | E-series to snap to (12 or 24) |

### `calc_e_series`

Snap a value to an E-series preferred value (mode: nearest|ceil|floor)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `number` | Value to snap |
| `series` | `integer` | E-series (12 or 24) |
| `mode` | `string` | nearest | ceil | floor |

### `calc_usb_c_cc`

Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `role` | `string` | Port role: sink/ufp or source/dfp |
| `advertised_current_a` | `number` | For a source, current to advertise at 5V (default USB power if omitted) |

### `calc_decoupling`

Plan decoupling/bypass caps for a rail (100 nF per power pin + bulk, derated rating)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `power_pins` | `integer` | Number of power pins to bypass |
| `rail_v` | `number` | Rail voltage feeding the pins |
| `bulk_uf` | `number` | Bulk capacitance in uF (default 10) |

### `calc_lipo_charge`

Size the MCP73831/2 PROG resistor for a Li-ion/Li-Po charge current

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `charge_current_ma` | `number` | Target charge current in mA (100-500) |
| `series` | `integer` | E-series to snap onto (12 or 24) |

### `calc_buck_lc`

Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `vin` | `number` | Input voltage |
| `vout` | `number` | Output voltage (< vin) |
| `iout` | `number` | Maximum load current (A) |
| `f_sw_hz` | `number` | Switching frequency (Hz) |
| `ripple_ratio` | `number` | Inductor ripple as fraction of Iout (default 0.3) |
| `output_ripple_v` | `number` | Allowed output ripple V (default 1% of Vout) |

---

## Pipeline

### `pipeline_run`

Run the full design pipeline from file or intent

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `source` | `string` | Design file path |
| `intent` | `string` | Synthesis intent |
| `output_dir` | `string` | Output directory |

### `pipeline_run_stage`

Run a single pipeline stage

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `stage` | `string` | Stage name |
| `source` | `string` | Design file path |
| `intent` | `string` | Synthesis intent |
| `design_name` | `string` | Design name |
| `output_dir` | `string` | Output directory |

### `pipeline_status`

Get pipeline processing status for a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Placement

### `place_components`

Place all components on the board

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Proof Pack

### `proof_run`

Run a Proof Pack from a proof.yaml file or directory to validate a design

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `string` | Path to proof.yaml or directory containing proof.yaml |

### `proof_run_design`

Run proof checks directly against a design in the current session (no proof.yaml needed)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Name of the design to validate |
| `checks` | `array` | Optional check definitions (name, type, severity, params). Default: structural checks |

### `proof_list_checks`

List all checks defined in a Proof Pack without running them

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `string` | Path to proof.yaml or directory containing proof.yaml |

---

## Routing

### `route_nets`

Route all nets using Manhattan MST routing

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Schematic

### `schematic_render`

Render a design as an SVG schematic

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `design_name` | `string` | Design name |

---

## Synthesis

### `synthesize_design`

Select and load the best-matching pre-built design template for an intent string (template selection by keyword match, not from-scratch circuit synthesis)

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `string` | Session identifier |
| `intent` | `string` | Design intent description |

### `list_synthesis_templates`

List available synthesis templates

**Parameters:**

*No parameters*

### `synthesize_power_tree`

Emit a real netlist (USB-C CC, regulators, I2C pull-ups) for an intent's power tree

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |
| `session_id` | `string` | Session identifier |

### `synthesize_and_check`

Synthesize an intent's power tree into a netlist and run ERC on it in one step

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |
| `session_id` | `string` | Session identifier |

### `synthesize_board`

Emit a real netlist for an intent's whole board via block composition and store it

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |
| `session_id` | `string` | Session identifier |

### `synthesize_board_and_check`

Synthesize an intent's whole board into a netlist and run ERC on it in one step

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `intent` | `string` | Design intent description |
| `session_id` | `string` | Session identifier |

---

## Error Handling

All tools return errors as structured JSON envelopes:

```json
{
  "error": true,
  "code": "TOOL_ERROR",
  "message": "Human-readable description",
  "details": {}
}
```

Common error codes:

- `DESIGN_NOT_FOUND` — Design name not found in session

- `INVALID_PARAMETER` — Parameter out of range or invalid

- `EXPORT_FAILED` — Export process failed
