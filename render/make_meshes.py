# /// script
# dependencies = ["numpy", "trimesh", "shapely", "networkx", "lxml", "scipy", "rtree", "mapbox-earcut", "manifold3d"]
# ///
"""Display meshes of both Sofle halves, in mm, for the Blender scene.

Each half's frame: x from the inner edge (0) outwards, y from the case's middle, z up from the
case floor. The left half's x is negative; the right half is its mirror image.
"""
import json, sys, os
from pathlib import Path
import numpy as np, trimesh
from shapely.geometry import Polygon, box
from shapely.affinity import translate

# The seller's 3D models, unpacked beside this repo
SRC = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[2] / '3Dmodel/3Dmodel/sofle-MX-narmal')
OUT = sys.argv[1]
SHIFT = np.array([604.5, 10.1])          # plate.stl onto the case's screw posts
X0, Y0 = 1462.5, -1354.86                # the case's inner edge and middle, in its own frame
PLATE_Z = 2.95 + 1.6                     # on the PCB, on the case's posts
PLATE_TOP = PLATE_Z + 5.0
CAP_BOTTOM = PLATE_TOP + 6.9
COVER_Z = PLATE_Z + 11.2                 # the acrylic strip on the plate's raised neck
WINDOW, WINDOW_FROM_TOP = (12.8, 28.0), 25.0  # the screen's window in the strip, from the photo

def sec(m, z):
    s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]); pl, T = s.to_2D()
    def w(c):
        c = np.asarray(c); return (np.c_[c, np.zeros(len(c)), np.ones(len(c))] @ T.T)[:, :2]
    return [Polygon(w(p.exterior.coords), [w(i.coords) for i in p.interiors]) for p in pl.polygons_full]

def local(m, dx=0.0, dy=0.0, dz=0.0):
    m = m.copy(); m.apply_translation([dx - X0, dy - Y0, dz]); return m

def rrect(w, h, r, n=6):
    pts = []
    for cx, cy, a0 in ((w/2 - r, h/2 - r, 0), (-w/2 + r, h/2 - r, 90), (-w/2 + r, -h/2 + r, 180), (w/2 - r, -h/2 + r, 270)):
        for i in range(n + 1):
            a = np.radians(a0 + 90 * i / n); pts.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    return np.array(pts)

# Cherry-like rows: height at the top's centre, and the top's tilt (+ is back edge higher)
ROWS = {'R1': (10.0, 9.0), 'R2': (8.5, 4.0), 'R3': (7.9, 0.5), 'R4': (8.6, -6.0)}
TOP_W, TOP_D, DISH = 12.6, 14.2, 0.45

def keycap(row, homing=False):
    h, tilt = ROWS[row]; t = np.tan(np.radians(tilt))
    base = rrect(18.1, 18.1, 0.9); top = rrect(TOP_W, TOP_D, 2.2)
    rings = []
    for k in range(7):
        f = k / 6; g = f ** 0.85  # a slightly full side
        xy = base * (1 - g) + top * g
        yc = 0.25 * g  # the top sits a little back
        z = h * f
        zz = z + (t * (xy[:, 1]) - DISH * (1 - (2 * xy[:, 0] / TOP_W) ** 2).clip(0)) * f ** 3 if k else np.zeros(len(xy))
        rings.append(np.c_[xy[:, 0], xy[:, 1] + yc, zz])
    for s in (0.8, 0.6, 0.4, 0.2):  # the dished top
        xy = top * s
        zz = h + t * xy[:, 1] - DISH * (1 - (2 * xy[:, 0] / TOP_W) ** 2)
        rings.append(np.c_[xy[:, 0], xy[:, 1] + 0.25, zz])
    n = len(base); V = np.vstack(rings); F = []
    for k in range(len(rings) - 1):
        for i in range(n):
            a, b = k * n + i, k * n + (i + 1) % n; c, d = a + n, b + n
            F += [(a, b, d), (a, d, c)]
    top_c = len(V); V = np.vstack([V, [0, 0.25, h - DISH]])
    last = (len(rings) - 1) * n
    F += [(last + i, last + (i + 1) % n, top_c) for i in range(n)]
    bot_c = len(V); V = np.vstack([V, [0, 0, 0]])
    F += [((i + 1) % n, i, bot_c) for i in range(n)]
    m = trimesh.Trimesh(V, F, process=True)
    if homing:
        bar = trimesh.creation.capsule(height=3.2, radius=0.32); bar.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
        y = -4.0; bar.apply_translation([0, y + 0.25, h + t * y - DISH * 1.0 + 0.05]); m = trimesh.util.concatenate([m, bar])
    return m, (h, tilt)

def switch():
    b = rrect(14.0, 14.0, 0.5, 2); t = rrect(10.0, 11.0, 1.0, 2) + [0, 0.6]
    V = np.vstack([np.c_[b, np.zeros(len(b))], np.c_[t, np.full(len(t), 5.6)]]); n = len(b); F = []
    for i in range(n):
        a, c = i, (i + 1) % n; F += [(a, c, c + n), (a, c + n, a + n)]
    V = np.vstack([V, [0, 0, 0], [0, 0.6, 5.6]])
    F += [(c, a, len(V) - 2) for a, c in [(i, (i + 1) % n) for i in range(n)]]
    F += [(a + n, c + n, len(V) - 1) for a, c in [(i, (i + 1) % n) for i in range(n)]]
    return trimesh.Trimesh(V, F, process=True)

def placed(m, x, y, r, z):
    m = m.copy(); m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(r), [0, 0, 1])); m.apply_translation([x, y, z]); return m

case = trimesh.load(os.path.join(SRC, 'sofle_shell.stl'))
plate = trimesh.load(os.path.join(SRC, 'plate.stl'))
cover = trimesh.load(os.path.join(SRC, 'Body2 (2).stl'))
joy = trimesh.load(os.path.join(SRC, 'joystick model v5.3mf'), force='mesh')
# The angled pad under each half (Body2.stl): a 3 degree wedge, centred under the case's floor
pad = trimesh.load(os.path.join(SRC, 'Body2.stl'))
foot = lambda m: max(sec(m, 0.1), key=lambda p: p.area).exterior
PAD_SHIFT = np.array(Polygon(foot(case)).centroid.coords[0]) - np.array(Polygon(foot(pad)).centroid.coords[0])
up = pad.face_normals[:, 2] > 0.3
nrm = (pad.face_normals[up] * pad.area_faces[up][:, None]).sum(0)
PAD_TILT = float(np.degrees(np.arctan2(-nrm[0], nrm[2])))  # top rises towards +x, the inner edge
probe = [pad.bounds[0][0] + 5, (pad.bounds[0][1] + pad.bounds[1][1]) / 2]  # on the top, outside its pocket
loc, _, _ = pad.ray.intersects_location([[*probe, 50]], [[0, 0, -1]])
x_probe = probe[0] + PAD_SHIFT[0] - X0
PAD_LIFT = float(loc[:, 2].max() - np.tan(np.radians(PAD_TILT)) * x_probe)  # the top plane's height at x = 0
print('pad shift', PAD_SHIFT.round(2), 'tilt', round(PAD_TILT, 2), 'lift at the inner edge', round(PAD_LIFT, 2))

# switch holes, in the case's frame
pl = max(sec(plate, 0.5), key=lambda p: p.area)
holes = [translate(Polygon(r), *SHIFT) for r in pl.interiors if Polygon(r).area > 150]
keys = []
for g in holes:
    if g.area > 400:  # Alt and the first rotated thumb key share a hole
        alt = (1406.182 - 1.513, -1387.152 + 1.172)
        keys.append((alt[0], alt[1], 0.0))
        rest = g.difference(box(alt[0] - 7.3, alt[1] - 7.3, alt[0] + 7.3, alt[1] + 7.3))
        rest = max(getattr(rest, 'geoms', [rest]), key=lambda q: q.area)
        best = None
        from shapely.affinity import rotate
        sq = rotate(box(-7, -7, 7, 7), -15, origin=(0, 0))
        cx0, cy0 = rest.centroid.coords[0]
        for dx in np.arange(-5, 5.01, 0.25):
            for dy in np.arange(-5, 5.01, 0.25):
                a = translate(sq, cx0 + dx, cy0 + dy).intersection(rest).area
                if best is None or a > best[0]: best = (a, cx0 + dx, cy0 + dy)
        keys.append((best[1], best[2], -15.0))
        print('rotated thumb fit', round(best[0], 1), 'of 196')
    else:
        mrr = g.minimum_rotated_rectangle; xy = np.asarray(mrr.exterior.coords)[:4]; e = xy[1] - xy[0]
        ang = np.degrees(np.arctan2(e[1], e[0])) % 90; ang = ang - 90 if ang > 45 else ang
        c = g.centroid.coords[0]; keys.append((c[0], c[1], round(ang, 1)))
cols = sorted({round(k[0], 0) for k in keys if k[2] == 0 and k[1] > -1380})
print('columns', cols)

# legends from the photo, left half: rows top to bottom, columns outer to inner
LEFT = [['Esc', '1 !', '2 @', '3 #', '4 $', '5 %'], ['–', 'Q', 'W', 'E', 'R', 'T'],
        ['*', 'A', 'S', 'D', 'F', 'G'], ['↑', 'Z', 'X', 'C', 'V', 'B']]
LEFT_THUMBS = ['Ctrl', 'Win', 'Alt', 'Fn', '+']   # left to right
RIGHT = [['6 ^', '7 &', '8 *', '9 (', '0 )', 'Del'], ['Y', 'U', 'I', 'O', 'P', '/'],
         ['H', 'J', 'K', 'L', '; :', '’ ”'], ['N', 'M', ', <', '. >', '/ ?', '→']]  # inner to outer
RIGHT_THUMBS = ['Del', 'PgUp', 'Fn', '0', '|']    # outer to inner, matching the left's order
ORANGE = {('L', 'Esc'), ('R', '→')}

info = []
grid = sorted([k for k in keys if k[2] == 0], key=lambda k: (k[0], -k[1]))
by_col = {}
for k in grid:
    c = min(range(len(cols)), key=lambda i: abs(cols[i] - k[0])); by_col.setdefault(c, []).append(k)
cap_parts = {'L': {'black': [], 'orange': []}, 'R': {'black': [], 'orange': []}}
switches = []
thumb_keys = []
for c, ks in by_col.items():
    ks.sort(key=lambda k: -k[1])
    for r, k in enumerate(ks):
        if r < 4:
            thumb = False; row = ['R1', 'R2', 'R3', 'R4'][r]; li = (r, c)
        else:
            thumb_keys.append(k); continue
        info.append({'x': k[0], 'y': k[1], 'r': k[2], 'row': row, 'pos': li, 'thumb': False})
thumb_keys += [k for k in keys if k[2] != 0]
thumb_keys.sort(key=lambda k: k[0])
for i, k in enumerate(thumb_keys):
    info.append({'x': k[0], 'y': k[1], 'r': k[2], 'row': 'R4', 'pos': ('T', i), 'thumb': True})
print(len(info), 'keys')

out = {'keys': [], 'parts': [], 'cover': None}
def save(m, name):
    m.export(os.path.join(OUT, name + '.stl')); out['parts'].append(name)

halves = {}
for half in ('L', 'R'):
    mirror = half == 'R'
    def fix(m):
        m = m.copy()
        if mirror:  # trimesh rewinds the faces itself for a reflection
            m.apply_transform(np.diag([-1, 1, 1, 1]))
        return m
    save(fix(local(case)), f'case_{half}')
    save(fix(local(pad, *PAD_SHIFT)), f'pad_{half}')
    save(fix(local(plate, *SHIFT, PLATE_Z)), f'plate_{half}')
    caps = {'black': [], 'orange': []}; sw = []
    for k in info:
        r, c = k['pos']
        if r == 'T':
            legend = LEFT_THUMBS[c] if half == 'L' else RIGHT_THUMBS[c]
        else:
            legend = LEFT[r][c] if half == 'L' else RIGHT[r][5 - c]
        homing = legend in ('F', 'J')
        cap, (h, tilt) = keycap(k['row'], homing)
        x, y = k['x'] - X0, k['y'] - Y0
        colour = 'orange' if (half, legend) in ORANGE else 'black'
        caps[colour].append(placed(cap, x, y, k['r'], CAP_BOTTOM))
        sw.append(placed(switch(), x, y, k['r'], PLATE_TOP))
        xs, rr = (-x, -k['r']) if mirror else (x, k['r'])
        out['keys'].append({'half': half, 'x': xs, 'y': y, 'r': rr, 'z': CAP_BOTTOM + h, 'tilt': tilt,
                            'legend': legend, 'colour': colour, 'top_back': 0.25})
    for colour, ms in caps.items():
        if ms: save(fix(trimesh.util.concatenate(ms)), f'caps_{colour}_{half}')
    save(fix(trimesh.util.concatenate(sw)), f'switches_{half}')
    # the acrylic strip: its screw holes onto the plate's pair 14 mm apart
    off = np.array([831.4, -1376.3]) + SHIFT - np.array([952.33, -748.27])
    cb = np.array(cover.bounds) + [[off[0], off[1], COVER_Z], [off[0], off[1], COVER_Z]]
    # The photo shows the screen through a clear window near the strip's top
    strip = translate(max(sec(cover, 0.5), key=lambda p: p.area), off[0] - X0, off[1] - Y0)
    wx, wy = (cb[0][0] + cb[1][0]) / 2 - X0, cb[1][1] - Y0 - WINDOW_FROM_TOP
    window = box(wx - WINDOW[0] / 2, wy - WINDOW[1] / 2, wx + WINDOW[0] / 2, wy + WINDOW[1] / 2)
    acrylic = trimesh.creation.extrude_polygon(strip.difference(window), 1.0); acrylic.apply_translation([0, 0, COVER_Z])
    pane = trimesh.creation.extrude_polygon(window, 1.0); pane.apply_translation([0, 0, COVER_Z])
    save(fix(acrylic), f'cover_{half}'); save(fix(pane), f'pane_{half}')
    knob = np.array([959.33, -757.97]) + off
    screws = [np.array(p) + off for p in ([952.33, -748.27], [966.35, -748.27])]
    sx = -1 if mirror else 1
    halves[half] = {
        'strip': [[sx * (cb[0][0] - X0), cb[0][1] - Y0], [sx * (cb[1][0] - X0), cb[1][1] - Y0]],
        'strip_z': [COVER_Z, COVER_Z + 1.0],
        'knob': [sx * (knob[0] - X0), knob[1] - Y0],
        'screws': [[sx * (s[0] - X0), s[1] - Y0] for s in screws],
        'top': float(cb[1][1] - Y0),
        'window': [sx * wx, wy],
    }
# one joystick cap from the four in the file
parts = joy.split(only_watertight=False)
cap = min(parts, key=lambda p: p.bounds[0][0])
cap.apply_translation(-np.array([(cap.bounds[0][0] + cap.bounds[1][0]) / 2, (cap.bounds[0][1] + cap.bounds[1][1]) / 2, cap.bounds[0][2]]))
print('joystick cap', np.round(cap.bounds, 2).tolist(), 'pieces', len(parts))
cap.export(os.path.join(OUT, 'joystick_cap.stl'))
out['halves'] = halves
out['pad'] = {'tilt': PAD_TILT, 'lift': PAD_LIFT}
out['levels'] = {'plate_top': PLATE_TOP, 'cap_bottom': CAP_BOTTOM, 'cover_z': COVER_Z, 'rim': 17.0}
json.dump(out, open(os.path.join(OUT, 'layout.json'), 'w'), indent=1, ensure_ascii=False)
print('parts', out['parts'])
print(json.dumps(halves, indent=0))
