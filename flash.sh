#!/usr/bin/env bash
# Flash one half: ./flash.sh left|right, then double-press that half's reset button.
#
# Both halves' bootloaders mount as NICENANO, so this tells them apart by USB serial number, kept
# in ~/.cache/sofle-status/<half>-serial after each half's first flash, and refuses to put one
# half's firmware on the other. The left half also refreshes the clock and cards afterwards.
set -euo pipefail
half="${1:?usage: ./flash.sh left|right}"
case "$half" in left) other=right ;; right) other=left ;; *) echo "usage: ./flash.sh left|right"; exit 2 ;; esac
uf2="$(cd "$(dirname "$0")" && pwd)/firmware/kyles_sofle_$half.uf2"
known="$HOME/.cache/sofle-status"
mkdir -p "$known"

echo "waiting for the $half half's bootloader drive (double-press its reset button)"
until [ -d /Volumes/NICENANO ]; do sleep 1; done
sleep 1
serial=$(ioreg -p IOUSB -l -w0 | python3 -c '
import re, sys
for block in re.split(r"\+-o ", sys.stdin.read()):  # one block per USB device
    if "Nice Keyboards" in block:
        m = re.search(r"\"USB Serial Number\" = \"([^\"]+)\"", block)
        if m:
            print(m.group(1))
            break
')
echo "bootloader drive, USB serial ${serial:-unknown}"
if [ -n "$serial" ] && [ "$serial" = "$(cat "$known/$other-serial" 2>/dev/null)" ]; then
  echo "that's the $other half: not flashing"
  exit 1
fi

# cp ends with a harmless "Device not configured" when the drive resets mid-copy
cp "$uf2" /Volumes/NICENANO/ 2>/dev/null || true
for _ in $(seq 1 90); do [ -d /Volumes/NICENANO ] || break; sleep 1; done
echo "flashed $half"
[ -n "$serial" ] && echo "$serial" > "$known/$half-serial"

if [ "$half" = left ] && command -v sofle-status >/dev/null; then
  for _ in $(seq 1 60); do sofle-status list | grep -q "via USB" && break; sleep 1; done
  sleep 3
  sofle-status cards > /dev/null && echo "sent the clock and cards"
fi
