# nice!view layer legend

A copy of ZMK's `nice_view` shield (from the cormoran/zmk `v0.3-branch+dya` fork) with a different
right-hand (peripheral) screen:

- **Base layer:** the keyboard's name and a small Sofle drawing.
- **While a layer key is held:** a cheat sheet for that layer (layer 1: navigation, symbols,
  F-keys, mouse, RGB; layer 2: Bluetooth slots, output, flash, restart, soft off).

The left (central) screen is the stock nice!view status screen.

## How it works

`widgets/legend_layer.c` raises a one-byte `zmk_legend_layer_changed` event on the central whenever
the highest active layer changes, and relays it to the peripheral with the fork's
`ZMK_RELAY_EVENT_CENTRAL_TO_PERIPHERAL` (needs `CONFIG_ZMK_SPLIT_RELAY_EVENT=y` on both halves).
`widgets/peripheral_status.c` swaps the image to match, and falls back to the base image whenever
the link to the central drops.

## Changing the legends

The images in `widgets/legend_art.c` are generated. Edit `art/concepts.py`, then run:

```
cd art && python3 build_legend.py
```

If the keymap changes, update the legend text to match.

## Settings

`CONFIG_NICE_VIEW_WIDGET_INVERTED=y` inverts the colours, as with the stock shield.
