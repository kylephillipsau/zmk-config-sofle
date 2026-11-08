# nice!view layer legend

A copy of ZMK's `nice_view` shield, from cormoran's `v0.3-branch+dya` fork of ZMK, with both
screens replaced.

The left (central) screen, `widgets/status.c`, shows both batteries, the layer, the Bluetooth slots,
held modifiers, the clock, and the card the Mac feeds through `widgets/host_link.c`. After a crash,
it shows the cause (`widgets/crash.c`).

The right (peripheral) screen, `widgets/peripheral_status.c`, shows the keyboard's name and a small
Sofle drawing on Base, and the layer's keys while NAV or SYSTEM is held. On the GAME layer, Tetris
(`widgets/tetris.c`) takes its place.

## How it works

`widgets/legend_layer.c` raises a one-byte `zmk_legend_layer_changed` event on the left half
whenever the highest active layer changes, and relays it to the right half with the fork's
`ZMK_RELAY_EVENT_CENTRAL_TO_PERIPHERAL`, which needs `CONFIG_ZMK_SPLIT_RELAY_EVENT=y` on both halves.
`widgets/peripheral_status.c` swaps the image to match, and falls back to Base whenever the link to
the left half drops.

## Changing the legends

The images in `widgets/legend_art.c` are generated. Edit `art/concepts.py`, then run:

```
cd art && python3 build_legend.py
```

If the keymap changes, update the legend text to match.

## Settings

`CONFIG_NICE_VIEW_WIDGET_INVERTED=y` inverts the colours, as with the stock shield.
