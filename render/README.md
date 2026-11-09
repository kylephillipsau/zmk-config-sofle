# Renders and 3D model

The scripts behind the renders in `docs/renders/` and the 3D model on
[kyle.au](https://kyle.au/projects/kyles-sofle). They read the seller's 3D files from
`../3Dmodel/3Dmodel/sofle-MX-narmal`, beside this repo. Run them from the repo root.

```sh
uv run render/make_meshes.py render/mesh
Blender -b -P render/scene.py -- render/mesh render/out 3840 192 hero,top,screens,joystick,side,pad
uv run render/grade.py render/out render/graded hero,top,screens,joystick,side,pad
Blender -b -P render/export_glb.py -- render/mesh render/out/kyles-sofle.glb
```

`export_glb.py` builds the same scene as `scene.py` and swaps its procedural materials for ones glTF
can carry. The two screen images are the left screen's card and the right screen's idle art.
