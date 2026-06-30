# Governed Component Schema v1

ZapTrace's governed component schema v1 defines the minimum machine-readable contract for a component that can be reviewed, sourced, placed, checked, and traced in an autonomous electronics workflow.

The historical `data/library/**/*.yaml` files can still load through `LibraryLoader`. Schema v1 adds a validation/reporting layer on top of that loader; the stricter release gate is handled separately by the component metadata validator.

## Required identity fields

A component must identify the exact part:

```yaml
id: ap2112k-3.3
name: AP2112K-3.3
category: power
manufacturer: Diodes Incorporated
mpn: AP2112K-3.3TRG1
lifecycle: active
```

Missing identity fields are schema errors because sourcing and lifecycle decisions cannot be made safely without them.

## Required traceability fields

A reviewed component must connect the schematic, footprint, and datasheet evidence:

```yaml
datasheet: https://example.com/ap2112k.pdf
package: SOT-23-5
footprint: AP2112K-SOT23-5
pins:
  1: {type: input, description: VIN}
  2: {type: power, description: GND}
  5: {type: output, description: VOUT}
```

Missing `datasheet`, `package`, `footprint`, or `pins` is a schema error.

## Governance sections

Schema v1 also models professional review evidence:

```yaml
electrical_limits:
  max_voltage_v: 6.0
  current_rating_a: 0.6
  temperature_range_c: [-40, 85]
sourcing:
  authorized_distributors: [Digi-Key, Mouser]
  mpn: AP2112K-3.3TRG1
compliance:
  rohs: true
  reach: true
provenance:
  reviewed_by: library-ci
  reviewed_at: 2026-06-30
  datasheet_sha256: <sha256>
```

Missing governance sections are warnings in schema v1 so the existing library can be measured before the stricter gate is enabled.

## Derived metadata

The validator derives some fields when possible:

- `sourcing.mpn` and `sourcing.manufacturer` are derived from top-level `mpn` and `manufacturer`.
- `provenance.datasheet` is derived from top-level `datasheet`.
- `electrical_limits.voltage_supply` is derived from top-level `voltage_supply`.
- Selected legacy `properties` such as `rated_power_w`, `max_voltage_v`, `current_rating_a`, and `temperature_range` are copied into `electrical_limits`.

## Validation API

```python
from zaptrace.library.loader import LibraryLoader

loader = LibraryLoader()
report = loader.governance_report()
loader.write_governance_report("component-governance.json")
```

The JSON report includes:

```text
schema_version
component_count
valid_count
reviewed_ready_count
error_count
warning_count
mean_coverage_score
validations[]
```

`valid` means no schema errors. `reviewed_ready` means no errors and no warnings.

## Adding a reviewed component

1. Add the YAML file under `data/library/<category>/<id>.yaml`.
2. Include all identity fields: `id`, `name`, `category`, `manufacturer`, `mpn`, `lifecycle`.
3. Include all traceability fields: `datasheet`, `package`, `footprint`, and `pins`.
4. Add `electrical_limits`, `sourcing`, `compliance`, and `provenance`.
5. Run:

```bash
uv run pytest tests/test_library.py tests/test_library_governance.py -q
```

Schema v1 validation is evidence, not manufacturer approval. A human review remains required for new or changed component claims.
