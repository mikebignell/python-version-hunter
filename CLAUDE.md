# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all tests
.venv/bin/pytest

# Run a single test file
.venv/bin/pytest tests/test_auto.py

# Run a single test by name
.venv/bin/pytest tests/test_auto.py::TestBrewUpgradePython::test_already_up_to_date_skips_upgrade

# Run with coverage
.venv/bin/pytest --cov=pyhunter --cov-report=term-missing

# Run the CLI
.venv/bin/pyhunter
.venv/bin/pyhunter --full-auto --dry-run
```

## Architecture

The tool is split into four focused modules plus a CLI and UI layer:

**`finder.py`** — Discovery only. `find_all_pythons()` is the main entry point: it calls `scan_path_executables()`, `scan_common_dirs()`, and `scan_venvs()`, then deduplicates by resolved path. Returns a list of `PythonInstall` dataclasses. `PythonInstall` is a pure data object — its `status`, `is_venv`, `has_newer_patch` etc. are all computed properties derived from its fields. No side effects.

**`versions.py`** — Network only. Fetches cycle data from `endoflife.date/api/python.json` and returns `CycleInfo` objects. Always degrades gracefully (returns `None`) on network failure — callers must handle this.

**`actions.py`** — Single-install operations. `upgrade_venv()` is the core venv rebuild: freeze → backup → delete → recreate → reinstall. `_run_visible()` streams subprocess output to the console; `_run_capturing()` captures it silently (used where output would alarm users, e.g. SSL cert installation). `ensure_ssl_certs()` handles python.org Framework Pythons which lack CA certs by default.

**`auto.py`** — Orchestration. `run_full_auto()` is the `--full-auto` pipeline. Also contains all Homebrew logic (`brew_upgrade_python`, `brew_remove_old_formulae`, `brew_cleanup_old_pythons`) and venv-health checks (`find_broken_venvs`, `find_chained_venvs`). `_brew_python_formulae()` parses `brew list --formula --versions`; `brew_upgrade_python()` calls `brew outdated` first to skip the upgrade if already current.

**`cli.py`** — Typer app. `_best_python()` selects the highest supported, non-venv Python for use as an upgrade target — it guards against selecting a Python that lives inside a venv dir via `_is_inside_venv_dir()`.

**`ui.py`** — Rich rendering. `make_results_table()` and `print_summary()` are the main display functions.

## Key invariants

**Venv detection via `pyvenv.cfg`**: venv membership is determined by walking parent directories looking for `pyvenv.cfg`, not by path prefix matching. This matters because macOS venv Pythons are often symlinks that `resolve()` to `/opt/homebrew/...` — always check both the original path and the resolved path (see `find_all_pythons()` in finder.py).

**`_best_python()` guard**: When selecting the upgrade target Python, `_is_inside_venv_dir()` is a belt-and-braces check in addition to the `is_venv` flag, because the scanner can miss some venv Pythons (e.g. `python3.14` siblings in a venv's bin dir).

**Same-version upgrade guard**: In `upgrade_venv()`, if the best available local Python is the same version as the venv already uses, the upgrade is skipped with an actionable message. `endoflife.date` may report a newer patch than is locally installed.

**Homebrew formula management**: `python@3.13` and `python@3.14` are separate Homebrew formulae. `brew_upgrade_python()` only upgrades the latest minor-version formula. `brew_remove_old_formulae()` uses `brew uses --installed <formula>` (not `brew deps`) to find dependents, then separates same-version companions (e.g. `python-tk@3.13`) from unrelated blockers. Companions get their new-version equivalent installed before the old one is removed.

## Docs rule

**Every code change must update both `README.md` and `docs/index.html` in the same commit.** The GitHub Pages site is at `docs/index.html` — check the feature cards, quick-start terminal, full-auto step list, and options table when adding flags or changing behaviour.
