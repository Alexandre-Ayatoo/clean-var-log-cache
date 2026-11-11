#!/usr/bin/env bash
# Compatibilité : toute l'aide se trouve dans le script unifié.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/clean-system.py" --only cache "$@"
