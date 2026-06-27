"""Guardrails for public manufacturing/readiness claims."""

from __future__ import annotations

from pathlib import Path

_POSITIVE_CLAIMS = (
    "generates manufacturing-ready",
    "produces manufacturing-ready",
    "one command to production",
    "fabrication-ready by default",
)


def test_no_positive_manufacturing_ready_claims_remain() -> None:
    roots = [Path("README.md"), Path("zaptrace"), Path("docs"), Path("benchmarks")]
    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".txt"}:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                for claim in _POSITIVE_CLAIMS:
                    if claim in text:
                        offenders.append(f"{path}: {claim}")
    assert offenders == []
