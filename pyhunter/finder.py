"""Core Python installation discovery logic."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# As of June 2026:
#   3.9  → EOL (Oct 2025)
#   3.10 → security-only (EOL Oct 2026)
#   3.11+ → fully supported
EOL_VERSIONS: set[tuple[int, int]] = {(2, x) for x in range(10)} | {
    (3, x) for x in range(10)  # 3.0–3.9
}
SECURITY_VERSIONS: set[tuple[int, int]] = {(3, 10)}


@dataclass
class PythonInstall:
    path: Path
    version: tuple[int, int, int]
    version_str: str
    install_type: str  # system | brew | pyenv | conda | venv | unknown
    venv_base: Optional[Path] = None
    is_current: bool = False

    @property
    def major_minor(self) -> tuple[int, int]:
        return (self.version[0], self.version[1])

    @property
    def is_venv(self) -> bool:
        return self.venv_base is not None

    @property
    def is_python2(self) -> bool:
        return self.version[0] == 2

    @property
    def status(self) -> str:
        mm = self.major_minor
        if mm in EOL_VERSIONS:
            return "eol"
        if mm in SECURITY_VERSIONS:
            return "security"
        return "supported"

    @property
    def status_label(self) -> str:
        if self.is_python2:
            return "☠ DEAD"
        return {"eol": "■ EOL", "security": "◆ SECURITY", "supported": "● OK"}[self.status]

    @property
    def status_color(self) -> str:
        return {
            "eol": "bright_red",
            "security": "bright_yellow",
            "supported": "bright_green",
        }[self.status]

    @property
    def is_os_managed(self) -> bool:
        """True for system Pythons that are owned by the OS and cannot/should not be deleted."""
        import sys as _sys
        s = str(self.path)
        if _sys.platform == "darwin":
            # SIP-protected paths and Apple CLT / Xcode installs
            return s.startswith("/usr/bin/") or "/Developer/CommandLineTools" in s
        return s.startswith("/usr/bin/")

    @property
    def recommendation(self) -> str:
        if self.is_os_managed:
            if self.status in ("eol", "security"):
                return "UPDATE VIA CLT"
            return "KEEP"
        if self.status == "eol":
            return "UPGRADE VENV" if self.is_venv else "DELETE"
        if self.status == "security":
            return "UPGRADE VENV" if self.is_venv else "CONSIDER UPGRADE"
        return "KEEP"

    @property
    def recommendation_color(self) -> str:
        return {
            "UPDATE VIA CLT": "bright_cyan",
            "UPGRADE VENV": "bright_yellow",
            "DELETE": "bright_red",
            "CONSIDER UPGRADE": "yellow",
            "KEEP": "bright_green",
        }[self.recommendation]


def _run(cmd: list[str], timeout: int = 5) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout + result.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
        return None


def get_version(python_path: Path) -> Optional[tuple[tuple[int, int, int], str]]:
    output = _run([str(python_path), "--version"])
    if not output:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return None
    version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return version, f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def _classify_path(path: Path) -> str:
    s = str(path)
    if ".pyenv" in s:
        return "pyenv"
    if any(k in s for k in ("miniconda", "anaconda", "conda", "mamba", "miniforge")):
        return "conda"
    if "/opt/homebrew" in s or "/usr/local/Cellar" in s or "/usr/local/opt" in s:
        return "brew"
    if "/Library/Frameworks/Python.framework" in s:
        return "python.org"
    if s.startswith("/usr/bin") or s.startswith("/usr/local/bin"):
        return "system"
    return "unknown"


def scan_path_executables() -> list[Path]:
    found: set[Path] = set()
    pattern = re.compile(r"^python(\d+(\.\d+)*)?$")
    for dir_str in os.environ.get("PATH", "").split(":"):
        dir_path = Path(dir_str)
        if not dir_path.is_dir():
            continue
        try:
            for entry in dir_path.iterdir():
                if pattern.match(entry.name) and (entry.is_file() or entry.is_symlink()):
                    try:
                        found.add(entry.resolve())
                    except (OSError, RuntimeError):
                        found.add(entry)
        except PermissionError:
            continue
    return list(found)


def scan_common_dirs() -> list[Path]:
    found: set[Path] = set()
    pattern = re.compile(r"^python(\d+(\.\d+)*)?$")

    def _scan_dir(d: Path) -> None:
        if not d.is_dir():
            return
        try:
            for entry in d.iterdir():
                if pattern.match(entry.name) and (entry.is_file() or entry.is_symlink()):
                    try:
                        found.add(entry.resolve())
                    except (OSError, RuntimeError):
                        found.add(entry)
        except PermissionError:
            pass

    for d in [Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin")]:
        _scan_dir(d)

    # python.org framework installs
    fw = Path("/Library/Frameworks/Python.framework/Versions")
    if fw.is_dir():
        try:
            for vdir in fw.iterdir():
                py = vdir / "bin" / "python3"
                if py.exists():
                    try:
                        found.add(py.resolve())
                    except (OSError, RuntimeError):
                        found.add(py)
        except PermissionError:
            pass

    # pyenv
    pyenv_versions = Path.home() / ".pyenv" / "versions"
    if pyenv_versions.is_dir():
        try:
            for vdir in pyenv_versions.iterdir():
                for py_name in ("python3", "python"):
                    py = vdir / "bin" / py_name
                    if py.is_file():
                        try:
                            found.add(py.resolve())
                        except (OSError, RuntimeError):
                            found.add(py)
                        break
        except PermissionError:
            pass

    # conda / mamba envs
    for base_name in ("miniconda3", "miniconda", "anaconda3", "anaconda", "miniforge3", "mambaforge"):
        base = Path.home() / base_name
        envs = base / "envs"
        if envs.is_dir():
            try:
                for env_dir in envs.iterdir():
                    py = env_dir / "bin" / "python3"
                    if py.is_file():
                        try:
                            found.add(py.resolve())
                        except (OSError, RuntimeError):
                            found.add(py)
            except PermissionError:
                pass

    # ~/.conda/envs
    dot_conda = Path.home() / ".conda" / "envs"
    if dot_conda.is_dir():
        try:
            for env_dir in dot_conda.iterdir():
                py = env_dir / "bin" / "python3"
                if py.is_file():
                    try:
                        found.add(py.resolve())
                    except (OSError, RuntimeError):
                        found.add(py)
        except PermissionError:
            pass

    return list(found)


def scan_venvs(
    search_paths: list[Path], max_depth: int = 5
) -> list[tuple[Path, Path]]:
    """Return (python_executable, venv_base) for each venv found."""
    results: list[tuple[Path, Path]] = []
    seen_venvs: set[Path] = set()

    def _walk(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            cfg = path / "pyvenv.cfg"
            if cfg.is_file():
                resolved = path.resolve()
                if resolved in seen_venvs:
                    return
                seen_venvs.add(resolved)
                for py_name in ("python3", "python"):
                    py = path / "bin" / py_name
                    if py.exists():
                        try:
                            results.append((py.resolve(), path.resolve()))
                        except (OSError, RuntimeError):
                            results.append((py, path))
                        return
                return
            for entry in path.iterdir():
                if (
                    entry.is_dir()
                    and not entry.name.startswith(".")
                    and not entry.is_symlink()
                    and entry.name not in ("node_modules", "__pycache__", ".git")
                ):
                    _walk(entry, depth + 1)
        except PermissionError:
            pass

    for p in search_paths:
        if p.is_dir():
            _walk(p, 0)

    return results


def get_pip_packages(venv_base: Path) -> list[str]:
    """Return pip freeze output for a venv."""
    pip = venv_base / "bin" / "pip"
    if not pip.exists():
        return []
    output = _run([str(pip), "freeze"], timeout=15)
    if not output:
        return []
    return [line for line in output.splitlines() if line and not line.startswith("#")]


def find_all_pythons(
    extra_paths: list[Path] | None = None,
    venv_search_paths: list[Path] | None = None,
    progress_callback=None,
) -> list[PythonInstall]:
    """Discover all Python installations on the system."""
    current_python = Path(sys.executable).resolve()

    if progress_callback:
        progress_callback("Scanning PATH…")
    path_execs = scan_path_executables()

    if progress_callback:
        progress_callback("Scanning common install locations…")
    common = scan_common_dirs()

    all_paths: set[Path] = set(path_execs + common)
    if extra_paths:
        for p in extra_paths:
            if p.exists():
                all_paths.add(p.resolve())

    venv_map: dict[Path, Path] = {}
    if venv_search_paths:
        if progress_callback:
            progress_callback("Scanning for virtual environments…")
        for py_path, venv_base in scan_venvs(venv_search_paths):
            all_paths.add(py_path)
            venv_map[py_path] = venv_base

    if progress_callback:
        progress_callback(f"Querying {len(all_paths)} executables…")

    installs: list[PythonInstall] = []
    seen_resolved: set[Path] = set()

    for path in sorted(all_paths):
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            resolved = path
        if resolved in seen_resolved:
            continue

        if progress_callback:
            progress_callback(f"Checking {path}…")

        version_info = get_version(path)
        if version_info is None:
            continue

        seen_resolved.add(resolved)
        version, version_str = version_info
        venv_base = venv_map.get(resolved) or venv_map.get(path)
        install_type = "venv" if venv_base else _classify_path(resolved)

        installs.append(
            PythonInstall(
                path=resolved,
                version=version,
                version_str=version_str,
                install_type=install_type,
                venv_base=venv_base,
                is_current=(resolved == current_python),
            )
        )

    return sorted(installs, key=lambda x: x.version, reverse=True)
