#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PYTHON="$APP_DIR/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 не найден. Установите Python 3.11 или новее." >&2
    exit 1
  fi

  echo "Виртуальное окружение не найдено, создаю .venv..."
  python3 -m venv "$APP_DIR/.venv"
  PYTHON="$APP_DIR/.venv/bin/python"
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$APP_DIR/requirements.txt"
fi

exec "$PYTHON" "$APP_DIR/run.py"
