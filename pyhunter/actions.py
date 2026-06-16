"""Upgrade and deletion actions for Python installations."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm

from pyhunter.finder import PythonInstall, get_pip_packages


def _run_visible(cmd: list[str], console: Console) -> bool:
    """Run a command, streaming output; return True on success."""
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    try:
        result = subprocess.run(cmd, text=True)
        return result.returncode == 0
    except (FileNotFoundError, PermissionError) as exc:
        console.print(f"[bright_red]Error: {exc}[/bright_red]")
        return False


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
    console.print(f"\n[bright_cyan]Upgrading venv:[/bright_cyan] {venv_path}")

    packages = get_pip_packages(venv_path)
    if packages:
        console.print(f"[bright_cyan]Found {len(packages)} package(s) to preserve.[/bright_cyan]")

    new_python = str(target_python) if target_python else sys.executable
    console.print(f"[bright_cyan]New Python:[/bright_cyan] {new_python}")

    if dry_run:
        console.print("[bright_yellow][DRY RUN] Would recreate venv and reinstall packages.[/bright_yellow]")
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

    if packages:
        pip = _pip_in_venv(venv_path)
        console.print(f"[bright_yellow]Reinstalling {len(packages)} package(s)…[/bright_yellow]")
        ok = _run_visible([str(pip), "install", "--quiet", "-r", str(req_backup)], console)
        if not ok:
            console.print(
                f"[bright_yellow]Some packages may not have installed. "
                f"Check {req_backup}[/bright_yellow]"
            )

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
