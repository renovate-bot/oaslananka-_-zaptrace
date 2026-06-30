# Placement scorecard evidence

ZapTrace's placement scorecard converts constraint-aware placement observations into machine-readable sign-off evidence. It does not move components; it scores an existing placement and explains what needs review or repair.

## Scorecard sections

`build_placement_scorecard(design)` reports:

```text
block_grouping
connector_constraints
decoupling_proximity
keepouts
thermal_spacing
placement_coverage
```

The scorecard includes:

```text
schema_version
overall_score
status
min_autonomous_score
min_review_score
group_count
component_count
placed_component_count
section_scores[]
observations[]
blocking_observation_count
warning_count
human_review_required
blocked
```

## Policy

- `blocked=true` when the score is below `min_autonomous_score` or a blocking observation exists.
- `human_review_required=true` when warnings exist or the score is below `min_review_score` but not blocked.
- Connector edge constraints, decoupling distance, keepout/near constraints, and thermal spacing are scored independently so repair agents can target the failing section.

## Proof-pack sign-off

Proof manifests can attach `placement_scorecard` evidence. It maps to autonomous sign-off as:

```text
passed=false                 -> placement-scorecard blocks autonomous-pass
human_review_required=true   -> placement-scorecard requires human review
passed=true with no warnings -> placement-scorecard passes
```
