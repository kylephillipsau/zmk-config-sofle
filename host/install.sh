#!/usr/bin/env bash
# Build sofle-status as ~/Applications/Sofle Status.app, link it into ~/.local/bin, and install the
# launch agent that syncs the keyboard's clock and cards when it connects (au.kyle.sofle-status,
# logging to ~/Library/Logs/sofle-status.log).
#
# The launch agent needs Input Monitoring. macOS keeps that permission for an app bundle across
# updates signed with the same certificate, so the tool lives in a bundle signed with an Apple
# Development certificate when there is one. A bare binary lost it on every rebuild.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="$HOME/Applications/Sofle Status.app"
exe="$app/Contents/MacOS/sofle-status"
link="$HOME/.local/bin/sofle-status"
label="au.kyle.sofle-status"
plist="$HOME/Library/LaunchAgents/$label.plist"

mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$HOME/.local/bin" \
  "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# Rebuild only when the source changed, so the signature (and the permission) stays put.
source_hash="$(shasum -a 256 "$here/sofle-status.swift" | cut -d' ' -f1)"
if [ -x "$exe" ] && [ "$(cat "$app/Contents/Resources/source.sha256" 2>/dev/null)" = "$source_hash" ]; then
  echo "$exe is up to date"
else
  cat > "$app/Contents/Info.plist" <<INFO
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>$label</string>
    <key>CFBundleName</key><string>Sofle Status</string>
    <key>CFBundleExecutable</key><string>sofle-status</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSUIElement</key><true/>
</dict>
</plist>
INFO
  swiftc -O -o "$exe" "$here/sofle-status.swift"
  identity="${SOFLE_SIGN_IDENTITY:-$(security find-identity -v -p codesigning | awk '/Apple Development/ { print $2; exit }')}"
  if [ -n "$identity" ]; then
    codesign --force --sign "$identity" "$app"
    echo "signed with $(security find-identity -v -p codesigning | awk -v id="$identity" '$2 == id' | cut -d'"' -f2)"
  else
    codesign --force --sign - "$app"
    echo "no Apple Development certificate: ad-hoc signed, so re-enable Input Monitoring after each rebuild"
  fi
  echo "$source_hash" > "$app/Contents/Resources/source.sha256"
  echo "built $app"
fi

# Claude Code's hooks and status line run ~/.local/bin/sofle-status
rm -f "$link"
ln -s "$exe" "$link"

cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key>
    <array><string>$exe</string><string>daemon</string></array>
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
