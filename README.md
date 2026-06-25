# 🐍 PY HUNTER

> **Find. Audit. Upgrade. Clean up.**  
> A retro-styled CLI tool to hunt down every Python installation on your machine, flag the old and non-compliant ones, and help you sort them out.

```
  ██████╗ ██╗   ██╗    ██╗  ██╗██╗   ██╗███╗  ██╗████████╗███████╗██████╗
  ██╔══██╗╚██╗ ██╔╝    ██║  ██║██║   ██║████╗ ██║╚══██╔══╝██╔════╝██╔══██╗
  ██████╔╝ ╚████╔╝     ███████║██║   ██║██╔██╗██║   ██║   █████╗  ██████╔╝
  ██╔═══╝   ╚██╔╝      ██╔══██║██║   ██║██║╚████║   ██║   ██╔══╝  ██╔══██╗
  ██║        ██║       ██║  ██║╚██████╔╝██║ ╚███║   ██║   ███████╗██║  ██║
  ╚═╝        ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
```

[![CI](https://github.com/mikebignell/python-version-hunter/actions/workflows/ci.yml/badge.svg)](https://github.com/mikebignell/python-version-hunter/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-brightgreen)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-cyan.svg)](LICENSE)
[![Vibe coded](https://img.shields.io/badge/vibe_coded-100%25_Claude-%23d97757?logo=anthropic)](https://claude.ai/claude-code)

---

## Features

- **Full system scan** — PATH, Homebrew/Linuxbrew, pyenv, conda/mamba, python.org installs, Microsoft Store
- **Virtual environment discovery** — recursively finds every venv by scanning for `pyvenv.cfg`
- **Live compliance data** — fetches latest patch versions and EOL dates from [endoflife.date](https://endoflife.date/api/python.json) at startup
- **Python 2 detection** — flags all Python 2.x as ☠ DEAD (EOL January 2020, no updates ever)
- **Auto-upgrade venvs** — recreates venvs with a newer Python, preserving all packages
- **Interactive mode** — step through each issue and decide: upgrade, delete, or skip
- **Platform-aware advice** — different instructions for macOS CLT, Linux apt/dnf/pacman, Windows winget
- **Retro 80s UI** — neon green-on-black terminal aesthetic with progress animations

---

## Platform support

| Platform | Scan | Venv upgrade | Notes |
|----------|------|-------------|-------|
| **macOS** | ✅ Full | ✅ | Detects Homebrew, pyenv, conda, python.org framework, system (SIP-aware) |
| **Linux** | ✅ Full | ✅ | Detects Linuxbrew, pyenv, conda, system (package-manager-aware) |
| **Windows** | ✅ Basic | ✅ | Detects python.org, pyenv-win, conda, Scoop, Chocolatey, Microsoft Store |

> **OS-managed Pythons** (macOS `/usr/bin`, Linux `/usr/bin`, Windows Store) are flagged with
> platform-appropriate update instructions rather than a delete prompt — you can't and shouldn't
> remove them directly.

---

## Installation

### Install / Update

```bash
curl -fsSL https://raw.githubusercontent.com/mikebignell/python-version-hunter/main/install.sh | bash
```

Run this to install, or run it again any time to update to the latest version. Checks for Python 3.11+, creates (or reuses) a dedicated venv at `~/.pyhunter`, and tells you what to add to your shell config.

### Manual

```bash
# Clone the repo
git clone https://github.com/mikebignell/python-version-hunter.git
cd python-version-hunter

# Install (ideally inside a venv with Python 3.11+)
pip install .

# Or install in editable/dev mode with test dependencies
pip install -e ".[dev]"
```

---

## Usage

### Scan (default)

```bash
pyhunter
```

Fetches live version data, scans your system, and displays a table of every Python found
with its compliance status, latest available patch, and recommended action.

### Interactive review

```bash
pyhunter --interactive
```

Walks you through each non-compliant installation one at a time.

### Auto-upgrade all EOL/security venvs

```bash
pyhunter --upgrade-venvs
```

Finds every virtual environment using an old Python and recreates it with a newer one.
Packages are preserved via `pip freeze` + reinstall. If a pinned version has no wheel for
the new Python, it retries with the latest available version and reports what changed.
For python.org Framework Pythons (`/Library/Frameworks/…`), SSL certificates are
automatically configured before pip runs so builds don't fail.

Specify a target Python explicitly:

```bash
pyhunter --upgrade-venvs --target-python /opt/homebrew/bin/python3.12
```

### Full auto mode

One command to fix everything:

```bash
pyhunter --full-auto
```

This orchestrates a complete remediation in order:

1. **`brew upgrade python`** — checks `brew outdated` first; skips entirely if already current. Upgrades only the latest minor-version formula (e.g. `python@3.14`); older formulae are skipped here and removed in step 6
2. **pyenv upgrade + audit** — upgrades pyenv itself, installs the latest stable Python, removes old/EOL pyenv versions (migrating dependent venvs first). With `--full-auto-remove-redundant-pyenv`: if pyenv ends up empty, uninstalls pyenv too
3. **Broken + chained venv repair** — finds venvs whose source Python was deleted *or* sourced from another venv (fragile coupling), and recreates them with a proper standalone Python
4. **Upgrade all out-of-date venvs** — recreates every venv on an old cycle/patch, preserving packages + upgrading pip
5. **Remove old Homebrew formulae** — migrates any remaining dependent venvs first; installs matching new-version companions (e.g. `python-tk@3.14`) before removing old ones (e.g. `python-tk@3.13`) so no functionality is lost; skips with a warning if an unrelated formula depends on the old Python
6. **Homebrew Cellar cleanup** — runs `brew cleanup` to remove stale patch-level Cellar entries
7. **PATH shadowing check** — verifies Homebrew Python comes before `/usr/bin/python3`
8. **Shell config check** — warns if `brew shellenv` is missing from `.zshrc`/`.bash_profile`
9. **`.python-version` scan** — flags pyenv pin files that point at EOL versions

Skip the confirmation prompt:

```bash
pyhunter --full-auto --yes
```

Preview without making changes:

```bash
pyhunter --full-auto --dry-run
```

### pyenv audit and cleanup

Upgrade pyenv itself, install the latest stable Python, remove old/EOL versions (migrating dependent venvs first):

```bash
pyhunter --pyenv-cleanup
pyhunter --pyenv-cleanup --dry-run   # preview what would change
```

If pyenv has no versions installed after cleanup, a warning is printed with the removal command. To remove pyenv automatically as part of `--full-auto`, use `--full-auto-remove-redundant-pyenv`:

```bash
pyhunter --full-auto --full-auto-remove-redundant-pyenv
```

### Homebrew Cellar cleanup

Remove old Python versions left in the Cellar after `brew upgrade`:

```bash
pyhunter --brew-cleanup
pyhunter --brew-cleanup --dry-run   # preview what would be removed
```

This is safer than running `brew cleanup` directly — the tool first checks whether any of your venvs still reference the old Cellar paths, upgrades them to the new Python, *then* runs `brew cleanup`. This avoids silently broken venvs.

`--brew-cleanup` is also included automatically in `--full-auto`.

### Dry run

Preview everything without making changes:

```bash
pyhunter --upgrade-venvs --dry-run
pyhunter --interactive --dry-run
pyhunter --brew-cleanup --dry-run
```

### Extra scan paths

```bash
pyhunter --scan-path ~/Projects --scan-path ~/work
```

---

## Options

| Flag | Short | Description |
|------|-------|-------------|
| `--scan-home` | `-H` | Scan home directory for venvs (default: on) |
| `--scan-path PATH` | `-p` | Additional directories to scan for venvs (repeatable) |
| `--interactive` | `-i` | Step through each issue interactively |
| `--upgrade-venvs` | `-u` | Auto-upgrade all EOL/security venvs |
| `--target-python PATH` | `-t` | Python to use when recreating venvs |
| `--dry-run` | `-n` | Preview changes without applying them |
| `--no-venvs` | | Skip virtual environment scanning |
| `--brew-remove-old` | | Uninstall old Homebrew Python minor-version formulae (migrates venvs first) |
| `--brew-cleanup` | | Remove stale Homebrew Cellar patch versions (upgrades dependent venvs first) |
| `--pyenv-cleanup` | | Upgrade pyenv, install latest Python, remove old/EOL versions, warn if empty |
| `--full-auto` | `-A` | Full automated remediation (upgrade, repair, verify, cleanup) |
| `--full-auto-remove-redundant-pyenv` | | Use with `--full-auto`: auto-remove pyenv if it has no versions remaining |
| `--yes` | `-y` | Skip confirmation prompts (use with `--full-auto`) |
| `--version` | `-V` | Show version and exit |

---

## Version status (as of June 2026)

| Python | Status | EOL date | Recommendation |
|--------|--------|----------|---------------|
| 2.x | ☠ DEAD | 2020-01-01 | Delete — no updates ever |
| ≤ 3.9 | 🔴 EOL | 2025-10-05 | Delete standalone; upgrade venvs |
| 3.10 | 🟡 Security-only | 2026-10-31 | Consider upgrading |
| 3.11+ | 🟢 Supported | 2027–2029+ | Keep |

> Status data is also fetched live at runtime from [endoflife.date](https://endoflife.date/api/python.json).
> The tool degrades gracefully when offline — the Latest Patch column shows `(offline)`.

---

## Python 2 — why delete?

Python 2 reached **permanent end-of-life on 1 January 2020**. There are no security patches,
no bug fixes, and there never will be. The final 2.7.18 release (April 2020) was a farewell
from volunteers, not a maintenance release. Any Python 2 on your machine is an unpatched, 
abandoned runtime.

The tool marks all Python 2 as `☠ DEAD` and shows a warning panel if any are found.

---

## How venv upgrade works

1. Reads `pip freeze` output from the existing venv
2. Backs up requirements to `<venv_name>_requirements_backup.txt`
3. Deletes the old venv directory
4. Creates a new venv with the target Python (`python -m venv`)
5. Reinstalls all packages (`pip install -r requirements_backup.txt`)

> **Note:** Package compatibility across Python versions isn't guaranteed.
> Review the backup file if the reinstall has issues.

---

## Development

```bash
pip install -e ".[dev]"
pytest
pytest --cov=pyhunter --cov-report=term-missing
```

Test matrix covers `finder`, `ui`, `versions`, `actions`, and CLI integration.

---

## License

[MIT](LICENSE)
