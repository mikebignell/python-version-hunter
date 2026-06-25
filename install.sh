#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/mikebignell/python-version-hunter.git"
INSTALL_DIR="${HOME}/.pyhunter"
MIN_MAJOR=3
MIN_MINOR=11

# ── Colours ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  GREEN="\033[0;32m" CYAN="\033[0;36m" YELLOW="\033[1;33m" RED="\033[0;31m" RESET="\033[0m"
else
  GREEN="" CYAN="" YELLOW="" RED="" RESET=""
fi

info()    { printf "  ${CYAN}→${RESET}  %s\n" "$*"; }
ok()      { printf "  ${GREEN}✓${RESET}  %s\n" "$*"; }
warn()    { printf "  ${YELLOW}⚠${RESET}  %s\n" "$*"; }
die()     { printf "\n  ${RED}✗${RESET}  %s\n\n" "$*" >&2; exit 1; }

printf "\n${GREEN}"
cat <<'ASCII'
  ██████╗ ██╗   ██╗    ██╗  ██╗██╗   ██╗███╗  ██╗████████╗███████╗██████╗
  ██╔══██╗╚██╗ ██╔╝    ██║  ██║██║   ██║████╗ ██║╚══██╔══╝██╔════╝██╔══██╗
  ██████╔╝ ╚████╔╝     ███████║██║   ██║██╔██╗██║   ██║   █████╗  ██████╔╝
  ██╔═══╝   ╚██╔╝      ██╔══██║██║   ██║██║╚████║   ██║   ██╔══╝  ██╔══██╗
  ██║        ██║       ██║  ██║╚██████╔╝██║ ╚███║   ██║   ███████╗██║  ██║
  ╚═╝        ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
ASCII
printf "${RESET}\n"
printf "  Python Version Hunter — installer\n\n"

# ── 1. Find a suitable Python ─────────────────────────────────────────────────
info "Looking for Python ${MIN_MAJOR}.${MIN_MINOR}+…"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
    major=${ver%%.*}
    minor=${ver##*.}
    if [ "${major:-0}" -ge "$MIN_MAJOR" ] && [ "${minor:-0}" -ge "$MIN_MINOR" ]; then
      PYTHON=$(command -v "$candidate")
      ok "Found ${PYTHON} (${ver})"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  warn "No Python ${MIN_MAJOR}.${MIN_MINOR}+ found on PATH."
  printf "\n  To install one:\n"
  if [[ "$OSTYPE" == darwin* ]]; then
    printf "    brew install python@3.14\n"
  elif command -v apt-get &>/dev/null; then
    printf "    sudo apt-get install python3.12\n"
  elif command -v dnf &>/dev/null; then
    printf "    sudo dnf install python3.12\n"
  fi
  printf "\n  Then re-run this script.\n\n"
  exit 1
fi

# ── 2. Create or reuse venv ───────────────────────────────────────────────────
IS_UPDATE=false
if [ -d "$INSTALL_DIR" ]; then
  IS_UPDATE=true
  info "Existing installation found at ${INSTALL_DIR} — updating…"
else
  info "Creating venv at ${INSTALL_DIR}…"
fi
"$PYTHON" -m venv "$INSTALL_DIR"
$IS_UPDATE || ok "Venv created."

# ── 3. Install / update pyhunter ─────────────────────────────────────────────
if $IS_UPDATE; then
  info "Updating pyhunter to latest…"
else
  info "Installing pyhunter…"
fi
"${INSTALL_DIR}/bin/pip" install --quiet --no-cache-dir --upgrade pip
"${INSTALL_DIR}/bin/pip" install --quiet --no-cache-dir --upgrade "git+${REPO}"
if $IS_UPDATE; then
  ok "pyhunter updated."
else
  ok "pyhunter installed."
fi

# ── 4. Shell PATH advice ──────────────────────────────────────────────────────
BIN="${INSTALL_DIR}/bin"

printf "\n"
if echo ":${PATH}:" | grep -q ":${BIN}:"; then
  ok "${BIN} is already on your PATH."
else
  warn "${BIN} is not on your PATH."
  SHELL_RC=""
  if [[ "${SHELL:-}" == */zsh ]];  then SHELL_RC="${HOME}/.zshrc"; fi
  if [[ "${SHELL:-}" == */bash ]]; then SHELL_RC="${HOME}/.bash_profile"; fi

  if [ -n "$SHELL_RC" ]; then
    printf "\n  Add this to %s and restart your shell:\n\n" "$SHELL_RC"
    printf "    ${GREEN}export PATH=\"%s:\$PATH\"${RESET}\n\n" "$BIN"
    printf "  Or run it once now:\n\n"
    printf "    ${CYAN}export PATH=\"%s:\$PATH\"${RESET}\n\n" "$BIN"
  else
    printf "\n  Add %s to your PATH.\n\n" "$BIN"
  fi
fi

printf "  ${GREEN}All done.${RESET} Run:\n\n"
printf "    ${CYAN}pyhunter${RESET}             # scan and report\n"
printf "    ${CYAN}pyhunter --full-auto${RESET} # fix everything\n\n"
