#!/usr/bin/env bash
# Build sofle-status into ~/.local/bin and install the launch agent that syncs the keyboard's clock
# and cards when it connects (au.kyle.sofle-status, logging to ~/Library/Logs/sofle-status.log).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.local/bin/sofle-status"
label="au.kyle.sofle-status"
plist="$HOME/Library/LaunchAgents/$label.plist"

mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
swiftc -O -o "$bin" "$here/sofle-status.swift"
echo "installed $bin"

# macOS ties the launch agent's Input Monitoring permission to the binary's signature. An ad-hoc
# signature changes with every build; a development certificate keeps it across rebuilds.
identity="${SOFLE_SIGN_IDENTITY:-$(security find-identity -v -p codesigning | awk '/Apple Development/ { print $2; exit }')}"
if [ -n "$identity" ]; then
  codesign --force --identifier au.kyle.sofle-status --sign "$identity" "$bin"
  echo "signed with $(security find-identity -v -p codesigning | awk -v id="$identity" '$2 == id' | cut -d'"' -f2)"
fi

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
