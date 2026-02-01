#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${LINFO_APP_DIR:-$SCRIPT_DIR}"
APP_ENTRYPOINT="${APP_DIR}/hwtop.py"
VENV_PYTHON="${LINFO_PYTHON:-$SCRIPT_DIR/.venv/bin/python}"

if [[ ! -x "$VENV_PYTHON" ]]; then
  VENV_PYTHON="$(command -v python3)"
fi

run_app() {
  exec "$VENV_PYTHON" "$APP_ENTRYPOINT" "$@"
}

if [[ "${LINFO_ELEVATE:-0}" == "1" ]]; then
  ENV_VARS=()
  for var in DISPLAY XAUTHORITY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS LANG LC_ALL; do
    value="${!var-}"
    if [[ -n "$value" ]]; then
      ENV_VARS+=("${var}=${value}")
    fi
  done
  exec pkexec env "${ENV_VARS[@]}" "$VENV_PYTHON" "$APP_ENTRYPOINT" "$@"
else
  run_app "$@"
fi
