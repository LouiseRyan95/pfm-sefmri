#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PIPELINE_PYTHON:-python3}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "$#" -lt 3 ]]; then
  "$PYTHON_BIN" "$MEDIR/lib/mefmri_nvd_import.py" --help
  exit $(( $# < 3 ? 2 : 0 ))
fi

exec "$PYTHON_BIN" "$MEDIR/lib/mefmri_nvd_import.py" "$@"
