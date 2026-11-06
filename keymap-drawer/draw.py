#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["keymap-drawer", "fonttools", "shapely", "pyyaml"]
# ///
"""Draw the keymap as 1-bit blueprint sheets, one SVG per layer.

`keymap parse` still reads the keymap. This turns its YAML, plus the physical layout JSON, into
drawings. Only black and white are used, so hierarchy comes from line weight and hatching. Text is
outlined to paths, so it looks the same on GitHub whatever fonts the viewer has.

    uv run keymap_img/draw.py keymap_img/blueprint.yaml
"""
import json
import math
import sys
from pathlib import Path

import yaml
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from keymap_drawer.physical_layout import QmkLayout
from shapely import affinity
from shapely.geometry import MultiPolygon, box
from shapely.ops import unary_union

BLACK, WHITE = "#000000", "#ffffff"
SHEET_W = 880
FRAME = 12  # frame inset from the sheet edge
STRIP_H = 76  # title strip height
PAD = 30  # space between the frame and the board
MIN_TEXT = 11  # smallest lettering, in px at the README's width

# Stroke icons on a 24 unit grid, in the same line weight as the drawing
ICONS = {
    "up": "M12 20V4M6 10l6-6 6 6",
    "down": "M12 4v16M6 14l6 6 6-6",
    "left": "M20 12H4M10 6l-6 6 6 6",
    "right": "M4 12h16M14 6l6 6-6 6",
    "shift": "M12 4l9 9h-5v7H8v-7H3z",
    "ctrl": "M5 14l7-8 7 8",
    "opt": "M3 7h6l7 11h5M14 7h7",
    "cmd": "M9 9h6v6H9zM9 9V6.5A2.5 2.5 0 1 0 6.5 9H9M15 9h2.5A2.5 2.5 0 1 0 15 6.5V9M15 15v2.5a2.5 2.5 0 1 0 2.5-2.5H15M9 15H6.5A2.5 2.5 0 1 0 9 17.5V15",
    "backspace": "M9 5h12v14H9l-6-7zM12 9l6 6M18 9l-6 6",
    "delete": "M15 5H3v14h12l6-7zM6 9l6 6M12 9l-6 6",
    "enter": "M20 5v8H5M10 8l-5 5 5 5",
    "tab": "M3 12h15M12 6l6 6-6 6M21 5v14",
    "prev": "M19 5v14L8 12zM5 5v14",
    "play": "M4 5v14l9-7zM16 5v14M20 5v14",
    "next": "M5 5v14l11-7zM19 5v14",
    "vol_up": "M3 9h4l5-4v14l-5-4H3zM16 12h6M19 9v6",
    "vol_down": "M3 9h4l5-4v14l-5-4H3zM16 12h6",
    "mute": "M3 9h4l5-4v14l-5-4H3zM16 9l6 6M22 9l-6 6",
    "bluetooth": "M7 8l10 8-5 4V4l5 4-10 8",
    "bluetooth_off": "M7 8l10 8-5 4V4l5 4-10 8M4 4l16 16",
    "restart": "M5 12a7 7 0 1 0 2-5M4 4v5h5",
    "flash": "M12 4v11M7 11l5 5 5-5M5 20h14",
    "mouse_left": "M12 3a6 6 0 0 0-6 6v6a6 6 0 0 0 12 0V9a6 6 0 0 0-6-6zM12 3v7M6 10h12M8 5l-2 3M10 4l-4 5",
    "mouse_right": "M12 3a6 6 0 0 0-6 6v6a6 6 0 0 0 12 0V9a6 6 0 0 0-6-6zM12 3v7M6 10h12M16 5l2 3M14 4l4 5",
    "mouse_mid": "M12 3a6 6 0 0 0-6 6v6a6 6 0 0 0 12 0V9a6 6 0 0 0-6-6zM12 6v5",
    "game": "M4 9h16v8H4zM8 11v4M6 13h4M15 12h.5M17 14h.5",
    "off": "M12 3v9M7 6a8 8 0 1 0 10 0",
    "battery": "M2 8h17v8H2zM22 11v2M6 11v2M10 11v2M14 11v2",
}

# What keymap-drawer's legends become
LEGENDS = {
    "↑": "icon:up", "↓": "icon:down", "←": "icon:left", "→": "icon:right",
    "⇧": "icon:shift", "⌃": "icon:ctrl", "⌥": "icon:opt", "⎇": "icon:opt", "⌘": "icon:cmd",
    "⌫": "icon:backspace", "⌦": "icon:delete", "⏎": "icon:enter", "↹": "icon:tab",
    "⏮": "icon:prev", "⏯": "icon:play", "⏭": "icon:next",
    "Vol+": "icon:vol_up", "Vol-": "icon:vol_down", "VOL\nMUTE": "icon:mute",
    "CLEAR\nALL BT": "Clear\nall", "CLEAR\nSLOT": "Clear\nslot", "BOOT\nLOADER": "Boot-\nloader",
    "SOFT\nOFF": "Soft\noff", "USB/\nBT": "USB\nBT", "▽": "",
    "$$mdi:apple-keyboard-command$$": "icon:cmd", "$$mdi:apple-keyboard-control$$": "icon:ctrl",
    "$$mdi:apple-keyboard-option$$": "icon:opt", "$$mdi:apple-keyboard-shift$$": "icon:shift",
    "$$mdi:arrow-up-bold$$": "icon:up", "$$mdi:arrow-down-bold$$": "icon:down",
    "$$mdi:arrow-left-bold$$": "icon:left", "$$mdi:arrow-right-bold$$": "icon:right",
    "$$mdi:backspace$$": "icon:backspace", "$$mdi:backspace-reverse-outline$$": "icon:delete",
    "$$mdi:keyboard-esc$$": "Esc", "$$mdi:keyboard-return$$": "icon:enter",
    "$$mdi:keyboard-space$$": "Space", "$$mdi:keyboard-tab$$": "icon:tab",
    "$$mdi:backup-restore$$": "Restart", "$$mdi:progress-download$$": "Boot-\nloader",
    "$$mdi:bluetooth-off$$": "Clear\nslot", "BT CLR ALL": "Clear\nall", "&soft_off": "Soft\noff",
    "$$mdi:minus-circle-outline$$": "", "$$mdi:transfer$$": "",
    "$$mdi:mouse-left-click-outline$$": "icon:mouse_left",
    "$$mdi:mouse-right-click-outline$$": "icon:mouse_right",
    "$$mdi:mouse-scroll-wheel$$": "icon:mouse_mid", "$$mdi:volume-off$$": "icon:mute",
    "&mkp MB4": "Back", "&mkp MB5": "Fwd", "&night_red": "Red",
    "&stick_scroll MOVE_Y(-20)": "icon:up", "&stick_scroll MOVE_Y(20)": "icon:down",
    "&stick_scroll MOVE_X(-20)": "icon:left", "&stick_scroll MOVE_X(20)": "icon:right",
    "OUT USB": "USB", "OUT BLE": "BT", "PG UP": "PgUp", "PG DN": "PgDn", "HOME": "Home", "END": "End",
    "RGB BRD": "Light-", "RGB BRI": "Light+", "RGB EFF": "Effect+", "RGB EFR": "Effect-",
    "RGB OFF": "Light\noff", "RGB SPI": "Speed+", "toggle": "Toggle",
}

# Keys that wipe something or stop the keyboard, whichever keymap they came from
CAREFUL = {"Clear\nall", "Clear\nslot", "Soft\noff", "Boot-\nloader", "Restart"}


# Punctuation that sits small in the font, so it needs a boost to read at key size
SMALL_MARKS = set(",.;:'\"`~-_")


class Lettering:
    """Outlines text with the font, sharing each glyph through <defs>."""

    def __init__(self, path):
        self.font = TTFont(path)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upem = self.font["head"].unitsPerEm
        self.defs = {}

    def width(self, text, size):
        total = 0
        for ch in text:
            name = self.cmap.get(ord(ch))
            total += self.glyphs[name].width if name else self.upem * 0.5
        return total * size / self.upem

    def _glyph(self, name):
        if name not in self.defs:
            pen = SVGPathPen(self.glyphs)
            self.glyphs[name].draw(pen)
            self.defs[name] = f'<path id="g{len(self.defs)}" d="{pen.getCommands()}"/>'
        return self.defs[name].split('"')[1]

    def draw(self, text, x, y, size, fill=WHITE, anchor="middle", weight=0.32):
        """Letters on the baseline y. weight thickens the thin drafting strokes."""
        if anchor == "middle":
            x -= self.width(text, size) / 2
        elif anchor == "end":
            x -= self.width(text, size)
        k = size / self.upem
        out = []
        for ch in text:
            name = self.cmap.get(ord(ch))
            if name:
                if ch != " ":
                    out.append(
                        f'<use href="#{self._glyph(name)}" transform="translate({x:.2f} {y:.2f}) '
                        f'scale({k:.5f} {-k:.5f})"/>'
                    )
                x += self.glyphs[name].width * k
            else:
                x += size * 0.5
        return (
            f'<g fill="{fill}" stroke="{fill}" stroke-width="{weight / k:.1f}" '
            f'stroke-linejoin="round">{"".join(out)}</g>'
        )


def icon(name, cx, cy, size, colour=WHITE, weight=1.5):
    k = size / 24
    return (
        f'<path d="{ICONS[name]}" transform="translate({cx - size / 2:.2f} {cy - size / 2:.2f}) '
        f'scale({k:.4f})" fill="none" stroke="{colour}" stroke-width="{weight / k:.2f}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def legend_of(key):
    if key is None:
        return {}
    if isinstance(key, dict):
        return key
    return {"t": key}


def resolve(text):
    text = str(text) if text is not None else ""
    text = LEGENDS.get(text, text)
    if text.startswith("$$") or (text.startswith("&") and len(text) > 1):
        print(f"no legend for {text}", file=sys.stderr)
        return ""
    return text


class Board:
    """Where everything physically is. Keys are {x, y, w, h, r}, centred, in the file's units."""

    def __init__(self, keys, unit, outlines=None, screens=(), parts=(), plate=None, knob=None, joystick=None):
        self.keys, self.unit = keys, unit
        self.outlines, self.screens, self.parts = outlines, list(screens), list(parts)
        self.plate, self.knob, self.joystick = plate, knob, joystick

    @classmethod
    def from_file(cls, path, root):
        """Measured from the real board, so this has the true stagger and edges."""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        plate = data.get("plate")
        if plate:
            plate = json.loads((root / plate).read_text(encoding="utf-8"))
        return cls(
            data["keys"], data["unit"], data.get("outlines"), data.get("screens", ()),
            data.get("parts", ()), plate, data.get("knob"), data.get("joystick"),
        )

    @classmethod
    def from_layout(cls, path, cfg):
        """From a QMK-style layout JSON, with the board edge traced around the keys."""
        info = json.loads(path.read_text(encoding="utf-8"))
        layouts = {name: value["layout"] for name, value in info["layouts"].items()}
        keys = [
            {"x": k.pos.x, "y": k.pos.y, "w": k.width - 6, "h": k.height - 6, "r": k.rotation}
            for k in QmkLayout(layouts=layouts).generate(None, 60.0).keys
        ]
        return cls(keys, 60.0, None, cfg.get("screens", ()), cfg.get("parts", ()))

    def bounds(self):
        points = [p for outline in self.outlines or [] for p in outline]
        if self.plate:
            xs = [v for line in self.plate["lines"] for v in (line[0], line[2])]
            ys = [v for line in self.plate["lines"] for v in (line[1], line[3])]
        elif points:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
        else:
            xs = [k["x"] + s * self.unit / 2 for k in self.keys for s in (-1, 1)]
            ys = [k["y"] + s * self.unit / 2 for k in self.keys for s in (-1, 1)]
        return min(xs), min(ys), max(xs), max(ys)


class Sheet:
    def __init__(self, cfg, board, letters):
        self.cfg, self.board, self.ink = cfg, board, letters
        left, top, right, bottom = board.bounds()
        self.scale = (SHEET_W - 2 * (FRAME + PAD)) / (right - left)
        self.key = board.unit * self.scale
        self.ox = FRAME + PAD - left * self.scale
        self.oy = FRAME + PAD - top * self.scale
        self.board_h = (bottom - top) * self.scale
        self.h = FRAME + PAD + self.board_h + PAD + STRIP_H + FRAME

    def place(self, x, y):
        return x * self.scale + self.ox, y * self.scale + self.oy

    def centre(self, index):
        k = self.board.keys[index]
        return self.place(k["x"], k["y"])

    def plate(self):
        """The vendor's plate drawing, as hairlines behind the keys."""
        data = self.board.plate
        path = ""
        for x1, y1, x2, y2 in data["lines"]:
            (a, b), (c, d) = self.place(x1, y1), self.place(x2, y2)
            path += f"M{a:.1f} {b:.1f}L{c:.1f} {d:.1f}"
        for cx, cy, r, a0, a1 in data["arcs"]:
            a1 += 360 if a1 < a0 else 0
            steps = max(6, int((a1 - a0) / 6))
            points = [
                self.place(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
                           cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
                for i in range(steps + 1)
            ]
            path += "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points)
        out = f'<path d="{path}" fill="none" stroke="{WHITE}" stroke-width="1" stroke-linecap="round"/>'
        for cx, cy, r in data["circles"]:
            x, y = self.place(cx, cy)
            out += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * self.scale:.1f}" fill="none" stroke="{WHITE}" stroke-width="1"/>'
        return out

    def outline(self):
        if self.board.plate:
            return self.plate()
        if self.board.outlines:
            polygons = [[self.place(*p) for p in o] for o in self.board.outlines]
        else:
            shapes = []
            for k in self.board.keys:
                x, y = self.place(k["x"], k["y"])
                w, h = k["w"] * self.scale, k["h"] * self.scale
                shapes.append(affinity.rotate(box(x - w / 2, y - h / 2, x + w / 2, y + h / 2), k["r"], origin=(x, y)))
            shape = unary_union(shapes).buffer(self.key * 0.5, join_style=2).buffer(-self.key * 0.38, join_style=1)
            polygons = [p.simplify(0.4).exterior.coords for p in (shape.geoms if isinstance(shape, MultiPolygon) else [shape])]
        paths = "".join("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z" for points in polygons)
        return f'<path d="{paths}" fill="{BLACK}" stroke="{WHITE}" stroke-width="2" stroke-linejoin="round"/>'

    def legend(self, text, cx, cy, width, colour=WHITE, big=0.42, min_size=MIN_TEXT):
        """One legend, centred on cx, cy: an icon, a letter, or a word or two."""
        text = resolve(text)
        if not text:
            return ""
        if text.startswith("icon:"):
            return icon(text[5:], cx, cy, self.key * big, colour)
        lines = text.split("\n")
        longest = max(lines, key=len)
        size = self.key * (big if len(longest) == 1 else min(big, 0.31 if len(longest) == 2 else 0.27))
        while size > min_size and self.ink.width(longest, size) > width:
            size -= 0.25
        lead = size * 1.12
        y = cy + size * 0.36 - lead * (len(lines) - 1) / 2
        out = ""
        for line in lines:
            out += self.ink.draw(line, cx, y, size, colour)
            y += lead
        return out

    def draw_key(self, index, binding, show_shifted=True):
        k = self.board.keys[index]
        cx, cy = self.centre(index)
        binding = dict(legend_of(binding))
        if not show_shifted:
            binding.pop("s", None)
        kind = binding.get("type", "")
        if k.get("skip"):
            return ""
        if str(binding.get("s", "")).endswith("bluetooth-connect$$"):
            binding = {"t": "BT", "h": binding.get("h", "")}
        if kind == "bootloader" or resolve(binding.get("t", "")) in CAREFUL:
            kind = "danger"
        cap_w, cap_h = k["w"] * self.scale, k["h"] * self.scale
        cap = min(cap_w, cap_h)
        half = cap / 2
        rect = f'x="{cx - cap_w / 2:.2f}" y="{cy - cap_h / 2:.2f}" width="{cap_w:.2f}" height="{cap_h:.2f}" rx="2.5"'
        spin = f' transform="rotate({k["r"]} {cx:.2f} {cy:.2f})"' if k["r"] else ""
        tap, hold, shifted = binding.get("t", ""), binding.get("h", ""), binding.get("s", "")
        if kind == "held":
            return (
                f'<rect {rect} fill="{WHITE}"{spin}/>'
                + self.ink.draw("Hold", cx, cy + self.key * 0.075, self.key * 0.23, BLACK, weight=0.42)
            )
        if kind == "trans" or tap == "▽":
            return f'<rect {rect} fill="{BLACK}" stroke="{WHITE}" stroke-width="1.25" stroke-dasharray="5 4"{spin}/>'
        if not (resolve(tap) or hold or shifted):
            return f'<rect {rect} fill="{BLACK}" stroke="{WHITE}" stroke-width="1.25" stroke-dasharray="0.1 4" stroke-linecap="round"{spin}/>'
        out = ""
        if kind == "danger":
            out += f'<rect {rect} fill="{BLACK}"{spin}/><rect {rect} fill="url(#hatch)" stroke="{WHITE}" stroke-width="1.5"{spin}/>'
            plate_w, plate_h = cap * 0.82, cap * 0.56
            out += (
                f'<rect x="{cx - plate_w / 2:.2f}" y="{cy - plate_h / 2:.2f}" width="{plate_w:.2f}" '
                f'height="{plate_h:.2f}" fill="{BLACK}"/>'
            )
            return out + self.legend(tap, cx, cy, plate_w - 4)
        out += f'<rect {rect} fill="{BLACK}" stroke="{WHITE}" stroke-width="1.5"{spin}/>'
        main_y = cy
        if hold:
            main_y -= self.key * 0.13
        if shifted:
            main_y += self.key * 0.14
        big = 0.42 if not hold else 0.3
        if resolve(tap) in SMALL_MARKS:
            big *= 1.25
        out += self.legend(tap, cx, main_y, cap - 8, big=big)
        if shifted:
            out += self.legend(shifted, cx, cy - self.key * 0.2, cap - 8, big=0.3)
        if hold:
            hold = "Ctrl" if resolve(hold) == "icon:ctrl" else hold
            rule_y = cy + self.key * 0.13
            out += (
                f'<path d="M{cx - half + 6:.2f} {rule_y:.2f}h{cap - 12:.2f}" stroke="{WHITE}" '
                'stroke-width="1"/>'
            )
            out += self.legend(hold, cx, cy + self.key * 0.28, cap - 10, big=0.22)
        return out

    def draw_combo(self, combo):
        points = [self.centre(p) for p in combo["p"]]
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        binding = legend_of(combo.get("k"))
        tap, shifted = resolve(binding.get("t", "")), binding.get("s", "")
        w, h = self.key * 0.46, self.key * 0.34
        label = f"{tap} {shifted}" if shifted else tap
        if not label.startswith("icon:"):
            w = max(w, self.ink.width(label, self.key * 0.22) + 10)
        out = f'<rect x="{cx - w / 2:.2f}" y="{cy - h / 2:.2f}" width="{w:.2f}" height="{h:.2f}" rx="2" fill="{WHITE}" stroke="{BLACK}" stroke-width="2"/>'
        if label.startswith("icon:"):
            return out + icon(label[5:], cx, cy, self.key * 0.27, BLACK)
        return out + self.ink.draw(label, cx, cy + self.key * 0.078, self.key * 0.22, BLACK, weight=0.42)

    def draw_screens(self, title):
        out = ""
        for part in self.board.parts:
            x, y = self.place(part["x"], part["y"])
            w, h = part["w"] * self.scale, part["h"] * self.scale
            out += f'<rect x="{x - w / 2:.2f}" y="{y - h / 2:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{BLACK}" stroke="{WHITE}" stroke-width="1.25"/>'
        for s in self.board.screens:
            cx, cy = self.place(s["x"], s["y"])
            w, h = s["w"] * self.scale, s["h"] * self.scale
            x, y = cx - w / 2, cy - h / 2
            out += f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="2" fill="{BLACK}" stroke="{WHITE}" stroke-width="1.25"/>'
            if s.get("shows_layer"):
                out += f'<rect x="{x + 4:.2f}" y="{y + 4:.2f}" width="{w - 8:.2f}" height="{h - 8:.2f}" fill="{WHITE}"/>'
                size = self.key * 0.36
                while self.ink.width(title, size) > h - 18 and size > MIN_TEXT:
                    size -= 0.25
                out += f'<g transform="rotate(-90 {cx:.2f} {cy:.2f})">'
                out += self.ink.draw(title, cx, cy + size * 0.36, size, BLACK, weight=0.42) + "</g>"
            elif s.get("label"):
                out += f'<g transform="rotate(-90 {cx:.2f} {cy:.2f})">'
                out += self.ink.draw(s["label"], cx, cy + 5, 15) + "</g>"
            else:
                out += f'<g transform="rotate(-90 {cx:.2f} {cy:.2f})">{icon("battery", cx, cy, self.key * 0.5)}</g>'
        return out

    def draw_knob(self, bindings, turn):
        knob = self.board.knob
        if not knob:
            return ""
        x, y = self.place(knob["x"], knob["y"])
        r = knob["r"] * self.scale
        out = f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{BLACK}" stroke="{WHITE}" stroke-width="2"/>'
        out += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r + 4:.2f}" fill="none" stroke="{WHITE}" stroke-width="1" stroke-dasharray="3 3"/>'
        binding = legend_of(bindings[knob["position"]])
        if binding.get("type") != "trans":
            out += self.legend(binding.get("t", ""), x, y, r * 1.6, big=0.3)
        if turn:
            out += f'<rect x="{x - 26:.2f}" y="{y - r - 26:.2f}" width="52" height="17" fill="{BLACK}"/>'
            out += self.ink.draw(turn, x, y - r - 12, MIN_TEXT + 2)
        return out

    def draw_joystick(self, bindings):
        stick = self.board.joystick
        if not stick:
            return ""
        x, y = self.place(stick["x"], stick["y"])
        r = stick["r"] * self.scale * 1.12
        out = f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{BLACK}" stroke="{WHITE}" stroke-width="2"/>'
        out += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * 0.36:.2f}" fill="none" stroke="{WHITE}" stroke-width="1"/>'
        spot = r * 0.68
        for name, dx, dy in (("up", 0, -1), ("down", 0, 1), ("left", -1, 0), ("right", 1, 0)):
            binding = legend_of(bindings[stick[name]])
            if binding.get("type") != "trans":
                # Show the way the stick is pushed. Scrolling may be reversed, so its direction misleads.
                legend = f"icon:{name}" if str(binding.get("t", "")).startswith("&stick_scroll") else binding.get("t", "")
                out += self.legend(legend, x + dx * spot, y + dy * spot, r, big=0.2)
        press = legend_of(bindings[stick["press"]])
        if press.get("type") != "trans":
            out += self.legend(press.get("t", ""), x, y, r * 0.6, big=0.19)
        return out

    def strip(self, number, title, reach, sheet_no, sheets):
        top = self.h - FRAME - STRIP_H
        right = SHEET_W - FRAME
        out = f'<path d="M{FRAME} {top:.2f}H{right}" stroke="{WHITE}" stroke-width="2"/>'
        index_w, info_w = 78, 212
        for x in (FRAME + index_w, right - info_w):
            out += f'<path d="M{x} {top:.2f}V{self.h - FRAME:.2f}" stroke="{WHITE}" stroke-width="1.25"/>'
        mid = top + STRIP_H / 2
        out += self.ink.draw(str(number), FRAME + index_w / 2, mid + 17, 48, weight=0.5)
        x = FRAME + index_w + 16
        out += self.ink.draw(title, x, mid - 3, 27, anchor="start", weight=0.45)
        out += self.ink.draw(reach, x, mid + 22, 15.5, anchor="start")
        x = right - info_w + 14
        out += self.ink.draw(self.cfg["name"], x, mid - 6, 18, anchor="start", weight=0.4)
        out += self.ink.draw(f"Sheet {sheet_no} of {sheets}", x, mid + 19, 14.5, anchor="start")
        return out

    def render(self, number, title, reach, rows, combos, sheet_no, sheets, show_shifted=True, turn=""):
        bindings = [k for row in rows for k in (row if isinstance(row, list) else [row])]
        body = ""
        body += f'<rect width="{SHEET_W}" height="{self.h:.2f}" fill="{BLACK}"/>'
        body += f'<rect x="{FRAME}" y="{FRAME}" width="{SHEET_W - 2 * FRAME}" height="{self.h - 2 * FRAME - STRIP_H:.2f}" fill="url(#grid)"/>'
        body += self.outline()
        body += self.draw_screens(title)
        for i, binding in enumerate(bindings):
            body += self.draw_key(i, binding, show_shifted)
        body += self.draw_knob(bindings, turn) + self.draw_joystick(bindings)
        for combo in combos:
            body += self.draw_combo(combo)
        body += f'<rect x="{FRAME}" y="{FRAME}" width="{SHEET_W - 2 * FRAME}" height="{self.h - 2 * FRAME:.2f}" fill="none" stroke="{WHITE}" stroke-width="2"/>'
        body += self.strip(number, title, reach, sheet_no, sheets)
        return self.wrap(body, f"{self.cfg['name']}: {title} layer", reach, self.h)

    def wrap(self, body, title, desc, height):
        defs = "".join(self.ink.defs.values())
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W} {height:.2f}" '
            f'width="{SHEET_W}" role="img"><title>{title}</title><desc>{desc}</desc><defs>'
            f'<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">'
            f'<circle cx="10" cy="10" r="0.7" fill="{WHITE}"/></pattern>'
            f'<pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" '
            f'patternTransform="rotate(45)"><rect width="2" height="7" fill="{WHITE}"/></pattern>'
            f"{defs}</defs>{body}</svg>\n"
        )


def key_to_symbols(cfg, here):
    """A small sheet explaining how to read the others."""
    samples = [
        ({"t": "A"}, "Tap"),
        ({"t": "Space", "h": "Layer"}, "Tap, or hold\nfor a layer"),
        ({"type": "trans"}, "Same as the\nlayer below"),
        ({"t": ""}, "Does nothing"),
        ({"type": "held"}, "Held to reach\nthis layer"),
        ({"t": "Soft\noff", "type": "danger"}, "Take care"),
    ]
    step = 118
    count = len(samples) + (1 if cfg.get("show_combos", True) else 0)
    keys = [{"x": i * step, "y": 0, "w": 56, "h": 56, "r": 0} for i in range(max(count, len(samples)))]
    sheet = Sheet(cfg, Board(keys, 60.0), Lettering(here / "fonts" / "osifont-lgpl3fe.ttf"))
    height = FRAME * 2 + 150
    sheet.oy = FRAME + 46
    body = f'<rect width="{SHEET_W}" height="{height}" fill="{BLACK}"/>'
    for i, (binding, caption) in enumerate(samples):
        body += sheet.draw_key(i, binding)
        cx, cy = sheet.centre(i)
        for n, line in enumerate(caption.split("\n")):
            body += sheet.ink.draw(line, cx, cy + sheet.key / 2 + 24 + n * 18, 15)
    if cfg.get("show_combos", True):
        cx, cy = sheet.centre(len(samples))
        body += sheet.draw_combo({"p": [len(samples)], "k": "Esc"})
        for n, line in enumerate(("Press the two", "keys around it")):
            body += sheet.ink.draw(line, cx, cy + sheet.key / 2 + 24 + n * 18, 15)
    body += f'<rect x="{FRAME}" y="{FRAME}" width="{SHEET_W - 2 * FRAME}" height="{height - 2 * FRAME}" fill="none" stroke="{WHITE}" stroke-width="2"/>'
    svg = sheet.wrap(body, "How to read the keymap drawings", "What each style of key means", height)
    (here / f"{cfg['prefix']}-key.svg").write_text(svg, encoding="utf-8")


def main():
    config_path = Path(sys.argv[1])
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    here = config_path.parent
    keymap = yaml.safe_load((root / cfg["keymap"]).read_text(encoding="utf-8"))
    if "board" in cfg:
        board = Board.from_file(root / cfg["board"], root)
    else:
        board = Board.from_layout(root / cfg["layout"], cfg)

    sheets = cfg["sheets"]
    for sheet_no, (layer, spec) in enumerate(sheets.items(), start=1):
        letters = Lettering(here / "fonts" / "osifont-lgpl3fe.ttf")
        sheet = Sheet(cfg, board, letters)
        combos = [c for c in keymap.get("combos", []) if layer in c.get("l", [layer])]
        if not cfg.get("show_combos", True):
            combos = []
        svg = sheet.render(
            list(keymap["layers"]).index(layer),
            spec.get("title", layer),
            spec["reach"],
            keymap["layers"][layer],
            combos,
            sheet_no,
            len(sheets),
            spec.get("show_shifted", True),
            spec.get("turn", ""),
        )
        out = here / f"{cfg['prefix']}-{spec['file']}.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"{out.name}: {len(svg) // 1024} KB")
    key_to_symbols(cfg, here)


if __name__ == "__main__":
    main()
