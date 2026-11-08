# How Kyles Sofle works

The internals behind the [README](README.md): how the Mac and Windows feed the left screen, how
Tetris runs, and where the screen art comes from.

## Claude Code status, clock and card

`host/sofle-status` feeds the left screen from the Mac. Everything travels in keyboard indicator
lights macOS doesn't use, as raw HID output reports over Bluetooth or USB, and the firmware decodes
them in `widgets/host_link.c`, whose header documents the format.

A report with Num Lock off carries two flags, and either lights the ✳ badge:

| Light | Meaning |
|---|---|
| Scroll Lock | some session is working |
| Compose | some session needs you (permission prompt) |

Reports with Num Lock on make up a frame, 2 bits per report in Scroll Lock and Compose, with Kana
alternating so no two reports in a row match. A frame is a type byte, a fixed-length payload and a
CRC-8: the clock, the usage limits, or one repo row. The next report with Num Lock off ends it and
carries the flags again. The keyboard drops any frame with the wrong length, a broken Kana sequence
or a bad CRC, and times in a frame count from its first report.

The keyboard can't answer, so the host sends a card when it changes, every 30 minutes, and whenever
the keyboard reconnects (it forgets everything when it sleeps), with a clock frame first. If nothing
else went out for 10 minutes, a clock frame does, so the card stays live. To keep the radio quiet, a
usage percentage that creeps up waits 3 minutes between sends (a new reset time or reaching 100%
goes at once), and repo rows keep their places when the same repos change order. Nothing goes over
Bluetooth while the keyboard is plugged in, since it shows what arrives over USB then, and unplugging
starts a push over Bluetooth.

ZMK asks the Mac for a Bluetooth peripheral latency of 30. While idle, the keyboard listens only
every 30th connection event, and a report waits up to about 360 ms to get through, against about
10 ms over USB. So when frame reports start arriving over Bluetooth, `widgets/host_link_ble.c` asks
for latency 0, and asks for latency 30 again 2 seconds after the last one, so idle power use stays
the same. macOS takes a few seconds to apply a request, and ignores ones outside Apple's accessory
guidelines (an interval range at least 15 ms wide, or exactly 15 ms), so both requests fix the
interval at 15 ms.

Where the data comes from:

- Flags: Claude Code runs `sofle-status hook` asynchronously on SessionStart, SessionEnd,
  UserPromptSubmit, PostToolUse, PermissionRequest, Notification, Stop and StopFailure. Each session
  keeps its own state in `~/.cache/sofle-status/sessions`, so concurrent sessions add up, and states
  older than 30 minutes count as stale. The flags never wait behind a card: a push ends every frame
  with the current flags.
- Usage: Claude Code passes `rate_limits` to the status line command, `sofle-status statusline`,
  which caches them in `usage.json` and prints nothing.
- Repos: SessionStart and UserPromptSubmit record the session's working directory in `projects/`. A
  push resolves the 3 most recent to git repos and asks `gh run list` about each, every 2 minutes (45
  seconds while a run is going). The name shown is the GitHub repo name.
- Event: the launch agent reads the Mac's calendars with EventKit every minute and when they change,
  and caches the next timed event that isn't cancelled or declined in `calendar.json`. Only the agent
  reads the calendar, so the Calendars permission belongs to Sofle Status rather than your terminal.
  The keyboard switches between the event and the repos on its own.

The hooks and status line are set in `~/.claude/settings.json` (`hooks` and `statusLine`). When
something changes, they start `sofle-status push` in the background, which sends whatever changed.
The `au.kyle.sofle-status` launch agent (`sofle-status daemon`) pushes when the keyboard connects or
disconnects, and every minute. It needs Input Monitoring (System Settings > Privacy & Security >
Input Monitoring > Sofle Status) and asks for Calendars access when it starts.

`host/install.sh` builds `~/Applications/Sofle Status.app`, links `~/.local/bin/sofle-status` to it,
and loads the launch agent. macOS keeps an app bundle's permissions across updates signed with the
same certificate, where a bare binary loses them on every rebuild. So the bundle is signed with an
Apple Development certificate when there is one, and `install.sh` rebuilds only when the source
changed.

Other commands:

| Command | What it does |
|---|---|
| `sofle-status cards` | shows the card and sends it |
| `sofle-status time` | syncs the clock |
| `sofle-status status` | shows every session and the combined flags |
| `sofle-status idle`, `working` or `needs` | shows those flags by hand and pauses the hooks |
| `sofle-status resume` | restarts the hooks |

`host/test_host_link.c` runs the firmware's decoder on the Mac against the reports the host would
send (`sofle-status encode`). With `--damage`, it checks that a dropped, merged or flipped report
only ever loses its frame:

```
cc -I boards/shields/nice_view_legend/widgets -o /tmp/test_host_link host/test_host_link.c \
   boards/shields/nice_view_legend/widgets/host_link.c
sofle-status encode | /tmp/test_host_link --damage
```

### Windows

`host/windows` is the same tool for Windows, in Rust: `sofle-status.exe` for the hooks, the status
line and the commands above, and `sofle-status-agent.exe` in place of the launch agent. It sends the
same reports, but not in the keyboard's lights. Windows keeps keyboards for itself and refuses an
app's output reports to them: over Bluetooth, `HidD_SetOutputReport` and `WriteFile` both fail with
"Incorrect function". So the left half also has a vendor-defined HID interface,
[zmk-raw-hid](https://github.com/zzeneg/zmk-raw-hid) (usage page 0xFF60), which any app may write
to, and `widgets/status.c` feeds each byte of its reports to the same decoder. Up to 32 reports
travel in one HID report, so a whole card takes 14 writes instead of about 450. A short HID report
is padded with copies of its last byte, which the decoder ignores as repeats. Every push starts
with the flags, because Windows sends the keyboard its own lights whenever they change, and with Num
Lock on, the keyboard takes that for the start of a frame.

How it differs from the Mac:

- There's no calendar yet, so the card shows the repos (the agent only reads `calendar.json`).
- Hooks and the status line ask the agent to push instead of starting a push themselves, so cards
  go out only while the agent runs. A hook still sends the flags itself.
- The agent looks for the keyboard every 2 seconds. A Bluetooth keyboard's devices can stay while
  it's asleep or on another slot, so it checks the Bluetooth device's connection state too, and
  takes a new last-connected time for a reconnection.
- State and the agent's log are in `%LOCALAPPDATA%\sofle-status`.
- CI needs `gh`: `winget install GitHub.cli`, then `gh auth login`.

`host\windows\install.ps1` (needs Rust) builds both programs into `~/.local/bin`, starts the agent,
and adds it to the programs Windows starts at sign-in. Then add the hooks and status line to
`~/.claude/settings.json`. The hooks run the program without a shell:

```json
"hooks": {
  "SessionStart": [{ "hooks": [{ "type": "command", "command": "C:/Users/<you>/.local/bin/sofle-status.exe", "args": ["hook"], "async": true }] }],
  ...the same for SessionEnd, UserPromptSubmit, PostToolUse, PermissionRequest, Notification, Stop and StopFailure
},
"statusLine": { "type": "command", "command": "~/.local/bin/sofle-status.exe statusline" }
```

`sofle-status list` shows whether Windows sees the raw HID interface. The left half needs firmware
with it, and the interface changes the keyboard's Bluetooth services, so a computer that paired with
it before may need to pair again.

`cargo test` in `host/windows` builds `host/test_host_link.c` with MSVC and runs the decoder, with
`--damage`, on the HID reports `sofle-status encode --raw` prints.

## Tetris

The rules live in `widgets/tetris_game.c`, plain C with no ZMK or LVGL: a 10 × 20 well, clockwise
rotation inside each piece's box with kicks of 0, ±1 and ±2 cells, a shuffled bag of all 7 pieces,
and the original game's speeds (level = 1 + lines / 10) and scoring. A landed piece can slide until
the next gravity tick.

`widgets/tetris.c` draws the screens, mirroring `spec_tetris*()` in `art/concepts.py`, and runs
everything on the display work queue: key events only queue an input, and gravity and auto-repeat
are delayed work on the same queue. The joystick is the right half's first column, so the right half
reads it itself and needs nothing from the left half except the active layer, which it already
relays for the legend. The best score is kept in settings.

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
| `art/make_readme_images.py` | `docs/images/`, the README's images: every screen in black and white, the plate drawing (`art/sofle_outline.json`, from the seller's case files) with the screens in it, and a Tetris clip played by `host/test_tetris.c --dump` |

Both screens draw with the helpers in `widgets/draw.c`, in portrait coordinates on 68 × 68 canvases
that are rotated into the panel's landscape orientation.

If the keymap changes, update the legend text in `art/concepts.py` and re-run `build_legend.py`.
The fonts in `art/fonts` are under the SIL Open Font License (texts in `art/fonts/LICENSES`).
