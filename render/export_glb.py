"""Both halves as scene.py builds them, as a GLB for the web viewer on kyle.au.

    Blender -b -P render/export_glb.py -- render/mesh render/out/kyles-sofle.glb

glTF carries a Principled BSDF's colour, roughness and metalness and an image plugged straight into
them, so this swaps the procedural bevels and grain for plain values, tints the screen art to the
nice!view's ink and grey ahead of time, and makes the acrylic over the controller plain see-through
plastic. Each part is one mesh, both halves together.
"""
import bpy, sys, os
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
MESH, GLB = os.path.abspath(argv[0]), os.path.abspath(argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
# Darks a little lighter than the stills, which light them far harder than a web page can
LIFT = float(os.environ.get("LIFT", "2.0"))

src = open(os.path.join(HERE, "scene.py")).read()
src = src[:src.index("\nfor name in SHOTS:")]
sys.argv = [sys.argv[0], "--", MESH, os.path.dirname(GLB), "16", "1", ""]
ns = {"__name__": "scene", "__file__": os.path.join(HERE, "scene.py")}
exec(compile(src, "scene.py", "exec"), ns)
sc, rig, halves = ns["build"]()


def principled(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def plain(m):
    """Keep only what glTF carries: drop the bevel, grain and anisotropy."""
    nt = m.node_tree; b = principled(m)
    for n in list(nt.nodes):
        if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL", "TEX_IMAGE", "SEPARATE_COLOR"):
            nt.nodes.remove(n)
    for key in ("Coat Weight", "Anisotropic"):
        if key in b.inputs: b.inputs[key].default_value = 0.0
    c = b.inputs["Base Color"]
    if not c.is_linked and b.inputs["Metallic"].default_value < 0.5:
        r, g, bl, a = c.default_value
        if max(r, g, bl) < 0.05:
            c.default_value = (r * LIFT, g * LIFT, bl * LIFT, a)


def image(name, rgb, data=False):
    """A new 8-bit image from RGB in 0..1: linear light, stored as sRGB, or raw data."""
    h, w, _ = rgb.shape
    img = bpy.data.images.new(name, w, h, alpha=False)
    if data: img.colorspace_settings.name = "Non-Color"
    else: rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(np.clip(rgb, 0, 1), 1 / 2.4) - 0.055)
    px = np.ones((h, w, 4), np.float32); px[..., :3] = rgb[::-1]
    img.pixels.foreach_set(px.ravel()); img.file_format = "PNG"; img.pack()
    return img


def pixels(path):
    img = bpy.data.images.load(path); w, h = img.size
    px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1]


INK, GREY = np.array((0.012, 0.013, 0.012)), np.array((0.50, 0.52, 0.49))   # as scene.py's screen_material
SCREEN_GLOW = float(os.environ.get("SCREEN_GLOW", "0.5"))


def screen(m):
    """The screen art, already in the memory LCD's two colours, as colour and a faint glow."""
    nt = m.node_tree; b = principled(m)
    path = next(n for n in nt.nodes if n.type == "TEX_IMAGE").image.filepath
    for n in list(nt.nodes):
        if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"): nt.nodes.remove(n)
    lit = pixels(bpy.path.abspath(path))[..., 0:1] > 0.5
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = image(m.name, np.where(lit, GREY, INK)); t.interpolation = "Closest"
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = SCREEN_GLOW


def acrylic(m):
    b = principled(m)
    b.inputs["Transmission Weight"].default_value = 0.0
    b.inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1); b.inputs["Alpha"].default_value = 0.1
    b.inputs["Roughness"].default_value = 0.05
    if hasattr(m, "surface_render_method"): m.surface_render_method = "BLENDED"


for m in bpy.data.materials:
    if not m.node_tree: continue
    if m.name.startswith("Screen "): screen(m)
    elif m.name == "Clear acrylic": acrylic(m)
    else: plain(m)

# Empty nodes at the parts the viewer's close-ups look at, named "anchor <part>"
ANCHORS = ['screen L', 'knob', 'joystick', 'screen R']
for name in ANCHORS:
    ob = bpy.data.objects[name]
    centre = sum((ob.matrix_world @ Vector(c) for c in ob.bound_box), Vector()) / 8
    e = bpy.data.objects.new("anchor " + name, None); sc.collection.objects.link(e); e.location = centre

# One mesh per part, both halves together, so the viewer can show a part on its own. Each is
# named for its part, and the page names the parts it lets you pick.
PARTS = {
    "case": ["case_"], "pads": ["pad_"], "plate": ["plate_"], "switches": ["switches_"],
    "keycaps": ["caps_", "legend "], "screens": ["screen ", "lcd ", "cover_", "pane_"],
    "knob": ["knob"], "joystick": ["joystick"], "screws": ["screw"],
}
bpy.ops.object.select_all(action="DESELECT")
model = [o for o in bpy.data.collections["model"].all_objects if o.type == "MESH"]
for o in model: o.select_set(True)
bpy.context.view_layer.objects.active = model[0]
bpy.ops.object.convert(target="MESH")
model = [o for o in bpy.data.collections["model"].all_objects if o.type == "MESH"]
for part, prefixes in PARTS.items():
    objects = [o for o in model if any(o.name.startswith(x) for x in prefixes)]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects: o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1: bpy.ops.object.join()
    objects[0].name = objects[0].data.name = part
    model = [o for o in model if o not in objects[1:]]
left = [o.name for o in bpy.data.collections["model"].all_objects if o.type == "MESH" and o.name not in PARTS]
assert not left, f"objects in no part: {left}"

os.makedirs(os.path.dirname(GLB), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=GLB, export_format="GLB", export_apply=True, export_yup=True,
    export_cameras=False, export_lights=False, export_extras=False,
    export_meshopt_compression_enable=True,
)
tris = sum(len(p.vertices) - 2 for o in bpy.data.objects if o.type == "MESH" for p in o.data.polygons)
print("wrote", GLB, os.path.getsize(GLB), "bytes,", tris, "triangles")
