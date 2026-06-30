"""Tests for synthesis → proof-pack integration."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.proof import run_proof, validate_proof_pack
from zaptrace.synthesis.proof import generate_synthesis_proof

_INTENT = "USB-C powered board, 3.3V rail, I2C sensor"


class TestGenerateSynthesisProof:
    def test_writes_bundle_files(self, tmp_path: Path) -> None:
        generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        for fname in ("design.yaml", "proof.yaml", "report.json"):
            assert (tmp_path / fname).exists(), f"{fname} not written"

    def test_pack_passes_at_baseline(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        # ERC/DRC baselines are snapshotted, so a freshly generated pack passes.
        assert pack.passed
        assert {r.check.name for r in pack.results} == {"erc", "drc", "footprints"}

    def test_bundle_validates(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        assert validate_proof_pack(pack.manifest, tmp_path) == []

    def test_records_synthesis_provenance(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        m = pack.manifest
        assert m.captured_intent == _INTENT
        assert m.input_record.source_type == "intent"
        assert m.input_record.normalized_intent_checksum_sha256
        assert m.agent_decisions, "synthesis decisions should be captured"
        assert all(d.actor == "zaptrace-synthesis" for d in m.agent_decisions)

    def test_reloaded_bundle_reproduces_verdict(self, tmp_path: Path) -> None:
        generated = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        # The portable audit path: load the on-disk bundle and re-run it.
        reloaded = run_proof(tmp_path)
        assert reloaded.passed == generated.passed
        gen_counts = {r.check.name: r.message for r in generated.results}
        rel_counts = {r.check.name: r.message for r in reloaded.results}
        assert gen_counts == rel_counts

    def test_report_json_is_wellformed(self, tmp_path: Path) -> None:
        generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "report.json").read_text())
        assert report["passed"] is True
        assert {c["name"] for c in report["checks"]} == {"erc", "drc", "footprints"}
