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

# Cross-platform venv executable candidates, tried in order.
_VENV_PY_CANDIDATES: list[tuple[str, ...]] = [
    ("bin", "python3"),       # Unix/macOS default
    ("bin", "python"),        # Unix fallback
    ("Scripts", "python.exe"),  # Windows
    ("Scripts", "python3.exe"), # Windows alternate
]

# Directories skipped during recursive venv scan.
_SCAN_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", ".tox", "dist", "build", "site-packages",
    # macOS system/sync dirs that contain no venvs and may raise InterruptedError
    "Library", "System", "Applications",
    # Cloud-sync roots
    "OneDrive", "Dropbox", "Google Drive", "iCloud Drive",
})

# Errors to swallow when scanning directories.
_SCAN_ERRORS = (PermissionError, InterruptedError, OSError)


@dataclass
class PythonInstall:
    path: Path
    version: tuple[int, int, int]
    version_str: str
    install_type: str  # system | brew | pyenv | conda | venv | unknown
    venv_base: Optional[Path] = None
    is_current: bool = False
    latest_patch: Optional[str] = None   # latest patch for this major.minor cycle
    latest_stable: Optional[str] = None  # latest stable Python overall (e.g. 3.14.6)

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
        """
        True when the Python is owned by the OS/package-manager and should not
        be deleted manually.

        - macOS: /usr/bin is SIP-protected; CLT paths are Apple-managed.
        - Linux: /usr/bin Python is owned by apt/dnf/pacman — deleting it can
          break system tools. Use the package manager instead.
        - Windows: system Python under WindowsApps is managed by the Store.
        """
        s = str(self.path)
        if sys.platform == "darwin":
            return s.startswith("/usr/bin/") or "/Developer/CommandLineTools" in s
        if sys.platform.startswith("linux"):
            return s.startswith("/usr/bin/")
        if sys.platform == "win32":
            # Microsoft Store / WindowsApps Pythons are managed
            appdata = os.environ.get("LOCALAPPDATA", "")
            return bool(appdata and s.startswith(os.path.join(appdata, "Microsoft", "WindowsApps")))
        return False

    @property
    def has_newer_patch(self) -> bool:
        """True when a newer patch exists within the same major.minor cycle."""
        if not self.latest_patch:
            return False
        try:
            return tuple(int(x) for x in self.latest_patch.split(".")) > self.version
        except ValueError:
            return False

    @property
    def has_newer_cycle(self) -> bool:
        """True when the overall latest Python is a higher minor/major than installed."""
        if not self.latest_stable:
            return False
        try:
            latest_mm = tuple(int(x) for x in self.latest_stable.split(".")[:2])
            return latest_mm > self.major_minor
        except ValueError:
            return False

    @property
    def recommendation(self) -> str:
        if self.is_os_managed:
            if self.status in ("eol", "security") or self.has_newer_patch or self.has_newer_cycle:
                return "UPDATE VIA PKG MGR"
            return "KEEP"
        if self.status == "eol":
            return "UPGRADE VENV" if self.is_venv else "DELETE"
        # A newer Python cycle exists (e.g. on 3.13, latest is 3.14)
        if self.has_newer_cycle:
            return "UPGRADE VENV" if self.is_venv else "UPGRADE AVAILABLE"
        # Same cycle but behind on patch (e.g. 3.14.5 when 3.14.6 is out)
        if self.has_newer_patch:
            return "UPGRADE VENV" if self.is_venv else "UPDATE PATCH"
        if self.status == "security":
            return "UPGRADE VENV" if self.is_venv else "CONSIDER UPGRADE"
        return "KEEP"

    @property
    def recommendation_color(self) -> str:
        return {
            "UPDATE VIA PKG MGR": "bright_cyan",
            "UPGRADE VENV":       "bright_yellow",
            "UPGRADE AVAILABLE":  "bright_yellow",
            "UPDATE PATCH":       "yellow",
            "DELETE":             "bright_red",
            "CONSIDER UPGRADE":   "yellow",
            "KEEP":               "bright_green",
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
    # Order matters: more specific checks first.
    if ".pyenv" in s:
        return "pyenv"
    if any(k in s for k in ("miniconda", "anaconda", "conda", "mamba", "miniforge")):
        return "conda"
    # macOS Homebrew
    if "/opt/homebrew" in s or "/usr/local/Cellar" in s or "/usr/local/opt" in s:
        return "brew"
    # Linux Homebrew (Linuxbrew)
    if "/home/linuxbrew" in s or "/.linuxbrew" in s:
        return "brew"
    # macOS python.org framework
    if "/Library/Frameworks/Python.framework" in s:
        return "python.org"
    # Windows python.org installer (LOCALAPPDATA\Programs\Python)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").lower()
        if local and local in s.lower() and "programs\\python" in s.lower():
            return "python.org"
        if "\\scoop\\apps\\python" in s.lower():
            return "scoop"
        if "\\chocolatey\\lib\\python" in s.lower():
            return "chocolatey"
        if "microsoft\\windowsapps" in s.lower():
            return "system"
    if s.startswith("/usr/bin") or s.startswith("/usr/local/bin"):
        return "system"
    return "unknown"


def scan_path_executables() -> list[Path]:
    """Find all python executables in PATH, cross-platform."""
    found: set[Path] = set()
    # Unix: python, python3, python3.11 etc.
    # Windows: python.exe, python3.exe, python3.11.exe
    unix_pat = re.compile(r"^python(\d+(\.\d+)*)?$")
    win_pat = re.compile(r"^python(\d+(\.\d+)*)?(\.exe)?$", re.IGNORECASE)
    pattern = win_pat if sys.platform == "win32" else unix_pat

    for dir_str in os.environ.get("PATH", "").split(os.pathsep):
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
        except _SCAN_ERRORS:
            continue
    return list(found)


def _add_py(path: Path, found: set[Path]) -> None:
    """Resolve and add a Python executable to the found set."""
    if path.exists():
        try:
            found.add(path.resolve())
        except (OSError, RuntimeError):
            found.add(path)


def scan_common_dirs() -> list[Path]:
    """Check well-known install locations for the current platform."""
    found: set[Path] = set()
    unix_pat = re.compile(r"^python(\d+(\.\d+)*)?$")

    def _scan_dir(d: Path) -> None:
        if not d.is_dir():
            return
        try:
            for entry in d.iterdir():
                if unix_pat.match(entry.name) and (entry.is_file() or entry.is_symlink()):
                    _add_py(entry, found)
        except _SCAN_ERRORS:
            pass

    # ── macOS ──────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        for d in (Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin")):
            _scan_dir(d)

        # python.org framework installs
        fw = Path("/Library/Frameworks/Python.framework/Versions")
        if fw.is_dir():
            try:
                for vdir in fw.iterdir():
                    _add_py(vdir / "bin" / "python3", found)
            except PermissionError:
                pass

    # ── Linux ──────────────────────────────────────────────────────────────
    elif sys.platform.startswith("linux"):
        for d in (Path("/usr/bin"), Path("/usr/local/bin"), Path("/snap/bin")):
            _scan_dir(d)

        # Linuxbrew
        linuxbrew = Path("/home/linuxbrew/.linuxbrew/bin")
        if not linuxbrew.is_dir():
            linuxbrew = Path.home() / ".linuxbrew" / "bin"
        _scan_dir(linuxbrew)

        # Common distro alternatives paths (deadsnakes PPA etc.)
        for d in (Path("/usr/bin"), Path("/usr/local/bin")):
            _scan_dir(d)

    # ── Windows ────────────────────────────────────────────────────────────
    elif sys.platform == "win32":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        prog_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        prog_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))

        # python.org installers (per-user and system-wide)
        for base in (local_app / "Programs", prog_files, prog_files_x86, Path("C:/")):
            if not base.is_dir():
                continue
            try:
                for entry in base.iterdir():
                    if re.match(r"^Python3?\d*$", entry.name, re.IGNORECASE):
                        _add_py(entry / "python.exe", found)
            except PermissionError:
                pass

        # Microsoft Store Python
        _scan_dir(local_app / "Microsoft" / "WindowsApps")

        # Scoop
        scoop_apps = Path.home() / "scoop" / "apps" / "python" / "current"
        _add_py(scoop_apps / "python.exe", found)

        # Chocolatey
        _add_py(Path("C:/tools/python3/python.exe"), found)

    # ── pyenv (all platforms; pyenv-win on Windows) ─────────────────────
    pyenv_home = Path.home() / ".pyenv"
    if sys.platform == "win32":
        pyenv_versions = pyenv_home / "pyenv-win" / "versions"
        py_bin = ("python.exe",)
    else:
        pyenv_versions = pyenv_home / "versions"
        py_bin = ("python3", "python")

    if pyenv_versions.is_dir():
        try:
            for vdir in pyenv_versions.iterdir():
                for name in py_bin:
                    candidate = vdir / ("bin" if sys.platform != "win32" else "") / name
                    if candidate.is_file():
                        _add_py(candidate, found)
                        break
        except _SCAN_ERRORS:
            pass

    # ── conda / mamba envs (all platforms) ─────────────────────────────
    conda_bases: list[Path] = []
    for base_name in ("miniconda3", "miniconda", "anaconda3", "anaconda", "miniforge3", "mambaforge"):
        conda_bases.append(Path.home() / base_name)
        if sys.platform == "win32":
            local_app = Path(os.environ.get("LOCALAPPDATA", ""))
            if local_app.is_dir():
                conda_bases.append(local_app / base_name)

    conda_bases.append(Path.home() / ".conda")

    py_exec = "python.exe" if sys.platform == "win32" else "python3"
    for base in conda_bases:
        envs = base / "envs"
        if not envs.is_dir():
            continue
        try:
            for env_dir in envs.iterdir():
                candidate = (
                    env_dir / py_exec
                    if sys.platform == "win32"
                    else env_dir / "bin" / py_exec
                )
                _add_py(candidate, found)
        except _SCAN_ERRORS:
            pass

    return list(found)


def _venv_executable(venv_path: Path) -> Optional[Path]:
    """Return the Python executable inside a venv directory, cross-platform."""
    for parts in _VENV_PY_CANDIDATES:
        candidate = venv_path.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


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
            if (path / "pyvenv.cfg").is_file():
                resolved = path.resolve()
                if resolved in seen_venvs:
                    return
                seen_venvs.add(resolved)
                py = _venv_executable(path)
                if py:
                    try:
                        results.append((py.resolve(), resolved))
                    except (OSError, RuntimeError):
                        results.append((py, path))
                return
            for entry in path.iterdir():
                try:
                    if (
                        entry.is_dir()
                        and not entry.name.startswith(".")
                        and not entry.is_symlink()
                        and entry.name not in _SCAN_SKIP_DIRS
                    ):
                        _walk(entry, depth + 1)
                except _SCAN_ERRORS:
                    continue
        except _SCAN_ERRORS:
            pass

    for p in search_paths:
        if p.is_dir():
            _walk(p, 0)

    return results


def get_pip_packages(venv_base: Path) -> list[str]:
    """Return pip freeze output for a venv, cross-platform."""
    pip = (
        venv_base / "Scripts" / "pip.exe"
        if sys.platform == "win32"
        else venv_base / "bin" / "pip"
    )
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

        # venv_map is keyed by the one executable scan_venvs happened to find
        # (e.g. bin/python3).  If PATH also exposed a sibling in the same venv
        # bin dir (e.g. bin/python3.14), the map lookup above will miss it.
        # Walk parents to catch that case.
        if venv_base is None:
            for parent in resolved.parents:
                if (parent / "pyvenv.cfg").exists():
                    venv_base = parent
                    break

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
