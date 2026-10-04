"""Render the README's images into docs/images, in black and white:

  - hero.png: the vendor's plate drawing (sofle_outline.json) with the real screens in its
    screen windows
  - one image per screen state, from the same functions that draw the firmware's art
  - tetris.gif: a game played by the firmware's own rules (widgets/tetris_game.c, through
    host/test_tetris.c --dump)

    python3 make_readme_images.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

import concepts as C

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, 'docs', 'images')

INK, PAPER = 0, 255
SCALE = 4  # gallery screens: 4 image pixels per screen pixel


def bw(screen, scale):
    """A 1-bit screen (1 = ink) as black on white, scaled up with hard pixel edges."""
    img = Image.new('L', screen.size, PAPER)
    img.paste(INK, mask=screen.convert('L').point(lambda v: 255 if v else 0))
    return img.resize((screen.width * scale, screen.height * scale), Image.NEAREST)


def framed(screen, scale=SCALE, pad=14, radius=18, border=3):
    """A screen inside a thin rounded bezel, as it sits behind the keyboard's glass."""
    face = bw(screen, scale)
    w, h = face.width + 2 * (pad + border), face.height + 2 * (pad + border)
    ss = 4  # draw the bezel large and shrink it, for smooth corners
    big = Image.new('L', (w * ss, h * ss), PAPER)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=radius * ss,
                                          outline=INK, width=border * ss)
    img = big.resize((w, h), Image.LANCZOS)
    img.paste(face, (pad + border, pad + border))
    return img


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path, optimize=True)
    print('wrote', os.path.relpath(path, REPO), f'{img.width}x{img.height}')


# ------------------------------------------------------------------------------------- screens

def screens():
    left_card = C.spec_usage_ci(usage=((62, '2:40'), (31, 'TUE')),
                                repos=(('TIMESPACE', 'ok'), ('ZMK-CONFIG', 'fail'), ('SITEDIFF', 'run')),
                                clock=(10, 18, 'AM'), wpm=64)
    return {
        'left-card.png': left_card,
        'left-event.png': C.spec_usage_event(event=('IN 12M', '10:30', 'WEEKLY PLANNING WITH DESIGN'),
                                             clock=(10, 18, 'AM')),
        'left-wpm.png': C.spec_left(clock=(11, 51, 'AM')),
        'right-idle.png': C.legend_idle(),
        'right-nav.png': C.legend_layer1(),
        'right-system.png': C.legend_layer2(),
        'tetris-title.png': C.spec_tetris_title(best=40579),
        'tetris-play.png': C.spec_tetris(),
        'tetris-over.png': C.spec_tetris_over(score=23403, best=40579),
    }


# ---------------------------------------------------------------------------------------- hero

def hero(left_screen, right_screen):
    outline = json.load(open(os.path.join(HERE, 'sofle_outline.json')))
    screen_scale = 2
    lx0, ly0, lx1, ly1 = outline['screens']['left']
    mm = left_screen.width * screen_scale / (lx1 - lx0)  # image pixels per mm: screens at 2x
    xs = [v for l in outline['lines'] for v in (l[0], l[2])]
    ys = [v for l in outline['lines'] for v in (l[1], l[3])]
    margin = 6
    x0, y0 = min(xs) - margin, min(ys) - margin
    w, h = int((max(xs) - x0 + margin) * mm), int((max(ys) - y0 + margin) * mm)

    ss = 3  # supersample the line art for clean edges
    big = Image.new('L', (w * ss, h * ss), PAPER)
    d = ImageDraw.Draw(big)
    k = mm * ss
    width = max(1, round(0.28 * k))
    def pt(x, y):
        return ((x - x0) * k, (y - y0) * k)
    for x_a, y_a, x_b, y_b in outline['lines']:
        d.line([pt(x_a, y_a), pt(x_b, y_b)], fill=INK, width=width)
    for cx, cy, r in outline['circles']:
        (px, py), rr = pt(cx, cy), r * k
        d.ellipse([px - rr, py - rr, px + rr, py + rr], outline=INK, width=width)
    for cx, cy, r, a0, a1 in outline['arcs']:
        (px, py), rr = pt(cx, cy), r * k
        if a1 < a0:
            a1 += 360
        steps = max(6, int((a1 - a0) / 4))
        pts = [(px + rr * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
                py + rr * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(steps + 1)]
        d.line(pts, fill=INK, width=width)
    img = big.resize((w, h), Image.LANCZOS)

    # the screens, centred in their windows, with their pixels kept square
    for screen, key in ((left_screen, 'left'), (right_screen, 'right')):
        wx0, wy0, wx1, wy1 = outline['screens'][key]
        face = bw(screen, screen_scale)
        px = int((wx0 - x0) * mm + ((wx1 - wx0) * mm - face.width) / 2)
        py = int((wy0 - y0) * mm + ((wy1 - wy0) * mm - face.height) / 2)
        img.paste(face, (px, py))
        ImageDraw.Draw(img).rectangle([px - 4, py - 4, px + face.width + 3, py + face.height + 3],
                                      outline=INK, width=2)  # the glass's edge
    return img


# -------------------------------------------------------------------------------------- tetris

def tetris_frames(pieces=24):
    """Frames of a game from the firmware's rules: (state, score, level, next, rows, cells, ghost)."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, 'test_tetris')
        widgets = os.path.join(REPO, 'boards', 'shields', 'nice_view_legend', 'widgets')
        subprocess.run(['cc', '-O2', '-I', widgets, '-o', exe, os.path.join(REPO, 'host', 'test_tetris.c'),
                        os.path.join(widgets, 'tetris_game.c')], check=True)
        out = subprocess.run([exe, '--dump', str(pieces)], check=True, capture_output=True, text=True).stdout
    frames = []
    for line in out.splitlines():
        f = line.split()
        rows = [int(v, 16) for v in f[4:24]]
        pairs = [tuple(map(int, v.split(','))) for v in f[24:]]
        frames.append((int(f[0]), int(f[1]), int(f[2]), int(f[3]), rows, pairs[:4], pairs[4:]))
    return frames


def tetris_gif(scale=3, frame_ms=70):
    names = 'IOTSZJL'
    images, durations = [framed(C.spec_tetris_title(best=40579), scale)], [1400]
    for state, score, level, nxt, rows, cells, ghost in tetris_frames():
        board = [''.join('#' if row >> c & 1 else '.' for c in range(10)) for row in rows]
        screen = C.spec_tetris(board=board, nxt=names[nxt], score=score, level=level,
                               cells=cells or [], ghost_cells=ghost)
        images.append(framed(screen, scale))
        durations.append(frame_ms)
    durations[-1] = 1600
    # merge repeated frames, so the file only holds changes
    merged, times = [images[0]], [durations[0]]
    for img, ms in zip(images[1:], durations[1:]):
        if img.tobytes() == merged[-1].tobytes():
            times[-1] += ms
        else:
            merged.append(img)
            times.append(ms)
    # one palette for every frame (the bezel's smooth corners need a few greys)
    palette = merged[0].convert('RGB').quantize(colors=8)
    frames = [m.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE) for m in merged]
    path = os.path.join(OUT, 'tetris.gif')
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=times, loop=0,
                   optimize=True, disposal=1)
    print('wrote', os.path.relpath(path, REPO), f'{len(frames)} frames, {os.path.getsize(path) // 1024} KB')


def main():
    os.makedirs(OUT, exist_ok=True)
    shots = screens()
    for name, screen in shots.items():
        save(framed(screen), name)
    save(hero(shots['left-card.png'], shots['right-idle.png']), 'hero.png')
    tetris_gif()


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    main()
