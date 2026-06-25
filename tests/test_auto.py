"""Tests for pyhunter.auto."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyhunter.auto import (
    BrokenVenv,
    _parse_pyvenv_cfg,
    _pyenv_root,
    brew_remove_old_formulae,
    brew_upgrade_python,
    check_path_shadowing,
    check_shell_config,
    check_pyenv_empty,
    find_broken_venvs,
    find_pyenv_installed_versions,
    pyenv_cleanup,
    pyenv_install_latest,
    repair_broken_venv,
    upgrade_pyenv_itself,
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

    def test_already_up_to_date_skips_upgrade(self):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(cmd)
            if "list" in cmd:
                return MagicMock(stdout="python@3.14 3.14.5\ncurl 8.0\n")
            if "outdated" in cmd:
                return MagicMock(stdout="")  # nothing outdated
            return MagicMock(returncode=0)
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            result = brew_upgrade_python(console, dry_run=False)
        assert result is True
        assert not any("upgrade" in c for c in calls)

    def test_dry_run_does_not_call_upgrade(self):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(cmd)
            if "list" in cmd:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\ncurl 8.0\n")
            if "outdated" in cmd:
                return MagicMock(stdout="python@3.14\n")
            return MagicMock(returncode=0)
        with patch("shutil.which", return_value="/usr/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            result = brew_upgrade_python(console, dry_run=True)
        assert result is True
        assert not any("upgrade" in c for c in calls)

    def test_calls_brew_upgrade_latest_only(self):
        console = _make_console()
        # Has python@3.13 and python@3.14 — should only upgrade python@3.14
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(cmd)
            if "list" in cmd:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\ncurl 8.0\n")
            if "outdated" in cmd:
                return MagicMock(stdout="python@3.14\n")
            return MagicMock(returncode=0)
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            result = brew_upgrade_python(console, dry_run=False)
        assert result is True
        upgrade_call = [c for c in calls if "upgrade" in c]
        assert upgrade_call
        assert "python@3.14" in upgrade_call[0]
        assert "python@3.13" not in upgrade_call[0]  # old formula not upgraded


# ── brew_remove_old_formulae ──────────────────────────────────────────────────

class TestBrewRemoveOldFormulae:
    def _make_side_effect(self, *, dependents: str = "", no_venvs: bool = True):
        """Return a subprocess.run side_effect for remove-old-formulae tests."""
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd)
            if "list" in cmd_str and "versions" in cmd_str:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\ncurl 8.0\n")
            if "uses" in cmd_str and "installed" in cmd_str:
                return MagicMock(stdout=dependents)
            return MagicMock(returncode=0, stdout="")
        return side_effect

    def test_no_old_formulae_reports_clean(self, tmp_path):
        console = _make_console()
        def side_effect(cmd, **kwargs):
            if "list" in " ".join(str(c) for c in cmd):
                return MagicMock(stdout="python@3.14 3.14.5\ncurl 8.0\n")
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            brew_remove_old_formulae([tmp_path], None, console, dry_run=False)

    def test_skips_formula_with_blocker_dependent(self, tmp_path):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            cmd_str = " ".join(str(c) for c in cmd)
            if "list" in cmd_str and "versions" in cmd_str:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\n")
            if "uses" in cmd_str and "installed" in cmd_str:
                return MagicMock(stdout="some-other-formula\n")  # unrelated dependent
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            brew_remove_old_formulae([tmp_path], None, console, dry_run=False)
        assert not any("uninstall" in " ".join(c) for c in calls)

    def test_removes_companion_versioned_formulae(self, tmp_path):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            cmd_str = " ".join(str(c) for c in cmd)
            if "list" in cmd_str and "versions" in cmd_str:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\n")
            if "uses" in cmd_str and "installed" in cmd_str:
                return MagicMock(stdout="python-tk@3.13\n")  # same-version companion
            if "list" in cmd_str and "python-tk@3.14" in cmd_str:
                return MagicMock(returncode=0, stdout="python-tk@3.14\n")  # already installed
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            brew_remove_old_formulae([tmp_path], None, console, dry_run=False)
        uninstall_calls = [c for c in calls if "uninstall" in c]
        assert uninstall_calls
        args = uninstall_calls[0]
        assert "python-tk@3.13" in args
        assert "python@3.13" in args

    def test_installs_new_companion_before_removing_old(self, tmp_path):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            cmd_str = " ".join(str(c) for c in cmd)
            if "list" in cmd_str and "versions" in cmd_str:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\n")
            if "uses" in cmd_str and "installed" in cmd_str:
                return MagicMock(stdout="python-tk@3.13\n")
            if "list" in cmd_str and "python-tk@3.14" in cmd_str:
                return MagicMock(returncode=1, stdout="")  # NOT already installed
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            brew_remove_old_formulae([tmp_path], None, console, dry_run=False)
        install_calls = [c for c in calls if "install" in c and "uninstall" not in c]
        assert any("python-tk@3.14" in c for c in install_calls)
        # install must come before uninstall
        install_idx   = next(i for i, c in enumerate(calls) if "install" in c and "uninstall" not in c)
        uninstall_idx = next(i for i, c in enumerate(calls) if "uninstall" in c)
        assert install_idx < uninstall_idx

    def test_dry_run_does_not_uninstall(self, tmp_path):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            cmd_str = " ".join(str(c) for c in cmd)
            if "list" in cmd_str and "versions" in cmd_str:
                return MagicMock(stdout="python@3.14 3.14.5\npython@3.13 3.13.13\n")
            if "uses" in cmd_str and "installed" in cmd_str:
                return MagicMock(stdout="")
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/brew"), \
             patch("subprocess.run", side_effect=side_effect):
            brew_remove_old_formulae([tmp_path], None, console, dry_run=True)
        assert not any("uninstall" in " ".join(c) for c in calls)


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


# ── pyenv management ──────────────────────────────────────────────────────────

class TestFindPyenvInstalledVersions:
    def test_returns_empty_when_no_versions_dir(self, tmp_path):
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path):
            assert find_pyenv_installed_versions() == []

    def test_finds_python3_binary(self, tmp_path):
        ver_dir = tmp_path / "versions" / "3.11.4" / "bin"
        ver_dir.mkdir(parents=True)
        (ver_dir / "python3").touch()
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path):
            result = find_pyenv_installed_versions()
        assert len(result) == 1
        assert result[0][0] == "3.11.4"

    def test_finds_python_fallback(self, tmp_path):
        ver_dir = tmp_path / "versions" / "3.9.7" / "bin"
        ver_dir.mkdir(parents=True)
        (ver_dir / "python").touch()
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path):
            result = find_pyenv_installed_versions()
        assert result[0][0] == "3.9.7"

    def test_skips_dir_without_python(self, tmp_path):
        (tmp_path / "versions" / "3.10.0" / "bin").mkdir(parents=True)
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path):
            assert find_pyenv_installed_versions() == []


class TestUpgradePyenvItself:
    def test_no_pyenv_returns_false(self):
        console = _make_console()
        with patch("shutil.which", return_value=None):
            assert upgrade_pyenv_itself(console) is False

    def test_brew_already_up_to_date(self):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            if "list" in " ".join(cmd) and "pyenv" in " ".join(cmd):
                return MagicMock(returncode=0)
            if "outdated" in " ".join(cmd):
                return MagicMock(stdout="")  # pyenv not outdated
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/pyenv"), \
             patch("subprocess.run", side_effect=side_effect), \
             patch("pyhunter.auto._pyenv_install_method", return_value="brew"):
            result = upgrade_pyenv_itself(console)
        assert result is True
        assert not any("upgrade" in " ".join(c) for c in calls)

    def test_brew_upgrades_when_outdated(self):
        console = _make_console()
        calls = []
        def side_effect(cmd, **kwargs):
            calls.append(list(cmd))
            if "outdated" in " ".join(cmd):
                return MagicMock(stdout="pyenv\n")
            return MagicMock(returncode=0, stdout="")
        with patch("shutil.which", return_value="/opt/homebrew/bin/pyenv"), \
             patch("subprocess.run", side_effect=side_effect), \
             patch("pyhunter.auto._pyenv_install_method", return_value="brew"):
            upgrade_pyenv_itself(console, dry_run=False)
        assert any("upgrade" in " ".join(c) and "pyenv" in " ".join(c) for c in calls)

    def test_git_dry_run(self, tmp_path):
        console = _make_console()
        (tmp_path / ".git").mkdir()
        with patch("shutil.which", return_value="/usr/local/bin/pyenv"), \
             patch("pyhunter.auto._pyenv_install_method", return_value="git"), \
             patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("pyhunter.auto._run_visible") as mock_run:
            result = upgrade_pyenv_itself(console, dry_run=True)
        assert result is True
        mock_run.assert_not_called()


class TestCheckPyenvEmpty:
    def test_does_nothing_when_versions_exist(self, tmp_path):
        console = _make_console()
        ver_dir = tmp_path / "versions" / "3.14.0" / "bin"
        ver_dir.mkdir(parents=True)
        (ver_dir / "python3").touch()
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("shutil.which", return_value="/usr/bin/pyenv"):
            check_pyenv_empty(console, dry_run=False, auto_remove=True)
        # no exception = pass; nothing removed

    def test_warns_when_empty_no_auto_remove(self, tmp_path):
        console = _make_console()
        (tmp_path / "versions").mkdir()
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("shutil.which", return_value="/usr/bin/pyenv"), \
             patch("pyhunter.auto._pyenv_install_method", return_value="other"):
            check_pyenv_empty(console, dry_run=False, auto_remove=False)

    def test_brew_auto_remove_dry_run(self, tmp_path):
        console = _make_console()
        (tmp_path / "versions").mkdir()
        calls = []
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("shutil.which", side_effect=lambda x: "/opt/homebrew/bin/" + x), \
             patch("pyhunter.auto._pyenv_install_method", return_value="brew"), \
             patch("pyhunter.auto._run_visible", side_effect=lambda cmd, c: calls.append(cmd)):
            check_pyenv_empty(console, dry_run=True, auto_remove=True)
        assert not calls  # dry run: no actual removal

    def test_git_auto_remove(self, tmp_path):
        console = _make_console()
        (tmp_path / "versions").mkdir()
        removed = []
        with patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("shutil.which", return_value="/usr/local/bin/pyenv"), \
             patch("pyhunter.auto._pyenv_install_method", return_value="git"), \
             patch("shutil.rmtree", side_effect=lambda p: removed.append(p)):
            check_pyenv_empty(console, dry_run=False, auto_remove=True)
        assert tmp_path in removed


class TestPyenvCleanup:
    def _make_cycles(self):
        from pyhunter.versions import CycleInfo
        return [
            CycleInfo(cycle="3.14", latest="3.14.6", eol=False),
            CycleInfo(cycle="3.13", latest="3.13.3", eol=False),
            CycleInfo(cycle="3.9",  latest="3.9.21", eol="2025-10-05"),
        ]

    def test_no_pyenv_skips(self, tmp_path):
        console = _make_console()
        with patch("shutil.which", return_value=None):
            pyenv_cleanup([tmp_path], None, self._make_cycles(), console)

    def test_identifies_old_versions(self, tmp_path):
        console = _make_console()
        ver_dir_old = tmp_path / "versions" / "3.9.7" / "bin"
        ver_dir_new = tmp_path / "versions" / "3.14.0" / "bin"
        for d in (ver_dir_old, ver_dir_new):
            d.mkdir(parents=True)
            (d / "python3").touch()
        removed = []
        with patch("shutil.which", return_value="/usr/bin/pyenv"), \
             patch("pyhunter.auto._pyenv_root", return_value=tmp_path), \
             patch("pyhunter.auto.upgrade_pyenv_itself", return_value=True), \
             patch("pyhunter.auto.remove_old_pyenv_version",
                   side_effect=lambda v, *a, **kw: removed.append(v)):
            pyenv_cleanup([tmp_path], None, self._make_cycles(), console, dry_run=True)
        assert "3.9.7" in removed
        assert "3.14.0" not in removed
