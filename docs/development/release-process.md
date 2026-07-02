# Release Process

ZapTrace uses SemVer-style release identifiers such as `v0.3.0`.

## Release checklist

1. Update `CHANGELOG.md` with a human-readable summary.
2. Verify the package version matches the intended tag.
3. Run the full quality and security workflows on `main`.
4. Create a signed Git tag if maintainer signing is configured.
5. Push a `v*` tag to trigger `.github/workflows/release.yml`.
6. Verify that release artifacts, SBOM, and provenance/attestation steps complete.
7. Review generated GitHub release notes before public announcement.

## Release workflow

The release workflow:

- checks that the tag matches the package version;
- runs Python and Rust quality gates;
- builds source/wheel artifacts;
- generates an SPDX SBOM;
- attests release artifacts;
- creates a GitHub Release.

## Publishing policy

Automatic PyPI/GHCR publishing is intentionally disabled until package naming, credential policy, and registry ownership are settled. Do not add publishing credentials without a separate reviewed issue and threat model.

## Non-claims

A release does not certify that generated boards are fabrication-ready, manufacturer-approved, production-ready, or safe without human review.
