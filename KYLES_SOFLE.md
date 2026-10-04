# Kyles Sofle

Personal ZMK config for an Eyelash Sofle, based on the seller's repo
([a741725193/zmk-sofle](https://github.com/a741725193/zmk-sofle), kept as the `upstream` remote).

## What's different from upstream

- **Name:** advertises as "Kyles Sofle" (`config/eyelash_sofle.conf`).
- **Screens:** `boards/shields/nice_view_legend`, a copy of ZMK's nice!view shield.
  - Right: keyboard name at rest; a cheat sheet for layer 1 or 2 while that layer is held. The
    left half relays the active layer (`widgets/legend_layer.c`).
  - Left: both batteries, layer, Bluetooth slots and held modifiers, then the clock, WPM, and a
    card with Claude usage limits and CI for recent repos, or a live WPM chart when nothing is
    feeding the card (`widgets/status.c`).
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
- **Layers** are named BASE / NAV / SYSTEM / GAME.
- **Tetris** on the right screen: layer 2 + T toggles the GAME layer, and the joystick plays.
  Left and right move, up rotates, down drops faster, pressing drops at once; Esc leaves the layer.
  The stick sends nothing while the layer is on, the game pauses while it's off, and the best
  score survives restarts. See [Tetris](#tetris).
- **Clock** on the left screen, synced from the Mac (see [Claude Code status](#claude-code-status)
  for how it travels). 12-hour by default; `CONFIG_NICE_VIEW_LEGEND_CLOCK_24H=y` for 24-hour.
- **Claude Code status** on the left screen: the ✳ badge lights while Claude is working or waiting
  on you. See [Claude Code status](#claude-code-status).
- **Card** under the clock, also fed from the Mac:
  - Claude's 5 hour and weekly usage limits: percent used, a bar, and when each resets
    (MAX at 100%);
  - the 3 repos where you most recently started a Claude Code session or sent a prompt, each with
    its latest GitHub Actions result: ✓ passed, ✗ failed, ○ running, nothing for no CI;
  - from 30 minutes before your next calendar event until 15 minutes after it starts (or its end,
    if sooner), the event in place of the repos: a bar with "IN 12M" or "NOW" and the start time,
    then the title over two lines.

  The card shows only while the Mac is feeding it: a frame arrived in the last 15 minutes (the
  Mac resends every 10), over the connection the keyboard is using now. On another Bluetooth slot,
  or once the Mac sleeps, the WPM chart takes its place.

## Building

Locally, in Docker (the west workspace lives in the `zmk-sofle-ws` volume):

```
./build.sh          # both halves -> firmware/kyles_sofle_{left,right}.uf2
./build.sh left     # one half: left | right | reset
./build.sh update   # after editing config/west.yml
```

GitHub Actions builds the same targets from `build.yaml` on every push.

To flash: plug a half in, run `./flash.sh left` or `./flash.sh right`, and double-press that
half's reset button. Both halves mount as `NICENANO`, so the script tells them apart by USB serial
number (remembered after each half's first flash) and won't put one half's firmware on the other.
Keymap and left-screen changes only need the left half; right-screen art needs the right.

## Claude Code status, clock and card

`host/sofle-status` feeds the left screen from the Mac. Everything travels in keyboard indicator
lights macOS doesn't use, as raw HID output reports over Bluetooth or USB, and the firmware decodes
them in `widgets/host_link.c` (the header documents the format).

A report with Num Lock off carries two flags, and either lights the ✳ badge:

| Light | Meaning |
|---|---|
| Scroll Lock | some session is working |
| Compose | some session needs you (permission prompt) |

Reports with Num Lock on are a frame, 2 bits per report in Scroll Lock and Compose, with Kana
alternating so no two reports in a row match. A frame is a type byte, a fixed-length payload and a
CRC-8: the clock, the usage limits, or one repo row. The next report with Num Lock off ends it and
carries the flags again. The keyboard drops any frame with the wrong length, a broken Kana
sequence or a bad CRC, and times in a frame count from its first report.

The keyboard can't answer, so the host sends a card when it changes, every 30 minutes, and
whenever the keyboard reconnects (it forgets everything when it sleeps), with a clock frame first.
If nothing else went out for 10 minutes, a clock frame does, so the card stays live. To keep the
radio quiet, a usage percentage that creeps up waits 3 minutes between sends (a new reset time or
reaching 100% goes at once), repo rows keep their places when the same repos change order, and
nothing goes over Bluetooth while the keyboard is plugged in, since it shows what arrives over
USB then. Unplugging starts a push over Bluetooth.

ZMK asks the Mac for a Bluetooth peripheral latency of 30: while idle, the keyboard listens only
every 30th connection event, and a report waits about 300 ms to get through (over USB it's about
10 ms). So when frame reports start arriving over Bluetooth, `widgets/host_link_ble.c` asks for
latency 0, and asks for latency 30 again 2 seconds after the last one, so idle power use stays the
same. macOS takes a few seconds to apply a request and reverts ones outside Apple's accessory
guidelines (an interval range at least 15 ms wide, or exactly 15 ms), so both requests fix the
interval at 15 ms.

Where the data comes from:

- **Flags:** Claude Code runs `sofle-status hook` asynchronously on SessionStart, SessionEnd,
  UserPromptSubmit, PostToolUse, PermissionRequest, Notification, Stop and StopFailure. Each
  session keeps its own state in `~/.cache/sofle-status/sessions`, so concurrent sessions add up.
  States older than 30 minutes count as stale. The flags never wait behind a card: a push ends
  every frame with the current flags.
- **Usage:** Claude Code passes `rate_limits` to the status line command,
  `sofle-status statusline`, which caches them in `usage.json` and prints nothing.
- **Repos:** SessionStart and UserPromptSubmit record the session's working directory in
  `projects/`. A push resolves the 3 most recent to git repos and asks `gh run list` about each,
  every 2 minutes (45 seconds while a run is going). The name is the GitHub repo name.
- **Event:** the launch agent reads the Mac's calendars with EventKit every minute and when they
  change, and caches the next timed event that isn't cancelled or declined in `calendar.json`.
  Only the agent reads the calendar, so the Calendars permission belongs to Sofle Status rather
  than your terminal. The keyboard switches between the event and the repos on its own.

Both are set in `~/.claude/settings.json` (`hooks` and `statusLine`). When something changes, the
hook or status line starts `sofle-status push` in the background, which sends whatever changed.
The `au.kyle.sofle-status` launch agent (`sofle-status daemon`) pushes when the keyboard connects
or disconnects, and every minute. It needs Input Monitoring (System Settings > Privacy & Security >
Input Monitoring > Sofle Status) and asks for Calendars access when it starts.

Install with `host/install.sh`. It builds `~/Applications/Sofle Status.app`, links
`~/.local/bin/sofle-status` to it, and loads the launch agent. macOS keeps an app bundle's
permissions across updates signed with the same certificate (a bare binary lost them on every
rebuild), so the bundle is signed with an Apple Development certificate when there is one, and
`install.sh` rebuilds only when the source changed.
Other commands: `sofle-status cards` shows the card and sends it; `sofle-status time` syncs the
clock; `sofle-status status` shows every session and the combined flags; `sofle-status
idle|working|needs` shows flags by hand and pauses the hooks; `sofle-status resume` restarts
them.

`host/test_host_link.c` runs the firmware's decoder on the Mac against the reports the host would
send (`sofle-status encode`), and with `--damage` checks that a dropped, merged or flipped report
only ever loses its frame:

```
cc -I boards/shields/nice_view_legend/widgets -o /tmp/test_host_link host/test_host_link.c \
   boards/shields/nice_view_legend/widgets/host_link.c
sofle-status encode | /tmp/test_host_link --damage
```

## Tetris

The rules live in `widgets/tetris_game.c`, plain C with no ZMK or LVGL: a 10 × 20 well, clockwise
rotation inside each piece's box with kicks of 0, ±1 and ±2 cells, a shuffled bag of all 7 pieces,
the original game's speeds (level = 1 + lines / 10) and scoring. A landed piece can slide until the
next gravity tick. `widgets/tetris.c` draws the screens, mirroring `spec_tetris*()` in
`art/concepts.py`, and runs everything on the display work queue: key events only queue an input,
and gravity and auto-repeat are delayed work on the same queue. The right half reads the joystick
itself, since it's that half's first column, so the game needs nothing from the left half except
the active layer, which it already relays for the legend. The best score is kept in settings.

`host/test_tetris.c` plays 5000 random games and 200 games by a simple placement player on the Mac,
checking after every move that nothing leaves the well, only full rows clear, and the score never
drops:

```
cc -I boards/shields/nice_view_legend/widgets -o /tmp/test_tetris host/test_tetris.c \
   boards/shields/nice_view_legend/widgets/tetris_game.c && /tmp/test_tetris
```

## Screen art

Everything on the screens comes from `art/`, rendered with PIL so the mockups and the device match:

| Script | Writes |
|---|---|
| `art/concepts.py` | the screen designs (mockups go to `art/out/`); `spec_left()` and `spec_usage_ci()` mirror the left screen |
| `art/build_legend.py` | `widgets/legend_art.c`, the right-screen images |
| `art/make_lvfont.py` | `fonts/*.c`, the pixel fonts as LVGL fonts |
| `art/make_glyphs.py` | `widgets/status_glyphs.h`, the left-screen icons |

Both screens draw with the helpers in `widgets/draw.c`: portrait coordinates on 68 × 68 canvases
that are rotated into the panel's landscape orientation.

If the keymap changes, update the legend text in `art/concepts.py` and re-run `build_legend.py`.
The fonts in `art/fonts` are under the SIL Open Font License (texts in `art/fonts/LICENSES`).
