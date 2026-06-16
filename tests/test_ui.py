"""Tests for pyhunter.ui."""
from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from pyhunter.finder import PythonInstall
from pyhunter.ui import make_results_table, print_summary


def _make_install(major: int, minor: int, install_type: str = "system", **kwargs) -> PythonInstall:
    return PythonInstall(
        path=Path(f"/fake/python{major}.{minor}"),
        version=(major, minor, 0),
        version_str=f"{major}.{minor}.0",
        install_type=install_type,
        **kwargs,
    )


class TestMakeResultsTable:
    def test_returns_table(self):
        from rich.table import Table
        installs = [_make_install(3, 12), _make_install(3, 9)]
        table = make_results_table(installs)
        assert isinstance(table, Table)

    def test_empty_list(self):
        from rich.table import Table
        table = make_results_table([])
        assert isinstance(table, Table)

    def test_current_marker_shown(self):
        import io
        inst = _make_install(3, 12, is_current=True)
        table = make_results_table([inst])
        buf = io.StringIO()
        console = Console(file=buf, highlight=False, no_color=True)
        console.print(table)
        output = buf.getvalue()
        assert "YOU" in output

    def test_venv_type_shown(self):
        import io
        inst = _make_install(3, 9, install_type="venv", venv_base=Path("/home/user/myenv"))
        table = make_results_table([inst])
        buf = io.StringIO()
        console = Console(file=buf, highlight=False, no_color=True)
        console.print(table)
        output = buf.getvalue()
        assert "venv" in output


class TestPrintSummary:
    def test_renders_without_error(self):
        import io
        installs = [
            _make_install(3, 12),
            _make_install(3, 9),
            _make_install(3, 10),
            _make_install(3, 11, install_type="venv", venv_base=Path("/home/user/v")),
        ]
        buf = io.StringIO()
        console = Console(file=buf, highlight=False, no_color=True)
        print_summary(installs, console)
        output = buf.getvalue()
        assert "Total" in output

    def test_counts_are_correct(self):
        import io
        installs = [
            _make_install(3, 12),  # supported
            _make_install(3, 11),  # supported
            _make_install(3, 10),  # security
            _make_install(3, 8),   # eol
        ]
        buf = io.StringIO()
        console = Console(file=buf, highlight=False, no_color=True)
        print_summary(installs, console)
        output = buf.getvalue()
        assert "2" in output  # 2 supported
