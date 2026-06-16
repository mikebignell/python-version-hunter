"""Tests for pyhunter.actions."""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from rich.console import Console

from pyhunter.actions import (
    advise_os_managed_python,
    delete_python,
    suggest_brew_upgrade,
    suggest_pyenv_upgrade,
    upgrade_venv,
    _pip_in_venv,
)
from pyhunter.finder import PythonInstall


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, highlight=False, no_color=True), buf


def _install(major=3, minor=9, path="/fake/python3", install_type="brew", **kwargs):
    return PythonInstall(
        path=Path(path),
        version=(major, minor, 0),
        version_str=f"{major}.{minor}.0",
        install_type=install_type,
        **kwargs,
    )


# ── _pip_in_venv ────────────────────────────────────────────────────────────

class TestPipInVenv:
    def test_unix_path(self):
        with patch.object(sys, "platform", "linux"):
            pip = _pip_in_venv(Path("/some/venv"))
        assert pip == Path("/some/venv/bin/pip")

    def test_windows_path(self):
        with patch.object(sys, "platform", "win32"):
            pip = _pip_in_venv(Path("C:/some/venv"))
        assert pip == Path("C:/some/venv/Scripts/pip.exe")


# ── upgrade_venv ─────────────────────────────────────────────────────────────

class TestUpgradeVenv:
    def test_refuses_non_venv(self):
        console, buf = _console()
        inst = _install()
        result = upgrade_venv(inst, None, console)
        assert result is False
        assert "Not a venv" in buf.getvalue()

    def test_dry_run_returns_true(self):
        console, buf = _console()
        inst = _install(venv_base=Path("/some/venv"))
        with patch("pyhunter.actions.get_pip_packages", return_value=[]):
            result = upgrade_venv(inst, None, console, dry_run=True)
        assert result is True
        assert "DRY RUN" in buf.getvalue()

    def test_dry_run_shows_package_count(self):
        console, buf = _console()
        inst = _install(venv_base=Path("/some/venv"))
        with patch("pyhunter.actions.get_pip_packages", return_value=["requests==2.31", "click==8.1"]):
            upgrade_venv(inst, None, console, dry_run=True)
        assert "2 package" in buf.getvalue()

    def test_upgrade_creates_new_venv(self, tmp_path):
        venv_dir = tmp_path / "myenv"
        venv_dir.mkdir()
        (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n")

        inst = _install(venv_base=venv_dir)
        console, buf = _console()

        with patch("pyhunter.actions.get_pip_packages", return_value=[]):
            with patch("pyhunter.actions._run_visible", return_value=True) as mock_run:
                result = upgrade_venv(inst, Path("/usr/bin/python3"), console)

        assert result is True
        run_calls = [str(c) for c in mock_run.call_args_list]
        # Should have called python -m venv
        assert any("venv" in c for c in run_calls)

    def test_uses_current_python_when_no_target(self, tmp_path):
        venv_dir = tmp_path / "myenv"
        venv_dir.mkdir()

        inst = _install(venv_base=venv_dir)
        console, _ = _console()

        with patch("pyhunter.actions.get_pip_packages", return_value=[]):
            with patch("pyhunter.actions._run_visible", return_value=True) as mock_run:
                upgrade_venv(inst, None, console)

        first_call_cmd = mock_run.call_args_list[0][0][0]
        assert first_call_cmd[0] == sys.executable


# ── delete_python ─────────────────────────────────────────────────────────────

class TestDeletePython:
    def test_refuses_current_python(self):
        console, buf = _console()
        inst = _install(path=sys.executable, is_current=True)
        result = delete_python(inst, console)
        assert result is False
        assert "currently running" in buf.getvalue()

    def test_refuses_os_managed(self):
        console, buf = _console()
        inst = _install(path="/usr/bin/python3")
        with patch("pyhunter.finder.sys.platform", "darwin"):
            result = delete_python(inst, console)
        assert result is False

    def test_dry_run_returns_true(self):
        console, buf = _console()
        inst = _install(path="/opt/homebrew/bin/python3.9")
        result = delete_python(inst, console, dry_run=True)
        assert result is True
        assert "DRY RUN" in buf.getvalue()

    def test_deletes_file_on_confirm(self, tmp_path):
        py = tmp_path / "python3"
        py.write_text("#!/bin/sh\n")

        inst = _install(path=str(py))
        console, buf = _console()

        with patch("pyhunter.actions.Confirm.ask", return_value=True):
            result = delete_python(inst, console)

        assert result is True
        assert not py.exists()

    def test_skips_on_deny(self, tmp_path):
        py = tmp_path / "python3"
        py.write_text("#!/bin/sh\n")

        inst = _install(path=str(py))
        console, buf = _console()

        with patch("pyhunter.actions.Confirm.ask", return_value=False):
            result = delete_python(inst, console)

        assert result is False
        assert py.exists()

    def test_handles_permission_error(self, tmp_path):
        py = tmp_path / "python3"
        py.write_text("#!/bin/sh\n")

        inst = _install(path=str(py))
        console, buf = _console()

        with patch("pyhunter.actions.Confirm.ask", return_value=True):
            with patch.object(Path, "unlink", side_effect=PermissionError):
                result = delete_python(inst, console)

        assert result is False
        assert "Permission denied" in buf.getvalue()


# ── advise_os_managed_python ──────────────────────────────────────────────────

class TestAdviseOsManagedPython:
    def test_macos_advice_mentions_softwareupdate(self):
        console, buf = _console()
        inst = _install(path="/usr/bin/python3")
        with patch.object(sys, "platform", "darwin"):
            advise_os_managed_python(inst, console)
        assert "softwareupdate" in buf.getvalue()

    def test_linux_advice_mentions_apt(self):
        console, buf = _console()
        inst = _install(path="/usr/bin/python3")
        with patch.object(sys, "platform", "linux"):
            advise_os_managed_python(inst, console)
        assert "apt" in buf.getvalue()

    def test_windows_advice_mentions_winget(self):
        console, buf = _console()
        inst = _install(path="C:/Windows/system32/python.exe")
        with patch.object(sys, "platform", "win32"):
            advise_os_managed_python(inst, console)
        assert "winget" in buf.getvalue()


# ── suggest_* ────────────────────────────────────────────────────────────────

class TestSuggestUpgrade:
    def test_pyenv_unix_mentions_install(self):
        console, buf = _console()
        with patch.object(sys, "platform", "linux"):
            suggest_pyenv_upgrade(_install(), console)
        assert "pyenv install" in buf.getvalue()

    def test_pyenv_windows_mentions_update(self):
        console, buf = _console()
        with patch.object(sys, "platform", "win32"):
            suggest_pyenv_upgrade(_install(), console)
        assert "pyenv" in buf.getvalue()

    def test_brew_mentions_upgrade(self):
        console, buf = _console()
        suggest_brew_upgrade(_install(), console)
        assert "brew upgrade" in buf.getvalue()
