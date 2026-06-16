"""Main CLI entry point."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.prompt import Confirm, Prompt
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from pyhunter import __version__
from pyhunter.actions import (
    advise_clt_update,
    delete_python,
    suggest_brew_upgrade,
    suggest_cycle_upgrade,
    suggest_patch_update,
    suggest_pyenv_upgrade,
    upgrade_venv,
)
from pyhunter.auto import run_full_auto, brew_cleanup_old_pythons, brew_remove_old_formulae, find_chained_venvs
from pyhunter.finder import find_all_pythons, PythonInstall
from pyhunter.versions import CycleInfo, fetch_release_info, latest_patch_for, latest_stable_version
from pyhunter.ui import (
    make_console,
    make_results_table,
    print_action_header,
    print_banner,
    print_no_issues,
    print_offline_warning,
    print_summary,
)

app = typer.Typer(
    name="pyhunter",
    help="🐍 Python Version Hunter — find, audit, and clean up Python installations.",
    add_completion=False,
    rich_markup_mode="rich",
)


def _is_inside_venv_dir(path: Path) -> bool:
    """True if any parent of path contains pyvenv.cfg — i.e. it lives inside a venv."""
    for parent in path.parents:
        if (parent / "pyvenv.cfg").exists():
            return True
    return False


def _best_python(installs: list[PythonInstall]) -> Optional[Path]:
    """Return the path to the highest supported, non-venv Python found."""
    candidates = [
        i for i in installs
        if not i.is_venv
        and not i.is_current
        and i.status == "supported"
        and not _is_inside_venv_dir(i.path)  # guard against venv Pythons missed by scanner
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda i: i.version)
    return best.path


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pyhunter {__version__}")
        raise typer.Exit()


def _scan_with_progress(
    extra_paths: list[Path],
    venv_paths: list[Path],
    console,
) -> tuple[list[PythonInstall], Optional[list[CycleInfo]]]:
    with Progress(
        SpinnerColumn(spinner_name="dots", style="bright_magenta"),
        TextColumn("[bright_green]{task.description}[/bright_green]"),
        BarColumn(bar_width=30, style="bright_cyan", complete_style="bright_green"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Fetching latest version data…", total=None)
        cycles = fetch_release_info()

        def _cb_live(msg: str) -> None:
            progress.update(task, description=msg[:60])

        _cb_live("Scanning system for Python installations…")
        installs = find_all_pythons(
            extra_paths=extra_paths or None,
            venv_search_paths=venv_paths or None,
            progress_callback=_cb_live,
        )

    return installs, cycles


def _interactive_review(installs: list[PythonInstall], console, dry_run: bool) -> None:
    """Walk the user through each non-OK installation one at a time."""
    issues = [
        i for i in installs
        if i.status != "supported" or i.has_newer_patch or i.has_newer_cycle or i.is_python2
    ]
    if not issues:
        print_no_issues(console)
        return

    print_action_header(f"INTERACTIVE REVIEW  ({len(issues)} items)", console)

    for idx, inst in enumerate(issues, 1):
        console.print(
            f"[bright_cyan]({idx}/{len(issues)})[/bright_cyan] "
            f"[{inst.status_color}]{inst.version_str}[/{inst.status_color}] "
            f"[dim]{inst.path}[/dim]"
        )
        console.print(
            f"  Status: [{inst.status_color}]{inst.status_label}[/{inst.status_color}]  "
            f"Type: [bright_cyan]{inst.install_type}[/bright_cyan]  "
            f"Recommended: [{inst.recommendation_color}]{inst.recommendation}[/{inst.recommendation_color}]"
        )
        if inst.is_venv and inst.venv_base:
            console.print(f"  Venv base: [dim]{inst.venv_base}[/dim]")

        # Build choices
        valid_keys: list[str] = []
        choices: list[str] = []
        if inst.is_venv:
            choices.append("[U]pgrade venv")
            valid_keys.append("u")
        if inst.is_os_managed:
            choices.append("[A]dvise pkg-mgr update")
            valid_keys.append("a")
        elif not inst.is_current:
            choices.append("[D]elete")
            valid_keys.append("d")
        if inst.has_newer_cycle and not inst.is_venv:
            choices.append("[U]pgrade to latest Python")
            if "u" not in valid_keys:
                valid_keys.append("u")
        if inst.has_newer_patch and not inst.is_venv and not inst.has_newer_cycle:
            choices.append("[P]atch update advice")
            valid_keys.append("p")
        elif not inst.has_newer_cycle and inst.install_type == "brew":
            choices.append("[S]uggest brew upgrade")
            if "s" not in valid_keys:
                valid_keys.append("s")
        elif inst.install_type == "pyenv":
            choices.append("[S]uggest pyenv upgrade")
            if "s" not in valid_keys:
                valid_keys.append("s")
        choices.append("[K]eep / skip")
        valid_keys.append("k")

        choice_str = "  ".join(choices)
        console.print(f"  Options: [bright_magenta]{choice_str}[/bright_magenta]")
        answer = Prompt.ask(
            "  [bright_cyan]Action[/bright_cyan]",
            choices=valid_keys,
            default="k",
        ).lower()

        if answer == "u" and inst.is_venv:
            upgrade_venv(inst, _best_python(installs), console, dry_run=dry_run)
        elif answer == "u" and inst.has_newer_cycle:
            suggest_cycle_upgrade(inst, console)
        elif answer == "a":
            advise_clt_update(inst, console)
        elif answer == "d":
            delete_python(inst, console, dry_run=dry_run)
        elif answer == "p":
            suggest_patch_update(inst, console)
        elif answer == "s":
            if inst.install_type == "pyenv":
                suggest_pyenv_upgrade(inst, console)
            else:
                suggest_brew_upgrade(inst, console)
        else:
            console.print("[dim]  Skipped.[/dim]")

        console.print()


@app.command()
def main(
    scan_home: Annotated[
        bool,
        typer.Option("--scan-home", "-H", help="Scan home directory for virtual environments."),
    ] = True,
    scan_paths: Annotated[
        Optional[list[Path]],
        typer.Option("--scan-path", "-p", help="Extra directories to scan for venvs."),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Interactively decide what to do with each issue."),
    ] = False,
    upgrade_venvs: Annotated[
        bool,
        typer.Option("--upgrade-venvs", "-u", help="Automatically upgrade all EOL/security venvs."),
    ] = False,
    target_python: Annotated[
        Optional[Path],
        typer.Option("--target-python", "-t", help="Python executable to use when upgrading venvs."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would be done without making changes."),
    ] = False,
    no_venvs: Annotated[
        bool,
        typer.Option("--no-venvs", help="Skip virtual environment scanning."),
    ] = False,
    brew_cleanup: Annotated[
        bool,
        typer.Option(
            "--brew-cleanup",
            help=(
                "Remove stale Python versions from the Homebrew Cellar. "
                "Upgrades any venvs that still reference them before cleaning."
            ),
        ),
    ] = False,
    brew_remove_old: Annotated[
        bool,
        typer.Option(
            "--brew-remove-old",
            help=(
                "Uninstall old Homebrew Python minor-version formulae (e.g. python@3.13 "
                "when python@3.14 is installed). Migrates dependent venvs first."
            ),
        ),
    ] = False,
    full_auto: Annotated[
        bool,
        typer.Option(
            "--full-auto", "-A",
            help=(
                "Full auto-remediation: upgrade Homebrew Python, repair broken venvs, "
                "upgrade all venvs to the latest Python, and verify PATH + shell config."
            ),
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts (use with --full-auto)."),
    ] = False,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """
    [bold bright_cyan]PY HUNTER[/bold bright_cyan] — Scan your system for all Python installations,
    show their compliance status, and help you clean up old or non-compliant versions.
    """
    console = make_console()
    print_banner(console)

    # Build venv search paths
    venv_paths: list[Path] = []
    if not no_venvs:
        if scan_home:
            venv_paths.append(Path.home())
        if scan_paths:
            venv_paths.extend(scan_paths)

    if dry_run:
        console.print("[bright_yellow]  ⚠  DRY RUN MODE — no changes will be made.[/bright_yellow]\n")

    installs, cycles = _scan_with_progress(
        extra_paths=list(scan_paths or []),
        venv_paths=venv_paths,
        console=console,
    )

    if cycles is None:
        print_offline_warning(console)
    else:
        latest = latest_stable_version(cycles)
        for inst in installs:
            inst.latest_patch = latest_patch_for(inst.major_minor, cycles)
            inst.latest_stable = latest

    if not installs:
        console.print("[bright_red]No Python installations found.[/bright_red]")
        raise typer.Exit(1)

    console.print(make_results_table(installs, cycles=cycles))
    console.print()
    print_summary(installs, console, cycles=cycles)

    if venv_paths:
        chained = find_chained_venvs(venv_paths)
        if chained:
            console.print()
            console.print(
                "[bright_yellow]  ⚠  CHAINED VENV(S) DETECTED[/bright_yellow] — "
                f"{len(chained)} venv(s) are sourced from another venv's Python "
                "(fragile — breaks if the parent venv is deleted or recreated):"
            )
            for c in chained:
                console.print(
                    f"    [yellow]{c.venv_base}[/yellow]  "
                    f"[dim]Python {c.python_version or '?'} → home inside {c.chained_venv}[/dim]"
                )
            console.print(
                "  Run [bright_green]pyhunter --full-auto[/bright_green] to repair."
            )
    console.print()

    # -- Auto upgrade venvs --
    if upgrade_venvs:
        venvs_to_upgrade = [
            i for i in installs
            if i.is_venv and (
                i.status in ("eol", "security") or i.has_newer_patch or i.has_newer_cycle
            )
        ]
        # Auto-select the best available Python if no explicit target given.
        effective_target = target_python or _best_python(installs)
        if effective_target and effective_target != Path(sys.executable):
            console.print(
                f"[bright_cyan]  Target Python:[/bright_cyan] {effective_target}\n"
            )
        if venvs_to_upgrade:
            print_action_header(f"AUTO-UPGRADING {len(venvs_to_upgrade)} VENV(S)", console)
            for inst in venvs_to_upgrade:
                upgrade_venv(inst, effective_target, console, dry_run=dry_run)
        else:
            console.print("[bright_green]No venvs require upgrading.[/bright_green]")
        console.print()

    # -- Interactive review --
    if interactive:
        _interactive_review(installs, console, dry_run=dry_run)

    # -- Remove old Homebrew minor-version formulae --
    if brew_remove_old:
        print_action_header("BREW REMOVE OLD PYTHON FORMULAE", console)
        brew_remove_old_formulae(
            venv_search_paths=venv_paths,
            target_python=target_python or _best_python(installs),
            console=console,
            dry_run=dry_run,
        )
        console.print()

    # -- Brew Cellar cleanup --
    if brew_cleanup:
        print_action_header("BREW CLEANUP — STALE CELLAR PYTHONS", console)
        brew_cleanup_old_pythons(
            venv_search_paths=venv_paths,
            target_python=target_python or _best_python(installs),
            console=console,
            dry_run=dry_run,
        )
        console.print()

    # -- Full auto mode --
    if full_auto:
        latest = latest_stable_version(cycles) if cycles else None
        run_full_auto(
            installs=installs,
            latest_stable=latest,
            venv_search_paths=venv_paths,
            console=console,
            dry_run=dry_run,
            yes=yes,
        )
        return

    # -- Plain scan advice --
    if not interactive and not upgrade_venvs:
        eol = [i for i in installs if i.status == "eol"]
        sec = [i for i in installs if i.status == "security"]
        if eol or sec:
            console.print(
                "[bright_yellow]  TIP:[/bright_yellow] Run with "
                "[bright_green]--interactive[/bright_green] to decide what to do with each issue, "
                "[bright_green]--upgrade-venvs[/bright_green] to auto-upgrade venvs, or "
                "[bright_green]--full-auto[/bright_green] for full automated remediation.\n"
            )
