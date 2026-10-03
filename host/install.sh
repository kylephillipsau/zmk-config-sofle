#!/usr/bin/env bash
# Build sofle-status and install it to ~/.local/bin.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin"
swiftc -O -o "$HOME/.local/bin/sofle-status" "$here/sofle-status.swift"
echo "installed $HOME/.local/bin/sofle-status"
