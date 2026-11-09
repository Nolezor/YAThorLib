#!/bin/sh
# Use the project-local Ghidra without editing any global MCP/client settings.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export GHIDRA_INSTALL_DIR="${GHIDRA_INSTALL_DIR:-$repo/.tools/ghidra_12.1.4_PUBLIC}"
if [ ! -d "$GHIDRA_INSTALL_DIR" ]; then
    echo 'Install Ghidra 12.1.x locally or set GHIDRA_INSTALL_DIR.' >&2
    exit 1
fi
exec "${REA_COMMAND:-rea}" "$@"
