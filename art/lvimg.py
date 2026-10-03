"""Helpers for nice!view 1-bit art: decode/encode LVGL INDEXED_1BIT C arrays, render previews."""
import re
from PIL import Image

INK = (236, 232, 214)     # light pixels as seen on the user's panel photo
PAPER = (30, 34, 82)      # dark navy panel background

def decode_c_array(src, name):
    """Return a native (w x h) 1-bit PIL image where ink pixels are 1."""
    m = re.search(name + r'_map\[\]\s*=\s*\{(.*?)\};', src, re.S)
    body = m.group(1)
    # drop the palette (#if ... #endif block)
    body = re.sub(r'#if.*?#endif', '', body, flags=re.S)
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    data = [int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]{2}', body)]
    hdr = re.search(r'lv_img_dsc_t\s+' + name + r'\s*=\s*\{(.*?)\};', src, re.S).group(1)
    w = int(re.search(r'header\.w\s*=\s*(\d+)', hdr).group(1))
    h = int(re.search(r'header\.h\s*=\s*(\d+)', hdr).group(1))
    stride = (w + 7) // 8
    img = Image.new('1', (w, h), 0)
    px = img.load()
    for y in range(h):
        for x in range(w):
            bit = (data[y * stride + x // 8] >> (7 - x % 8)) & 1
            px[x, y] = 1 if bit == 0 else 0   # index 0 = LVGL black = ink
    return img

def native_to_portrait(img):
    """Native 160-wide landscape -> portrait as mounted (right edge becomes top)."""
    return img.transpose(Image.Transpose.ROTATE_90)

def portrait_to_native(img):
    return img.transpose(Image.Transpose.ROTATE_270)

def preview(img, scale=4, gap=0):
    """Colourise a 1-bit image (1 = ink) like the real panel and upscale."""
    rgb = Image.new('RGB', img.size, PAPER)
    ink = Image.new('RGB', img.size, INK)
    rgb.paste(ink, mask=img.convert('L').point(lambda v: 255 if v else 0))
    return rgb.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
