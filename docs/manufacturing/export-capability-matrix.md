# Manufacturing Export Capability Matrix

ZapTrace records manufacturing export evidence even when a format is produced by an external backend. The goal is deterministic proof-pack evidence, not a claim that every manufacturing format has a native exporter.

| Format | Backend | Support | Proof-pack kind | Release impact | Notes |
|---|---|---|---|---|---|
| Gerber | ZapTrace | supported | `gerber` | blocking | Native RS-274X exporter |
| Drill / Excellon | ZapTrace | supported | `excellon` | blocking | Native drill exporter |
| BOM | ZapTrace | supported | `bom` | blocking | Native CSV/JSON BOM exporters |
| Pick-and-place | ZapTrace | supported | `pick_and_place` | blocking | Native centroid CSV from placement data |
| ODB++ | KiCad CLI / external | external evidence | `odbpp` | blocking when required | Attach command, tool version, output hash, and warnings |
| IPC-2581 | KiCad CLI / external | external evidence | `ipc2581` | blocking when required | Attach command, tool version, output hash, and warnings |

Unsupported variants, layers, stackups, or backends must fail with actionable errors. They must never silently produce partial manufacturing output.

Proof packs can include manufacturing export logs with:

- backend and tool version;
- command/config used to generate the files;
- output paths, sizes, and SHA-256 hashes;
- warnings;
- unsupported paths or variants;
- release-blocking status.
