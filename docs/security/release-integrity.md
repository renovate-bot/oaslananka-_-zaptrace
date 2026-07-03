# Release Integrity

ZapTrace release integrity relies on GitHub Releases, workflow logs, SBOM generation, and artifact attestations.

## What to verify

For an official release, verify:

1. The release tag matches the package version.
2. The release was created by the repository release workflow.
3. Release assets are associated with the release tag.
4. SBOM/provenance or attestation artifacts are present when the workflow produced them.
5. The changelog describes user-visible and security-relevant changes.

## Verify with GitHub CLI

```bash
gh release view v0.3.0 --repo oaslananka/zaptrace
gh release download v0.3.0 --repo oaslananka/zaptrace --dir /tmp/zaptrace-release
```

## Verify artifact attestation

When GitHub artifact attestations are available, use GitHub's attestation verification tooling for the release assets. The expected repository identity is:

```text
oaslananka/zaptrace
```

The expected workflow is the repository release workflow under `.github/workflows/release.yml`.

## Hashes and checksums

Recent release automation generates a `SHA256SUMS` manifest for release artifacts. Compare local artifact hashes against that manifest using `sha256sum --check SHA256SUMS`. If an older release does not include a checksum manifest, rely on GitHub release transport security plus available attestations/SBOM and prefer upgrading to a release with checksum evidence.

## Non-claims

Release integrity verifies artifact origin and tamper evidence. It does not prove that generated hardware is safe, manufacturable, compliant, or correct.

## Detailed verification guide

For commands and expected identities, see [Release Verification Guide](release-verification.md).
