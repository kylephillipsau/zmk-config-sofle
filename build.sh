#!/usr/bin/env bash
# Local ZMK build in Docker, mirroring zmkfirmware/zmk build-user-config.yml (v0.3).
# The west workspace (zmk, zephyr, modules) lives in a Docker volume so it stays
# out of this repo. UF2 files are written to ./firmware/.
#
#   ./build.sh            # build left + right
#   ./build.sh left       # build one target: left | right | reset
#   ./build.sh update     # re-run `west update` (after editing config/west.yml)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
IMAGE="zmkfirmware/zmk-build-arm:3.5-branch"
VOLUME="zmk-sofle-ws"
BOARD="nice_nano_v2"
DISPLAY_SHIELD="${DISPLAY_SHIELD:-nice_view_legend}"

run() {
  docker run --rm \
    -v "$VOLUME:/ws" \
    -v "$REPO/config:/ws/config" \
    -v "$REPO:/zmk-config" \
    -w /ws "$IMAGE" bash -c "$1"
}

init() {
  run '
    set -e
    git config --global --add safe.directory "*"
    if [ ! -d .west ]; then west init -l /ws/config; fi
    west update --fetch-opt=--filter=tree:0
    west zephyr-export
  '
}

build() {
  local name="$1" shield="$2" west_args="${3:-}" cmake_args="${4:-}"
  echo "==> Building $name ($shield)"
  run "
    set -e
    git config --global --add safe.directory '*'
    west zephyr-export > /dev/null  # registers Zephyr in the (ephemeral) container home
    west build -p always -s zmk/app -d build/$name -b $BOARD $west_args -- \
      -DZMK_CONFIG=/ws/config -DSHIELD='$shield' -DZMK_EXTRA_MODULES=/zmk-config $cmake_args
    mkdir -p /zmk-config/firmware
    cp build/$name/zephyr/zmk.uf2 /zmk-config/firmware/kyles_sofle_$name.uf2
  "
}

left()  { build left  "eyelash_sofle_left $DISPLAY_SHIELD raw_hid_adapter" \
            "-S studio-rpc-usb-uart" "-DCONFIG_ZMK_STUDIO=y -DCONFIG_ZMK_STUDIO_LOCKING=n"; }
right() { build right "eyelash_sofle_right $DISPLAY_SHIELD"; }
reset() { build reset "settings_reset"; }

docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
run 'test -d /ws/.west' 2>/dev/null || init

case "${1:-all}" in
  update) init ;;
  left)   left ;;
  right)  right ;;
  reset)  reset ;;
  all)    left; right ;;
  *) echo "usage: $0 [all|left|right|reset|update]" >&2; exit 1 ;;
esac

ls -la "$REPO/firmware" 2>/dev/null || true
