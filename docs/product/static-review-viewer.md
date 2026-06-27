# Static Review Viewer

The static review viewer generates a local browser bundle for design and proof-pack inspection. It does not upload private designs to a cloud service and does not mutate design state.

Generate a viewer bundle:

```bash
zaptrace viewer examples/esp32_i2c_sensor_node/design.yaml --proof examples/esp32_i2c_sensor_node/.proof/proof.yaml --output build/review-viewer
```

Open `build/review-viewer/index.html` in a browser.

The bundle contains:

- `assets/schematic.svg` for the schematic overview;
- `assets/pcb-top.svg` and `assets/pcb-bottom.svg` for local PCB layer review;
- DRC/DFM marker summaries when the design contains validation results;
- `data/bom.json` for BOM summary review;
- `data/proof-summary.json` and `data/viewer-manifest.json` for proof-pack status and artifact provenance.

This is a static inspection artifact for CI and local review. Fabrication still requires explicit ERC/DRC/DFM/proof-pack signoff.
