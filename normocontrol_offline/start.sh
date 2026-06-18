#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# macOS may abort Tk/CustomTkinter apps if an OCR/converter subprocess is
# spawned after CoreFoundation was initialized. The app still executes external
# tools normally; this only disables Apple's conservative fork-safety abort.
if [ "$(uname -s)" = "Darwin" ]; then
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
fi

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
