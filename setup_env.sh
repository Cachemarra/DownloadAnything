#!/usr/bin/env sh
set -euo pipefail

# Determine project directory (directory of this script)
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# Find python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Error: python3 not found. Please install Python 3." >&2
  exit 1
fi

cd "$PROJECT_DIR"

# Create venv if missing
if [ ! -d .venv ]; then
  echo "Creating virtual environment at $PROJECT_DIR/.venv"
  "$PY" -m venv .venv
fi

# Activate venv
# shellcheck disable=SC1091
. .venv/bin/activate

echo "Upgrading pip..."
python -m pip install --upgrade pip

if [ -f requirements.txt ]; then
  echo "Installing dependencies from requirements.txt"
  pip install -r requirements.txt
else
  echo "No requirements.txt found; skipping dependency install"
fi

echo "Environment ready. Activate with: . .venv/bin/activate"
