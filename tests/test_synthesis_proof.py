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
        for fname in (
            "design.yaml",
            "proof.yaml",
            "report.json",
            "requirements_coverage.json",
            "assumptions.json",
            "kicad_schematic_parity.json",
        ):
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

    def test_requirements_coverage_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report_path = tmp_path / "requirements_coverage.json"
        report = json.loads(report_path.read_text())

        assert report["schema_version"] == "1.0"
        assert report["requirements_hash"] == pack.manifest.requirements_coverage.requirements_hash
        assert pack.manifest.requirements_coverage.report_path == "requirements_coverage.json"
        assert pack.manifest.requirements_coverage.requirement_count == len(report["requirements"])
        assert any(a.path == "requirements_coverage.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(row["kind"] == "export" and row["id"] == "report.json" for row in report["traceability"])

    def test_assumptions_artifact_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "assumptions.json").read_text())

        assert report["schema_version"] == "1.0"
        assert pack.manifest.assumptions_evidence.report_path == "assumptions.json"
        assert pack.manifest.assumptions_evidence.assumption_count == len(report["assumptions"])
        assert pack.manifest.assumptions_evidence.unconfirmed_high_risk_count == report["unconfirmed_high_risk_count"]
        assert any(a.path == "assumptions.json" and a.kind == "report" for a in pack.manifest.artifacts)

    def test_kicad_schematic_parity_report_is_written_and_manifested(self, tmp_path: Path) -> None:
        pack = generate_synthesis_proof(_INTENT, tmp_path, name="UsbI2c")
        report = json.loads((tmp_path / "kicad_schematic_parity.json").read_text())

        assert report["schema_version"] == "1.0"
        assert report["check"] == "ir_to_kicad_schematic_netlist"
        assert pack.manifest.kicad_schematic_parity.report_path == "kicad_schematic_parity.json"
        assert pack.manifest.kicad_schematic_parity.passed == report["passed"]
        assert any(a.path == "kicad_schematic_parity.json" and a.kind == "report" for a in pack.manifest.artifacts)
        assert any(
            a.path.endswith(".kicad_netlist_evidence.json") and a.kind == "netlist" for a in pack.manifest.artifacts
        )
