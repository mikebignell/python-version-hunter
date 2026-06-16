"""Upgrade and deletion actions for Python installations."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm

from pyhunter.finder import PythonInstall, get_pip_packages, get_version


def _run_visible(cmd: list[str], console: Console) -> bool:
    """Run a command, streaming output; return True on success."""
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(cmd, text=True)
        return result.returncode == 0
    except (FileNotFoundError, PermissionError) as exc:
        console.print(f"[bright_red]Error: {exc}[/bright_red]")
        return False


def _run_capturing(cmd: list[str]) -> tuple[int, str, str]:
    """Run a command capturing stdout+stderr; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, text=True, capture_output=True)
        return result.returncode, result.stdout, result.stderr
    except (FileNotFoundError, PermissionError) as exc:
        return 1, "", str(exc)


# ── python.org Framework SSL cert installation ────────────────────────────────

def _is_framework_python(python_path: Path) -> bool:
    return "/Library/Frameworks/Python.framework" in str(python_path)


def ensure_ssl_certs(python_path: Path, console: Console) -> None:
    """
    Python.org macOS installers ship without CA certificates wired up.
    Attempt the bundled Install Certificates.command; if that needs root,
    fall back to --user install of certifi. If SSL already works, skip.
    """
    if not _is_framework_python(python_path):
        return

    # Quick check: can the Python actually verify a cert?
    rc, _, _ = _run_capturing([
        str(python_path), "-c",
        "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)"
    ])
    if rc == 0:
        return  # certs already work

    console.print(
        "  [bright_yellow]⚠  python.org Framework Python — SSL certificates not configured, fixing…[/bright_yellow]"
    )

    # Try the bundled installer (captured, not streamed — it can error noisily)
    ver_match = re.search(r"Python\.framework/Versions/(\d+\.\d+)", str(python_path))
    if ver_match:
        cert_cmd = Path(f"/Applications/Python {ver_match.group(1)}/Install Certificates.command")
        if cert_cmd.exists():
            rc, _, stderr = _run_capturing(["bash", str(cert_cmd)])
            if rc == 0:
                console.print("  [bright_green]✓ SSL certificates installed.[/bright_green]")
                return
            if "Permission denied" in stderr or "EACCES" in stderr or rc == 1:
                # Script needs root to write to system site-packages — use --user instead
                console.print(
                    "  [dim]Install Certificates.command needs root; "
                    "installing certifi to user site-packages instead…[/dim]"
                )

    # --user install avoids needing sudo for the Framework Python
    rc2, _, _ = _run_capturing([
        str(python_path), "-m", "pip", "install", "--quiet", "--user", "--upgrade", "certifi"
    ])
    if rc2 == 0:
        console.print("  [bright_green]✓ certifi installed (--user).[/bright_green]")
    else:
        console.print(
            "  [bright_yellow]Could not install certifi automatically. "
            "If SSL errors occur, run:[/bright_yellow]\n"
            f"  [bright_green]sudo {python_path} -m pip install --upgrade certifi[/bright_green]"
        )


# ── Package reinstall with fallback ──────────────────────────────────────────

def _reinstall_packages(
    pip: Path,
    packages: list[str],
    req_backup: Path,
    console: Console,
) -> None:
    """
    Install pinned requirements. For any package that fails (e.g. no wheel
    for this Python version), retry without the version pin to get the latest.
    """
    console.print(f"[bright_yellow]Reinstalling {len(packages)} package(s)…[/bright_yellow]")
    rc, stdout, stderr = _run_capturing([str(pip), "install", "--quiet", "-r", str(req_backup)])

    if rc == 0:
        console.print("[bright_green]  ✓ All packages reinstalled.[/bright_green]")
        return

    # Parse which packages failed from pip's error output
    failed_names = _extract_failed_packages(stderr + stdout)

    if not failed_names:
        console.print(
            f"[bright_yellow]  ⚠ Some packages may not have installed. "
            f"Check {req_backup}[/bright_yellow]"
        )
        return

    console.print(
        f"  [bright_yellow]⚠ {len(failed_names)} package(s) failed with pinned version, "
        f"retrying without version constraint:[/bright_yellow]"
    )

    retried_ok: list[str] = []
    retried_fail: list[str] = []

    for name in failed_names:
        console.print(f"  [bright_cyan]  → {name}[/bright_cyan]")
        rc2, _, _ = _run_capturing([str(pip), "install", "--quiet", name])
        if rc2 == 0:
            retried_ok.append(name)
        else:
            retried_fail.append(name)

    if retried_ok:
        console.print(
            f"  [bright_green]  ✓ Installed latest: {', '.join(retried_ok)}[/bright_green]"
        )
    if retried_fail:
        console.print(
            f"  [bright_red]  ✗ Could not install: {', '.join(retried_fail)}[/bright_red]\n"
            f"    Install manually: pip install {' '.join(retried_fail)}"
        )


def _extract_failed_packages(output: str) -> list[str]:
    """Extract package names from pip error output."""
    names: list[str] = []
    # "× Preparing metadata ... did not run successfully" with package name on next context line
    # "error: metadata-generation-failed\n× Encountered error while generating package metadata.\n╰─> <name>"
    for pattern in [
        r"╰─>\s+(\S+)",                  # pip metadata error arrow
        r"error in (\S+) setup command",  # older pip
        r"Failed to build (\S+)",
        r"Could not build wheels for (\S+)",
        r"ERROR: Could not find a version.*for (\S+)",
    ]:
        for m in re.finditer(pattern, output, re.IGNORECASE):
            name = m.group(1).strip().rstrip(".,;")
            if name and name not in names:
                names.append(name)
    return names


def _pip_in_venv(venv_path: Path) -> Path:
    """Return the pip executable path inside a venv, cross-platform."""
    win = venv_path / "Scripts" / "pip.exe"
    unix = venv_path / "bin" / "pip"
    return win if sys.platform == "win32" else unix


def upgrade_venv(
    install: PythonInstall,
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> bool:
    """Recreate a venv with a newer Python, reinstalling packages."""
    if not install.venv_base:
        console.print("[bright_red]Not a venv — cannot upgrade.[/bright_red]")
        return False

    venv_path = install.venv_base
    new_python = str(target_python) if target_python else sys.executable

    # Resolve new Python version string for clear compliance output
    new_ver_result = get_version(Path(new_python))
    new_ver_str = new_ver_result[1] if new_ver_result else new_python

    # Guard: if the target is not actually newer, there's nothing to do.
    # This happens when endoflife.date reports a newer patch but the only
    # locally available Python is the same version the venv is already on.
    if new_ver_result and new_ver_result[0] <= install.version:
        console.print(
            f"\n[bright_yellow]Skipping venv:[/bright_yellow] {venv_path}\n"
            f"  Target Python ({new_ver_str}) is not newer than current ({install.version_str}) — "
            f"run [bright_green]brew upgrade python[/bright_green] first to get a newer version."
        )
        return True

    console.print(
        f"\n[bright_cyan]Upgrading venv:[/bright_cyan] {venv_path}\n"
        f"  [dim]{install.version_str}[/dim] [{install.status_color}]({install.status_label})[/{install.status_color}]"
        f"  [bright_cyan]→[/bright_cyan]  [bright_green]{new_ver_str}[/bright_green]"
    )

    packages = get_pip_packages(venv_path)
    if packages:
        console.print(f"  [dim]{len(packages)} package(s) will be preserved[/dim]")

    if dry_run:
        console.print("[bright_yellow]  [DRY RUN] Would recreate venv and reinstall packages.[/bright_yellow]")
        return True

    req_backup = venv_path.parent / f"{venv_path.name}_requirements_backup.txt"
    if packages:
        req_backup.write_text("\n".join(packages) + "\n")
        console.print(f"[dim]Requirements backed up to {req_backup}[/dim]")

    console.print("[bright_yellow]Removing old venv…[/bright_yellow]")
    shutil.rmtree(venv_path, ignore_errors=True)

    console.print("[bright_yellow]Creating new venv…[/bright_yellow]")
    if not _run_visible([new_python, "-m", "venv", str(venv_path)], console):
        console.print("[bright_red]Failed to create new venv.[/bright_red]")
        return False

    # Fix SSL certs for python.org Framework Pythons before running pip
    ensure_ssl_certs(Path(new_python), console)

    pip = _pip_in_venv(venv_path)
    _run_visible([str(pip), "install", "--quiet", "--upgrade", "pip"], console)

    if packages:
        _reinstall_packages(pip, packages, req_backup, console)

    console.print("[bright_green]✓ Venv upgraded successfully.[/bright_green]")
    return True


def advise_os_managed_python(install: PythonInstall, console: Console) -> None:
    """Show platform-appropriate advice for an OS-managed Python."""
    console.print(
        f"\n[bright_cyan]System Python {install.version_str} at {install.path}[/bright_cyan]"
    )

    if sys.platform == "darwin":
        console.print(
            "  This Python is [bright_yellow]managed by macOS[/bright_yellow] (SIP-protected —\n"
            "  cannot be deleted even with sudo). The OS and Xcode tooling depend on it.\n"
        )
        console.print("  [bright_cyan]Update via Command Line Tools:[/bright_cyan]")
        console.print(
            "  [bright_green]softwareupdate --all --install --force[/bright_green]"
            "  [dim]# all macOS/CLT updates[/dim]"
        )
        console.print(
            "  [bright_green]xcode-select --install[/bright_green]"
            "  [dim]# reinstall CLT[/dim]\n"
        )
        console.print("  [bright_cyan]Better: shadow it with Homebrew Python:[/bright_cyan]")
        console.print(
            "  [bright_green]brew install python[/bright_green]"
            "  [dim]# /opt/homebrew/bin/python3 (Apple Silicon)[/dim]"
        )
        console.print(
            "  Ensure [bright_green]/opt/homebrew/bin[/bright_green] (or "
            "[bright_green]/usr/local/bin[/bright_green] on Intel) is "
            "[bold]before[/bold] [bright_green]/usr/bin[/bright_green] in your PATH."
        )

    elif sys.platform.startswith("linux"):
        console.print(
            "  This Python is [bright_yellow]managed by your package manager[/bright_yellow].\n"
            "  Deleting it directly can break system tools — use the package manager instead.\n"
        )
        console.print("  [bright_cyan]Update via package manager:[/bright_cyan]")
        console.print(
            "  [bright_green]sudo apt install python3[/bright_green]"
            "  [dim]# Debian / Ubuntu[/dim]"
        )
        console.print(
            "  [bright_green]sudo dnf install python3[/bright_green]"
            "  [dim]# Fedora / RHEL[/dim]"
        )
        console.print(
            "  [bright_green]sudo pacman -S python[/bright_green]"
            "  [dim]# Arch[/dim]\n"
        )
        console.print("  [bright_cyan]Better: install a newer Python alongside it:[/bright_cyan]")
        console.print(
            "  [bright_green]brew install python[/bright_green]"
            "  [dim]# Linuxbrew (no sudo)[/dim]"
        )
        console.print("  [bright_green]pyenv install 3.13.x && pyenv global 3.13.x[/bright_green]")

    elif sys.platform == "win32":
        console.print(
            "  This Python is [bright_yellow]managed by the Microsoft Store[/bright_yellow].\n"
            "  Update it through the Store or remove it via Apps & Features.\n"
        )
        console.print("  [bright_cyan]Install a standalone Python instead:[/bright_cyan]")
        console.print(
            "  [bright_green]winget install Python.Python.3.12[/bright_green]"
            "  [dim]# WinGet[/dim]"
        )
        console.print(
            "  [bright_green]choco upgrade python[/bright_green]"
            "  [dim]# Chocolatey[/dim]"
        )
        console.print(
            "  Or download from [bright_green]python.org/downloads[/bright_green]"
        )


# Keep the old name as an alias so existing callers in cli.py don't break.
advise_clt_update = advise_os_managed_python


def delete_python(
    install: PythonInstall, console: Console, dry_run: bool = False
) -> bool:
    """Delete a Python executable (with safety checks)."""
    if install.is_os_managed:
        platform_name = {"darwin": "macOS", "win32": "Windows"}.get(
            sys.platform, "your OS"
        )
        console.print(
            f"[bright_red]✗ Refusing to delete — this Python is managed by {platform_name}.[/bright_red]"
        )
        advise_os_managed_python(install, console)
        return False

    if install.is_current:
        console.print(
            "[bright_red]✗ Refusing to delete the currently running Python.[/bright_red]"
        )
        return False

    console.print(f"\n[bright_red]Delete:[/bright_red] {install.path}")
    if dry_run:
        console.print(f"[bright_yellow][DRY RUN] Would delete {install.path}[/bright_yellow]")
        return True

    if not Confirm.ask(f"[bright_red]Really delete {install.path}?[/bright_red]", default=False):
        console.print("[dim]Skipped.[/dim]")
        return False

    try:
        install.path.unlink()
        console.print(f"[bright_green]✓ Deleted {install.path}[/bright_green]")
        return True
    except PermissionError:
        sudo = "" if sys.platform == "win32" else "sudo "
        console.print(
            f"[bright_red]Permission denied. Try: {sudo}rm {install.path}[/bright_red]"
        )
        return False


def suggest_cycle_upgrade(install: PythonInstall, console: Console) -> None:
    """Show how to install a newer Python cycle alongside the existing one."""
    latest = install.latest_stable or "latest"
    console.print(
        f"\n[bright_cyan]Newer Python available:[/bright_cyan] "
        f"{install.version_str} → [bright_yellow]{latest}[/bright_yellow]"
    )
    console.print(
        "  Installing a new Python version [bold]does not remove[/bold] the old one —\n"
        "  both coexist. Update your venvs and shell default afterwards.\n"
    )
    t = install.install_type
    if t == "brew":
        console.print("  [bright_cyan]Homebrew:[/bright_cyan]")
        console.print(f"  [bright_green]brew install python[/bright_green]  [dim]# installs latest[/dim]")
        console.print(f"  [bright_green]brew unlink python@{install.major_minor[1]} && brew link python[/bright_green]  [dim]# switch default[/dim]")
    elif t == "pyenv":
        console.print("  [bright_cyan]pyenv:[/bright_cyan]")
        console.print(f"  [bright_green]pyenv install {latest}[/bright_green]")
        console.print(f"  [bright_green]pyenv global {latest}[/bright_green]")
    elif t == "conda":
        console.print("  [bright_cyan]conda:[/bright_cyan]")
        console.print(f"  [bright_green]conda install python={latest}[/bright_green]")
    elif t in ("python.org", "system"):
        advise_os_managed_python(install, console)
    else:
        console.print(
            f"  Download [bright_green]python.org/downloads[/bright_green] "
            f"or use your package manager to install Python {latest}."
        )
    console.print(
        "\n  [dim]After installing, run [bright_green]pyhunter --upgrade-venvs "
        f"--target-python $(which python{latest[:4]})[/bright_green] "
        "to update your venvs.[/dim]"
    )


def suggest_patch_update(install: PythonInstall, console: Console) -> None:
    """Show how to update to the latest patch release for this install type."""
    latest = install.latest_patch or "latest"
    console.print(
        f"\n[bright_cyan]Patch update available:[/bright_cyan] "
        f"{install.version_str} → [bright_yellow]{latest}[/bright_yellow]"
    )
    t = install.install_type
    if t == "brew":
        suggest_brew_upgrade(install, console)
    elif t == "pyenv":
        suggest_pyenv_upgrade(install, console)
    elif t in ("python.org", "system"):
        advise_os_managed_python(install, console)
    elif t == "conda":
        console.print(
            f"  [bright_green]conda update -n base python[/bright_green]  "
            "[dim]# base env[/dim]"
        )
        console.print(
            f"  [bright_green]conda update -n <env-name> python[/bright_green]  "
            "[dim]# named env[/dim]"
        )
    else:
        console.print(
            f"  Download [bright_green]python.org/downloads[/bright_green] "
            f"or use your package manager to install {latest}."
        )


def suggest_pyenv_upgrade(install: PythonInstall, console: Console) -> None:
    console.print(
        f"\n[bright_cyan]Pyenv upgrade suggestion for Python {install.version_str}:[/bright_cyan]"
    )
    if sys.platform == "win32":
        console.print("  [bright_green]pyenv update[/bright_green]  [dim]# update pyenv-win[/dim]")
        console.print("  [bright_green]pyenv install 3.13.x[/bright_green]")
        console.print("  [bright_green]pyenv global 3.13.x[/bright_green]")
    else:
        console.print("  [bright_green]pyenv install --list | grep '  3\\.'[/bright_green]  [dim]# available versions[/dim]")
        console.print("  [bright_green]pyenv install 3.13.x[/bright_green]")
        console.print("  [bright_green]pyenv global 3.13.x[/bright_green]")


def suggest_brew_upgrade(install: PythonInstall, console: Console) -> None:
    console.print(
        f"\n[bright_cyan]Homebrew upgrade suggestion for Python {install.version_str}:[/bright_cyan]"
    )
    console.print("  [bright_green]brew upgrade python[/bright_green]")
    console.print("  [bright_green]brew upgrade python@3.13[/bright_green]  [dim]# specific version[/dim]")
