# Generated Board Release Gate

The generated-board release gate promotes the M7 generated-board pipeline from acceptance coverage into a strict release-quality report.

The gate runs the ESP32 USB sensor pipeline end to end:

```text
BoardGenerationIntent
-> Design IR compilation
-> KiCad schematic generation
-> KiCad PCB generation
-> generated-project evidence bundle
-> manufacturing export manifest
-> review handoff
```

## Command

```bash
python scripts/ci_generated_board_release_gate.py \
  --output docs/reports/generated-board-release-gate.json \
  --markdown docs/reports/generated-board-release-gate.md \
  --strict
```

## Current committed result

- Gate: `generated-board-release-gate-v1`
- Family: `esp32_usb_sensor`
- Design: `esp32_usb_sensor_generated_v1`
- Required artifacts: 9
- Missing required artifacts: 0
- Passed: `true`

## What it proves

- The supported generated-board pipeline can produce a reviewable KiCad project.
- The generated project includes schematic and PCB artifacts.
- The aggregate evidence bundle records stable SHA-256 hashes.
- Manufacturing export and review handoff placeholders are present.
- Non-claims remain visible.

## CI integration

The `Quality` workflow runs this gate as `Generated board release gate`. The final release-gate summary depends on that job and treats it as a blocking gate.

## Artifact regression checks

The committed JSON report is treated as a regression snapshot. Tests compare a freshly generated report against `docs/reports/generated-board-release-gate.json`, including the required artifact kinds, relative paths, SHA-256 hashes, report structure, blocking reasons, and non-claims. Any intentional generated-artifact drift must update the committed report and tests together.

## Non-claims

The gate is release evidence for a reviewable generated board project. It is not fabrication approval, not electrical correctness, not DRC/ERC approval, not manufacturer approval, not certification, and not production readiness.
