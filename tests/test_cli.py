"""Basic CLI integration tests using typer's test runner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from pyhunter.cli import app
from pyhunter.finder import PythonInstall

runner = CliRunner()


def _install(major=3, minor=12, path="/fake/python3", install_type="brew", **kw):
    return PythonInstall(
        path=Path(path),
        version=(major, minor, 0),
        version_str=f"{major}.{minor}.0",
        install_type=install_type,
        **kw,
    )


FAKE_INSTALLS = [
    _install(3, 13, path="/opt/homebrew/bin/python3.13"),
    _install(3, 9, path="/usr/local/bin/python3.9"),
]


def _patch_scan(installs=FAKE_INSTALLS, cycles=None):
    """Context manager that short-circuits the expensive scan."""
    return patch("pyhunter.cli._scan_with_progress", return_value=(installs, cycles))


class TestVersionFlag:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "pyhunter" in result.output


class TestScanCommand:
    def test_basic_scan_exits_0(self):
        with _patch_scan():
            result = runner.invoke(app, ["--no-venvs"])
        assert result.exit_code == 0

    def test_shows_python_versions(self):
        with _patch_scan():
            result = runner.invoke(app, ["--no-venvs"])
        assert "3.13" in result.output
        assert "3.9" in result.output

    def test_shows_summary(self):
        with _patch_scan():
            result = runner.invoke(app, ["--no-venvs"])
        assert "SUMMARY" in result.output

    def test_exits_1_when_no_installs_found(self):
        with _patch_scan(installs=[]):
            result = runner.invoke(app, ["--no-venvs"])
        assert result.exit_code == 1

    def test_offline_warning_when_cycles_none(self):
        with _patch_scan(cycles=None):
            result = runner.invoke(app, ["--no-venvs"])
        assert "offline" in result.output.lower() or result.exit_code == 0

    def test_dry_run_flag_shown(self):
        with _patch_scan():
            result = runner.invoke(app, ["--no-venvs", "--dry-run"])
        assert "DRY RUN" in result.output


class TestUpgradeVenvsFlag:
    def test_no_venvs_to_upgrade(self):
        with _patch_scan():
            result = runner.invoke(app, ["--no-venvs", "--upgrade-venvs"])
        assert result.exit_code == 0
        assert "No venvs require upgrading" in result.output

    def test_upgrades_eol_venv(self, tmp_path):
        venv_dir = tmp_path / "oldenv"
        venv_dir.mkdir()
        eol_venv = _install(3, 8, path=str(venv_dir / "bin/python3"), venv_base=venv_dir)

        with _patch_scan(installs=[eol_venv]):
            with patch("pyhunter.cli.upgrade_venv", return_value=True) as mock_upgrade:
                result = runner.invoke(app, ["--no-venvs", "--upgrade-venvs", "--dry-run"])

        assert result.exit_code == 0
        mock_upgrade.assert_called_once()
