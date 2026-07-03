from __future__ import annotations

from scripts.ci_dco_check import has_signoff, is_code_sensitive_path


def test_code_sensitive_paths_include_source_and_workflows() -> None:
    assert is_code_sensitive_path("zaptrace/core/model.py")
    assert is_code_sensitive_path("zaptrace_core/src/lib.rs")
    assert is_code_sensitive_path(".github/workflows/quality.yml")
    assert is_code_sensitive_path("pyproject.toml")
    assert is_code_sensitive_path("Dockerfile")


def test_code_sensitive_paths_exclude_plain_docs() -> None:
    assert not is_code_sensitive_path("README.md")
    assert not is_code_sensitive_path("docs/security/release-verification.md")


def test_signed_off_by_detection() -> None:
    assert has_signoff("feat: add check\n\nSigned-off-by: Ada Lovelace <ada@example.com>")
    assert not has_signoff("feat: add check\n\nSigned off by Ada")
