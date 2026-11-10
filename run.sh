#!/bin/sh
set -eu
APP_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_ROOT"
if [ -f "$APP_ROOT/.env.local" ]; then
  set -a
  . "$APP_ROOT/.env.local"
  set +a
fi
if [ -n "${PYTHON_BIN:-}" ]; then
  :
elif [ -x "$APP_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$APP_ROOT/.venv/bin/python"
else
  PYTHON_BIN=python3
fi
exec "$PYTHON_BIN" app.py
