from __future__ import annotations

from pathlib import Path


def test_release_workflow_generates_and_verifies_checksums() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "Generate checksum manifest" in workflow
    assert "scripts/generate_checksum_manifest.py release-artifacts" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow


def test_release_job_checks_out_repo_before_running_release_scripts() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    release_section = workflow.split("github-release:", 1)[1]
    checkout_pos = release_section.index("actions/checkout")
    checksum_pos = release_section.index("scripts/generate_checksum_manifest.py")
    assert checkout_pos < checksum_pos
