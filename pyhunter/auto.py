"""Full auto-remediation: upgrade Python, fix venvs, verify environment."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich import box

from pyhunter.actions import _run_visible, _pip_in_venv, upgrade_venv
from pyhunter.finder import PythonInstall, _SCAN_ERRORS, _SCAN_SKIP_DIRS, get_pip_packages


# ── Broken venv detection ────────────────────────────────────────────────────

@dataclass
class BrokenVenv:
    venv_base: Path
    missing_home: Path   # the 'home =' path from pyvenv.cfg that no longer exists
    python_version: Optional[str]  # version string from pyvenv.cfg if present


def _parse_pyvenv_cfg(cfg_path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in cfg_path.read_text(errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return data


def find_broken_venvs(search_paths: list[Path], max_depth: int = 5) -> list[BrokenVenv]:
    """Find venvs whose source Python no longer exists."""
    broken: list[BrokenVenv] = []
    seen: set[Path] = set()

    def _walk(path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            cfg = path / "pyvenv.cfg"
            if cfg.is_file():
                resolved = path.resolve()
                if resolved in seen:
                    return
                seen.add(resolved)
                data = _parse_pyvenv_cfg(cfg)
                home = data.get("home")
                if home:
                    home_path = Path(home)
                    if not home_path.is_dir():
                        broken.append(BrokenVenv(
                            venv_base=resolved,
                            missing_home=home_path,
                            python_version=data.get("version"),
                        ))
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
    return broken


# ── PATH / shell checks ──────────────────────────────────────────────────────

def check_path_shadowing(console: Console) -> bool:
    """Verify Homebrew Python appears before /usr/bin/python3 in PATH."""
    console.print("[bright_cyan]Checking PATH shadowing…[/bright_cyan]")
    python3 = shutil.which("python3")
    if python3 is None:
        console.print("  [bright_red]✗ python3 not found in PATH at all.[/bright_red]")
        return False

    if "/opt/homebrew" in python3 or "/usr/local/bin" in python3 or "/.linuxbrew" in python3:
        console.print(f"  [bright_green]✓ python3 → {python3}[/bright_green]  (Homebrew shadows system)")
        return True

    if python3.startswith("/usr/bin"):
        console.print(
            f"  [bright_red]✗ python3 → {python3}[/bright_red]  "
            "(system Python — Homebrew is NOT shadowing)\n"
        )
        if sys.platform == "darwin":
            console.print(
                "  [bright_cyan]Fix: ensure /opt/homebrew/bin (Apple Silicon) or\n"
                "  /usr/local/bin (Intel) is before /usr/bin in your PATH.[/bright_cyan]"
            )
            console.print("  Add to [bright_green]~/.zshrc[/bright_green] or [bright_green]~/.bash_profile[/bright_green]:")
            console.print('  [bright_green]eval "$(/opt/homebrew/bin/brew shellenv)"[/bright_green]')
        return False

    console.print(f"  [bright_cyan]  python3 → {python3}[/bright_cyan]")
    return True


_SHELL_RC_FILES = [
    Path.home() / ".zshrc",
    Path.home() / ".bash_profile",
    Path.home() / ".bashrc",
    Path.home() / ".profile",
]

def check_shell_config(console: Console) -> None:
    """Warn if no shell rc file contains brew shellenv."""
    console.print("[bright_cyan]Checking shell configuration…[/bright_cyan]")
    found_brew_shellenv = False
    found_in: list[Path] = []
    for rc in _SHELL_RC_FILES:
        if rc.exists():
            try:
                content = rc.read_text(errors="replace")
                if "brew shellenv" in content:
                    found_in.append(rc)
                    found_brew_shellenv = True
            except OSError:
                pass

    if found_brew_shellenv:
        for f in found_in:
            console.print(f"  [bright_green]✓ brew shellenv found in {f}[/bright_green]")
    else:
        console.print(
            "  [bright_yellow]⚠  brew shellenv not found in any shell rc file.[/bright_yellow]\n"
            "  Homebrew PATH may not be set after a new terminal session.\n"
            "  Add to [bright_green]~/.zshrc[/bright_green]:\n"
            '  [bright_green]eval "$(/opt/homebrew/bin/brew shellenv)"[/bright_green]  '
            "[dim]# Apple Silicon[/dim]\n"
            '  [bright_green]eval "$(/usr/local/bin/brew shellenv)"[/bright_green]    '
            "[dim]# Intel[/dim]"
        )

    # Check for .python-version files that pin an EOL version
    _check_python_version_files(console)


def _check_python_version_files(console: Console) -> None:
    """Warn about .python-version files that pin non-current versions."""
    from pyhunter.finder import EOL_VERSIONS, SECURITY_VERSIONS
    hits: list[tuple[Path, str]] = []

    def _walk(path: Path, depth: int) -> None:
        if depth > 4:
            return
        try:
            pv = path / ".python-version"
            if pv.is_file():
                try:
                    ver = pv.read_text().strip()
                    match = re.match(r"(\d+)\.(\d+)", ver)
                    if match:
                        mm = (int(match.group(1)), int(match.group(2)))
                        if mm in EOL_VERSIONS or mm in SECURITY_VERSIONS:
                            hits.append((pv, ver))
                except OSError:
                    pass
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

    _walk(Path.home(), 0)
    if hits:
        console.print(
            f"  [bright_yellow]⚠  Found {len(hits)} .python-version file(s) pinning old versions:[/bright_yellow]"
        )
        for path, ver in hits:
            console.print(f"    [yellow]{path}[/yellow]  →  [bright_red]{ver}[/bright_red]")
        console.print(
            "  Update with [bright_green]echo '3.14' > <path>/.python-version[/bright_green] "
            "or [bright_green]pyenv local 3.14.x[/bright_green]"
        )


# ── Homebrew upgrade ─────────────────────────────────────────────────────────

def brew_upgrade_python(console: Console, dry_run: bool = False) -> bool:
    """Run brew upgrade python for all installed python formulae."""
    brew = shutil.which("brew")
    if not brew:
        console.print("  [bright_yellow]Homebrew not found — skipping.[/bright_yellow]")
        return False

    # Find which python formulae are installed
    result = subprocess.run([brew, "list", "--formula"], capture_output=True, text=True)
    installed = result.stdout.splitlines()
    formulae = [f for f in installed if re.match(r"^python(@\d+\.\d+)?$", f)]

    if not formulae:
        console.print("  [bright_yellow]No Homebrew Python formulae found.[/bright_yellow]")
        return False

    console.print(f"  [bright_cyan]Upgrading:[/bright_cyan] {', '.join(formulae)}")
    if dry_run:
        console.print(f"  [bright_yellow][DRY RUN] Would run: brew upgrade {' '.join(formulae)}[/bright_yellow]")
        return True

    return _run_visible([brew, "upgrade"] + formulae, console)


# ── pyenv upgrade ─────────────────────────────────────────────────────────────

def pyenv_install_latest(latest: str, console: Console, dry_run: bool = False) -> bool:
    """Install the latest Python via pyenv and set it as global default."""
    pyenv = shutil.which("pyenv")
    if not pyenv:
        console.print("  [bright_yellow]pyenv not found — skipping.[/bright_yellow]")
        return False

    console.print(f"  [bright_cyan]Installing Python {latest} via pyenv…[/bright_cyan]")
    if dry_run:
        console.print(f"  [bright_yellow][DRY RUN] Would run: pyenv install {latest} && pyenv global {latest}[/bright_yellow]")
        return True

    ok = _run_visible([pyenv, "install", "--skip-existing", latest], console)
    if ok:
        _run_visible([pyenv, "global", latest], console)
    return ok


# ── Venv upgrade with pip bump ────────────────────────────────────────────────

def upgrade_venv_with_pip(
    install: PythonInstall,
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> bool:
    """Recreate a venv then upgrade pip inside it."""
    ok = upgrade_venv(install, target_python, console, dry_run=dry_run)
    if ok and not dry_run and install.venv_base:
        pip = _pip_in_venv(install.venv_base)
        if pip.exists():
            console.print("[bright_cyan]  Upgrading pip…[/bright_cyan]")
            _run_visible([str(pip), "install", "--quiet", "--upgrade", "pip"], console)
    return ok


def repair_broken_venv(
    broken: BrokenVenv,
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> bool:
    """Recreate a broken venv (source Python gone) with the target Python."""
    new_python = str(target_python) if target_python else sys.executable
    console.print(
        f"\n[bright_yellow]Repairing broken venv:[/bright_yellow] {broken.venv_base}\n"
        f"  [dim]Missing source: {broken.missing_home}[/dim]\n"
        f"  [bright_cyan]New Python:[/bright_cyan] {new_python}"
    )

    # Read packages before deleting
    packages = get_pip_packages(broken.venv_base)
    if packages:
        console.print(f"  [bright_cyan]Preserving {len(packages)} package(s)[/bright_cyan]")

    if dry_run:
        console.print(f"  [bright_yellow][DRY RUN] Would recreate {broken.venv_base}[/bright_yellow]")
        return True

    req_backup = broken.venv_base.parent / f"{broken.venv_base.name}_requirements_backup.txt"
    if packages:
        req_backup.write_text("\n".join(packages) + "\n")

    import shutil as _shutil
    _shutil.rmtree(broken.venv_base, ignore_errors=True)

    if not _run_visible([new_python, "-m", "venv", str(broken.venv_base)], console):
        console.print(f"  [bright_red]Failed to recreate {broken.venv_base}[/bright_red]")
        return False

    if packages:
        pip = _pip_in_venv(broken.venv_base)
        _run_visible([str(pip), "install", "--quiet", "-r", str(req_backup)], console)

    pip = _pip_in_venv(broken.venv_base)
    if pip.exists():
        _run_visible([str(pip), "install", "--quiet", "--upgrade", "pip"], console)

    console.print(f"  [bright_green]✓ Repaired.[/bright_green]")
    return True


# ── Full auto orchestrator ────────────────────────────────────────────────────

def run_full_auto(
    installs: list[PythonInstall],
    latest_stable: Optional[str],
    venv_search_paths: list[Path],
    console: Console,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    from rich.prompt import Confirm

    def _header(title: str) -> None:
        console.print()
        console.print(Rule(f"[bold bright_magenta]{title}[/bold bright_magenta]", style="bright_magenta"))
        console.print()

    # ── Plan ──────────────────────────────────────────────────────────────
    _header("FULL AUTO — REMEDIATION PLAN")

    has_brew = any(i.install_type == "brew" for i in installs if not i.is_venv)
    has_pyenv = any(i.install_type == "pyenv" for i in installs if not i.is_venv)
    venvs_to_fix = [
        i for i in installs
        if i.is_venv and (i.status in ("eol", "security") or i.has_newer_patch or i.has_newer_cycle)
    ]

    console.print("[bright_cyan]Steps that will run:[/bright_cyan]")
    step = 1
    if has_brew:
        console.print(f"  [bright_green]{step}.[/bright_green] brew upgrade python  (all installed Python formulae)")
        step += 1
    if has_pyenv and latest_stable:
        console.print(f"  [bright_green]{step}.[/bright_green] pyenv install {latest_stable} && pyenv global {latest_stable}")
        step += 1

    console.print(f"  [bright_green]{step}.[/bright_green] Scan for broken venvs (source Python deleted)")
    step += 1
    console.print(f"  [bright_green]{step}.[/bright_green] Repair broken venvs")
    step += 1
    console.print(f"  [bright_green]{step}.[/bright_green] Upgrade {len(venvs_to_fix)} out-of-date venv(s) + pip")
    step += 1
    console.print(f"  [bright_green]{step}.[/bright_green] Check PATH shadowing (Homebrew before /usr/bin)")
    step += 1
    console.print(f"  [bright_green]{step}.[/bright_green] Check shell config & .python-version files")

    if dry_run:
        console.print("\n[bright_yellow]  DRY RUN — no changes will be made.[/bright_yellow]")

    if not yes and not dry_run:
        console.print()
        if not Confirm.ask("[bright_magenta]Proceed?[/bright_magenta]", default=True):
            console.print("[dim]Aborted.[/dim]")
            return

    # ── Step 1: Homebrew ──────────────────────────────────────────────────
    if has_brew:
        _header("STEP: BREW UPGRADE PYTHON")
        brew_ok = brew_upgrade_python(console, dry_run=dry_run)
        if brew_ok and not dry_run:
            console.print("  [bright_green]✓ Homebrew Python updated.[/bright_green]")
            console.print("  [dim]Re-scanning to find new Python path…[/dim]")
            # Re-discover the best Python after the upgrade
            from pyhunter.finder import find_all_pythons
            fresh = find_all_pythons()
            supported = [i for i in fresh if i.status == "supported" and not i.is_venv]
            if supported:
                best_fresh = max(supported, key=lambda i: i.version)
                console.print(f"  [bright_green]Best Python now: {best_fresh.version_str} at {best_fresh.path}[/bright_green]")
                # Refresh in the caller's list
                for inst in installs:
                    if inst.path == best_fresh.path:
                        break

    # ── Step 2: pyenv ─────────────────────────────────────────────────────
    if has_pyenv and latest_stable:
        _header("STEP: PYENV INSTALL LATEST")
        pyenv_install_latest(latest_stable, console, dry_run=dry_run)

    # ── Determine best target Python ──────────────────────────────────────
    from pyhunter.finder import find_all_pythons
    if not dry_run and (has_brew or has_pyenv):
        post_upgrade = find_all_pythons()
    else:
        post_upgrade = installs

    best_candidates = [
        i for i in post_upgrade if i.status == "supported" and not i.is_venv and not i.is_current
    ]
    target_python = max(best_candidates, key=lambda i: i.version).path if best_candidates else None
    if target_python:
        console.print(f"\n  [bright_cyan]Using Python {max(best_candidates, key=lambda i: i.version).version_str} for venv recreation.[/bright_cyan]")

    # ── Step 3+4: Broken venvs ────────────────────────────────────────────
    _header("STEP: BROKEN VENV SCAN + REPAIR")
    broken = find_broken_venvs(venv_search_paths)
    if broken:
        console.print(f"  [bright_yellow]Found {len(broken)} broken venv(s):[/bright_yellow]")
        for b in broken:
            console.print(f"    [yellow]{b.venv_base}[/yellow]  [dim](was Python {b.python_version or '?'})[/dim]")
        console.print()
        for b in broken:
            repair_broken_venv(b, target_python, console, dry_run=dry_run)
    else:
        console.print("  [bright_green]✓ No broken venvs found.[/bright_green]")

    # ── Step 5: Upgrade out-of-date venvs ─────────────────────────────────
    _header(f"STEP: UPGRADE {len(venvs_to_fix)} VENV(S) + PIP")
    if venvs_to_fix:
        for inst in venvs_to_fix:
            upgrade_venv_with_pip(inst, target_python, console, dry_run=dry_run)
    else:
        console.print("  [bright_green]✓ All venvs are already up to date.[/bright_green]")

    # ── Step 6: PATH check ────────────────────────────────────────────────
    _header("STEP: PATH SHADOWING CHECK")
    check_path_shadowing(console)

    # ── Step 7: Shell config + .python-version ────────────────────────────
    _header("STEP: SHELL CONFIG CHECK")
    check_shell_config(console)

    # ── Done ──────────────────────────────────────────────────────────────
    console.print()
    console.print(
        Panel(
            "[bright_green]✓ Full auto-remediation complete.[/bright_green]"
            + ("\n[dim]Open a new terminal to pick up any PATH changes.[/dim]" if not dry_run else ""),
            border_style="bright_green",
            box=box.DOUBLE,
        )
    )
