# Benchmark Fixture Coverage

ZapTrace 0.3.0 introduced a 12-family benchmark manifest. The next benchmark-depth step is tracking which families have committed fixture artifacts, not merely target definitions.

`zaptrace.benchmark.fixtures` evaluates each family from `zaptrace/benchmark/manifests/board-families-v1.json` against the required artifact patterns declared in the manifest:

- `requirements.json`
- `proof-pack/manifest.json`
- `golden/*.kicad_*`
- `exports/*`

The coverage report is intentionally a repository completeness gate. It does not claim that a fixture is electrically correct, manufacturable, certified, or production-ready.

## Current committed coverage

The first complete committed family fixture is:

```text
benchmarks/esp32_usb_sensor/
```

It contains:

```text
requirements.json
proof-pack/manifest.json
golden/esp32_usb_sensor.kicad_pro
golden/esp32_usb_sensor.kicad_sch
golden/esp32_usb_sensor.kicad_pcb
golden/fixture.json
exports/manifest.json
```

The current coverage report intentionally shows the remaining 11 families as incomplete so future work can be measured one family at a time.

## Generate the report

```bash
python scripts/ci_benchmark_fixture_coverage.py \
  --output docs/reports/benchmark-fixture-coverage.json \
  --markdown docs/reports/benchmark-fixture-coverage.md \
  --strict \
  --min-complete-families 1
```

Raising `--min-complete-families` is the intended ratchet as more families gain real fixtures.

## Non-claims

A complete fixture means the required files exist and are machine-checkable. It does not mean:

- the board is fabrication-ready;
- the board is manufacturer-approved;
- the circuit is electrically correct;
- the proof pack is sufficient for no-human-review sign-off;
- the generated artifacts are certified or production-ready.
