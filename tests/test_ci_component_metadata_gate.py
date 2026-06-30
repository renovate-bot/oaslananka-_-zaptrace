from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.ci_component_metadata_gate import build_gate_summary, main
from zaptrace.library.loader import LibraryLoader


def _write_part(root: Path, comp_id: str, *, datasheet: str = "https://example.com/ds.pdf") -> None:
    path = root / "power" / f"{comp_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {
                "id": comp_id,
                "name": comp_id,
                "category": "power",
                "manufacturer": "Acme",
                "mpn": f"{comp_id}-MPN",
                "datasheet": datasheet,
                "package": "SOT-23-5",
                "footprint": "SOT-23-5",
                "pins": {"1": {"type": "input"}},
                "electrical_limits": {"max_voltage_v": 6},
                "sourcing": {"authorized_distributors": ["Digi-Key"]},
                "compliance": {"rohs": True},
                "provenance": {"reviewed_by": "ci"},
            }
        ),
        encoding="utf-8",
    )


def test_component_metadata_gate_passes_within_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "good")
    out = tmp_path / "gate.json"

    code = main(
        ["--library-root", str(root), "--max-errors", "0", "--max-warnings", "0", "--strict", "--output", str(out)]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 0
    assert data["blocked"] is False
    assert data["component_count"] == 1


def test_component_metadata_gate_fails_when_errors_exceed_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "bad", datasheet="")
    out = tmp_path / "gate.json"

    code = main(
        ["--library-root", str(root), "--max-errors", "0", "--max-warnings", "99", "--strict", "--output", str(out)]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 1
    assert data["blocked"] is True
    assert data["error_count"] == 1
    assert data["report"]["validations"][0]["findings"][0]["field"] == "datasheet"


def test_build_gate_summary_allows_baseline_budget(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write_part(root, "bad", datasheet="")
    report = LibraryLoader(root).governance_report()

    summary = build_gate_summary(report, max_errors=1, max_warnings=99)

    assert summary["blocked"] is False
    assert summary["error_count"] == 1
