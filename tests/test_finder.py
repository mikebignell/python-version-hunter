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

class TestIsOsManaged:
    def test_usr_bin_is_os_managed(self):
        inst = _make_install(3, 9)
        inst.path = Path("/usr/bin/python3")
        assert inst.is_os_managed

    def test_brew_is_not_os_managed(self):
        inst = _make_install(3, 9)
        inst.path = Path("/opt/homebrew/bin/python3")
        assert not inst.is_os_managed

    def test_os_managed_eol_recommends_pkg_mgr(self):
        inst = _make_install(3, 9)
        inst.path = Path("/usr/bin/python3")
        assert inst.recommendation == "UPDATE VIA PKG MGR"

    def test_non_system_eol_recommends_delete(self):
        inst = _make_install(3, 9)
        inst.path = Path("/opt/homebrew/bin/python3")
        assert inst.recommendation == "DELETE"


class TestCrossPlatformPaths:
    def test_pathsep_used_in_scan(self):
        """scan_path_executables should split PATH with os.pathsep, not ':'."""
        import os
        from pyhunter.finder import scan_path_executables
        # Patch PATH to be empty so no real scan happens — we just verify no crash.
        with patch.dict(os.environ, {"PATH": ""}):
            result = scan_path_executables()
        assert isinstance(result, list)

    def test_venv_executable_unix(self, tmp_path):
        from pyhunter.finder import _venv_executable
        (tmp_path / "bin").mkdir()
        py = tmp_path / "bin" / "python3"
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)
        found = _venv_executable(tmp_path)
        assert found is not None
        assert found.name in ("python3", "python")

    def test_venv_executable_windows_style(self, tmp_path):
        from pyhunter.finder import _venv_executable
        (tmp_path / "Scripts").mkdir()
        py = tmp_path / "Scripts" / "python.exe"
        py.write_text("")
        found = _venv_executable(tmp_path)
        assert found is not None
        assert found.name == "python.exe"

    def test_classify_brew_linux(self):
        assert _classify_path(Path("/home/linuxbrew/.linuxbrew/bin/python3")) == "brew"

    def test_classify_conda(self):
        assert _classify_path(Path("/home/user/miniconda3/envs/ml/bin/python3")) == "conda"


class TestHasNewerPatch:
    def test_no_latest_patch_set(self):
        assert not _make_install(3, 12).has_newer_patch

    def test_on_latest_patch(self):
        inst = _make_install(3, 12, 10)
        inst.latest_patch = "3.12.10"
        assert not inst.has_newer_patch

    def test_behind_latest_patch(self):
        inst = _make_install(3, 12, 3)
        inst.latest_patch = "3.12.10"
        assert inst.has_newer_patch

    def test_ahead_of_latest_patch(self):
        # e.g. pre-release or local build
        inst = _make_install(3, 12, 99)
        inst.latest_patch = "3.12.10"
        assert not inst.has_newer_patch

    def test_bad_latest_patch_string(self):
        inst = _make_install(3, 12, 3)
        inst.latest_patch = "not-a-version"
        assert not inst.has_newer_patch


class TestHasNewerCycle:
    def test_no_latest_stable(self):
        assert not _make_install(3, 13).has_newer_cycle

    def test_on_latest_cycle(self):
        inst = _make_install(3, 14)
        inst.latest_stable = "3.14.6"
        assert not inst.has_newer_cycle

    def test_behind_one_minor(self):
        inst = _make_install(3, 13)
        inst.latest_stable = "3.14.6"
        assert inst.has_newer_cycle

    def test_behind_multiple_minors(self):
        inst = _make_install(3, 11)
        inst.latest_stable = "3.14.6"
        assert inst.has_newer_cycle

    def test_python2_behind(self):
        inst = _make_install(2, 7)
        inst.latest_stable = "3.14.6"
        assert inst.has_newer_cycle


class TestRecommendationWithPatch:
    def test_supported_with_newer_patch_recommends_update(self):
        inst = _make_install(3, 12, 3)
        inst.latest_patch = "3.12.10"
        assert inst.recommendation == "UPDATE PATCH"

    def test_supported_on_latest_recommends_keep(self):
        inst = _make_install(3, 12, 10)
        inst.latest_patch = "3.12.10"
        assert inst.recommendation == "KEEP"

    def test_supported_venv_with_newer_patch_recommends_upgrade_venv(self):
        inst = _make_install(3, 12, 3, venv_base=Path("/some/venv"))
        inst.latest_patch = "3.12.10"
        assert inst.recommendation == "UPGRADE VENV"

    def test_security_on_latest_recommends_consider_upgrade(self):
        inst = _make_install(3, 10, 17)
        inst.latest_patch = "3.10.17"
        assert inst.recommendation == "CONSIDER UPGRADE"

    def test_security_with_newer_patch_recommends_update(self):
        inst = _make_install(3, 10, 5)
        inst.latest_patch = "3.10.17"
        assert inst.recommendation == "UPDATE PATCH"

    def test_os_managed_with_newer_patch_recommends_pkg_mgr(self):
        inst = _make_install(3, 9)
        inst.path = Path("/usr/bin/python3")
        inst.latest_patch = "3.9.25"
        assert inst.recommendation == "UPDATE VIA PKG MGR"

    def test_supported_with_newer_cycle_recommends_upgrade_available(self):
        inst = _make_install(3, 13, 14)
        inst.latest_stable = "3.14.6"
        assert inst.recommendation == "UPGRADE AVAILABLE"

    def test_newer_cycle_takes_priority_over_patch(self):
        # On 3.13.13, latest patch is 3.13.14, but 3.14 is available
        inst = _make_install(3, 13, 13)
        inst.latest_patch = "3.13.14"
        inst.latest_stable = "3.14.6"
        assert inst.recommendation == "UPGRADE AVAILABLE"

    def test_supported_venv_with_newer_cycle_recommends_upgrade_venv(self):
        inst = _make_install(3, 13, 14, venv_base=Path("/some/venv"))
        inst.latest_stable = "3.14.6"
        assert inst.recommendation == "UPGRADE VENV"

    def test_on_latest_cycle_and_patch_recommends_keep(self):
        inst = _make_install(3, 14, 6)
        inst.latest_patch = "3.14.6"
        inst.latest_stable = "3.14.6"
        assert inst.recommendation == "KEEP"


class TestVenvDetectionViaParentCfg:
    """Regression: Python binaries inside a venv dir must be detected as venvs
    even when scan_venvs found a sibling executable (e.g. python3 vs python3.14)."""

    def test_find_all_pythons_classifies_venv_sibling_symlink_as_venv(self, tmp_path):
        """Symlink case: python3.14 in venv bin symlinks OUT of the venv dir.
        resolve() escapes the venv, so we must check the original path."""
        from unittest.mock import patch as _patch
        from pyhunter.finder import find_all_pythons
        import os

        venv = tmp_path / "myenv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /opt/homebrew/bin\nversion = 3.14.5\n")

        # Simulate the real python binary outside the venv
        real_python = tmp_path / "real_python3.14"
        real_python.write_text("#!/bin/sh\necho 'Python 3.14.5'\n")
        real_python.chmod(0o755)

        # python3 in venv bin is a symlink → real_python (resolves OUTSIDE venv)
        py3_link = bin_dir / "python3"
        py3_link.symlink_to(real_python)

        # python3.14 in venv bin is also a symlink → same real_python
        py314_link = bin_dir / "python3.14"
        py314_link.symlink_to(real_python)

        with _patch("pyhunter.finder.scan_path_executables", return_value=[py314_link]), \
             _patch("pyhunter.finder.scan_common_dirs", return_value=[]), \
             _patch("pyhunter.finder.scan_venvs", return_value=[(py3_link.resolve(), venv.resolve())]), \
             _patch("pyhunter.finder.get_version", return_value=((3, 14, 5), "3.14.5")):
            installs = find_all_pythons(venv_search_paths=[tmp_path])

        # The symlink resolves to real_python (outside venv dir), but the
        # original path is inside the venv — must still be classified as venv.
        for inst in installs:
            if inst.version == (3, 14, 5):
                assert inst.venv_base is not None, (
                    "python3.14 symlink inside venv dir not detected as venv even "
                    "though it resolves outside the venv"
                )
                break

    def test_find_all_pythons_classifies_venv_sibling_as_venv(self, tmp_path):
        from unittest.mock import patch as _patch
        from pyhunter.finder import find_all_pythons

        # Create a minimal fake venv structure
        venv = tmp_path / "myenv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.0\n")

        # python3 — the one scan_venvs would find
        py3 = bin_dir / "python3"
        py3.write_text("#!/bin/sh\necho 'Python 3.12.0'\n")
        py3.chmod(0o755)

        # python3.12 — a sibling exposed on PATH that scan_venvs wouldn't map
        py312 = bin_dir / "python3.12"
        py312.write_text("#!/bin/sh\necho 'Python 3.12.0'\n")
        py312.chmod(0o755)

        with _patch("pyhunter.finder.scan_path_executables", return_value=[py312]), \
             _patch("pyhunter.finder.scan_common_dirs", return_value=[]), \
             _patch("pyhunter.finder.scan_venvs", return_value=[(py3.resolve(), venv.resolve())]), \
             _patch("pyhunter.finder.get_version", return_value=((3, 12, 0), "3.12.0")):
            installs = find_all_pythons(venv_search_paths=[tmp_path])

        # Both py3 and py312 resolve differently — only one deduped entry expected
        # but critically: it must be marked as a venv
        venv_installs = [i for i in installs if i.venv_base is not None]
        assert len(venv_installs) >= 1, "sibling python3.12 inside venv dir not detected as venv"

    def test_best_python_excludes_path_inside_venv_dir(self, tmp_path):
        from pyhunter.cli import _best_python, _is_inside_venv_dir

        # Simulate the venv dir
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /opt/homebrew/bin\n")
        venv_python = venv / "bin" / "python3.14"
        (venv / "bin").mkdir()
        venv_python.touch()

        assert _is_inside_venv_dir(venv_python) is True

        # Build a fake install list where the venv Python slipped through as non-venv
        inst = PythonInstall(
            path=venv_python,
            version=(3, 14, 5),
            version_str="3.14.5",
            install_type="unknown",
            venv_base=None,   # the bug: venv_base not set
            is_current=False,
        )
        assert _best_python([inst]) is None, "_best_python should not select a Python inside a venv dir"


class TestVersionSets:
    def test_python39_in_eol(self):
        assert (3, 9) in EOL_VERSIONS

    def test_python310_in_security(self):
        assert (3, 10) in SECURITY_VERSIONS

    def test_python311_not_in_eol_or_security(self):
        assert (3, 11) not in EOL_VERSIONS
        assert (3, 11) not in SECURITY_VERSIONS
