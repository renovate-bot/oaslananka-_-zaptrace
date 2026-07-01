"""Tests for CLI commands.

Most tests use Click's CliRunner to verify command parsing and output.
"""

from __future__ import annotations

from click.testing import CliRunner

from zaptrace.cli.main import cli


def _runner() -> CliRunner:
    return CliRunner()


class TestCLIHelp:
    def test_help_succeeds(self) -> None:
        result = _runner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ZapTrace" in result.output

    def test_version(self) -> None:
        result = _runner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.3.0" in result.output


class TestCLICommands:
    def test_templates(self) -> None:
        result = _runner().invoke(cli, ["templates"])
        assert result.exit_code == 0
        assert "ID" in result.output

    def test_erc_rules(self) -> None:
        result = _runner().invoke(cli, ["erc-rules"])
        assert result.exit_code == 0
        assert "ERC001" in result.output

    def test_parse_missing_file(self) -> None:
        result = _runner().invoke(cli, ["parse", "/nonexistent/file.yaml"])
        assert result.exit_code != 0

    def test_synthesize_success(self) -> None:
        result = _runner().invoke(cli, ["synthesize", "esp32 i2c sensor"])
        assert result.exit_code == 0

    def test_synthesize_failure_shows_error(self) -> None:
        result = _runner().invoke(cli, ["synthesize", "zzz_nonexistent_xyz"])
        assert result.exit_code != 0

    def test_inspect_no_design(self) -> None:
        result = _runner().invoke(cli, ["inspect", "nonexistent"])
        assert result.exit_code != 0

    def test_library_search(self) -> None:
        result = _runner().invoke(cli, ["library", "search", "esp32"])
        assert result.exit_code == 0

    def test_library_search_no_match(self) -> None:
        result = _runner().invoke(cli, ["library", "search", "zzznonexistent"])
        assert result.exit_code == 0
        assert "No matches" in result.output

    def test_library_get_missing(self) -> None:
        result = _runner().invoke(cli, ["library", "get", "nonexistent"])
        assert result.exit_code != 0

    def test_pipeline_no_args(self) -> None:
        result = _runner().invoke(cli, ["pipeline"])
        assert result.exit_code != 0


class TestRequirementsCommand:
    def test_requirements_prints_json(self) -> None:
        result = _runner().invoke(cli, ["requirements", "esp32 usb-c 3.3v i2c"])
        assert result.exit_code == 0
        assert "requirements" in result.output
        assert "constraints" in result.output
        assert "VDD_3V3" in result.output

    def test_requirements_writes_artifacts(self, tmp_path) -> None:
        out = tmp_path / "contract"
        result = _runner().invoke(cli, ["requirements", "rp2040 usb 5v", "--output", str(out)])
        assert result.exit_code == 0
        assert (out / "requirements.json").exists()
        assert (out / "constraints.yaml").exists()
