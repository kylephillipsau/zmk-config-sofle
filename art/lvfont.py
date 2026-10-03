"""Render text from an lv_font_conv (bpp 1, uncompressed) C file the way LVGL 8 places glyphs.
Used to check that on-device text matches the PIL mockups."""
import re
from PIL import Image


class LvFont:
    def __init__(self, path):
        src = open(path).read()
        bm = src[src.index('glyph_bitmap[] = {'):src.index('};', src.index('glyph_bitmap[] = {'))]
        blocks = re.split(r'/\* U\+([0-9A-F]{4}) ".*?" \*/', bm)[1:]
        cps = [int(blocks[i], 16) for i in range(0, len(blocks), 2)]
        datas = [[int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]+', blocks[i + 1])] for i in range(0, len(blocks), 2)]
        dscs = re.findall(r'\{\.bitmap_index = (\d+), \.adv_w = (\d+), \.box_w = (\d+), \.box_h = (\d+), \.ofs_x = (-?\d+), \.ofs_y = (-?\d+)\}', src)[1:]
        assert len(dscs) == len(cps), (len(dscs), len(cps))
        self.glyphs = {}
        for cp, data, dsc in zip(cps, datas, dscs):
            _, adv, bw, bh, ox, oy = map(int, dsc)
            self.glyphs[chr(cp)] = (data, (adv + 8) >> 4, bw, bh, ox, oy)
        self.line_height = int(re.search(r'\.line_height = (\d+)', src).group(1))
        self.base_line = int(re.search(r'\.base_line = (\d+)', src).group(1))

    def width(self, s):
        return sum(self.glyphs[c][1] for c in s)

    def draw(self, img, x, y, s, fill=1):
        """y is the top of the LVGL line box, as passed to lv_canvas_draw_text."""
        px = img.load()
        for c in s:
            data, adv, bw, bh, ox, oy = self.glyphs[c]
            gx = x + ox
            gy = y + (self.line_height - self.base_line) - bh - oy
            for i in range(bw * bh):
                if data[i // 8] >> (7 - i % 8) & 1:
                    xx, yy = gx + i % bw, gy + i // bw
                    if 0 <= xx < img.width and 0 <= yy < img.height:
                        px[xx, yy] = fill
            x += adv

    def cap_top(self):
        """Offset from the line-box top to the top of capital letters (matches the C helper)."""
        _, _, _, bh, _, oy = self.glyphs['H' if 'H' in self.glyphs else '0']
        return self.line_height - self.base_line - bh - oy
