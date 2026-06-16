"""80s retro terminal UI components."""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule

from pyhunter.finder import PythonInstall
from pyhunter.versions import CycleInfo, eol_date_for, latest_patch_for, latest_stable_version

try:
    import pyfiglet  # type: ignore
    _HAS_FIGLET = True
except ImportError:
    _HAS_FIGLET = False


RETRO_BANNER_FALLBACK = r"""
  ██████╗ ██╗   ██╗    ██╗  ██╗██╗   ██╗███╗  ██╗████████╗███████╗██████╗
  ██╔══██╗╚██╗ ██╔╝    ██║  ██║██║   ██║████╗ ██║╚══██╔══╝██╔════╝██╔══██╗
  ██████╔╝ ╚████╔╝     ███████║██║   ██║██╔██╗██║   ██║   █████╗  ██████╔╝
  ██╔═══╝   ╚██╔╝      ██╔══██║██║   ██║██║╚████║   ██║   ██╔══╝  ██╔══██╗
  ██║        ██║       ██║  ██║╚██████╔╝██║ ╚███║   ██║   ███████╗██║  ██║
  ╚═╝        ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
"""

TAGLINE = "  >>>  F I N D  ·  A U D I T  ·  U P G R A D E  ·  C L E A N U P  <<<"

STATUS_LEGEND = (
    "[bright_green]● SUPPORTED[/bright_green]  "
    "[bright_yellow]◆ SECURITY-ONLY[/bright_yellow]  "
    "[bright_red]■ EOL[/bright_red]  "
    "[red]☠ PYTHON 2 (DEAD)[/red]"
)

TYPE_ICONS = {
    "system":     "⚙",
    "brew":       "🍺",
    "pyenv":      "🐍",
    "conda":      "🅒",
    "python.org": "🐍",
    "venv":       "📦",
    "unknown":    "?",
}

PYTHON2_WARNING = """\
[bold red]☠  PYTHON 2 ALERT[/bold red]
Python 2 reached permanent end-of-life on [bold]1 January 2020[/bold].
[bright_red]There are no security updates, no patches, and no exceptions — ever.[/bright_red]
The final release (2.7.18, April 2020) was a farewell, not a lifeline.

[bright_yellow]Any Python 2 on your machine is a security liability.[/bright_yellow]
If it is not OS-managed (SIP-protected), it should be deleted.
If it is under [dim]/usr/bin[/dim], see the UPDATE VIA CLT advice above.\
"""


def make_console() -> Console:
    return Console(highlight=False)


def print_banner(console: Console) -> None:
    if _HAS_FIGLET:
        art = pyfiglet.figlet_format("PY HUNTER", font="banner3")
        console.print(f"[bright_green]{art}[/bright_green]")
    else:
        console.print(f"[bright_green]{RETRO_BANNER_FALLBACK}[/bright_green]")
    console.print(f"[bright_cyan]{TAGLINE}[/bright_cyan]")
    console.print(Rule(style="bright_cyan"))
    console.print()


def _latest_cell(inst: PythonInstall, cycles: Optional[list[CycleInfo]]) -> Text:
    """Build the 'Latest' table cell for a single install."""
    if cycles is None:
        return Text("(offline)", style="dim")

    if inst.is_python2:
        return Text("2.7.18  final ever", style="red")

    latest = latest_patch_for(inst.major_minor, cycles)
    if latest is None:
        return Text("—", style="dim")

    installed = inst.version_str
    if installed == latest:
        return Text(f"✓ {latest}", style="bright_green")

    # Compare patch versions
    try:
        inst_parts = tuple(int(x) for x in installed.split("."))
        lat_parts = tuple(int(x) for x in latest.split("."))
        if inst_parts >= lat_parts:
            return Text(f"✓ {latest}", style="bright_green")
    except ValueError:
        pass

    eol_date = eol_date_for(inst.major_minor, cycles)
    eol_str = f"\n[dim]EOL {eol_date}[/dim]" if eol_date and eol_date != "unknown" else ""
    return Text.from_markup(f"[bright_yellow]→ {latest}[/bright_yellow]{eol_str}")


def make_results_table(
    installs: list[PythonInstall],
    cycles: Optional[list[CycleInfo]] = None,
) -> Table:
    table = Table(
        box=box.DOUBLE,
        border_style="bright_cyan",
        header_style="bold bright_cyan",
        show_lines=True,
        title="[bold bright_cyan]■ PYTHON INSTALLATIONS DETECTED ■[/bold bright_cyan]",
        title_style="bright_cyan",
        caption=STATUS_LEGEND,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Installed", style="bold", min_width=10)
    table.add_column("Status", min_width=14)
    table.add_column("Type", min_width=10)
    table.add_column("Latest Patch", min_width=16)
    table.add_column("Action", min_width=16)
    table.add_column("Path", style="dim", overflow="fold")

    for i, inst in enumerate(installs, 1):
        ver_text = Text(inst.version_str)
        if inst.is_current:
            ver_text.append(" ◀ YOU", style="bright_magenta")
        color = "red" if inst.is_python2 else inst.status_color
        ver_text.stylize(color)

        status_text = Text(inst.status_label, style=color)

        icon = TYPE_ICONS.get(inst.install_type, "?")
        type_label = f"{icon} {inst.install_type}"
        if inst.is_venv and inst.venv_base:
            type_label += f"\n[dim]{inst.venv_base.name}[/dim]"
        type_text = Text.from_markup(type_label, style="bright_cyan")

        latest_text = _latest_cell(inst, cycles)

        action_text = Text(inst.recommendation, style=inst.recommendation_color)

        table.add_row(
            str(i),
            ver_text,
            status_text,
            type_text,
            latest_text,
            action_text,
            str(inst.path),
        )

    return table


def print_summary(
    installs: list[PythonInstall],
    console: Console,
    cycles: Optional[list[CycleInfo]] = None,
) -> None:
    py2 = [i for i in installs if i.is_python2]
    eol = [i for i in installs if i.status == "eol" and not i.is_python2]
    sec = [i for i in installs if i.status == "security"]
    ok  = [i for i in installs if i.status == "supported"]
    venvs = [i for i in installs if i.is_venv]

    # Latest available from endoflife.date
    latest_str = "unavailable (offline)"
    if cycles:
        lv = latest_stable_version(cycles)
        if lv:
            latest_str = f"[bright_green]{lv}[/bright_green]"

    lines = [
        f"  [bright_green]Supported    :[/bright_green] {len(ok):>3}",
        f"  [bright_yellow]Security-only:[/bright_yellow] {len(sec):>3}",
        f"  [bright_red]EOL (Py3)    :[/bright_red] {len(eol):>3}",
        f"  [red]Python 2     :[/red] {len(py2):>3}",
        f"  [bright_cyan]Virtual envs :[/bright_cyan] {len(venvs):>3}",
        f"  [bright_cyan]Total found  :[/bright_cyan] {len(installs):>3}",
        "",
        f"  [bright_cyan]Latest stable:[/bright_cyan] {latest_str}",
    ]

    panel = Panel(
        "\n".join(lines),
        title="[bold bright_cyan]SUMMARY[/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.DOUBLE,
        expand=False,
    )
    console.print(panel)

    if py2:
        console.print()
        console.print(
            Panel(
                PYTHON2_WARNING,
                title="[bold red]☠  PYTHON 2 DETECTED[/bold red]",
                border_style="red",
                box=box.DOUBLE,
            )
        )


def print_action_header(label: str, console: Console) -> None:
    console.print()
    console.print(Rule(f"[bold bright_magenta]{label}[/bold bright_magenta]", style="bright_magenta"))
    console.print()


def print_no_issues(console: Console) -> None:
    console.print(
        Panel(
            "[bright_green]✓ All Python installations are up to date![/bright_green]",
            border_style="bright_green",
            box=box.DOUBLE,
        )
    )


def print_offline_warning(console: Console) -> None:
    console.print(
        "[dim]  ⚠  Could not reach endoflife.date — latest version data unavailable.[/dim]\n"
    )
