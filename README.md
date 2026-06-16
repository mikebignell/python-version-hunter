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

Finds every virtual environment using an old Python and recreates it with a newer one —
packages are preserved via `pip freeze` + reinstall.

Specify a target Python explicitly:

```bash
pyhunter --upgrade-venvs --target-python /opt/homebrew/bin/python3.12
```

### Dry run

Preview everything without making changes:

```bash
pyhunter --upgrade-venvs --dry-run
pyhunter --interactive --dry-run
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
