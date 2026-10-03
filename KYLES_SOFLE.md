# Kyles Sofle

Personal ZMK config for an Eyelash Sofle, based on the seller's repo
([a741725193/zmk-sofle](https://github.com/a741725193/zmk-sofle), kept as the `upstream` remote).

## What's different from upstream

- **Name:** advertises as "Kyles Sofle" (`config/eyelash_sofle.conf`).
- **Screens:** `boards/shields/nice_view_legend`, a copy of ZMK's nice!view shield.
  - Right: keyboard name at rest; a cheat sheet for layer 1 or 2 while that layer is held. The
    left half relays the active layer (`widgets/legend_layer.c`).
  - Left: both batteries, layer, Bluetooth slots, held modifiers and caps lock, plus a live WPM
    chart (`widgets/status.c`).
- **Joystick:** arrows on the base layer; scrolls (vertical and horizontal) on layers 1 and 2,
  reversed to suit macOS natural scrolling. Scroll speed is tunable live in
  [DYA Studio](https://studio.dya.cormoran.works/).
- **Caps Lock key:** Esc on tap, Ctrl on hold. Pressing both Shifts turns on Caps Word.
- **Knob:** volume on the base layer, scroll on layer 1, Ctrl+Left/Right on layer 2 (switch
  Spaces / full-screen apps on macOS).
- **Bluetooth slots:** 1 Mac, 2 phone, 3 work computer, 4 Boox tablet, shown as icons on both
  screens (`SLOT_ICONS` in `art/concepts.py`). Slots are assigned by pairing each device while
  its slot is selected.
- **RGB:** layer 1 + X turns the underglow on in solid red.
- **Layers** are named BASE / NAV / SYSTEM.

## Building

Locally, in Docker (the west workspace lives in the `zmk-sofle-ws` volume):

```
./build.sh          # both halves -> firmware/kyles_sofle_{left,right}.uf2
./build.sh left     # one half: left | right | reset
./build.sh update   # after editing config/west.yml
```

GitHub Actions builds the same targets from `build.yaml` on every push.

To flash: plug a half in, double-press its reset button, and copy its `.uf2` onto the `NICENANO`
drive. Keymap and left-screen changes only need the left half; right-screen art needs the right.

## Screen art

Everything on the screens comes from `art/`, rendered with PIL so the mockups and the device match:

| Script | Writes |
|---|---|
| `art/concepts.py` | the screen designs (mockups go to `art/out/`) |
| `art/build_legend.py` | `widgets/legend_art.c`, the right-screen images |
| `art/make_lvfont.py` | `fonts/*.c`, the pixel fonts as LVGL fonts |
| `art/make_glyphs.py` | `widgets/status_glyphs.h`, the left-screen icons |

If the keymap changes, update the legend text in `art/concepts.py` and re-run `build_legend.py`.
The fonts in `art/fonts` are under the SIL Open Font License (texts in `art/fonts/LICENSES`).
