# Release Verification Guide

Use this guide to verify the integrity and expected origin of ZapTrace release artifacts.

## Expected identity

Official source repository:

```text
https://github.com/oaslananka/zaptrace
```

Expected release workflow:

```text
.github/workflows/release.yml
```

Release tags use SemVer-style identifiers such as:

```text
v0.3.0
```

## Download release assets

```bash
gh release view v0.3.0 --repo oaslananka/zaptrace
gh release download v0.3.0 --repo oaslananka/zaptrace --dir /tmp/zaptrace-release
```

## Verify checksum manifest

Recent releases are expected to include `SHA256SUMS` when release automation produced distribution artifacts.

```bash
cd /tmp/zaptrace-release
sha256sum --check SHA256SUMS
```

Expected result: every listed artifact reports `OK`.

## Verify GitHub artifact attestation

When GitHub artifact attestations are present, verify each downloaded artifact against the repository identity:

```bash
gh attestation verify ./artifact-name --repo oaslananka/zaptrace
```

Expected result: the attestation verifies successfully and identifies the repository as `oaslananka/zaptrace`.

## Verify release tag and changelog

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
git fetch --tags
git tag --list 'v*'
git show --stat v0.3.0
```

Then compare the release version with `pyproject.toml`, `zaptrace_core/Cargo.toml`, and `CHANGELOG.md`.

## What this does not prove

Release verification confirms artifact integrity and origin evidence. It does not prove that generated circuit boards are safe, manufacturable, compliant, production-ready, or correct without human engineering review.
