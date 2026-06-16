"""Upgrade and deletion actions for Python installations."""
from __future__ import annotations

import shutil
import subprocess
import sys
import venv
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
        console.print(
            f"[bright_cyan]Found {len(packages)} package(s) to preserve.[/bright_cyan]"
        )

    new_python = str(target_python) if target_python else sys.executable
    console.print(f"[bright_cyan]New Python:[/bright_cyan] {new_python}")

    if dry_run:
        console.print("[bright_yellow][DRY RUN] Would recreate venv and reinstall packages.[/bright_yellow]")
        return True

    # Write requirements backup next to the venv
    req_backup = venv_path.parent / f"{venv_path.name}_requirements_backup.txt"
    if packages:
        req_backup.write_text("\n".join(packages) + "\n")
        console.print(f"[dim]Requirements backed up to {req_backup}[/dim]")

    # Delete and recreate
    console.print(f"[bright_yellow]Removing old venv…[/bright_yellow]")
    shutil.rmtree(venv_path, ignore_errors=True)

    console.print(f"[bright_yellow]Creating new venv…[/bright_yellow]")
    ok = _run_visible([new_python, "-m", "venv", str(venv_path)], console)
    if not ok:
        console.print(f"[bright_red]Failed to create new venv.[/bright_red]")
        return False

    if packages:
        pip = venv_path / "bin" / "pip"
        console.print(f"[bright_yellow]Reinstalling {len(packages)} package(s)…[/bright_yellow]")
        ok = _run_visible(
            [str(pip), "install", "--quiet", "-r", str(req_backup)], console
        )
        if not ok:
            console.print(
                f"[bright_yellow]Some packages may not have installed. "
                f"Check {req_backup}[/bright_yellow]"
            )

    console.print(f"[bright_green]✓ Venv upgraded successfully.[/bright_green]")
    return True


def advise_clt_update(install: PythonInstall, console: Console) -> None:
    """Explain how to update an OS-managed Python via CLT / Software Update."""
    console.print(
        f"\n[bright_cyan]System Python {install.version_str} at {install.path}[/bright_cyan]"
    )
    console.print(
        "  This Python is [bright_yellow]managed by macOS[/bright_yellow] (SIP-protected — "
        "cannot be deleted even with sudo).\n"
        "  The OS needs it; other tools (Xcode, Git, build scripts) call it directly.\n"
    )
    console.print("  [bright_cyan]How to get a newer system Python:[/bright_cyan]")
    console.print(
        "  [bright_green]softwareupdate --all --install --force[/bright_green]"
        "  [dim]# pull all macOS/CLT updates[/dim]"
    )
    console.print(
        "  [bright_green]xcode-select --install[/bright_green]"
        "  [dim]# re-install Command Line Tools[/dim]\n"
    )
    console.print("  [bright_cyan]Better practice — shadow it with Homebrew Python:[/bright_cyan]")
    console.print(
        "  [bright_green]brew install python[/bright_green]           "
        "[dim]# installs /opt/homebrew/bin/python3[/dim]"
    )
    console.print(
        "  Make sure [bright_green]/opt/homebrew/bin[/bright_green] (or "
        "[bright_green]/usr/local/bin[/bright_green] on Intel) comes [bold]before[/bold] "
        "[bright_green]/usr/bin[/bright_green] in your PATH.\n"
        "  Then [bright_green]python3[/bright_green] in your shell will use the Homebrew "
        "version, leaving the system one untouched."
    )


def delete_python(
    install: PythonInstall, console: Console, dry_run: bool = False
) -> bool:
    """Delete a Python executable (with safety checks)."""
    if install.is_os_managed:
        console.print(
            "[bright_red]✗ Refusing to delete a macOS system Python — "
            "it is SIP-protected and required by the OS.[/bright_red]"
        )
        advise_clt_update(install, console)
        return False
    if install.is_current:
        console.print(
            "[bright_red]✗ Refusing to delete the currently running Python.[/bright_red]"
        )
        return False

    console.print(f"\n[bright_red]Delete:[/bright_red] {install.path}")
    if not dry_run:
        if not Confirm.ask(
            f"[bright_red]Really delete {install.path}?[/bright_red]", default=False
        ):
            console.print("[dim]Skipped.[/dim]")
            return False

    if dry_run:
        console.print(f"[bright_yellow][DRY RUN] Would delete {install.path}[/bright_yellow]")
        return True

    try:
        install.path.unlink()
        console.print(f"[bright_green]✓ Deleted {install.path}[/bright_green]")
        return True
    except PermissionError:
        console.print(
            f"[bright_red]Permission denied. Try: sudo rm {install.path}[/bright_red]"
        )
        return False


def suggest_pyenv_upgrade(install: PythonInstall, console: Console) -> None:
    console.print(
        f"\n[bright_cyan]Pyenv upgrade suggestion for Python {install.version_str}:[/bright_cyan]"
    )
    console.print("  [bright_green]pyenv install --list | grep '  3\\.'[/bright_green]  "
                  "[dim]# see available versions[/dim]")
    console.print("  [bright_green]pyenv install 3.12.x[/bright_green]  [dim]# install latest[/dim]")
    console.print("  [bright_green]pyenv global 3.12.x[/bright_green]  [dim]# set as default[/dim]")


def suggest_brew_upgrade(install: PythonInstall, console: Console) -> None:
    console.print(
        f"\n[bright_cyan]Homebrew upgrade suggestion for Python {install.version_str}:[/bright_cyan]"
    )
    console.print("  [bright_green]brew upgrade python[/bright_green]")
    console.print("  [bright_green]brew upgrade python@3.12[/bright_green]  [dim]# for a specific version[/dim]")
