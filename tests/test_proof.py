"""Tests for the Proof Pack system.

Covers manifest, checker, pack loading, and CLI integration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from zaptrace.proof import (
    CheckDefinition,
    CheckResult,
    CheckStatus,
    ManifestModel,
    ProofManifest,
    ProofPack,
    ProofRunner,
    capture_environment,
    hash_file,
    run_proof,
    validate_proof_pack,
)
from zaptrace.proof.manifest import (
    ArtifactRecord,
    CheckCategory,
    CheckRecord,
    CheckSeverity,
    CheckSource,
    EnvironmentRecord,
    InputRecord,
    KiCadOracleEvidence,
)

# ===========================================================================
# Manifest tests
# ===========================================================================


class TestCheckDefinition:
    def test_minimal(self) -> None:
        c = CheckDefinition(name="test_check", type="drc")
        assert c.name == "test_check"
        assert c.type == "drc"
        assert c.severity == CheckSeverity.ERROR
        assert c.category == CheckCategory.CUSTOM

    def test_full(self) -> None:
        c = CheckDefinition(
            name="full_check",
            description="Check everything",
            category=CheckCategory.ERC,
            severity=CheckSeverity.WARNING,
            type="erc",
            params={"min_voltage": 3.3},
            expected="pass",
            expected_count=0,
            tags=["power", "critical"],
        )
        assert c.severity == CheckSeverity.WARNING
        assert c.category == CheckCategory.ERC
        assert c.params["min_voltage"] == 3.3
        assert "power" in c.tags

    def test_expected_defaults(self) -> None:
        c = CheckDefinition(name="defaults", type="routed")
        assert c.expected == "pass"
        assert c.expected_count is None


class TestManifestModel:
    def test_defaults(self) -> None:
        m = ManifestModel()
        assert m.min_clearance_mm == 0.15
        assert m.min_trace_width_mm == 0.15
        assert m.max_layer_count == 2
        assert m.allowed_layer_counts == [1, 2, 4]

    def test_custom(self) -> None:
        m = ManifestModel(
            min_clearance_mm=0.2,
            min_trace_width_mm=0.25,
            max_layer_count=4,
            allowed_layer_counts=[2, 4],
        )
        assert m.min_clearance_mm == 0.2
        assert m.max_layer_count == 4


class TestProofManifest:
    def test_minimal(self) -> None:
        m = ProofManifest(name="test", design_path="design.yaml")
        assert m.version == "1.0"
        assert m.checks == []
        assert m.author == ""

    def test_full(self) -> None:
        m = ProofManifest(
            version="1.0",
            name="Full Test Pack",
            description="Validates everything",
            design_path="../designs/my_board.yaml",
            model=ManifestModel(min_clearance_mm=0.2),
            checks=[
                CheckDefinition(name="ch1", type="drc"),
                CheckDefinition(name="ch2", type="erc", severity=CheckSeverity.WARNING),
            ],
            references={"gerber_top": "golden/gerber_top.gbr"},
            author="test-bot",
            tags=["ci", "nightly"],
            requires=["zaptrace>=0.2.0"],
        )
        assert len(m.checks) == 2
        assert m.model.min_clearance_mm == 0.2
        assert m.author == "test-bot"
        assert "ci" in m.tags


# ===========================================================================
# Checker tests
# ===========================================================================


@dataclass
class FakeComponent:
    """Minimal component stub for testing."""

    ref: str
    footprint: str | None = None


@dataclass
class FakePinNode:
    """Minimal net-node stub matching NetNode.pin_name."""

    pin_name: str


@dataclass
class FakeNet:
    """Minimal net stub for testing."""

    id: str
    name: str
    nodes: list = field(default_factory=list)


@dataclass
class FakeTrace:
    """Minimal trace stub matching TraceSegment attributes used by checker."""

    net_id: str = ""
    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)
    width: float = 0.2


@dataclass
class FakeRouteResult:
    """Minimal route-result stub matching RouteResult.traces."""

    traces: list = field(default_factory=list)


@dataclass
class FakeDesign:
    """Minimal design stub for checker tests."""

    components: dict = field(default_factory=dict)
    nets: dict = field(default_factory=dict)
    routing: FakeRouteResult | None = None

    def __init__(
        self,
        components: list | None = None,
        nets: list | None = None,
        traces: list | None = None,
    ):
        if components and all(hasattr(c, "id") for c in components):
            self.components = {c.id: c for c in components}
        elif components:
            self.components = {c.ref: c for c in components}
        else:
            self.components = {}
        self.nets = {n.id: n for n in (nets or [])}
        self.routing = FakeRouteResult(traces=traces or [])


class TestCheckStatus:
    def test_values(self) -> None:
        assert CheckStatus.PASS.value == "pass"
        assert CheckStatus.FAIL.value == "fail"
        assert CheckStatus.ERROR.value == "error"
        assert CheckStatus.SKIP.value == "skip"


class TestCheckResult:
    def test_passed_property(self) -> None:
        c = CheckDefinition(name="t", type="drc")
        r = CheckResult(check=c, status=CheckStatus.PASS)
        assert r.passed is True

    def test_failed_property(self) -> None:
        c = CheckDefinition(name="t", type="drc")
        r = CheckResult(check=c, status=CheckStatus.FAIL)
        assert r.passed is False

    def test_to_dict(self) -> None:
        c = CheckDefinition(name="my_check", type="erc", category=CheckCategory.ERC)
        r = CheckResult(check=c, status=CheckStatus.PASS, message="OK", duration_ms=5.0)
        d = r.to_dict()
        assert d["name"] == "my_check"
        assert d["category"] == "erc"
        assert d["status"] == "pass"
        assert d["message"] == "OK"
        assert d["duration_ms"] == 5.0


class TestProofRunner:
    def test_unknown_check_type_skips(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)
        check = CheckDefinition(name="unknown", type="nonexistent_check_type")
        results = runner.run_checks([check])
        assert len(results) == 1
        assert results[0].status == CheckStatus.SKIP
        assert "Unknown" in results[0].message

    def test_routed_all_pass(self) -> None:
        design = FakeDesign(
            nets=[FakeNet("n1", "VCC"), FakeNet("n2", "GND")],
            traces=[FakeTrace(net_id="n1"), FakeTrace(net_id="n2")],
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="routed", type="routed")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_routed_some_fail(self) -> None:
        design = FakeDesign(
            nets=[FakeNet("n1", "VCC"), FakeNet("n2", "GND")],
            traces=[FakeTrace(net_id="n1")],
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="routed", type="routed")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL
        assert "unrouted" in results[0].message.lower()

    def test_footprint_exists_pass(self) -> None:
        design = FakeDesign(components=[FakeComponent("R1", "0805"), FakeComponent("C1", "0603")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="fps", type="footprint_exists")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_footprint_exists_fail(self) -> None:
        design = FakeDesign(components=[FakeComponent("R1", None), FakeComponent("C1", "0603")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="fps", type="footprint_exists")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL
        assert "1 missing" in results[0].message

    def test_net_connected_pass(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC", nodes=[FakePinNode("R1.p1"), FakePinNode("C1.p1")])])
        runner = ProofRunner(design)
        check = CheckDefinition(
            name="netchk",
            type="net_connected",
            params={"net_name": "VCC", "expected_pins": ["R1.p1"]},
        )
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_net_connected_fail(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC", nodes=[FakePinNode("R1.p1")])])
        runner = ProofRunner(design)
        check = CheckDefinition(
            name="netchk",
            type="net_connected",
            params={"net_name": "VCC", "expected_pins": ["R1.p1", "C1.p1"]},
        )
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_net_connected_missing_param(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)
        check = CheckDefinition(name="netchk", type="net_connected", params={})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.ERROR

    def test_net_connected_net_not_found(self) -> None:
        design = FakeDesign(nets=[FakeNet("n1", "VCC")])
        runner = ProofRunner(design)
        check = CheckDefinition(name="netchk", type="net_connected", params={"net_name": "NONEXISTENT"})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_clearance_pass(self) -> None:
        # Traces far apart
        design = FakeDesign(
            traces=[
                FakeTrace(net_id="n1", start=(0, 0), end=(10, 10)),
                FakeTrace(net_id="n2", start=(100, 100), end=(200, 200)),
            ]
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="clear", type="clearance", params={"min_clearance_mm": 0.15})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS

    def test_clearance_violation(self) -> None:
        # Traces close together — simplified check computes distance between segments
        design = FakeDesign(
            traces=[
                FakeTrace(net_id="n1", start=(0, 0), end=(5, 5)),
                FakeTrace(net_id="n2", start=(0, 0), end=(6, 6)),
            ]
        )
        runner = ProofRunner(design)
        check = CheckDefinition(name="clear", type="clearance", params={"min_clearance_mm": 2.0})
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.FAIL

    def test_custom_registration(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)

        def custom_check(_check: CheckDefinition) -> CheckResult:
            return CheckResult(check=_check, status=CheckStatus.PASS, message="Custom OK")

        runner.register("my_custom", custom_check)
        check = CheckDefinition(name="custom", type="my_custom")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.PASS
        assert results[0].message == "Custom OK"

    def test_exception_in_check(self) -> None:
        design = FakeDesign()
        runner = ProofRunner(design)

        def broken_check(_check: CheckDefinition) -> CheckResult:
            raise RuntimeError("Something broke")

        runner.register("broken", broken_check)
        check = CheckDefinition(name="broken", type="broken")
        results = runner.run_checks([check])
        assert results[0].status == CheckStatus.ERROR
        assert "Something broke" in results[0].message

    def test_trace_distance_far(self) -> None:
        t1 = FakeTrace(net_id="n1", start=(0, 0), end=(10, 10))
        t2 = FakeTrace(net_id="n2", start=(100, 100), end=(200, 200))
        dist = ProofRunner._trace_distance(t1, t2)
        assert dist > 100  # Very far apart

    def test_trace_distance_invalid(self) -> None:
        class BadTrace:
            pass

        dist = ProofRunner._trace_distance(BadTrace(), BadTrace())
        assert dist == float("inf")


# ===========================================================================
# YAML serialization tests
# ===========================================================================


class TestManifestYAML:
    def test_round_trip(self, tmp_path: Path) -> None:
        manifest = ProofManifest(
            name="RoundTrip Test",
            description="Testing YAML round-trip",
            design_path="design.yaml",
            model=ManifestModel(min_clearance_mm=0.2, max_layer_count=4),
            checks=[
                CheckDefinition(name="drc_check", type="drc", severity=CheckSeverity.ERROR),
                CheckDefinition(name="routed_check", type="routed"),
            ],
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        # Reload
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        loaded = ProofManifest(**data)
        assert loaded.name == manifest.name
        assert len(loaded.checks) == len(manifest.checks)
        assert loaded.model.min_clearance_mm == 0.2

    def test_yaml_with_tags(self, tmp_path: Path) -> None:
        data = {
            "version": "1.0",
            "name": "Tagged Pack",
            "design_path": "design.yaml",
            "checks": [
                {"name": "c1", "type": "drc", "tags": ["quick", "ci"]},
                {"name": "c2", "type": "erc", "tags": ["full"]},
            ],
        }
        path = tmp_path / "proof.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f)
        with open(path) as f:
            loaded = ProofManifest(**yaml.safe_load(f))
        assert len(loaded.checks) == 2
        assert loaded.checks[0].tags == ["quick", "ci"]


# ===========================================================================
# ProofPack tests
# ===========================================================================


class TestProofPackLoad:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="Test", design_path="design.yaml")
        yaml_path = proof_dir / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(yaml_path)
        assert pack.manifest.name == "Test"
        assert pack.manifest.design_path == "design.yaml"

    def test_load_from_directory(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="DirTest", design_path="design.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(proof_dir)
        assert pack.manifest.name == "DirTest"

    def test_load_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            ProofPack.load(Path("/nonexistent/proof.yaml"))

    def test_run_missing_design(self, tmp_path: Path) -> None:
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="MissingDesign", design_path="nonexistent.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        pack = ProofPack.load(proof_dir)
        with pytest.raises(FileNotFoundError):
            pack.run()


class TestProofPackResults:
    def test_summary_empty(self) -> None:
        manifest = ProofManifest(name="Empty", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        assert "Empty" in pack.summary
        assert "Total:   0" in pack.summary

    def test_report_json(self) -> None:
        manifest = ProofManifest(name="JSON Test", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        report = pack.report_json()
        data = json.loads(report)
        assert data["name"] == "JSON Test"
        assert data["passed"] is True
        assert data["checks"] == []

    def test_passed_property_empty(self) -> None:
        manifest = ProofManifest(name="Empty", design_path="d.yaml")
        pack = ProofPack(manifest=manifest)
        assert pack.passed is True  # No checks = vacuously true


class TestRunProof:
    def test_run_proof_convenience(self, tmp_path: Path) -> None:
        """Test run_proof with a proof directory (design won't exist but we test loader)."""
        proof_dir = tmp_path / "proof"
        proof_dir.mkdir()
        manifest = ProofManifest(name="Convenience", design_path="design.yaml")
        with open(proof_dir / "proof.yaml", "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        # This should load but fail on design
        with pytest.raises(FileNotFoundError):
            run_proof(proof_dir)

    def test_run_proof_with_file_path(self, tmp_path: Path) -> None:
        manifest = ProofManifest(name="FileTest", design_path="design.yaml")
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        with pytest.raises(FileNotFoundError):
            run_proof(yaml_path)

    def test_run_proof_invalid_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "proof.yaml"
        yaml_path.write_text("invalid: [yaml: broken\n  bad", encoding="utf-8")
        with pytest.raises((yaml.YAMLError, KeyError, ValueError)):
            run_proof(yaml_path)


# ===========================================================================
# CLI integration tests
# ===========================================================================


class TestProofCLI:
    def test_proof_group_help(self) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "--help"])
        assert result.exit_code == 0
        assert "Manage and run Proof Packs" in result.output

    def test_proof_list_no_pack(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "list", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0

    def test_proof_info_no_pack(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "info", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0

    def test_proof_list_success(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="CLI Test",
            design_path="design.yaml",
            checks=[CheckDefinition(name="chk1", type="drc", description="DRC check")],
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "list", str(yaml_path)])
        assert result.exit_code == 0
        assert "chk1" in result.output
        assert "drc" in result.output

    def test_proof_info_success(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        manifest = ProofManifest(
            name="Info Test",
            design_path="design.yaml",
            description="My proof pack",
            author="test",
        )
        yaml_path = tmp_path / "proof.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        runner = CliRunner()
        result = runner.invoke(cli, ["proof", "info", str(yaml_path)])
        assert result.exit_code == 0
        assert "Info Test" in result.output
        assert "test" in result.output

    def test_proof_pack_help(self) -> None:
        """zaptrace proof-pack --help should work."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", "--help"])
        assert result.exit_code == 0
        assert "DESIGN_PATH" in result.output
        assert "proof pack" in result.output.lower()

    def test_proof_pack_nonexistent_design(self) -> None:
        """proof-pack with a non-existent file should fail gracefully."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", "/nonexistent/design.yaml"])
        assert result.exit_code != 0

    def test_proof_pack_json_output(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack with --format json should produce valid JSON output (pass or fail)."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--format", "json"])
        # Exit code 1 is valid when checks fail
        assert result.exit_code in (0, 1)
        import json as _json

        data = _json.loads(result.output)
        assert "name" in data
        assert "results" in data

    def test_proof_pack_verbose(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack --verbose shows check details regardless of pass/fail."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--verbose"])
        # Exit code 1 is valid when checks fail
        assert result.exit_code in (0, 1)
        assert "Checks:" in result.output

    def test_proof_pack_bundle_output(self, tmp_path: Path, sample_design_path: Path) -> None:
        """proof-pack --output writes bundle files even when checks fail."""
        from click.testing import CliRunner

        from zaptrace.cli.main import cli

        design = sample_design_path
        out_dir = tmp_path / "proof-bundle"
        runner = CliRunner()
        result = runner.invoke(cli, ["proof-pack", str(design), "--output", str(out_dir)])
        # Bundle is written before early-exit on check failure
        assert result.exit_code in (0, 1)
        assert out_dir.exists()
        assert (out_dir / "proof.yaml").exists()
        assert (out_dir / "results.json").exists()


# ===========================================================================
# v1 Evidence field tests
# ===========================================================================


class TestHashFile:
    def test_hash_file_known_value(self, tmp_path: Path) -> None:
        """SHA-256 of known bytes should match expected hex digest."""
        f = tmp_path / "data.txt"
        f.write_bytes(b"hello world\n")
        digest = hash_file(f)
        expected = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
        assert digest == expected

    def test_hash_file_binary(self, tmp_path: Path) -> None:
        """Binary content produces a deterministic hash."""
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        d1 = hash_file(f)
        d2 = hash_file(f)
        assert d1 == d2
        assert len(d1) == 64

    def test_hash_file_not_found(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            hash_file(Path("/nonexistent/file.bin"))


class TestValidateProofPack:
    def test_valid_manifest_no_errors(self) -> None:
        """A minimal manifest with human-review limitation should pass."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            limitations=["Requires human engineer review before fabrication."],
        )
        errors = validate_proof_pack(manifest, Path("."))
        assert errors == []

    def test_missing_name(self) -> None:
        """Missing name should produce an error."""
        manifest = ProofManifest(name="", design_path="design.yaml")
        errors = validate_proof_pack(manifest, Path("."))
        assert any("name" in e.lower() for e in errors)

    def test_missing_design_path(self) -> None:
        """Empty design_path should produce an error."""
        manifest = ProofManifest(name="test", design_path="")
        errors = validate_proof_pack(manifest, Path("."))
        assert any("design_path" in e.lower() for e in errors)

    def test_missing_human_review_warning(self) -> None:
        """Manifest without 'human engineer review' in limitations should warn."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            limitations=["some other limitation"],
        )
        errors = validate_proof_pack(manifest, Path("."))
        assert any("human-engineer-review" in e.lower() for e in errors)

    def test_artifact_hash_mismatch(self, tmp_path: Path) -> None:
        """Artifact with wrong SHA-256 should be flagged."""
        f = tmp_path / "artifact.gbr"
        f.write_bytes(b"content")
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            artifacts=[
                ArtifactRecord(path="artifact.gbr", kind="gerber", sha256="0000deadbeef" * 4),
            ],
        )
        errors = validate_proof_pack(manifest, tmp_path)
        assert any("hash mismatch" in e.lower() for e in errors)

    def test_artifact_missing_file(self, tmp_path: Path) -> None:
        """Artifact path that does not exist should be flagged."""
        manifest = ProofManifest(
            name="test",
            design_path="design.yaml",
            artifacts=[
                ArtifactRecord(path="nonexistent.gbr", kind="gerber", sha256="00" * 32),
            ],
        )
        errors = validate_proof_pack(manifest, tmp_path)
        assert any("missing" in e.lower() for e in errors)


class TestCaptureEnvironment:
    def test_basic_fields(self) -> None:
        """capture_environment should return Python version and platform."""
        env = capture_environment()
        assert isinstance(env, EnvironmentRecord)
        assert env.python_version
        assert env.platform

    def test_zaptrace_version(self) -> None:
        """Environment record should include zaptrace version."""
        env = capture_environment()
        assert env.zaptrace_version or env.zaptrace_version == ""


class TestInputRecord:
    def test_defaults(self) -> None:
        """InputRecord should have sensible defaults."""
        r = InputRecord(source_type="file", filename="design.yaml")
        assert r.source_type == "file"
        assert r.filename == "design.yaml"
        assert r.checksum_sha256 is None

    def test_with_checksum(self) -> None:
        """InputRecord with SHA-256 checksum."""
        r = InputRecord(
            source_type="file",
            filename="design.yaml",
            checksum_sha256="abc123",
        )
        assert r.checksum_sha256 == "abc123"


class TestArtifactRecord:
    def test_minimal(self) -> None:
        """ArtifactRecord can be created with just path and kind."""
        r = ArtifactRecord(path="gerber_top.gbr", kind="gerber")
        assert r.sha256 is None
        assert r.size_bytes == 0

    def test_full(self) -> None:
        """ArtifactRecord with all fields."""
        r = ArtifactRecord(
            path="gerber_top.gbr",
            kind="gerber",
            sha256="abcd" * 16,
            size_bytes=1024,
        )
        assert r.sha256 == "abcd" * 16
        assert r.size_bytes == 1024


class TestCheckSource:
    def test_values(self) -> None:
        """CheckSource enum values."""
        assert CheckSource.ZAPTRACE == "zaptrace"
        assert CheckSource.KICAD == "kicad"
        assert CheckSource.FAB_PROFILE == "fab_profile"
        assert CheckSource.EXTERNAL == "external"


def test_proof_bundle_records_kicad_oracle_metadata(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    design_path.write_text("meta:\n  name: OracleProof\ncomponents: {}\n", encoding="utf-8")
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        """version: '1.0'
name: oracle-proof
design_path: design.yaml
checks: []
""",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    pack.run()
    bundle = pack.bundle(tmp_path / "out")

    assert bundle.exists()
    assert pack.manifest.kicad_oracle
    evidence = pack.manifest.kicad_oracle[0]
    assert evidence.status in {"passed", "failed", "skipped"}
    if evidence.status == "skipped":
        assert evidence.skip_reason


def test_proof_bundle_records_final_state_hash(tmp_path: Path) -> None:
    design_path = tmp_path / "design.yaml"
    design_path.write_text("meta:\n  name: HashProof\ncomponents: {}\n", encoding="utf-8")
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        """version: '1.0'
name: hash-proof
design_path: design.yaml
checks: []
""",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    pack.run()
    pack.bundle(tmp_path / "out")

    assert len(pack.manifest.final_state_hash) == 64
    assert pack.manifest.transaction_history == []


def test_validate_rejects_absolute_or_parent_artifact_paths(tmp_path: Path) -> None:
    manifest = ProofManifest(
        name="bad-artifact-path",
        design_path="design.yaml",
        artifacts=[ArtifactRecord(path="../escape.gbr", kind="gerber", sha256="0" * 64)],
    )
    errors = validate_proof_pack(manifest, tmp_path)
    assert any("relative and contained" in err for err in errors)


def test_validate_rejects_malformed_artifact_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gbr"
    artifact.write_text("G04 test*", encoding="utf-8")
    manifest = ProofManifest(
        name="bad-hash",
        design_path="design.yaml",
        artifacts=[ArtifactRecord(path="artifact.gbr", kind="gerber", sha256="not-a-sha")],
    )
    errors = validate_proof_pack(manifest, tmp_path)
    assert any("sha256" in err.lower() for err in errors)


def test_validate_requires_skip_reason_for_skipped_check() -> None:
    manifest = ProofManifest(
        name="skip-reason",
        design_path="design.yaml",
        check_records=[CheckRecord(name="oracle", status="skipped")],
    )
    errors = validate_proof_pack(manifest, Path("."))
    assert any("skip reason" in err.lower() for err in errors)


def test_validate_requires_kicad_oracle_skip_reason() -> None:
    manifest = ProofManifest(
        name="oracle-skip",
        design_path="design.yaml",
        kicad_oracle=[KiCadOracleEvidence(check="drc", status="skipped")],
    )
    errors = validate_proof_pack(manifest, Path("."))
    assert any("skip_reason" in err for err in errors)


def test_stable_id_ignores_runtime_environment_and_absolute_paths(tmp_path: Path) -> None:
    manifest_a = ProofManifest(
        name="stable",
        design_path=str(tmp_path / "design.yaml"),
        environment=EnvironmentRecord(python_version="3.12", platform="linux-a"),
        artifacts=[ArtifactRecord(path="/tmp/out.gbr", kind="gerber", sha256="1" * 64)],
        references={"fab.gbr": str(tmp_path / "fab.gbr")},
    )
    manifest_b = ProofManifest(
        name="stable",
        design_path="/different/root/design.yaml",
        environment=EnvironmentRecord(python_version="3.13", platform="linux-b"),
        artifacts=[ArtifactRecord(path="/different/out.gbr", kind="gerber", sha256="2" * 64)],
        references={"fab.gbr": "/another/root/fab.gbr"},
    )
    assert ProofPack(manifest_a).stable_id == ProofPack(manifest_b).stable_id
