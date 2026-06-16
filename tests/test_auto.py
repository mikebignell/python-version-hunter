"""Tests for pyhunter.auto."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyhunter.auto import (
    BrokenVenv,
    _parse_pyvenv_cfg,
    brew_upgrade_python,
    check_path_shadowing,
    check_shell_config,
    find_broken_venvs,
    pyenv_install_latest,
    repair_broken_venv,
)
from pyhunter.finder import PythonInstall


def _make_console():
    from rich.console import Console
    return Console(quiet=True)


# ── _parse_pyvenv_cfg ────────────────────────────────────────────────────────

class TestParsePyvenvCfg:
    def test_parses_home_and_version(self, tmp_path):
        cfg = tmp_path / "pyvenv.cfg"
        cfg.write_text("home = /usr/bin\nversion = 3.11.4\n")
        data = _parse_pyvenv_cfg(cfg)
        assert data["home"] == "/usr/bin"
        assert data["version"] == "3.11.4"

    def test_handles_missing_file(self, tmp_path):
        data = _parse_pyvenv_cfg(tmp_path / "nonexistent.cfg")
        assert data == {}

    def test_handles_malformed_lines(self, tmp_path):
        cfg = tmp_path / "pyvenv.cfg"
        cfg.write_text("not_a_kv_line\nhome = /usr/bin\n")
        data = _parse_pyvenv_cfg(cfg)
        assert data["home"] == "/usr/bin"


# ── find_broken_venvs ────────────────────────────────────────────────────────

class TestFindBrokenVenvs:
    def test_finds_broken_venv(self, tmp_path):
        venv = tmp_path / "myvenv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /nonexistent/path/that/does/not/exist\nversion = 3.9.0\n"
        )
        result = find_broken_venvs([tmp_path])
        assert len(result) == 1
        assert result[0].venv_base == venv.resolve()
        assert result[0].python_version == "3.9.0"

    def test_skips_healthy_venv(self, tmp_path):
        venv = tmp_path / "goodvenv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            f"home = {tmp_path}\nversion = 3.12.0\n"
        )
        result = find_broken_venvs([tmp_path])
        assert result == []

    def test_skips_no_pyvenv_cfg(self, tmp_path):
        (tmp_path / "notavenv").mkdir()
        result = find_broken_venvs([tmp_path])
        assert result == []

    def test_skips_missing_home_key(self, tmp_path):
        venv = tmp_path / "novenv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version = 3.11.0\n")
        result = find_broken_venvs([tmp_path])
        assert result == []

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "deep_venv"
        deep.mkdir(parents=True)
        (deep / "pyvenv.cfg").write_text("home = /gone\n")
        assert find_broken_venvs([tmp_path], max_depth=2) == []
        assert len(find_broken_venvs([tmp_path], max_depth=5)) == 1


# ── check_path_shadowing ─────────────────────────────────────────────────────

class TestCheckPathShadowing:
    def test_homebrew_apple_silicon_ok(self):
        console = _make_console()
        with patch("shutil.which", return_value="/opt/homebrew/bin/python3"):
            result = check_path_shadowing(console)
        assert result is True

    def test_homebrew_intel_ok(self):
        console = _make_console()
        with patch("shutil.which", return_value="/usr/local/bin/python3"):
            result = check_path_shadowing(console)
        assert result is True

    def test_linuxbrew_ok(self):
        console = _make_console()
        with patch("shutil.which", return_value="/home/linuxbrew/.linuxbrew/bin/python3"):
            result = check_path_shadowing(console)
        assert result is True

    def test_system_python_not_ok(self):
        console = _make_console()
        with patch("shutil.which", return_value="/usr/bin/python3"):
            result = check_path_shadowing(console)
        assert result is False

    def test_not_found_not_ok(self):
        console = _make_console()
        with patch("shutil.which", return_value=None):
            result = check_path_shadowing(console)
        assert result is False


# ── brew_upgrade_python ───────────────────────────────────────────────────────

class TestBrewUpgradePython:
    def test_no_brew_returns_false(self):
        console = _make_console()
        with patch("shutil.which", return_value=None):
            assert brew_upgrade_python(console) is False

    def test_no_python_formulae(self):
        console = _make_console()
        mock_result = MagicMock()
        mock_result.stdout = "curl 8.0\ngit 2.40\nnode 20.0\n"
        with patch("shutil.which", return_value="/usr/bin/brew"), \
             patch("subprocess.run", return_value=mock_result):
            assert brew_upgrade_python(console) is False

    def test_dry_run_does_not_call_upgrade(self):
        console = _make_console()
        # brew list --formula --versions output format
        mock_list = MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\ncurl 8.0\n")
        with patch("shutil.which", return_value="/usr/bin/brew"), \
             patch("subprocess.run", return_value=mock_list) as mock_run:
            result = brew_upgrade_python(console, dry_run=True)
        assert result is True
        # Only the brew list call, not brew upgrade
        assert mock_run.call_count == 1

    def test_calls_brew_upgrade_latest_only(self):
        console = _make_console()
        # Has python@3.13 and python@3.14 — should only upgrade python@3.14
        mock_list = MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\ncurl 8.0\n")
        mock_upgrade = MagicMock(returncode=0)
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(cmd)
            if "list" in cmd:
                return mock_list
            return mock_upgrade
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            result = brew_upgrade_python(console, dry_run=False)
        assert result is True
        upgrade_call = [c for c in calls if "upgrade" in c]
        assert upgrade_call
        assert "python@3.14" in upgrade_call[0]
        assert "python@3.13" not in upgrade_call[0]  # old formula not upgraded


# ── pyenv_install_latest ──────────────────────────────────────────────────────

class TestPyenvInstallLatest:
    def test_no_pyenv_returns_false(self):
        console = _make_console()
        with patch("shutil.which", return_value=None):
            assert pyenv_install_latest("3.14.6", console) is False

    def test_dry_run_returns_true_without_running(self):
        console = _make_console()
        with patch("shutil.which", return_value="/usr/bin/pyenv"), \
             patch("subprocess.run") as mock_run:
            result = pyenv_install_latest("3.14.6", console, dry_run=True)
        assert result is True
        mock_run.assert_not_called()


# ── repair_broken_venv ────────────────────────────────────────────────────────

class TestRepairBrokenVenv:
    def test_dry_run(self, tmp_path):
        console = _make_console()
        broken = BrokenVenv(
            venv_base=tmp_path / "myvenv",
            missing_home=Path("/gone/python3/bin"),
            python_version="3.9.0",
        )
        result = repair_broken_venv(broken, None, console, dry_run=True)
        assert result is True
        assert not (tmp_path / "myvenv").exists()  # not actually created

    def test_recreates_venv(self, tmp_path):
        console = _make_console()
        venv_dir = tmp_path / "myvenv"
        venv_dir.mkdir()
        broken = BrokenVenv(
            venv_base=venv_dir,
            missing_home=Path("/gone/python3/bin"),
            python_version="3.9.0",
        )
        with patch("pyhunter.auto._run_visible", return_value=True) as mock_run:
            repair_broken_venv(broken, Path(sys.executable), console, dry_run=False)
        # Should have called venv creation
        venv_call = [c for c in [call[0][0] for call in mock_run.call_args_list]
                     if "-m" in c and "venv" in c]
        assert venv_call
