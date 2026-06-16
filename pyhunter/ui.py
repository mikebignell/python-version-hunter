"""80s retro terminal UI components."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule

from pyhunter.finder import PythonInstall

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
    "[bright_red]■ EOL[/bright_red]"
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


def make_results_table(installs: list[PythonInstall]) -> Table:
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
    table.add_column("Version", style="bold", min_width=10)
    table.add_column("Status", min_width=14)
    table.add_column("Type", min_width=10)
    table.add_column("Action", min_width=16)
    table.add_column("Path", style="dim", overflow="fold")

    for i, inst in enumerate(installs, 1):
        # version cell
        ver_text = Text(inst.version_str)
        if inst.is_current:
            ver_text.append(" ◀ YOU", style="bright_magenta")
        ver_text.stylize(inst.status_color)

        # status cell
        status_text = Text(inst.status_label, style=inst.status_color)

        # type cell
        icon = TYPE_ICONS.get(inst.install_type, "?")
        type_label = f"{icon} {inst.install_type}"
        if inst.is_venv and inst.venv_base:
            type_label += f"\n[dim]{inst.venv_base.name}[/dim]"
        type_text = Text.from_markup(type_label, style="bright_cyan")

        # action cell
        action_text = Text(inst.recommendation, style=inst.recommendation_color)

        table.add_row(
            str(i),
            ver_text,
            status_text,
            type_text,
            action_text,
            str(inst.path),
        )

    return table


def print_summary(installs: list[PythonInstall], console: Console) -> None:
    eol = [i for i in installs if i.status == "eol"]
    sec = [i for i in installs if i.status == "security"]
    ok = [i for i in installs if i.status == "supported"]
    venvs = [i for i in installs if i.is_venv]

    lines = [
        f"  [bright_green]Supported  :[/bright_green] {len(ok):>3}",
        f"  [bright_yellow]Security   :[/bright_yellow] {len(sec):>3}",
        f"  [bright_red]EOL        :[/bright_red] {len(eol):>3}",
        f"  [bright_cyan]Virtual envs:[/bright_cyan] {len(venvs):>3}",
        f"  [bright_cyan]Total found :[/bright_cyan] {len(installs):>3}",
    ]
    panel = Panel(
        "\n".join(lines),
        title="[bold bright_cyan]SUMMARY[/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.DOUBLE,
        expand=False,
    )
    console.print(panel)


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
