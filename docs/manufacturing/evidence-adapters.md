# Manufacturing Evidence Adapters

Manufacturing evidence adapters turn generated fabrication files into proof-pack evidence. The first adapter scans an output directory and records:

- Gerber files;
- Excellon drill files;
- BOM CSV;
- pick-and-place CSV;
- manufacturing manifest JSON;
- ZIP bundles;
- optional ODB++ and IPC-2581 attachments when present.

Each artifact record includes a relative path, kind, file size, and SHA-256 hash. Gerber and Excellon files receive smoke validation so CI can fail early when an exporter emits malformed or incomplete files.

Fab profile validation is represented as release-blocking manufacturing evidence: DFM errors block release, warnings remain visible for review.

Current limitations:

- Gerber/Excellon smoke validation checks basic syntax markers only.
- ODB++ and IPC-2581 records can be attached to proof packs, but full external parsers are intentionally left to provider-specific adapters.
- Evidence is not manufacturer approval and does not remove human fabrication review.
