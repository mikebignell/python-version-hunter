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

from pyhunter.actions import _run_visible, _pip_in_venv, upgrade_venv, ensure_ssl_certs, _reinstall_packages
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


@dataclass
class ChainedVenv:
    venv_base: Path
    chained_home: Path     # the home= path, which is itself inside another venv
    chained_venv: Path     # the parent venv that home= lives inside
    python_version: Optional[str]


def find_chained_venvs(search_paths: list[Path], max_depth: int = 5) -> list[ChainedVenv]:
    """
    Find venvs whose pyvenv.cfg home= path lives inside another venv.
    This happens when a venv was created using a venv Python (e.g. a tool's
    own .venv) rather than a standalone Homebrew or system Python.
    The child venv works as long as the parent venv exists and is unchanged,
    but is silently broken if the parent venv is deleted or recreated.
    """
    chained: list[ChainedVenv] = []
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
                    # Check if home= path is inside another venv
                    for parent in home_path.parents:
                        if (parent / "pyvenv.cfg").exists() and parent.resolve() != resolved:
                            chained.append(ChainedVenv(
                                venv_base=resolved,
                                chained_home=home_path,
                                chained_venv=parent.resolve(),
                                python_version=data.get("version"),
                            ))
                            break
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
    return chained


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


# ── Homebrew upgrade + old formula removal ────────────────────────────────────

def _brew_python_formulae() -> list[tuple[str, tuple[int, int]]]:
    """Return [(formula_name, (major, minor))] for all installed Python formulae."""
    brew = shutil.which("brew")
    if not brew:
        return []
    result = subprocess.run([brew, "list", "--formula", "--versions"], capture_output=True, text=True)
    out: list[tuple[str, tuple[int, int]]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if not re.match(r"^python(@\d+\.\d+)?$", name):
            continue
        # Version from formula name (python@3.13) or from installed version string
        m = re.search(r"@(\d+)\.(\d+)$", name)
        if m:
            out.append((name, (int(m.group(1)), int(m.group(2)))))
        else:
            # plain "python" — parse version from the version column
            ver = parts[1] if len(parts) > 1 else ""
            vm = re.match(r"(\d+)\.(\d+)", ver)
            if vm:
                out.append((name, (int(vm.group(1)), int(vm.group(2)))))
    return out


def brew_upgrade_python(console: Console, dry_run: bool = False) -> bool:
    """Upgrade only the latest Homebrew Python formula; skip older minor versions."""
    brew = shutil.which("brew")
    if not brew:
        console.print("  [bright_yellow]Homebrew not found — skipping.[/bright_yellow]")
        return False

    formulae = _brew_python_formulae()
    if not formulae:
        console.print("  [bright_yellow]No Homebrew Python formulae found.[/bright_yellow]")
        return False

    latest_mm = max(mm for _, mm in formulae)
    latest_formulae = [name for name, mm in formulae if mm == latest_mm]
    old_formulae    = [name for name, mm in formulae if mm < latest_mm]

    if old_formulae:
        console.print(
            f"  [dim]Skipping older formulae (to be removed after venv migration): "
            f"{', '.join(old_formulae)}[/dim]"
        )

    console.print(f"  [bright_cyan]Upgrading:[/bright_cyan] {', '.join(latest_formulae)}")
    if dry_run:
        console.print(f"  [bright_yellow][DRY RUN] Would run: brew upgrade {' '.join(latest_formulae)}[/bright_yellow]")
        return True

    return _run_visible([brew, "upgrade"] + latest_formulae, console)


def brew_remove_old_formulae(
    venv_search_paths: list[Path],
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> None:
    """
    Uninstall Homebrew Python formulae for older minor versions.
    Upgrades any venvs still referencing them first, then removes them.
    """
    brew = shutil.which("brew")
    if not brew:
        return

    formulae = _brew_python_formulae()
    if not formulae:
        return

    latest_mm = max(mm for _, mm in formulae)
    old_formulae = [(name, mm) for name, mm in formulae if mm < latest_mm]

    if not old_formulae:
        console.print("  [bright_green]✓ No old Python formulae to remove.[/bright_green]")
        return

    console.print(
        f"  [bright_yellow]Old formulae to remove:[/bright_yellow] "
        f"{', '.join(name for name, _ in old_formulae)}"
    )

    # Find venvs still referencing these formulae's Cellar paths
    for formula_name, mm in old_formulae:
        cellar_pattern = re.compile(
            rf"/opt/homebrew/Cellar/{re.escape(formula_name)}/"
            rf"|/usr/local/Cellar/{re.escape(formula_name)}/"
            rf"|Python\.framework/Versions/{mm[0]}\.{mm[1]}/"
        )

        live_at_risk: list[Path] = []
        for venv_root in venv_search_paths:
            def _check(path: Path, depth: int) -> None:
                if depth > 5:
                    return
                try:
                    cfg = path / "pyvenv.cfg"
                    if cfg.is_file():
                        data = _parse_pyvenv_cfg(cfg)
                        home = data.get("home", "")
                        if cellar_pattern.search(home):
                            live_at_risk.append(path.resolve())
                        return
                    for entry in path.iterdir():
                        try:
                            if (
                                entry.is_dir()
                                and not entry.name.startswith(".")
                                and not entry.is_symlink()
                                and entry.name not in _SCAN_SKIP_DIRS
                            ):
                                _check(entry, depth + 1)
                        except _SCAN_ERRORS:
                            continue
                except _SCAN_ERRORS:
                    pass
            if venv_root.is_dir():
                _check(venv_root, 0)

        if live_at_risk:
            console.print(
                f"  [bright_yellow]⚠  {len(live_at_risk)} venv(s) still reference "
                f"{formula_name} — upgrading before removal:[/bright_yellow]"
            )
            from pyhunter.finder import PythonInstall, scan_venvs
            venv_results = scan_venvs(venv_search_paths)
            for venv_path in live_at_risk:
                matches = [r for r in venv_results if r[1] == venv_path]
                if matches:
                    py_path, venv_base, ver_str, install_type = matches[0]
                    ver_tuple = tuple(int(x) for x in ver_str.split(".")) if ver_str else (0, 0, 0)
                    inst = PythonInstall(
                        path=py_path,
                        version=ver_tuple,
                        version_str=ver_str or "?",
                        install_type=install_type,
                        venv_base=venv_base,
                    )
                    upgrade_venv_with_pip(inst, target_python, console, dry_run=dry_run)

        if dry_run:
            console.print(f"  [bright_yellow][DRY RUN] Would run: brew uninstall {formula_name}[/bright_yellow]")
        else:
            console.print(f"  [bright_cyan]Removing {formula_name}…[/bright_cyan]")
            _run_visible([brew, "uninstall", formula_name], console)


# ── Homebrew Cellar cleanup ───────────────────────────────────────────────────

def _brew_stale_cellar_paths(console: Console) -> list[Path]:
    """Return Cellar paths that `brew cleanup --dry-run` would remove."""
    brew = shutil.which("brew")
    if not brew:
        return []
    result = subprocess.run(
        [brew, "cleanup", "--dry-run"],
        capture_output=True, text=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        # Lines look like: "Removing python@3.14: 3.14.5 ..."  or just the path
        m = re.match(r".*(/opt/homebrew/Cellar/\S+|/usr/local/Cellar/\S+)", line)
        if m:
            p = Path(m.group(1))
            if p.exists():
                paths.append(p)
    return paths


def brew_cleanup_old_pythons(
    venv_search_paths: list[Path],
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> None:
    """
    Run `brew cleanup` for Python formulae, but only after ensuring no venv
    still references the Cellar paths that would be removed.
    """
    brew = shutil.which("brew")
    if not brew:
        console.print("  [bright_yellow]Homebrew not found — skipping.[/bright_yellow]")
        return

    stale_paths = _brew_stale_cellar_paths(console)
    python_stale = [p for p in stale_paths if "python" in p.parts[-3].lower()]

    if not python_stale:
        console.print("  [bright_green]✓ No stale Python Cellar entries to clean up.[/bright_green]")
        return

    console.print(f"  [bright_cyan]Stale Cellar entries found:[/bright_cyan]")
    for p in python_stale:
        console.print(f"    [dim]{p}[/dim]")

    # Cross-reference: any venv whose pyvenv.cfg home= lives inside a stale path?
    at_risk: list[BrokenVenv] = []
    for venv_root in venv_search_paths:
        for bv in find_broken_venvs([venv_root]):
            for stale in python_stale:
                try:
                    bv.missing_home.relative_to(stale)
                    at_risk.append(bv)
                    break
                except ValueError:
                    pass

    # Also scan live venvs
    live_at_risk: list[Path] = []
    for venv_root in venv_search_paths:
        def _check_venv(path: Path, depth: int) -> None:
            if depth > 5:
                return
            try:
                cfg = path / "pyvenv.cfg"
                if cfg.is_file():
                    data = _parse_pyvenv_cfg(cfg)
                    home = data.get("home")
                    if home:
                        for stale in python_stale:
                            try:
                                Path(home).relative_to(stale)
                                live_at_risk.append(path.resolve())
                                return
                            except ValueError:
                                pass
                    return
                for entry in path.iterdir():
                    try:
                        if (
                            entry.is_dir()
                            and not entry.name.startswith(".")
                            and not entry.is_symlink()
                            and entry.name not in _SCAN_SKIP_DIRS
                        ):
                            _check_venv(entry, depth + 1)
                    except _SCAN_ERRORS:
                        continue
            except _SCAN_ERRORS:
                pass
        if venv_root.is_dir():
            _check_venv(venv_root, 0)

    if live_at_risk:
        console.print(
            f"\n  [bright_yellow]⚠  {len(live_at_risk)} venv(s) still reference stale Cellar paths "
            f"— upgrading before cleanup:[/bright_yellow]"
        )
        from pyhunter.finder import PythonInstall, scan_venvs
        venv_results = scan_venvs(venv_search_paths)
        for venv_path in live_at_risk:
            matches = [
                (py_path, venv_base, ver_str, install_type)
                for py_path, venv_base, ver_str, install_type in venv_results
                if venv_base == venv_path
            ]
            if matches:
                py_path, venv_base, ver_str, install_type = matches[0]
                ver_tuple = tuple(int(x) for x in ver_str.split(".")) if ver_str else (0, 0, 0)
                inst = PythonInstall(
                    path=py_path,
                    version=ver_tuple,
                    version_str=ver_str or "?",
                    install_type=install_type,
                    venv_base=venv_base,
                )
                upgrade_venv_with_pip(inst, target_python, console, dry_run=dry_run)
            else:
                # Repair it as a broken venv
                repair_broken_venv(
                    BrokenVenv(venv_base=venv_path, missing_home=Path("/stale"), python_version=None),
                    target_python, console, dry_run=dry_run,
                )

    if dry_run:
        console.print(
            f"\n  [bright_yellow][DRY RUN] Would run: brew cleanup[/bright_yellow]\n"
            f"  [dim]({len(python_stale)} stale Python Cellar entries would be removed)[/dim]"
        )
        return

    console.print("\n  [bright_cyan]Running brew cleanup…[/bright_cyan]")
    _run_visible([brew, "cleanup"], console)
    console.print("  [bright_green]✓ Cellar cleaned.[/bright_green]")


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
    """Recreate a venv (upgrade_venv already handles pip bump and SSL certs)."""
    return upgrade_venv(install, target_python, console, dry_run=dry_run)


def repair_broken_venv(
    broken: BrokenVenv,
    target_python: Optional[Path],
    console: Console,
    dry_run: bool = False,
) -> bool:
    """Recreate a broken venv (source Python gone) with the target Python."""
    from pyhunter.finder import get_version
    new_python = str(target_python) if target_python else sys.executable
    new_ver_result = get_version(Path(new_python))
    new_ver_str = new_ver_result[1] if new_ver_result else new_python
    old_ver_str = broken.python_version or "unknown"

    console.print(
        f"\n[bright_yellow]Repairing broken venv:[/bright_yellow] {broken.venv_base}\n"
        f"  [dim]{old_ver_str}[/dim] [bright_red](source deleted)[/bright_red]"
        f"  [bright_cyan]→[/bright_cyan]  [bright_green]{new_ver_str}[/bright_green]"
    )

    # Read packages before deleting
    packages = get_pip_packages(broken.venv_base)
    if packages:
        console.print(f"  [dim]{len(packages)} package(s) will be preserved[/dim]")

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

    ensure_ssl_certs(Path(new_python), console)

    pip = _pip_in_venv(broken.venv_base)
    _run_visible([str(pip), "install", "--quiet", "--upgrade", "pip"], console)

    if packages:
        _reinstall_packages(pip, packages, req_backup, console)

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
    if has_brew:
        console.print(f"  [bright_green]{step}.[/bright_green] brew cleanup  (remove stale Cellar Pythons, upgrade any venvs that reference them first)")
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

    # ── Step 3+4: Broken + chained venvs ─────────────────────────────────
    _header("STEP: BROKEN + CHAINED VENV SCAN + REPAIR")
    broken = find_broken_venvs(venv_search_paths)
    chained = find_chained_venvs(venv_search_paths)

    if broken:
        console.print(f"  [bright_yellow]Found {len(broken)} broken venv(s) (source Python deleted):[/bright_yellow]")
        for b in broken:
            console.print(f"    [yellow]{b.venv_base}[/yellow]  [dim](was Python {b.python_version or '?'})[/dim]")
        console.print()
        for b in broken:
            repair_broken_venv(b, target_python, console, dry_run=dry_run)
    else:
        console.print("  [bright_green]✓ No broken venvs found.[/bright_green]")

    if chained:
        console.print(
            f"\n  [bright_yellow]Found {len(chained)} chained venv(s) "
            f"(sourced from another venv — fragile coupling):[/bright_yellow]"
        )
        for c in chained:
            console.print(
                f"    [yellow]{c.venv_base}[/yellow]  "
                f"[dim]→ home inside {c.chained_venv}[/dim]"
            )
        console.print()
        for c in chained:
            console.print(f"  [bright_cyan]Repairing chained venv:[/bright_cyan] {c.venv_base}")
            repair_broken_venv(
                BrokenVenv(
                    venv_base=c.venv_base,
                    missing_home=c.chained_home,
                    python_version=c.python_version,
                ),
                target_python, console, dry_run=dry_run,
            )
    elif not broken:
        console.print("  [bright_green]✓ No chained venvs found.[/bright_green]")

    # ── Step 5: Upgrade out-of-date venvs ─────────────────────────────────
    _header(f"STEP: UPGRADE {len(venvs_to_fix)} VENV(S) + PIP")
    if venvs_to_fix:
        for inst in venvs_to_fix:
            upgrade_venv_with_pip(inst, target_python, console, dry_run=dry_run)
    else:
        console.print("  [bright_green]✓ All venvs are already up to date.[/bright_green]")

    # ── Brew: remove old minor-version formulae ───────────────────────────
    if has_brew:
        _header("STEP: BREW REMOVE OLD PYTHON FORMULAE")
        brew_remove_old_formulae(venv_search_paths, target_python, console, dry_run=dry_run)

    # ── Brew cleanup (stale Cellar patches) ───────────────────────────────
    if has_brew:
        _header("STEP: BREW CLEANUP — STALE CELLAR PYTHONS")
        brew_cleanup_old_pythons(venv_search_paths, target_python, console, dry_run=dry_run)

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
