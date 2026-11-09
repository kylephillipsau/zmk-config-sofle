"""Studio stills of Kyle's Sofle. Run: blender -b -P scene.py -- MESH_DIR OUT_DIR WIDTH SAMPLES SHOT[,SHOT]"""
import bpy, bmesh, math, sys, os, json
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
MESH, OUT, WIDTH, SAMPLES, SHOTS = argv[0], argv[1], int(argv[2]), int(argv[3]), argv[4].split(",")
HERE = os.path.dirname(os.path.abspath(MESH))
HEIGHT = round(WIDTH / 2.39)
MM = 0.001
E = lambda k, d: float(os.environ.get(k, d))
BEVEL, EXPOSURE, POOL, SHEEN, KEY, RIM = E("BEVEL", 0.00035), E("EXPOSURE", -4.5), E("POOL", 1.0), E("SHEEN", 1.0), E("KEY", 1.0), E("RIM", 0.25)
MATTE, ROUGH, SCREEN, CAPS = E("MATTE", 0.006), E("ROUGH", 0.45), E("SCREEN", 1.2), E("CAPS", 0.007)
GAP, TOE, LS = E("GAP", 44), E("TOE", 9), E("LS", 1.7)
JGRAIN, JBUMP = E("JGRAIN", 1.6), E("JBUMP", 0.12)  # texture coordinates are in mm: the meshes are scaled by their objects  # gap between inner edges (mm), toe-in (deg), light scale
LAYOUT = json.load(open(os.path.join(MESH, "layout.json")))
DISH, TOP_W = 0.45, 12.6
FONT_TEXT = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT_SYM = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
SYMBOLS = set("↑→–’”")

def material(name, colour, rough, metal=0.0, spec=0.5, grain=None, grain_strength=0.18, coat=0.0, aniso=0.0, radial=False, bump_mm=0.04):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*colour, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for key in ("Specular IOR Level", "Specular"):
        if key in b.inputs: b.inputs[key].default_value = spec; break
    if coat and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = coat
        if "Coat Roughness" in b.inputs: b.inputs["Coat Roughness"].default_value = 0.02
    if aniso and "Anisotropic" in b.inputs:
        b.inputs["Anisotropic"].default_value = aniso
        if radial:
            tg = nt.nodes.new("ShaderNodeTangent"); tg.direction_type = "RADIAL"; tg.axis = "Z"
            nt.links.new(tg.outputs["Tangent"], b.inputs["Tangent"])
    bevel = nt.nodes.new("ShaderNodeBevel"); bevel.samples = 8; bevel.inputs["Radius"].default_value = BEVEL
    if grain:
        tc = nt.nodes.new("ShaderNodeTexCoord"); n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = grain; n.inputs["Detail"].default_value = 6
        nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
        bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = grain_strength
        bump.inputs["Distance"].default_value = bump_mm * MM
        nt.links.new(bevel.outputs["Normal"], bump.inputs["Normal"])
        nt.links.new(n.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    else:
        nt.links.new(bevel.outputs["Normal"], b.inputs["Normal"])
    return m

def glass(name):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.95, 0.95, 0.95, 1); b.inputs["Roughness"].default_value = 0.0
    b.inputs["Transmission Weight"].default_value = 1.0; b.inputs["IOR"].default_value = 1.49
    return m

def screen_material(name, path):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(path); tex.interpolation = "Closest"
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.012, 0.013, 0.012, 1)   # ink
    mix.inputs[7].default_value = (0.50, 0.52, 0.49, 1)      # the memory LCD's pale grey
    nt.links.new(tex.outputs["Color"], mix.inputs[0])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    nt.links.new(mix.outputs[2], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = SCREEN
    b.inputs["Roughness"].default_value = 0.3
    return m

MATS = {}
def make_materials():
    black = (MATTE, MATTE, MATTE * 1.08)
    MATS.update({
        "case": material("Matte black case", black, ROUGH, spec=0.35),
        "plate": material("Matte black plate", black, ROUGH, spec=0.35),
        "pad": material("Matte black pad", black, ROUGH, spec=0.35),
        "switches": material("Switch housing", (0.01, 0.01, 0.011), 0.5),
        "caps_black": material("Black PBT", (CAPS, CAPS, CAPS * 1.08), 0.68, spec=0.18, grain=9000, grain_strength=0.1),
        "caps_orange": material("Orange PBT", (0.60, 0.105, 0.035), 0.62, spec=0.3, grain=9000, grain_strength=0.12),
        "cover": material("Black acrylic", (0.003, 0.003, 0.0035), 0.04, spec=0.5, coat=1.0),
        "pane": glass("Clear acrylic"),
        "legend": material("Legend", (0.70, 0.70, 0.68), 0.45, spec=0.3),
        "legend_dark": material("Legend on orange", (0.02, 0.018, 0.016), 0.5, spec=0.3),
        "knob": material("Anodised knob", (0.045, 0.045, 0.05), 0.3, metal=1.0, aniso=0.4),
        "knob_top": material("Spun knob face", (0.16, 0.16, 0.17), 0.16, metal=1.0, aniso=0.85, radial=True),
        "joystick": material("Textured joystick", (0.006, 0.006, 0.0065), 0.85, spec=0.3, grain=JGRAIN, grain_strength=1.0, bump_mm=JBUMP),
        "screws": material("Black oxide", (0.035, 0.035, 0.037), 0.33, metal=1.0),
        "lcd": material("LCD glass edge", (0.02, 0.02, 0.022), 0.15, spec=0.5),
    })

def tidy(ob, mat, angle=32):
    bm = bmesh.new(); bm.from_mesh(ob.data); bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-7); bm.to_mesh(ob.data); bm.free()
    ob.data.shade_smooth()
    try: ob.data.set_sharp_from_angle(angle=math.radians(angle))
    except Exception as e: print("smooth by angle failed", e)
    wn = ob.modifiers.new("weighted", "WEIGHTED_NORMAL"); wn.mode = "FACE_AREA"; wn.keep_sharp = True
    ob.data.materials.clear(); ob.data.materials.append(MATS[mat])

def link(ob, parent):
    for c in list(ob.users_collection): c.objects.unlink(ob)
    MODEL.objects.link(ob); ob.parent = parent

def load(name, mat, parent, angle=32):
    bpy.ops.wm.stl_import(filepath=os.path.join(MESH, name + ".stl"), global_scale=MM)
    ob = bpy.context.selected_objects[0]; ob.name = name
    tidy(ob, mat, angle); link(ob, parent); return ob

def plane(name, w, h, loc, mat, parent):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    vs = [bm.verts.new((sx * w / 2, sy * h / 2, 0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    f = bm.faces.new(vs); uv = bm.loops.layers.uv.new()
    for loop, co in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): loop[uv].uv = co
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); MODEL.objects.link(ob); ob.parent = parent; ob.location = loc
    me.materials.append(MATS[mat] if isinstance(mat, str) else mat); return ob

def cylinder(name, r, h, loc, parent, mats, verts=128, bevel=0.0004):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=loc)
    ob = bpy.context.object; ob.name = name
    for m in mats: ob.data.materials.append(MATS[m])
    if len(mats) > 1:
        for p in ob.data.polygons: p.material_index = 1 if p.normal.z > 0.9 else 0
    ob.data.shade_smooth()
    try: ob.data.set_sharp_from_angle(angle=math.radians(40))
    except Exception: pass
    if bevel:
        bv = ob.modifiers.new("bevel", "BEVEL"); bv.width = bevel; bv.segments = 4; bv.limit_method = "ANGLE"
    link(ob, parent); return ob

def legends(halves, caps):
    fonts = {"text": bpy.data.fonts.load(FONT_TEXT), "sym": bpy.data.fonts.load(FONT_SYM)}
    dg = bpy.context.evaluated_depsgraph_get()
    for k in LAYOUT["keys"]:
        txt = k["legend"]; sym = any(ch in SYMBOLS for ch in txt)
        word = len(txt) > 2 and " " not in txt
        size, dy = (3.3, 2.4) if word else (3.7, 2.6) if " " in txt else (4.6, 1.9)
        if txt in ("→", "↑"): size, dy = (5.0, 2.6) if txt == "↑" else (4.0, 3.6)
        if txt in ("–", "*"): size, dy = 4.4, 2.6
        cu = bpy.data.curves.new("legend", "FONT"); cu.body = txt; cu.font = fonts["sym" if sym else "text"]
        cu.size = size * MM; cu.align_x = "CENTER"; cu.align_y = "CENTER"
        tmp = bpy.data.objects.new("tmp", cu); bpy.context.scene.collection.objects.link(tmp)
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg)); bpy.data.objects.remove(tmp); bpy.data.curves.remove(cu)
        # Flat on the top's tilted plane, lifted just clear of the cylindrical dish at its widest
        hw = max(abs(v.co.x) for v in me.vertices) / MM
        lift = DISH * min(1.0, (2 * hw / TOP_W) ** 2) + 0.04
        ob = bpy.data.objects.new("legend " + txt, me); MODEL.objects.link(ob); ob.parent = halves[k["half"]]
        r, t = math.radians(k["r"]), math.tan(math.radians(k["tilt"]))
        ly = k["top_back"] + dy
        ob.location = (MM * (k["x"] - ly * math.sin(r)), MM * (k["y"] + ly * math.cos(r)), MM * (k["z"] + t * ly - DISH + lift))
        ob.rotation_euler = (math.radians(k["tilt"]), 0, r)
        me.materials.append(MATS["legend_dark" if k["colour"] == "orange" else "legend"])

def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    make_materials()
    sc = bpy.context.scene; sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("METAL", "NONE"):
        try:
            prefs.compute_device_type = kind; prefs.get_devices()
            for d in prefs.devices: d.use = True
            break
        except Exception as e: print("device", kind, e)
    sc.cycles.device = "GPU" if prefs.compute_device_type != "NONE" else "CPU"
    sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = os.environ.get("DENOISE", "1") == "1"
    sc.cycles.max_bounces = 12; sc.cycles.glossy_bounces = 6; sc.cycles.transmission_bounces = 8
    sc.render.resolution_x, sc.render.resolution_y = WIDTH, HEIGHT
    sc.view_settings.view_transform = "AgX"
    for look_name in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try: sc.view_settings.look = look_name; break
        except Exception: pass
    sc.view_settings.exposure = EXPOSURE
    world = bpy.data.worlds.new("World"); sc.world = world; world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0025, 0.0027, 0.003, 1)
    global MODEL, GROUND
    MODEL = bpy.data.collections.new("model"); sc.collection.children.link(MODEL)
    GROUND = bpy.data.collections.new("ground"); sc.collection.children.link(GROUND)
    rig = bpy.data.objects.new("rig", None); sc.collection.objects.link(rig)
    halves, caps = {}, {}
    for half, sign in (("L", -1), ("R", 1)):
        e = bpy.data.objects.new("half " + half, None); sc.collection.objects.link(e); e.parent = rig
        e.location = (sign * GAP / 2 * MM, 0, 0); e.rotation_euler = (0, 0, math.radians(-sign * TOE))
        load("pad_" + half, "pad", e)
        # The case rests on the pad's sloped top, its inner edge raised
        tilt = bpy.data.objects.new("tilt " + half, None); sc.collection.objects.link(tilt); tilt.parent = e
        tilt.location = (0, 0, LAYOUT["pad"]["lift"] * MM)
        tilt.rotation_euler = (0, math.radians(sign * LAYOUT["pad"]["tilt"]), 0)  # left: -y turn lifts +x, its inner edge
        e = tilt
        halves[half] = e
        load("case_" + half, "case", e); load("plate_" + half, "plate", e)
        load("switches_" + half, "switches", e)
        for colour in ("black", "orange"):
            caps[(half, colour)] = load(f"caps_{colour}_{half}", "caps_" + colour, e, angle=50)
        load("cover_" + half, "cover", e); load("pane_" + half, "pane", e)
        h = LAYOUT["halves"][half]; z0, z1 = h["strip_z"]
        wx, wy = h["window"]
        screen = screen_material("Screen " + half, os.path.join(HERE, "screen_left-card.png" if half == "L" else "screen_right-idle.png"))
        plane("screen " + half, 10.8 * MM, 25.4 * MM, (wx * MM, wy * MM, (z0 - 0.08) * MM), screen, e)
        plane("lcd " + half, 13.4 * MM, 28.6 * MM, (wx * MM, wy * MM, (z0 - 0.16) * MM), "lcd", e)
        kx, ky = h["knob"]
        if half == "L":
            cylinder("knob", 6.6 * MM, 8.0 * MM, (kx * MM, ky * MM, (z1 + 0.8 + 4.0) * MM), e, ["knob", "knob_top"])
        else:
            bpy.ops.wm.stl_import(filepath=os.path.join(MESH, "joystick_cap.stl"), global_scale=MM)
            j = bpy.context.selected_objects[0]; j.name = "joystick"; tidy(j, "joystick", 40); link(j, e)
            j.location = (kx * MM, ky * MM, (z1 + 1.0 - 7.0) * MM)
        for sx, sy in h["screws"]:
            cylinder("screw", 1.5 * MM, 0.8 * MM, (sx * MM, sy * MM, (z1 + 0.45) * MM), e, ["screws"], verts=48, bevel=0.0003)
    bpy.context.view_layer.update()
    legends(halves, caps)
    return sc, rig, halves

def floor(sc, z, rough=0.24, shade=0.03):
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, z)); f = bpy.context.object; f.name = "floor"
    m = bpy.data.materials.new("Floor"); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (shade, shade, shade * 1.06, 1); b.inputs["Roughness"].default_value = rough
    f.data.materials.append(m)
    for c in list(f.users_collection): c.objects.unlink(f)
    GROUND.objects.link(f)

def look(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat("-Z", "Y").to_euler()

def area(sc, name, loc, target, size, energy, colour=(1, 1, 1), size_y=None, spread=None):
    l = bpy.data.lights.new(name, "AREA"); l.energy = energy; l.color = colour
    if size_y: l.shape = "RECTANGLE"; l.size = size; l.size_y = size_y
    else: l.size = size
    if spread is not None: l.spread = math.radians(spread)
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o); o.location = loc; look(o, target)
    o.visible_camera = False; o.light_linking.receiver_collection = MODEL
    return o

def spot(sc, name, loc, target, energy, size_deg, blend=1.0, colour=(1, 1, 1), radius=0.05):
    l = bpy.data.lights.new(name, "SPOT"); l.energy = energy * POOL; l.spot_size = math.radians(size_deg); l.spot_blend = blend; l.color = colour
    l.shadow_soft_size = radius
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o); o.location = loc; look(o, target)
    o.light_linking.receiver_collection = GROUND

def camera(sc, loc, target, lens, fstop, focus_point):
    c = bpy.data.cameras.new("cam"); c.lens = lens; c.sensor_width = 36
    c.dof.use_dof = fstop is not None
    o = bpy.data.objects.new("cam", c); sc.collection.objects.link(o); o.location = loc; look(o, target); sc.camera = o
    if fstop: c.dof.aperture_fstop = fstop; c.dof.focus_distance = (Vector(loc) - Vector(focus_point)).length
    c.clip_start = 0.005; c.clip_end = 30
    return o

WARM, COOL = (1.0, 0.84, 0.68), (0.70, 0.83, 1.0)

def studio(sc, t, z_floor, key=30.0, rim=1.0, halo=(0.0, 0.16), s=None):
    s = s or LS; t = Vector(t); e = s * s
    area(sc, "key", t + Vector((-0.30, -0.28, 0.42)) * s, t, 0.40 * s, key * KEY * e, WARM, 0.22 * s)
    area(sc, "rim right", t + Vector((0.30, 0.34, 0.12)) * s, t, 0.035 * s, 110 * rim * RIM * e, COOL, 0.7 * s, spread=30)
    area(sc, "rim left", t + Vector((-0.34, 0.26, 0.10)) * s, t, 0.035 * s, 70 * rim * RIM * e, WARM, 0.6 * s, spread=30)
    area(sc, "top strip", t + Vector((0.0, 0.05, 0.45)) * s, t, 0.6 * s, 26 * rim * KEY * e, (1, 1, 1), 0.03 * s)
    spot(sc, "halo", t + Vector((halo[0], halo[1] + 0.05, 0.75)) * s, (t.x + halo[0] * s, t.y + (halo[1] + 0.12) * s, z_floor), 7000 * e, 26, 1.0, (0.86, 0.9, 1.0), 0.3 * s)
    floor(sc, z_floor)
    cam = sc.camera.location; back = (cam - t).normalized()
    area(sc, "sheen", cam + back * 0.35 * s + Vector((0, 0, 0.12 * s)), t, 1.0 * s, 250 * SHEEN * e, (1, 1, 1), 0.6 * s)

def point(halves, half, x, y, z):
    return halves[half].matrix_world @ Vector((x * MM, y * MM, z * MM))

def shot_hero(sc, rig, halves):
    t = Vector((0.0, 0.006, 0.012))
    camera(sc, (0.17, -0.78, 0.29), t, 70, 5.6, point(halves, "L", -30, -10, 22))
    studio(sc, t, 0.0)

def shot_top(sc, rig, halves):
    t = Vector((0.0, 0.004, 0.01))
    camera(sc, (0.0, -0.52, 0.98), t, 85, 8.0, t)
    studio(sc, t, 0.0, key=26)

def shot_screens(sc, rig, halves):
    h = LAYOUT["halves"]["L"]; wx, wy = h["window"]
    kx, ky = h["knob"]
    t = point(halves, "L", wx - 6, (wy + ky) / 2 - 2, 18)
    sc.view_settings.exposure = EXPOSURE - 0.25
    camera(sc, t + Vector((0.12, -0.27, 0.24)), t, 100, 4.0, point(halves, "L", wx, (wy + ky) / 2, 18))
    studio(sc, t, 0.0, key=18, s=1.1)

def shot_joystick(sc, rig, halves):
    h = LAYOUT["halves"]["R"]; kx, ky = h["knob"]
    wx, wy = h["window"]
    t = point(halves, "R", kx + 10, (wy + ky) / 2 - 6, 18)
    sc.view_settings.exposure = EXPOSURE - 0.35
    camera(sc, t + Vector((0.13, -0.22, 0.27)), t, 100, 4.0, point(halves, "R", kx + 2, ky + 4, 22))
    studio(sc, t, 0.0, key=12, s=1.1)

def shot_side(sc, rig, halves):
    t = point(halves, "L", -75, 0, 20)
    sc.view_settings.exposure = EXPOSURE - 0.2
    camera(sc, t + Vector((-0.42, -0.30, 0.07)), t, 105, 4.0, point(halves, "L", -120, 40, 24))
    studio(sc, t, 0.0, key=16, rim=0.45, s=1.2)

def shot_dbg(sc, rig, halves):
    h = LAYOUT["halves"]["R"]; kx, ky = h["knob"]; wx, wy = h["window"]
    t = point(halves, "R", wx, wy - 10, 17)
    camera(sc, t + Vector((-0.06, -0.16, 0.22)), t, 100, None, None)
    studio(sc, t, 0.0, key=12, s=1.1)

def shot_pad(sc, rig, halves):
    # Low, from in front and between the halves, at the left half's raised inner edge and its pad
    t = point(halves, "L", -66, -40, 10)
    sc.view_settings.exposure = EXPOSURE + 0.2
    camera(sc, t + Vector((0.13, -0.50, 0.05)), t, 85, 8.0, point(halves, "L", -66, -55, 8))
    studio(sc, t, 0.0, key=26, s=1.3)

def shot_dbgj(sc, rig, halves):
    h = LAYOUT["halves"]["R"]; kx, ky = h["knob"]
    t = point(halves, "R", kx, ky, 22)
    camera(sc, t + Vector((0.03, -0.07, 0.07)), t, 100, None, None)
    studio(sc, t, 0.0, key=12, s=1.1)

def shot_dbgl(sc, rig, halves):
    t = point(halves, "L", -60, -30, 22)
    camera(sc, t + Vector((0.03, -0.14, 0.24)), t, 100, None, None)
    studio(sc, t, 0.0, key=12, s=1.1)

for name in SHOTS:
    sc, rig, halves = build()
    globals()["shot_" + name](sc, rig, halves)
    sc.render.filepath = os.path.join(OUT, name + ".png")
    sc.render.image_settings.file_format = "PNG"
    try: sc.render.image_settings.color_depth = "16"
    except Exception: pass
    bpy.ops.render.render(write_still=True)
    print("wrote", sc.render.filepath)
