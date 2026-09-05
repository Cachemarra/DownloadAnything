#!/usr/bin/env sh
set -euo pipefail

# Determine project directory (directory of this script)
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

# Ensure environment is set up
if [ ! -d .venv ]; then
  echo "Virtual environment not found. Creating one..."
  if command -v python3 >/dev/null 2>&1; then
    PY=python3
  elif command -v python >/dev/null 2>&1; then
    PY=python
  else
    echo "Error: python3 not found. Please install Python 3." >&2
    exit 1
  fi
  "$PY" -m venv .venv
fi

# Activate venv
# shellcheck disable=SC1091
. .venv/bin/activate

# Install dependencies if uvicorn is missing
if ! command -v uvicorn >/dev/null 2>&1; then
  echo "Installing dependencies..."
  python -m pip install --upgrade pip
  if [ -f requirements.txt ]; then
    pip install -r requirements.txt
  else
    # Fallback minimal deps
    pip install "fastapi>=0.110,<1.0" "uvicorn[standard]>=0.25,<1.0"
  fi
fi

# Run the app
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
