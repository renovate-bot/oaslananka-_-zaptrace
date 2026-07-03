from __future__ import annotations

from pathlib import Path

from scripts.generate_checksum_manifest import build_manifest, sha256_file, write_manifest


def test_checksum_manifest_is_sorted_and_excludes_itself(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "release-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "b.whl").write_text("b", encoding="utf-8")
    (artifact_dir / "a.tar.gz").write_text("a", encoding="utf-8")
    output = artifact_dir / "SHA256SUMS"

    write_manifest(artifact_dir, output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["a.tar.gz", "b.whl"]
    assert all("SHA256SUMS" not in line for line in lines)
    assert lines[0].startswith(sha256_file(artifact_dir / "a.tar.gz"))


def test_empty_manifest_is_empty(tmp_path: Path) -> None:
    assert build_manifest(tmp_path, tmp_path / "SHA256SUMS") == ""
