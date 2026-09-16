#!/usr/bin/env bash
#
# Quaver bootstrap — download the project and start the setup wizard.
#   curl -fsSL https://raw.githubusercontent.com/Hasanlz/qobuz-downloader/main/bootstrap.sh | bash
#
# Override with env: QUAVER_REPO_URL, QUAVER_REF (default main), QUAVER_HOME
# (default ~/quaver). Extra arguments are passed to wizard.py (e.g. --defaults).
set -euo pipefail

REPO_URL="${QUAVER_REPO_URL:-https://github.com/Hasanlz/qobuz-downloader.git}"
REF="${QUAVER_REF:-main}"
DEST="${QUAVER_HOME:-$HOME/quaver}"

BOLD="$(tput bold 2>/dev/null || true)"
DIM="$(tput dim 2>/dev/null || true)"
RESET="$(tput sgr0 2>/dev/null || true)"
GREEN="$(tput setaf 2 2>/dev/null || true)"
RED="$(tput setaf 1 2>/dev/null || true)"

note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
good() { printf '  %s✓ %s%s\n' "$GREEN" "$1" "$RESET"; }
fail() { printf '  %s✗ %s%s\n' "$RED" "$1" "$RESET" >&2; exit 1; }

printf '\n%s  Quaver bootstrap%s\n' "$BOLD" "$RESET"

# 1. Python 3.12+ (the app requires it; the wizard runs on it)
PY=""
for cand in python3.13 python3.12 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PY="$cand"
    break
  fi
done
[ -n "$PY" ] || fail "Python 3.12+ not found. Install it first:
    Ubuntu/Debian: sudo apt install python3.12
    Fedora:        sudo dnf install python3.12
    macOS:         brew install python@3.12"
good "python: $("$PY" --version 2>&1) ($(command -v "$PY"))"

# 2. git — clone or update the checkout
command -v git >/dev/null 2>&1 || fail "git not found. Install it first:
    Ubuntu/Debian: sudo apt install git
    macOS:         xcode-select --install (or brew install git)"

if [ -d "$DEST/.git" ]; then
  note "updating existing checkout → $DEST"
  git -C "$DEST" fetch --depth 1 origin "$REF" >/dev/null
  git -C "$DEST" checkout -q FETCH_HEAD
elif [ -e "$DEST" ]; then
  fail "$DEST exists but is not a git checkout — remove it or set QUAVER_HOME"
else
  note "cloning $REPO_URL ($REF) → $DEST"
  git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$DEST"
fi
good "repository ready"

# 3. the wizard does the rest: venv, pip installs, credentials, settings, PATH
printf '\n'
exec "$PY" "$DEST/wizard.py" "$@"
