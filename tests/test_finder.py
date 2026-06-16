"""Tests for pyhunter.finder."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyhunter.finder import (
    EOL_VERSIONS,
    SECURITY_VERSIONS,
    PythonInstall,
    _classify_path,
    get_version,
    scan_venvs,
)


# ---------------------------------------------------------------------------
# PythonInstall.status
# ---------------------------------------------------------------------------

def _make_install(major: int, minor: int, patch_: int = 0, **kwargs) -> PythonInstall:
    return PythonInstall(
        path=Path("/fake/python3"),
        version=(major, minor, patch_),
        version_str=f"{major}.{minor}.{patch_}",
        install_type="system",
        **kwargs,
    )


class TestPythonInstallStatus:
    def test_python2_is_eol(self):
        assert _make_install(2, 7).status == "eol"

    def test_python3_old_is_eol(self):
        for minor in range(0, 10):  # 3.0–3.9
            assert _make_install(3, minor).status == "eol", f"3.{minor} should be EOL"

    def test_python310_is_security(self):
        assert _make_install(3, 10).status == "security"

    def test_python311_is_supported(self):
        assert _make_install(3, 11).status == "supported"

    def test_python312_is_supported(self):
        assert _make_install(3, 12).status == "supported"

    def test_python313_is_supported(self):
        assert _make_install(3, 13).status == "supported"


class TestRecommendation:
    def test_eol_system_recommends_delete(self):
        inst = _make_install(3, 8)
        assert inst.recommendation == "DELETE"

    def test_eol_venv_recommends_upgrade(self):
        inst = _make_install(3, 8, venv_base=Path("/some/venv"))
        assert inst.recommendation == "UPGRADE VENV"

    def test_security_venv_recommends_upgrade(self):
        inst = _make_install(3, 10, venv_base=Path("/some/venv"))
        assert inst.recommendation == "UPGRADE VENV"

    def test_supported_recommends_keep(self):
        inst = _make_install(3, 12)
        assert inst.recommendation == "KEEP"


class TestIsVenv:
    def test_no_venv_base(self):
        assert not _make_install(3, 12).is_venv

    def test_with_venv_base(self):
        assert _make_install(3, 12, venv_base=Path("/some/venv")).is_venv


# ---------------------------------------------------------------------------
# _classify_path
# ---------------------------------------------------------------------------

class TestClassifyPath:
    def test_pyenv(self):
        assert _classify_path(Path("/home/user/.pyenv/versions/3.11.0/bin/python3")) == "pyenv"

    def test_brew_homebrew(self):
        assert _classify_path(Path("/opt/homebrew/bin/python3")) == "brew"

    def test_brew_cellar(self):
        assert _classify_path(Path("/usr/local/Cellar/python@3.12/3.12.0/bin/python3")) == "brew"

    def test_system(self):
        assert _classify_path(Path("/usr/bin/python3")) == "system"

    def test_conda(self):
        assert _classify_path(Path("/home/user/miniconda3/envs/myenv/bin/python")) == "conda"

    def test_unknown(self):
        assert _classify_path(Path("/home/user/tools/python3")) == "unknown"


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

class TestGetVersion:
    def test_valid_version_output(self):
        with patch("pyhunter.finder._run", return_value="Python 3.11.4"):
            result = get_version(Path("/usr/bin/python3"))
        assert result == ((3, 11, 4), "3.11.4")

    def test_none_when_no_output(self):
        with patch("pyhunter.finder._run", return_value=None):
            result = get_version(Path("/usr/bin/python3"))
        assert result is None

    def test_none_when_unparseable(self):
        with patch("pyhunter.finder._run", return_value="not a version string"):
            result = get_version(Path("/usr/bin/python3"))
        assert result is None

    def test_version_from_stderr_style(self):
        with patch("pyhunter.finder._run", return_value="Python 2.7.18"):
            result = get_version(Path("/usr/bin/python"))
        assert result == ((2, 7, 18), "2.7.18")


# ---------------------------------------------------------------------------
# scan_venvs
# ---------------------------------------------------------------------------

class TestScanVenvs:
    def test_finds_venv(self, tmp_path):
        # Create a fake venv structure
        venv_dir = tmp_path / "myenv"
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir(parents=True)
        (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.11.4\n")
        py = bin_dir / "python3"
        py.write_text("#!/bin/sh\nexec python3 $@\n")
        py.chmod(0o755)

        results = scan_venvs([tmp_path])
        paths = [r[1] for r in results]
        assert venv_dir.resolve() in paths

    def test_ignores_non_venv_dirs(self, tmp_path):
        (tmp_path / "regular_dir").mkdir()
        results = scan_venvs([tmp_path])
        assert results == []

    def test_respects_max_depth(self, tmp_path):
        # Create a venv 3 levels deep
        deep = tmp_path / "a" / "b" / "c" / "venv"
        (deep / "bin").mkdir(parents=True)
        (deep / "pyvenv.cfg").write_text("home = /usr/bin\n")
        py = deep / "bin" / "python3"
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)

        # max_depth=2 should NOT find it (3 levels deep)
        results = scan_venvs([tmp_path], max_depth=2)
        assert results == []

        # max_depth=4 should find it
        results = scan_venvs([tmp_path], max_depth=4)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# EOL / security sets sanity check
# ---------------------------------------------------------------------------

class TestVersionSets:
    def test_python39_in_eol(self):
        assert (3, 9) in EOL_VERSIONS

    def test_python310_in_security(self):
        assert (3, 10) in SECURITY_VERSIONS

    def test_python311_not_in_eol_or_security(self):
        assert (3, 11) not in EOL_VERSIONS
        assert (3, 11) not in SECURITY_VERSIONS
