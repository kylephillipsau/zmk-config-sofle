"""Mockups of right-screen concepts for the nice!view (portrait 68x160, 1 = ink)."""
import sys
sys.path.insert(0, '.')
from PIL import Image, ImageDraw, ImageFont
from lvimg import decode_c_array, native_to_portrait, preview

W, H = 68, 160
F = 'fonts/'
silk = ImageFont.truetype(F + 'Silkscreen-Regular.ttf', 8)      # 5px caps
silk_b = ImageFont.truetype(F + 'Silkscreen-Bold.ttf', 8)
silk16 = ImageFont.truetype(F + 'Silkscreen-Regular.ttf', 16)   # 10px caps
jer20 = ImageFont.truetype(F + 'Jersey10-Regular.ttf', 20)      # 11px
jer30 = ImageFont.truetype(F + 'Jersey10-Regular.ttf', 30)      # 16px
jer40 = ImageFont.truetype(F + 'Jersey10-Regular.ttf', 40)      # 22px
mont14 = ImageFont.truetype(F + 'Montserrat[wght].ttf', 14)
mont14.set_variation_by_name('SemiBold')


def glyph(rows):
    return [[c == '#' for c in r] for r in rows]


WIFI = glyph([
    "...#####...",
    ".##.....##.",
    "#..#####..#",
    ".##.....##.",
    "...#####...",
    "..#.....#..",
    "....###....",
    ".....#.....",
])
CROSS = glyph([
    "#.....#",
    ".#...#.",
    "..#.#..",
    "...#...",
    "..#.#..",
    ".#...#.",
    "#.....#",
])
BT = glyph([
    "...#...",
    "...##..",
    ".#.#.#.",
    "..###..",
    "...#...",
    "..###..",
    ".#.#.#.",
    "...##..",
    "...#...",
])
USB = glyph([
    "...#...",
    "..###..",
    "...#.#.",
    ".#.#.#.",
    ".#.##..",
    "..##...",
    "...#...",
    "..###..",
])
BOLT = glyph([
    "...##",
    "..##.",
    ".####",
    "..##.",
    ".##..",
    "##...",
])
ARROW_U = glyph(["...#...", "..###..", ".#####.", "#######", "..###..", "..###..", "..###.."])
CAPS = glyph([
    "....#....",
    "...###...",
    "..#####..",
    ".###.###.",
    "###...###",
    "..##.##..",
    "..##.##..",
    "..#####..",
    ".........",
    "..#####..",
])
MOON = glyph([
    "..####.",
    ".##....",
    "##.....",
    "##.....",
    "##.....",
    ".##....",
    "..####.",
])


def rot(g, k):
    for _ in range(k % 4):
        g = [list(r) for r in zip(*g[::-1])]
    return g


def blit(img, g, x, y, ink=1):
    px = img.load()
    for j, row in enumerate(g):
        for i, on in enumerate(row):
            if on and 0 <= x + i < img.width and 0 <= y + j < img.height:
                px[x + i, y + j] = ink


def new():
    img = Image.new('1', (W, H), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = '1'
    return img, d


def text_w(d, s, font):
    b = d.textbbox((0, 0), s, font=font)
    return b[2] - b[0], b[3] - b[1], b[0], b[1]


def text(d, xy, s, font, anchor='l', fill=1):
    w, h, ox, oy = text_w(d, s, font)
    x, y = xy
    if anchor == 'c':
        x = (W - w) // 2 if x is None else x - w // 2
    elif anchor == 'r':
        x = x - w
    d.text((x - ox, y - oy), s, font=font, fill=fill)
    return w, h


def battery(d, x, y, level, charging=False, img=None):
    # mirrors util.c draw_battery()
    d.rectangle([x, y, x + 28, y + 11], outline=1, fill=0)
    fill = (level + 2) // 4
    if fill:
        d.rectangle([x + 2, y + 2, x + 1 + fill, y + 9], fill=1)
    d.rectangle([x + 30, y + 3, x + 32, y + 8], fill=1)
    d.point([(x + 31, y + 4 + k) for k in range(4)], fill=0)
    if charging and img is not None:
        blit(img, BOLT, x + 12, y + 3, ink=0)


def status_bar(img, d, level=78, connected=True):
    battery(d, 0, 2, level, img=img)
    blit(img, WIFI if connected else CROSS, W - (11 if connected else 7) - 1, 3)


def dither(img, box, pattern='checker'):
    px = img.load()
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pattern == 'checker' and (x + y) % 2 == 0:
                px[x, y] = 1
            elif pattern == 'sparse' and x % 4 == 0 and y % 4 == (x // 4) % 2 * 2:
                px[x, y] = 1
            elif pattern == 'lines' and y % 3 == 0:
                px[x, y] = 1


def mini_sofle(img, d, cx, y):
    """A small two-half Sofle silhouette with column stagger and the encoder knob."""
    stagger = [3, 3, 1, 0, 1, 2]  # outer pinky .. index column offsets
    k, g = 3, 1                   # key size, gap
    def half(x0, mirror):
        cols = list(range(6))
        for c in cols:
            cc = 5 - c if mirror else c
            off = stagger[cc]
            for r in range(4):
                xx = x0 + c * (k + g)
                yy = y + off + r * (k + g)
                d.rectangle([xx, yy, xx + k - 1, yy + k - 1], fill=1)
        # thumb row
        for t in range(3):
            tx = x0 + (2 + t) * (k + g) if not mirror else x0 + (1 - t + 3) * (k + g) - 4
            ty = y + 4 * (k + g) + 2 + (t if not mirror else t)
            d.rectangle([tx, ty, tx + k - 1, ty + k - 1], fill=1)
    half(cx - 30, False)
    half(cx + 7, True)
    # encoder knob on the left half's inner edge
    d.ellipse([cx - 6, y + 12, cx - 1, y + 17], outline=1)


# ---------------------------------------------------------------- concepts

def current_balloon():
    src = open('reference/stock_art.c').read()
    img, d = new()
    status_bar(img, d)
    art = native_to_portrait(decode_c_array(src, 'balloon'))
    img.paste(art, (0, 20))
    return img


def nameplate(level=78):
    img, d = new()
    status_bar(img, d, level)
    # big stacked name
    text(d, (None, 30), 'KYLES', jer30, 'c')
    text(d, (None, 50), 'SOFLE', jer30, 'c')
    d.line([(6, 74), (61, 74)], fill=1)
    mini_sofle(img, d, 34, 86)
    d.line([(6, 122), (61, 122)], fill=1)
    text(d, (None, 129), 'EST 2026', silk, 'c')
    dither(img, (0, 142, W, 160), 'checker')
    d.rectangle([14, 145, 53, 156], fill=0)
    text(d, (None, 148), 'MK I', silk, 'c')
    return img


def cheat_card():
    img, d = new()
    status_bar(img, d)
    d.rectangle([0, 20, W - 1, 31], fill=1)
    text(d, (None, 23), 'QUICK KEYS', silk_b, 'c', fill=0)
    rows = [
        ('SOFT OFF', 'Q+S+Z'),
        ('WAKE', 'RESET'),
        ('BT SLOT', 'L2 1-5'),
        ('BT CLEAR', 'L2 Q'),
        ('USB/BLE', 'L2 A/S'),
        ('FLASH', 'L2 C'),
        ('RGB', 'L1 Z/X'),
        ('ARROWS', 'L1 IJKL'),
    ]
    y = 35
    for label, keys in rows:
        text(d, (1, y), label, silk)
        text(d, (W - 1, y + 7), keys, silk_b, 'r')
        y += 15
        d.point([(x, y - 2) for x in range(0, W, 2)], fill=1)
    return img


def legend_idle(level=78):
    img, d = new()
    status_bar(img, d, level)
    text(d, (None, 34), 'KYLES', jer30, 'c')
    text(d, (None, 52), 'SOFLE', jer30, 'c')
    mini_sofle(img, d, 34, 84)
    text(d, (None, 124), 'HOLD A LAYER', silk, 'c')
    text(d, (None, 132), 'FOR KEYS', silk, 'c')
    d.rectangle([0, 146, W - 1, 159], outline=1)
    text(d, (None, 150), 'BASE', silk_b, 'c')
    return img


def arrow_cluster(img, d, x, y):
    """Inverted-T arrow keys, 4 boxes of 11px."""
    s = 11
    boxes = [(x + s, y, 0), (x, y + s + 1, 3), (x + s, y + s + 1, 2), (x + 2 * s, y + s + 1, 1)]
    for bx, by, r in boxes:
        d.rectangle([bx, by, bx + s - 1, by + s - 1], outline=1)
        blit(img, rot(ARROW_U, r), bx + 2, by + 2)


# Silkscreen draws ; ' , . as 1-2px specks, so key labels use these bolder glyphs.
# Rows 0-4 sit on the caps height; row 5 is a descender.
PUNCT = {
    ';': glyph(["##", "##", "..", "##", "##", ".#"]),
    "'": glyph(["##", "##", ".#", "..", ".."]),
    ',': glyph(["..", "..", "..", "##", "##", ".#"]),
    '.': glyph(["..", "..", "..", "##", "##"]),
    '/': glyph(["...##", "..##.", ".##..", "##...", "#...."]),
    '\\': glyph(["##...", ".##..", "..##.", "...##", "....#"]),
}


def key_label(img, d, x, y, label):
    """Draw a key label with bold punctuation; returns the drawn width."""
    x0 = x
    for ch in label:
        if ch in PUNCT:
            g = PUNCT[ch]
            blit(img, g, x, y)
            x += len(g[0]) + 1
        elif ch == ' ':
            x += 3
        else:
            # align on the caps baseline rather than each glyph's own bbox
            cap_top = d.textbbox((0, 0), 'H', font=silk_b)[1]
            d.text((x, y - cap_top), ch, font=silk_b, fill=1)
            x += round(d.textlength(ch, font=silk_b))
    return x - x0


def legend_rows(img, d, y, rows, step=10):
    for k, a in rows:
        key_label(img, d, 1, y, k)
        text(d, (W - 1, y), a, silk, 'r')
        y += step
    return y


def legend_header(d, label):
    d.rectangle([0, 20, W - 1, 33], fill=1)
    text(d, (None, 24), label, silk_b, 'c', fill=0)


def legend_layer1():
    """Layer 1 as defined in config/eyelash_sofle.keymap (layer_1)."""
    img, d = new()
    status_bar(img, d)
    legend_header(d, 'L1  NAV')
    arrow_cluster(img, d, 0, 37)
    text(d, (W - 1, 43), 'ON', silk, 'r')
    text(d, (W - 1, 52), 'IJKL', silk_b, 'r')
    legend_rows(img, d, 65, [
        ('YH', 'PG UP/DN'),
        ('UO', 'END/HOME'),
        ('P\\', '-  ='),
        ("; '", '[  ]'),
        ('1-0', 'F1-F10'),
        ('./', 'F11 F12'),
        ('WER', 'CLICKS'),
        ('Z-M', 'RGB'),
        (',', 'INSERT'),
    ])
    return img


def legend_layer2():
    """Layer 2 as defined in config/eyelash_sofle.keymap (layer_2)."""
    img, d = new()
    status_bar(img, d)
    legend_header(d, 'L2  SYSTEM')
    blit(img, BT, 2, 38)
    for i in range(5):
        x = 12 + i * 11
        d.rectangle([x, 37, x + 9, 47], outline=1)
        text(d, (x + 5, 40), str(i + 1), silk_b, 'c')
    for i, icon in enumerate(SLOT_ICONS):
        if icon:
            blit(img, icon, 12 + i * 11 + (10 - len(icon[0])) // 2, 50)
    legend_rows(img, d, 62, [
        ('Q', 'BT CLEAR'),
        ('W', 'CLEAR ALL'),
        ('A', 'USB OUT'),
        ('S', 'BLE OUT'),
        ('C /', 'FLASH'),
        ('Z ,', 'RESTART'),
        ('.', 'SOFT OFF'),
        ('P\\', '_  +'),
        ("; '", '{  }'),
    ])
    return img


def big_batt(img, d, y, label, level, charging=False):
    text(d, (1, y), label, jer30)
    text(d, (W - 1, y), f'{level}%', jer30, 'r')
    # segmented bar
    segs = 10
    for i in range(segs):
        x = 1 + i * 7
        on = i < (level + 5) // 10
        d.rectangle([x, y + 20, x + 5, y + 25], fill=1 if on else 0, outline=1)
    if charging:
        blit(img, BOLT, 16, y + 5)


def dashboard(caps=False):
    img, d = new()
    # no stock status bar: this concept *is* the status screen
    big_batt(img, d, 2, 'L', 64)
    big_batt(img, d, 36, 'R', 91, charging=False)
    d.line([(0, 68), (W - 1, 68)], fill=1)
    # host
    blit(img, BT, 2, 77)
    text(d, (12, 73), '2', jer40)
    text(d, (31, 77), 'WORK', silk_b)
    blit(img, WIFI, 31, 87)
    text(d, (45, 88), 'ON', silk)
    d.line([(0, 102), (W - 1, 102)], fill=1)
    # caps lock
    if caps:
        d.rectangle([0, 107, W - 1, 127], fill=1)
        blit(img, CAPS, 4, 112, ink=0)
        text(d, (18, 112), 'CAPS', silk16, fill=0)
    else:
        d.rectangle([0, 107, W - 1, 127], outline=1)
        blit(img, CAPS, 4, 112)
        text(d, (W - 4, 114), 'caps off', silk, 'r')
    # layer
    text(d, (None, 136), 'LAYER0', mont14, 'c')
    return img


def stats():
    img, d = new()
    status_bar(img, d)
    text(d, (None, 24), 'KEYS TYPED', silk, 'c')
    text(d, (None, 36), '12,408', jer30, 'c')
    # hourly bar chart (last 12 hours)
    vals = [2, 5, 9, 14, 11, 3, 1, 6, 12, 16, 13, 8]
    base = 86
    for i, v in enumerate(vals):
        x = 2 + i * 5 + (i // 1) * 0
        d.rectangle([x, base - v * 1.6, x + 3, base], fill=1)
    d.line([(0, base + 2), (W - 1, base + 2)], fill=1)
    text(d, (1, base + 5), '-12H', silk)
    text(d, (W - 1, base + 5), 'NOW', silk, 'r')
    d.line([(0, 102), (W - 1, 102)], fill=1)
    text(d, (1, 107), 'AWAKE', silk)
    text(d, (W - 1, 104), '3:12', jer20, 'r')
    text(d, (1, 121), 'TOP WPM', silk)
    text(d, (W - 1, 118), '94', jer20, 'r')
    d.line([(0, 132), (W - 1, 132)], fill=1)
    blit(img, MOON, 2, 140)
    text(d, (12, 141), 'SLEEP 58M', silk)
    return img


# ------------------------------------------------------------ left (central) screen concepts

CMD = glyph([
    ".##...##.",
    "#..#.#..#",
    "#..#.#..#",
    ".#######.",
    "...#.#...",
    ".#######.",
    "#..#.#..#",
    "#..#.#..#",
    ".##...##.",
])
OPT = glyph([
    "###..####",
    "...#.....",
    "....#....",
    ".....#...",
    "......###",
])
CTRL = glyph([
    "....#....",
    "...#.#...",
    "..#...#..",
    ".#.....#.",
])
SHIFT = glyph([
    "....#....",
    "...#.#...",
    "..#...#..",
    ".#.....#.",
    "###...###",
    "..#...#..",
    "..#...#..",
    "..#####..",
])
GEAR = glyph([
    "...###...",
    ".#.###.#.",
    "#########",
    ".###.###.",
    "###...###",
    ".###.###.",
    "#########",
    ".#.###.#.",
    "...###...",
])

LAYER_NAMES = {0: 'BASE', 1: 'NAV', 2: 'SYSTEM'}

CLAUDE_SPARK = glyph([
    "....#....",
    ".#..#..#.",
    "..#.#.#..",
    "...###...",
    "#########",
    "...###...",
    "..#.#.#..",
    ".#..#..#.",
    "....#....",
])


def mini_batt(img, d, x, y, label, level, w=31):
    """Label, percentage and a 10-segment bar in a w-wide column."""
    text(d, (x, y), label, silk_b)
    text(d, (x + w - 1, y), f'{level}%', silk, 'r')
    seg_w = (w - 9) // 10
    for i in range(10):
        sx = x + i * (seg_w + 1)
        on = i < (level + 5) // 10
        if on:
            d.rectangle([sx, y + 8, sx + seg_w - 1, y + 11], fill=1)
        else:
            d.rectangle([sx, y + 8, sx + seg_w - 1, y + 11], outline=1)


def slot_tabs(img, d, y, active=1, connected=(1,), bonded=(0, 1, 3)):
    """Five Bluetooth slot tabs: filled = active, solid = connected, dashed = paired, none = free."""
    for i in range(5):
        x = 1 + i * 13
        box = [x, y, x + 11, y + 11]
        if i == active:
            d.rectangle(box, fill=1)
        elif i in connected:
            d.rectangle(box, outline=1)
        elif i in bonded:
            for k in range(0, 12, 2):
                d.point([(x + k, y), (x + k, y + 11), (x, y + k), (x + 11, y + k)], fill=1)
        text(d, (x + 6, y + 3), str(i + 1), silk_b, 'c', fill=0 if i == active else 1)


def mod_hud(img, d, y, held=()):
    """Mac modifier badges; held ones are inverted."""
    mods = [('cmd', CMD), ('opt', OPT), ('ctrl', CTRL), ('shift', SHIFT)]
    for i, (name, g) in enumerate(mods):
        x = 1 + i * 17
        box = [x, y, x + 15, y + 14]
        on = name in held
        d.rectangle(box, fill=1 if on else 0, outline=1)
        gw, gh = len(g[0]), len(g)
        blit(img, g, x + (16 - gw) // 2, y + (15 - gh) // 2, ink=0 if on else 1)


def wpm_chart(img, d, y0, y1, values):
    """Dithered area sparkline across the full width."""
    n = len(values)
    hi = max(values) or 1
    pts = []
    for i, v in enumerate(values):
        x = round(i * (W - 1) / (n - 1))
        pts.append((x, y1 - round(v / hi * (y1 - y0))))
    px = img.load()
    for x in range(W):
        # interpolate the line height at x
        for i in range(n - 1):
            if pts[i][0] <= x <= pts[i + 1][0]:
                x0, ya = pts[i]
                x1, yb = pts[i + 1]
                yy = ya + (yb - ya) * (x - x0) / max(1, x1 - x0)
                break
        for y in range(int(yy) + 1, y1 + 1):
            if (x + y) % 2 == 0:
                px[x, y] = 1
    d.line(pts, fill=1)
    d.line([(0, y1 + 1), (W - 1, y1 + 1)], fill=1)


WPM_SAMPLE = [12, 30, 44, 51, 38, 47, 63, 58, 66, 61]


def left_cockpit(layer=0, held=(), caps=False):
    img, d = new()
    mini_batt(img, d, 0, 1, 'L', 87)
    mini_batt(img, d, 36, 1, 'R', 92)
    # layer bar
    d.rectangle([0, 17, W - 1, 34], fill=1)
    text(d, (None, 20), LAYER_NAMES.get(layer, f'L{layer}'), jer20, 'c', fill=0)
    # output + slots
    blit(img, BT, 1, 40)
    text(d, (10, 41), 'SLOT 2', silk_b)
    text(d, (W - 1, 41), 'ON', silk, 'r')
    slot_tabs(img, d, 51)
    # modifiers
    mod_hud(img, d, 69, held)
    # caps
    if caps:
        d.rectangle([0, 88, W - 1, 99], fill=1)
        blit(img, CAPS, 2, 89, ink=0)
        text(d, (14, 91), 'CAPS LOCK', silk_b, fill=0)
    else:
        text(d, (None, 91), 'caps off', silk, 'c')
    # wpm
    text(d, (1, 106), 'WPM', silk)
    text(d, (W - 1, 104), str(WPM_SAMPLE[-1]), jer20, 'r')
    wpm_chart(img, d, 120, 157, WPM_SAMPLE)
    return img


def left_typing(layer=0):
    img, d = new()
    # compact status strip
    battery(d, 0, 1, 87, img=img)
    text(d, (36, 3), 'R92', silk_b)
    blit(img, BT, 55, 2)
    text(d, (W - 1, 3), '2', silk_b, 'r')
    d.line([(0, 16), (W - 1, 16)], fill=1)
    text(d, (None, 22), 'WORDS / MIN', silk, 'c')
    text(d, (None, 31), str(WPM_SAMPLE[-1]), jer40, 'c')
    wpm_chart(img, d, 60, 98, WPM_SAMPLE)
    text(d, (1, 103), '-30S', silk)
    text(d, (W - 1, 103), 'NOW', silk, 'r')
    d.line([(0, 113), (W - 1, 113)], fill=1)
    text(d, (1, 118), 'KEYS', silk)
    text(d, (W - 1, 116), '4,182', jer20, 'r')
    d.rectangle([0, 140, W - 1, 159], fill=1)
    text(d, (None, 143), LAYER_NAMES.get(layer), jer20, 'c', fill=0)
    return img


def left_classic(layer=0):
    """Stock layout, restyled in the legend's visual language."""
    img, d = new()
    battery(d, 0, 2, 87, img=img)
    blit(img, WIFI, W - 12, 4)
    d.rectangle([0, 20, W - 1, 62], outline=1)
    wpm_chart(img, d, 26, 58, WPM_SAMPLE)
    d.rectangle([W - 18, 49, W - 2, 59], fill=0)
    text(d, (W - 3, 51), '61', silk_b, 'r')
    # dice-pattern profile circles, slightly smaller and pixel-styled
    pos = [(14, 80), (53, 80), (34, 98), (14, 116), (53, 116)]
    for i, (cx, cy) in enumerate(pos):
        r = 10
        if i == 1:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
            text(d, (cx, cy - 2), str(i + 1), silk_b, 'c', fill=0)
        else:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=1)
            text(d, (cx, cy - 2), str(i + 1), silk_b, 'c')
    d.rectangle([0, 138, W - 1, 159], fill=1)
    text(d, (None, 142), LAYER_NAMES.get(layer), jer20, 'c', fill=0)
    return img


def left_stock():
    """Approximation of the current stock left screen (from the seller's photo)."""
    img, d = new()
    battery(d, 0, 2, 70, img=img)
    blit(img, GEAR, W - 10, 3)
    d.rectangle([0, 21, W - 1, 62], outline=1)
    text(d, (W - 3, 52), '0', silk, 'r')
    pos = [(14, 82), (53, 82), (34, 101), (14, 120), (53, 120)]
    for i, (cx, cy) in enumerate(pos):
        r = 12
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=1)
        if i == 0:
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=1)
        f = ImageFont.truetype(F + 'Montserrat[wght].ttf', 18)
        text(d, (cx, cy - 6), str(i + 1), f, 'c', fill=0 if i == 0 else 1)
    text(d, (None, 141), 'LAYER0', mont14, 'c')
    return img


def render_left():
    import os
    os.makedirs('out', exist_ok=True)
    out = {
        'left_stock': left_stock(),
        'left_cockpit': left_cockpit(),
        'left_cockpit_l1': left_cockpit(layer=1, held=('cmd', 'shift'), caps=True),
        'left_typing': left_typing(),
        'left_classic': left_classic(),
    }
    for k, im in out.items():
        im.save(f'out/mock_{k}.png')
        preview(im, 4).save(f'out/mock_{k}@4x.png')
    sheet = Image.new('RGB', (len(out) * (W * 3 + 12), H * 3), (255, 255, 255))
    for i, im in enumerate(out.values()):
        sheet.paste(preview(im, 3), (i * (W * 3 + 12), 0))
    sheet.save('out/left_sheet.png')
    return out


# ---------------------------------------------- left screen v2: fixed status top + bottom module

CAPSLOCK = glyph([
    "....#....",
    "...###...",
    "..#####..",
    ".#######.",
    "###...###",
    "..#...#..",
    "..#####..",
    ".........",
    "..#####..",
])
MODULE_TOP = 68


def status_top(img, d, layer=0, held=(), caps=False, active=1):
    mini_batt(img, d, 0, 0, 'L', 87)
    mini_batt(img, d, 36, 0, 'R', 92)
    d.rectangle([0, 15, W - 1, 30], fill=1)
    text(d, (None, 17), LAYER_NAMES.get(layer, f'L{layer}'), jer20, 'c', fill=0)
    slot_tabs(img, d, 34, active=active)
    mods = [('cmd', CMD), ('opt', OPT), ('ctrl', CTRL), ('shift', SHIFT), ('caps', CAPSLOCK)]
    for i, (name, g) in enumerate(mods):
        x = i * 14
        on = name in held or (name == 'caps' and caps)
        d.rectangle([x, 50, x + 11, 62], fill=1 if on else 0, outline=1)
        gw, gh = len(g[0]), len(g)
        blit(img, g, x + (12 - gw) // 2, 50 + (13 - gh) // 2, ink=0 if on else 1)
    d.line([(0, 65), (W - 1, 65)], fill=1)


def module_wpm(img, d):
    y = MODULE_TOP + 2
    text(d, (1, y + 3), 'WPM', silk_b)
    text(d, (W - 1, y), str(WPM_SAMPLE[-1]), jer30, 'r')
    wpm_chart(img, d, y + 26, 156, WPM_SAMPLE)
    text(d, (1, 152), '', silk)


def module_session():
    pass


def left_v2(module, **kw):
    img, d = new()
    status_top(img, d, **kw)
    module(img, d)
    return img


def mod_session(img, d):
    y = MODULE_TOP + 2
    text(d, (1, y), 'SESSION', silk_b)
    rows = [('TIME', '0:47'), ('KEYS', '3,214'), ('ACC', '94%'), ('PEAK', '88')]
    yy = y + 10
    for label, val in rows:
        text(d, (1, yy + 2), label, silk)
        text(d, (W - 1, yy), val, jer20, 'r')
        yy += 13
    # keys per minute, last 30 minutes: 30 bars x 2px
    vals = [0, 0, 3, 8, 14, 22, 19, 25, 31, 28, 12, 4, 0, 0, 6, 18, 27, 33, 29, 35,
            30, 24, 26, 31, 38, 34, 22, 15, 20, 26]
    base, top = 157, yy + 2
    hi = max(vals)
    for i, v in enumerate(vals):
        x = 4 + i * 2
        h = round(v / hi * (base - top))
        if h:
            d.line([(x, base - h), (x, base)], fill=1)
    d.line([(0, base + 1), (W - 1, base + 1)], fill=1)


def mod_focus(img, d):
    y = MODULE_TOP + 2
    text(d, (1, y), 'FOCUS', silk_b)
    text(d, (W - 1, y), '2/4', silk, 'r')
    text(d, (None, y + 11), '18:42', jer40, 'c')
    # progress bar, 25 minute round
    frac = 1 - (18 * 60 + 42) / (25 * 60)
    d.rectangle([0, y + 38, W - 1, y + 46], outline=1)
    dither(img, (2, y + 40, 2 + round((W - 4) * frac), y + 45), 'checker')
    d.rectangle([2, y + 40, 1 + round((W - 4) * frac), y + 44], fill=1)
    text(d, (None, y + 52), 'NEXT: BREAK', silk, 'c')
    d.rectangle([0, 146, W - 1, 159], outline=1)
    text(d, (None, 150), 'L2+T PAUSE', silk, 'c')


def mod_echo(img, d):
    y = MODULE_TOP + 2
    text(d, (1, y), 'LAST KEYS', silk_b)
    # newest first; modifiers drawn as glyphs
    d.rectangle([0, y + 10, W - 1, y + 34], fill=1)
    blit(img, CMD, 6, y + 18, ink=0)
    blit(img, SHIFT, 18, y + 18, ink=0)
    text(d, (W - 6, y + 13), '4', jer30, 'r', fill=0)
    older = [('', '['), ('', 'PG UP'), ('cmd', 'C'), ('', 'TAB')]
    yy = y + 39
    for mod, key in older:
        x = 2
        if mod == 'cmd':
            blit(img, CMD, x, yy - 2)
            x += 12
        text(d, (W - 2, yy), key, silk_b, 'r')
        d.point([(xx, yy + 9) for xx in range(0, W, 2)], fill=1)
        yy += 12


def render_left_v2():
    import os
    os.makedirs('out', exist_ok=True)
    out = {
        'left_stock': left_stock(),
        'left_v2_wpm': left_v2(module_wpm),
        'left_v2_session': left_v2(mod_session),
        'left_v2_focus': left_v2(mod_focus, layer=0),
        'left_v2_echo': left_v2(mod_echo, layer=1, held=('cmd', 'shift'), caps=True),
    }
    for k, im in out.items():
        im.save(f'out/mock_{k}.png')
        preview(im, 4).save(f'out/mock_{k}@4x.png')
    sheet = Image.new('RGB', (len(out) * (W * 3 + 12), H * 3), (255, 255, 255))
    for i, im in enumerate(out.values()):
        sheet.paste(preview(im, 3), (i * (W * 3 + 12), 0))
    sheet.save('out/left_sheet.png')
    return out


# ------------------------------------------------- left screen: fun / hacker modules (full height)

tiny = ImageFont.truetype(F + 'Tiny5-Regular.ttf', 8)   # lowercase-capable 5px terminal font
TOP = 12  # first row below the one-line status strip


def status_strip(img, d, layer='BASE', l=87, r=92, slot=2):
    text(d, (1, 1), f'L{l} R{r}', tiny)
    text(d, (W - 1, 1), f'{layer} bt{slot}', tiny, 'r')
    d.line([(0, 9), (W - 1, 9)], fill=1)


def term(d, y, line, x=1, fill=1):
    d.text((x, y - 1), line, font=tiny, fill=fill)
    return y + 8


def fun_uptime():
    img, d = new()
    status_strip(img, d)
    y = TOP + 1
    y = term(d, y, '$ uptime')
    y = term(d, y, ' up 0:47, 1 user')
    y = term(d, y, ' load average')
    for label, v in [('1m', 0.52), ('5m', 0.31), ('15m', 0.12)]:
        term(d, y, ' ' + label)
        d.rectangle([16, y, 49, y + 5], outline=1)
        d.rectangle([18, y + 2, 18 + round(30 * v), y + 3], fill=1)
        text(d, (W - 1, y), f'{v:.2f}', tiny, 'r')
        y += 9
    y = term(d, y, '$ acpi')
    for name, lvl in [('BAT0', 87), ('BAT1', 92)]:
        term(d, y, name)
        d.rectangle([20, y, 52, y + 5], outline=1)
        d.rectangle([22, y + 2, 22 + round(28 * lvl / 100), y + 3], fill=1)
        text(d, (W - 1, y), f'{lvl}', tiny, 'r')
        y += 9
    y = term(d, y + 1, '$ who')
    y = term(d, y, ' kyle  tty1  bt2')
    y = term(d, y + 1, '$ fortune')
    y = term(d, y, ' git rebase -i @~3')
    y = term(d, y + 1, '$')
    d.rectangle([8, y - 8, 11, y - 2], fill=1)  # cursor
    return img


def tux(img, d, x, y, mode='awake'):
    """~30x36 Tux. Panel dark = Tux's black, ink = his white belly and eyes."""
    # body + head outline (black filled = paper, outlined in ink)
    d.ellipse([x + 3, y + 10, x + 28, y + 36], outline=1, fill=0)
    d.ellipse([x + 7, y, x + 24, y + 18], outline=1, fill=0)
    # white belly and face
    d.ellipse([x + 8, y + 14, x + 23, y + 35], fill=1)
    d.ellipse([x + 10, y + 5, x + 21, y + 17], fill=1)
    if mode == 'sleep':
        d.line([(x + 11, y + 9), (x + 14, y + 9)], fill=0)
        d.line([(x + 17, y + 9), (x + 20, y + 9)], fill=0)
    else:
        d.rectangle([x + 12, y + 7, x + 13, y + 10], fill=0)
        d.rectangle([x + 18, y + 7, x + 19, y + 10], fill=0)
    # beak
    d.polygon([(x + 12, y + 12), (x + 19, y + 12), (x + 15, y + 15)], fill=0, outline=0)
    d.line([(x + 13, y + 12), (x + 18, y + 12)], fill=1)
    d.polygon([(x + 13, y + 13), (x + 18, y + 13), (x + 15, y + 15)], outline=0)
    # flippers
    if mode == 'typing':
        d.line([(x + 4, y + 22), (x + 9, y + 30)], fill=1)
        d.line([(x + 27, y + 22), (x + 22, y + 30)], fill=1)
    else:
        d.line([(x + 3, y + 20), (x + 1, y + 28)], fill=1)
        d.line([(x + 28, y + 20), (x + 30, y + 28)], fill=1)
    # feet
    d.ellipse([x + 7, y + 34, x + 14, y + 38], fill=1)
    d.ellipse([x + 17, y + 34, x + 24, y + 38], fill=1)


def meter(d, y, label, frac):
    text(d, (1, y), label, tiny)
    d.rectangle([20, y, W - 1, y + 5], outline=1)
    d.rectangle([22, y + 2, 22 + round((W - 25) * frac), y + 3], fill=1)


def fun_tux(mode='typing'):
    img, d = new()
    status_strip(img, d)
    text(d, (0, TOP + 1), 'tux', silk_b)
    text(d, (W - 1, TOP + 1), 'lvl 7', tiny, 'r')
    if mode == 'typing':
        tux(img, d, 18, TOP + 14, 'typing')
        # tiny keyboard he's typing on
        d.rectangle([12, TOP + 54, 55, TOP + 61], outline=1)
        for i in range(9):
            d.point([(15 + i * 5, TOP + 57), (16 + i * 5, TOP + 57)], fill=1)
        text(d, (None, TOP + 66), 'clack clack', tiny, 'c')
    else:
        tux(img, d, 18, TOP + 18, 'sleep')
        text(d, (54, TOP + 14), 'z', tiny)
        text(d, (59, TOP + 9), 'Z', tiny)
        text(d, (None, TOP + 66), 'idle 4m...', tiny, 'c')
    y = TOP + 80
    meter(d, y, 'fed', 0.8 if mode == 'typing' else 0.35)
    meter(d, y + 9, 'joy', 0.9 if mode == 'typing' else 0.6)
    meter(d, y + 18, 'xp', 0.42)
    d.line([(0, y + 28), (W - 1, y + 28)], fill=1)
    y += 32
    for line in (['typing feeds him.', 'fast typing makes', 'him happy. he naps', 'when you stop.']):
        y = term(d, y, line)
    return img


def life_grid(w, h, gens, seed=7):
    import random
    rnd = random.Random(seed)
    g = [[1 if rnd.random() < 0.33 else 0 for _ in range(w)] for _ in range(h)]
    for _ in range(gens):
        n = [[0] * w for _ in range(h)]
        for yy in range(h):
            for xx in range(w):
                c = sum(g[(yy + dy) % h][(xx + dx) % w] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - g[yy][xx]
                n[yy][xx] = 1 if c == 3 or (c == 2 and g[yy][xx]) else 0
        g = n
    return g


def fun_life():
    img, d = new()
    status_strip(img, d)
    text(d, (0, TOP + 1), 'life', silk_b)
    text(d, (W - 1, TOP + 1), 'gen 1842', tiny, 'r')
    cw, ch = 22, 38
    g = life_grid(cw, ch, 12)
    oy = TOP + 11
    d.rectangle([0, oy - 1, W - 1, oy + ch * 3 + 1], outline=1)
    for yy in range(ch):
        for xx in range(cw):
            if g[yy][xx]:
                d.rectangle([2 + xx * 3, oy + 1 + yy * 3, 3 + xx * 3, oy + 2 + yy * 3], fill=1)
    pop = sum(map(sum, g))
    y = oy + ch * 3 + 5
    y = term(d, y, f'pop {pop}  seed: keys')
    y = term(d, y, 'each key = 1 tick')
    return img


def fun_snake():
    img, d = new()
    status_strip(img, d, layer='GAME')
    text(d, (0, TOP + 1), 'snake', silk_b)
    text(d, (W - 1, TOP + 1), '12  hi 31', tiny, 'r')
    oy = TOP + 11
    d.rectangle([0, oy, W - 1, oy + 117], outline=1)
    cell = 4
    path = [(7, 20), (7, 19), (7, 18), (7, 17), (8, 17), (9, 17), (10, 17), (11, 17), (11, 16),
            (11, 15), (11, 14), (10, 14), (9, 14), (8, 14), (7, 14), (6, 14), (5, 14), (4, 14),
            (4, 13), (4, 12), (4, 11)]
    for i, (cx, cy) in enumerate(path):
        x0, y0 = 2 + cx * cell, oy + 2 + cy * cell
        d.rectangle([x0, y0, x0 + cell - 2, y0 + cell - 2], fill=1)
    hx, hy = path[0]
    d.rectangle([2 + hx * cell - 1, oy + 2 + hy * cell - 1, 2 + hx * cell + cell - 1, oy + 2 + hy * cell + cell - 1], fill=1)
    ax, ay = 12, 6
    d.ellipse([2 + ax * cell - 1, oy + 2 + ay * cell - 1, 2 + ax * cell + 2, oy + 2 + ay * cell + 2], outline=1)
    y = oy + 121
    y = term(d, y, 'joystick steers')
    y = term(d, y, 'L2+G play/quit')
    return img


def fun_evtest():
    img, d = new()
    status_strip(img, d, layer='NAV')
    y = TOP + 1
    y = term(d, y, '$ evtest')
    y += 2
    d.rectangle([0, y, W - 1, y + 25], fill=1)
    d.text((2, y + 1), 'KEY_LEFTBRACE', font=tiny, fill=0)
    text(d, (2, y + 12), '0x2F', jer20, fill=0)
    text(d, (W - 3, y + 15), 'val 1', tiny, 'r', fill=0)
    y += 30
    rows = [('usage', '07:002F'), ('pos', '#36 r2 c11'), ('layer', '1 NAV'), ('mods', '0b00001000'), ('', 'LGUI'),
            ('behav', '&kp LBKT')]
    for k, v in rows:
        term(d, y, k)
        text(d, (W - 1, y), v, tiny, 'r')
        y += 9
    d.line([(0, y + 1), (W - 1, y + 1)], fill=1)
    y += 5
    y = term(d, y, 'SYN_REPORT')
    y = term(d, y, ' +12ms  KEY_A 0')
    y = term(d, y, ' +3ms   KEY_A 1')
    y = term(d, y, ' +98ms  LGUI 1')
    return img


def fun_hostlink():
    img, d = new()
    status_strip(img, d)
    text(d, (None, TOP + 2), '14:32', jer40, 'c')
    text(d, (None, TOP + 25), 'fri 3 oct', tiny, 'c')
    d.line([(0, TOP + 35), (W - 1, TOP + 35)], fill=1)
    y = TOP + 39
    # last shell command
    d.rectangle([0, y, W - 1, y + 15], fill=1)
    blit(img, CROSS, 2, y + 4, ink=0)
    text(d, (12, y + 3), '$? 1', silk_b, fill=0)
    text(d, (W - 3, y + 5), '12.4s', tiny, 'r', fill=0)
    y += 19
    y = term(d, y, 'make test')
    y += 2
    term(d, y, 'git')
    text(d, (W - 1, y), 'main* +3 -1', tiny, 'r')
    y += 9
    term(d, y, 'ci')
    text(d, (W - 1, y), 'build passed', tiny, 'r')
    y += 9
    term(d, y, 'mail')
    text(d, (W - 1, y), '4 unread', tiny, 'r')
    y += 11
    text(d, (0, y), 'cpu', tiny)
    vals = [3, 5, 4, 9, 14, 11, 6, 4, 8, 16, 18, 12, 7, 5, 6, 10, 13, 9]
    for i, v in enumerate(vals):
        x = 16 + i * 3
        d.rectangle([x, y + 18 - v, x + 1, y + 18], fill=1)
    text(d, (W - 1, y), '34%', tiny, 'r')
    y += 22
    text(d, (0, y), 'mem', tiny)
    d.rectangle([16, y, W - 1, y + 5], outline=1)
    d.rectangle([18, y + 2, 18 + round((W - 21) * 0.61), y + 3], fill=1)
    y += 10
    y = term(d, y, 'pushed by sofled')
    return img


def render_fun():
    import os
    os.makedirs('out', exist_ok=True)
    out = {
        'fun_uptime': fun_uptime(),
        'fun_tux': fun_tux('typing'),
        'fun_tux_sleep': fun_tux('sleep'),
        'fun_life': fun_life(),
        'fun_snake': fun_snake(),
        'fun_evtest': fun_evtest(),
        'fun_hostlink': fun_hostlink(),
    }
    for k, im in out.items():
        im.save(f'out/mock_{k}.png')
        preview(im, 4).save(f'out/mock_{k}@4x.png')
    sheet = Image.new('RGB', (len(out) * (W * 3 + 12), H * 3), (255, 255, 255))
    for i, im in enumerate(out.values()):
        sheet.paste(preview(im, 3), (i * (W * 3 + 12), 0))
    sheet.save('out/fun_sheet.png')
    return out


# ------------------------------------------------ left screen: final spec (mirrors widgets/status.c)
# Text is drawn with the generated LVGL fonts using LVGL's own placement rules (advance widths,
# integer centring), so this is what the firmware draws, pixel for pixel.

def _lvfonts():
    from lvfont import LvFont
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'boards', 'shields',
                        'nice_view_legend', 'fonts')
    return {k: LvFont(os.path.join(base, f'lv_font_{k}.c'))
            for k in ('silkscreen_8', 'silkscreen_bold_8', 'jersey_1x', 'jersey_2x')}


import os
LVF = None


def lv_text(img, font, x, w, cap_y, align, s, fill=1):
    """Same contract as draw_text() in status.c: cap_y is the top of capital letters."""
    global LVF
    LVF = LVF or _lvfonts()
    f = LVF[font]
    lw = f.width(s)
    # LVGL wraps text wider than its box (and ':' counts as a break), so treat overflow as a bug.
    # The trailing advance of the last glyph is spacing, not ink, so allow for it.
    last_spacing = f.glyphs[s[-1]][1] - (f.glyphs[s[-1]][2] + f.glyphs[s[-1]][4]) if s else 0
    assert lw - last_spacing <= w, f'{s!r} in {font} is {lw}px wide, box is {w}px'
    if align == 'c':
        x += (w - lw) // 2
    elif align == 'r':
        x += w - lw
    f.draw(img, x, cap_y - f.cap_top(), s, fill)


BOLT_G = glyph(["...##", "..##.", ".####", "..##.", ".##..", "##..."])


def spec_battery(img, d, x, label, level, charging=False):
    if charging:
        blit(img, BOLT_G, x, 0)  # the bolt replaces the L/R letter (fits next to "100%")
    else:
        lv_text(img, 'silkscreen_bold_8', x, 31, 0, 'l', label)
    lv_text(img, 'silkscreen_8', x, 31, 0, 'r', '--' if level < 0 else f'{level}%')
    for i in range(10):
        sx = x + i * 3
        if level >= 0 and i < (level + 5) // 10:
            d.rectangle([sx, 8, sx + 1, 11], fill=1)
        else:
            d.rectangle([sx, 11, sx + 1, 11], fill=1)


def spec_left(layer='BASE', l=87, r=92, charging=False, usb=False, active=1, connected=(1,),
              bonded=(0, 1, 3), held=(), caps=False, wpm=None, agent='idle', clock=(11, 51, 'AM')):
    img, d = new()
    # --- status (top canvas, rows 0..67)
    spec_battery(img, d, 0, 'L', l, charging)
    spec_battery(img, d, 36, 'R', r)
    d.rectangle([0, 15, W - 1, 30], fill=1)
    lv_text(img, 'jersey_1x', 0, W, 18, 'c', layer, fill=0)
    if usb:
        d.rectangle([0, 34, W - 1, 45], fill=1)
        lv_text(img, 'silkscreen_bold_8', 0, W, 38, 'c', 'USB', fill=0)
    else:
        for i in range(5):
            x, y = 1 + i * 13, 34
            if i == active and i in connected:
                d.rectangle([x, y, x + 11, y + 11], fill=1)
            elif i == active:
                d.rectangle([x, y, x + 11, y + 11], outline=1)
                d.rectangle([x + 1, y + 1, x + 10, y + 10], outline=1)
            elif i in connected:
                d.rectangle([x, y, x + 11, y + 11], outline=1)
            elif i in bonded:
                for k in range(0, 12, 2):
                    d.point([(x + k, y), (x + k, y + 11), (x, y + k), (x + 11, y + k)], fill=1)
            on = i == active and i in connected
            icon = SLOT_ICONS[i]
            if icon:
                blit(img, icon, x + (12 - len(icon[0])) // 2, y + (12 - len(icon)) // 2, ink=0 if on else 1)
            else:
                lv_text(img, 'silkscreen_bold_8', x, 12, y + 3, 'c', str(i + 1), fill=0 if on else 1)
    mods = [('cmd', CMD), ('opt', OPT), ('ctrl', CTRL), ('shift', SHIFT), ('claude', CLAUDE_SPARK)]
    for i, (name, g) in enumerate(mods):
        x = i * 14
        on = name in held or (name == 'claude' and agent in ('working', 'needs'))
        if on:
            d.rectangle([x, 50, x + 11, 62], fill=1)
        else:
            d.rectangle([x, 50, x + 11, 62], outline=1)
        gw, gh = len(g[0]), len(g)
        blit(img, g, x + (12 - gw) // 2, 50 + (13 - gh) // 2, ink=0 if on else 1)
    d.rectangle([0, 65, W - 1, 65], fill=1)
    # --- WPM module (middle + bottom canvases, rows 68..159)
    hist = wpm or [0] * 12 + [12, 30, 44, 51, 38, 47, 63, 58, 66, 61, 70, 74, 69, 58, 64, 72, 77, 71]
    spec_clock_header(img, d, clock)
    spec_wpm_label(img, d, hist[-1], clock[2] if clock else None)
    top, bot = 106, 156
    hi = max(max(hist), 10)
    n = len(hist)
    pts = [(i * (W - 1) // (n - 1), bot - hist[i] * (bot - top) // hi) for i in range(n)]
    px = img.load()
    for i in range(n - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        for x in range(x0, x1 + (1 if i == n - 2 else 0)):
            yy = y0 + (y1 - y0) * (x - x0) // max(1, x1 - x0)
            for y in range(yy + 1, bot + 1):
                if (x + y) % 2 == 0:
                    px[x, y] = 1
    for i in range(n - 1):
        bresenham(px, pts[i], pts[i + 1])
    d.rectangle([0, 157, W - 1, 157], fill=1)
    spec_agent_banner(img, d, agent)
    return img


def spec_clock_header(img, d, clock):
    """Big time in the module header (rows 67-92). Mirrors draw_clock() in status.c."""
    if clock is None:
        lv_text(img, 'jersey_2x', 1, W - 1, 71, 'l', '--:--')
        return
    h, m, ampm = clock
    lv_text(img, 'jersey_2x', 1, W - 1, 71, 'l', f'{h}:{m:02d}')


def spec_wpm_label(img, d, wpm, ampm='AM'):
    lv_text(img, 'silkscreen_8', 1, 30, 97, 'l', f'WPM')
    lv_text(img, 'silkscreen_bold_8', 22, 30, 97, 'l', str(wpm))
    if ampm:
        lv_text(img, 'silkscreen_bold_8', 0, W, 97, 'r', ampm)


def spec_agent_banner(img, d, agent):
    """Claude Code banner over the top of the chart (rows 94-119)."""
    if agent not in ('needs', 'done'):
        return
    solid = agent == 'needs'
    d.rectangle([0, 94, W - 1, 119], fill=0)
    if solid:
        d.rectangle([0, 94, W - 1, 119], fill=1)
    else:
        d.rectangle([0, 94, W - 1, 119], outline=1)
    ink = 0 if solid else 1
    lv_text(img, 'jersey_1x', 0, W, 98, 'c', 'CLAUDE', fill=ink)
    lv_text(img, 'silkscreen_bold_8', 0, W, 111, 'c', 'NEEDS YOU' if solid else 'DONE', fill=ink)


def spec_agent_header(img, d, agent, wpm):
    """WPM header, or a Claude Code banner (rows 67-92). Mirrors draw_agent_header() in status.c."""
    if agent in ('needs', 'done'):
        solid = agent == 'needs'
        if solid:
            d.rectangle([0, 67, W - 1, 92], fill=1)
        else:
            d.rectangle([0, 67, W - 1, 92], outline=1)
        ink = 0 if solid else 1
        lv_text(img, 'jersey_1x', 0, W, 71, 'c', 'CLAUDE', fill=ink)
        lv_text(img, 'silkscreen_bold_8', 0, W, 84, 'c', 'NEEDS YOU' if solid else 'DONE', fill=ink)
        return
    lv_text(img, 'silkscreen_bold_8', 1, 30, 71, 'l', 'WPM')
    lv_text(img, 'jersey_2x', 0, W, 71, 'r', str(wpm))


def bresenham(px, p0, p1):
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        px[x0, y0] = 1
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def render_spec():
    os.makedirs('out', exist_ok=True)
    out = {
        'spec_base': spec_left(),
        'spec_nav': spec_left(layer='NAV', charging=True, r=-1, held=('cmd', 'shift'), caps=True),
        'spec_usb': spec_left(layer='SYSTEM', usb=True, wpm=[0] * 30),
        'spec_away': spec_left(active=0, connected=()),
        'spec_agent_working': spec_left(agent='working'),
        'spec_agent_needs': spec_left(agent='needs'),
        'spec_agent_done': spec_left(agent='done'),
        'spec_clock_pm': spec_left(clock=(12, 22, 'PM'), agent='working'),
        'spec_clock_unknown': spec_left(clock=None),
    }
    for k, im in out.items():
        im.save(f'out/mock_{k}.png')
        preview(im, 4).save(f'out/mock_{k}@4x.png')
    sheet = Image.new('RGB', (len(out) * (W * 3 + 12), H * 3), (255, 255, 255))
    for i, im in enumerate(out.values()):
        sheet.paste(preview(im, 3), (i * (W * 3 + 12), 0))
    sheet.save('out/spec_sheet.png')
    return out


# ------------------------------------------------------------- Bluetooth slot icons (slots 1-4)
# Slot 1 Mac, 2 phone, 3 work computer, 4 Boox tablet; slot 5 keeps its number.

ICON_LAPTOP = glyph([
    ".#######.",
    ".#.....#.",
    ".#.....#.",
    ".#.....#.",
    ".#######.",
    "#########",
])
ICON_PHONE = glyph([
    "#####",
    "#...#",
    "#...#",
    "#...#",
    "#...#",
    "#...#",
    "#.#.#",
    "#####",
])
ICON_BRIEFCASE = glyph([
    "..###..",
    "..#.#..",
    "#######",
    "#.....#",
    "###.###",
    "#.....#",
    "#######",
])
ICON_TABLET = glyph([
    "#######",
    "#.....#",
    "#.###.#",
    "#.....#",
    "#.###.#",
    "#.....#",
    "#.##..#",
    "#.....#",
    "#######",
])
SLOT_ICONS = [ICON_LAPTOP, ICON_PHONE, ICON_BRIEFCASE, ICON_TABLET, None]


if __name__ == '__main__':
    import os; os.makedirs('out', exist_ok=True)
    out = {
        'current': current_balloon(),
        'nameplate': nameplate(),
        'cheat': cheat_card(),
        'legend_idle': legend_idle(),
        'legend_l1': legend_layer1(),
        'legend_l2': legend_layer2(),
        'dash': dashboard(False),
        'dash_caps': dashboard(True),
        'stats': stats(),
    }
    for k, im in out.items():
        im.save(f'out/mock_{k}.png')
        preview(im, 4).save(f'out/mock_{k}@4x.png')
    # contact sheet for review
    sheet = Image.new('RGB', (len(out) * (W * 3 + 12), H * 3), (255, 255, 255))
    for i, im in enumerate(out.values()):
        sheet.paste(preview(im, 3), (i * (W * 3 + 12), 0))
    sheet.save('out/sheet.png')
    print('ok', list(out))
