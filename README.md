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

- **Full system scan** — PATH, Homebrew, pyenv, conda/mamba, python.org framework installs
- **Virtual environment discovery** — recursively finds every `.venv` / `venv` in your home directory
- **Compliance status** — flags EOL versions (< 3.10), security-only (3.10), and supported (3.11+)
- **Auto-upgrade venvs** — recreates venvs with a newer Python, preserving installed packages
- **Interactive mode** — step through each issue and decide: upgrade, delete, or keep
- **Retro 80s UI** — neon green-on-black terminal aesthetic with progress animations

---

## Installation

```bash
# Clone the repo
git clone https://github.com/mikebignell/python-version-hunter.git
cd python-version-hunter

# Install (ideally inside a venv with Python 3.11+)
pip install .

# Or install in editable/dev mode
pip install -e ".[dev]"
```

---

## Usage

### Scan (default)

```bash
pyhunter
```

Scans your system and home directory, displays a full table of every Python found, and prints a summary.

### Interactive review

```bash
pyhunter --interactive
```

Walks you through each non-compliant installation one at a time, letting you choose to upgrade, delete, or skip.

### Auto-upgrade all EOL/security venvs

```bash
pyhunter --upgrade-venvs
```

Finds every virtual environment using an old Python and recreates it with a newer one (packages are preserved).

Specify a target Python explicitly:

```bash
pyhunter --upgrade-venvs --target-python /opt/homebrew/bin/python3.12
```

### Dry run

Preview what would happen without making any changes:

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
| `--scan-path PATH` | `-p` | Additional directories to scan for venvs |
| `--interactive` | `-i` | Step through each issue interactively |
| `--upgrade-venvs` | `-u` | Auto-upgrade all EOL/security venvs |
| `--target-python PATH` | `-t` | Python to use when recreating venvs |
| `--dry-run` | `-n` | Preview changes without applying them |
| `--no-venvs` | | Skip virtual environment scanning |
| `--version` | `-V` | Show version and exit |

---

## Version status (as of June 2026)

| Python | Status | Recommendation |
|--------|--------|---------------|
| ≤ 3.9 | 🔴 EOL | Delete standalone, upgrade venvs |
| 3.10 | 🟡 Security-only | Consider upgrading |
| 3.11+ | 🟢 Supported | Keep |

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

Run with coverage:

```bash
pytest --cov=pyhunter --cov-report=term-missing
```

---

## How venv upgrade works

1. Reads `pip freeze` output from the existing venv
2. Backs up requirements to `<venv_name>_requirements_backup.txt`
3. Deletes the old venv directory
4. Creates a new venv with the target Python
5. Reinstalls all packages

> **Note:** Package compatibility is not guaranteed across Python versions. Always review the requirements backup if the reinstall has issues.

---

## License

MIT
