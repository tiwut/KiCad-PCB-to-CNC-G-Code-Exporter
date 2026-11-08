#!/usr/bin/env bash
#
# Quick installation script for KiCad PCB to G-Code Exporter.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN=""

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: Python 3 is required but was not found in PATH."
    exit 1
fi

echo "Running KiCad PCB to G-Code Plugin installer..."
"$PYTHON_BIN" "$SCRIPT_DIR/install.py" "$@"
