# Datasheet fact and provenance model

ZapTrace represents datasheet-derived engineering facts as machine-readable evidence. This model is evidence, not manufacturer approval and not a substitute for human datasheet review.

## Source reference

Every fact carries a `DatasheetSourceRef`:

```text
datasheet_url
datasheet_sha256
page
table
figure
section
source_snippet
```

`datasheet_sha256` is computed over the source text or PDF bytes that fed the extractor. Page, table, figure, and section identify where the fact came from.

## Fact scope

Datasheet facts use explicit safety scopes:

```text
absolute_maximum
recommended_operating
pin_function
package
electrical_characteristic
thermal_characteristic
```

Absolute maximum ratings and recommended operating conditions are intentionally stored in separate lists:

```text
absolute_maximum[]
recommended_operating[]
other_facts[]
```

This prevents an agent from treating absolute-maximum survival limits as normal operating recommendations.

## Fact report

`build_datasheet_fact_report(component_id, raw_text, datasheet_url=...)` returns:

```text
schema_version
component_id
datasheet_url
datasheet_sha256
absolute_maximum[]
recommended_operating[]
other_facts[]
import_losses[]
fact_count
```

The current extractor populates recommended operating voltage/temperature, package, electrical characteristics, and pin-function facts from deterministic regex extraction. Later confidence/conflict gates build on the same model.

## Proof-pack evidence

Proof manifests can attach `datasheet_provenance` metadata:

```text
report_path
component_count
fact_count
absolute_maximum_count
recommended_operating_count
missing_hash_count
message
```

A proof pack should include the full JSON report as an artifact and the manifest summary as provenance metadata.
