#!/usr/bin/env bash
# Build sofle-status into ~/.local/bin and install the launch agent that keeps the keyboard's clock
# synced (au.kyle.sofle-status, logging to ~/Library/Logs/sofle-status.log).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin/sofle-status"
label="au.kyle.sofle-status"
plist="$HOME/Library/LaunchAgents/$label.plist"

mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
swiftc -O -o "$bin" "$here/sofle-status.swift"
echo "installed $bin"

cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key>
    <array><string>$bin</string><string>daemon</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/sofle-status.log</string>
</dict>
</plist>
PLIST

# (Re)load so the agent runs the binary just built
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "loaded launch agent $label"
