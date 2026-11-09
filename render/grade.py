# /// script
# dependencies = ["pillow", "numpy"]
# ///
"""Vignette and fine grain, then full-size JPEGs, web-size copies and a contact sheet."""
import sys, numpy as np
from pathlib import Path
from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
shots = sys.argv[3].split(",")
out.mkdir(exist_ok=True)
rng = np.random.default_rng(7)
thumbs = []
for name in shots:
    im = np.asarray(Image.open(src / f"{name}.png").convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = im.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / np.sqrt(2)
    im *= (1 - 0.42 * r ** 2.4)[..., None]
    grain = rng.normal(0, 0.011, (h, w)).astype(np.float32)
    im = np.clip(im + grain[..., None] * (0.35 + im), 0, 1)
    pic = Image.fromarray((im * 255 + 0.5).astype(np.uint8))
    pic.save(out / f"kyles-sofle-{name}.jpg", quality=93, subsampling=0)
    small = pic.resize((1600, round(1600 * h / w)), Image.LANCZOS)
    small.save(out / f"kyles-sofle-{name}-web.jpg", quality=88)
    thumbs.append(pic.resize((1200, round(1200 * h / w)), Image.LANCZOS))
tw, th = thumbs[0].size
cols = 2
rows = (len(thumbs) + 1) // cols
sheet = Image.new("RGB", (tw * cols + 12 * (cols - 1), th * rows + 12 * (rows - 1)), (0, 0, 0))
for i, t in enumerate(thumbs):
    sheet.paste(t, ((i % cols) * (tw + 12), (i // cols) * (th + 12)))
sheet.save(out / "kyles-sofle-stills.jpg", quality=90)
print("graded", len(shots))
