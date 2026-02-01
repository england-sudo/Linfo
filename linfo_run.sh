#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/linfo"
LAUNCHER="${INSTALL_DIR}/linfo_launcher.sh"

LINFO_NO_LAUNCH=1 python3 "${SCRIPT_DIR}/install.py"

if [[ -x "${LAUNCHER}" ]]; then
  exec "${LAUNCHER}"
fi

echo "Launcher not found at ${LAUNCHER}. Installation may have failed." >&2
exit 1
