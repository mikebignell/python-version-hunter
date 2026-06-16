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
    suggest_pyenv_upgrade,
    upgrade_venv,
)
from pyhunter.finder import find_all_pythons, PythonInstall
from pyhunter.versions import CycleInfo, fetch_release_info
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
    issues = [i for i in installs if i.status != "supported" or i.is_python2]
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
            choices.append("[A]dvise CLT update")
            valid_keys.append("a")
        elif not inst.is_current:
            choices.append("[D]elete")
            valid_keys.append("d")
        if inst.install_type in ("brew",):
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
            upgrade_venv(inst, None, console, dry_run=dry_run)
        elif answer == "a":
            advise_clt_update(inst, console)
        elif answer == "d":
            delete_python(inst, console, dry_run=dry_run)
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

    if not installs:
        console.print("[bright_red]No Python installations found.[/bright_red]")
        raise typer.Exit(1)

    console.print(make_results_table(installs, cycles=cycles))
    console.print()
    print_summary(installs, console, cycles=cycles)
    console.print()

    # -- Auto upgrade venvs --
    if upgrade_venvs:
        venvs_to_upgrade = [
            i for i in installs if i.is_venv and i.status in ("eol", "security")
        ]
        if venvs_to_upgrade:
            print_action_header(f"AUTO-UPGRADING {len(venvs_to_upgrade)} VENV(S)", console)
            for inst in venvs_to_upgrade:
                upgrade_venv(inst, target_python, console, dry_run=dry_run)
        else:
            console.print("[bright_green]No venvs require upgrading.[/bright_green]")
        console.print()

    # -- Interactive review --
    if interactive:
        _interactive_review(installs, console, dry_run=dry_run)

    # -- Plain scan advice --
    if not interactive and not upgrade_venvs:
        eol = [i for i in installs if i.status == "eol"]
        sec = [i for i in installs if i.status == "security"]
        if eol or sec:
            console.print(
                "[bright_yellow]  TIP:[/bright_yellow] Run with "
                "[bright_green]--interactive[/bright_green] to decide what to do with each issue, "
                "or [bright_green]--upgrade-venvs[/bright_green] to auto-upgrade venvs.\n"
            )
