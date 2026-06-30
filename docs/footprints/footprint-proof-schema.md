# Footprint proof schema

`footprint_proof.json` records machine-readable evidence for generated, imported, and vendored land patterns. It is a provenance contract; pad/pin validation and release blocking gates build on this schema.

## Required evidence

A footprint proof includes:

```text
schema_version
package_id
footprint_name
source
pad_count
pin_count
pin_map
pads
courtyard_mm
paste_enabled_pad_count
paste_disabled_pad_count
solder_mask_policy
thermal_pads
pin1
notes
```

## Source provenance

`source` identifies where the land pattern came from:

```text
source_type: generated | vendored | imported | unknown
source_name
source_path
source_sha256
generator
generator_version
attribution
```

Generated footprints use `zaptrace.ee.footprints` and the ZapTrace version. Vendored footprints record the source `.kicad_mod` path and SHA-256.

## Pad and pin evidence

Each pad records:

```text
pad_id
layer
shape
position_mm
size_mm
drill_mm
plated
solder_paste
solder_mask
```

`pin_map` maps logical pin ids to footprint pad ids. When no explicit symbol mapping is supplied, the builder uses `pad.id -> pad.id`.

## Courtyard, paste/mask, and pin-1

`courtyard_mm` records the footprint courtyard extent. Paste evidence is summarized by enabled/disabled pad counts. Solder mask is currently recorded as the policy string plus per-pad assumed mask openings.

`pin1` records whether a pad id such as `1`, `A1`, or `P1` exists. Missing pin-1 evidence is not automatically rejected by this schema, but downstream validators should treat it as a blocking issue for risky packages.

## Fixture

A sample generated proof is committed at:

```text
tests/fixtures/footprints/sot23_footprint_proof.json
```
