/*
 * SPDX-License-Identifier: MIT
 *
 * Drawing helpers shared by both screens. See draw.h.
 */

#include <stdio.h>
#include <string.h>
#include <zephyr/kernel.h>

#include "draw.h"
#include "util.h"

void fill(const struct frame *f, int x, int y, int w, int h, lv_color_t c) {
    lv_draw_rect_dsc_t dsc;
    init_rect_dsc(&dsc, c);
    lv_canvas_draw_rect(f->canvas, x, y - f->y0, w, h, &dsc);
}

void put_px(const struct frame *f, int x, int y, lv_color_t c) {
    y -= f->y0;
    if (x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE) {
        return;
    }
    // Written straight to the buffer; rotate_canvas() invalidates the canvas afterwards.
    f->buf[y * CANVAS_SIZE + x] = c;
}

void outline(const struct frame *f, int x, int y, int w, int h, lv_color_t c) {
    fill(f, x, y, w, 1, c);
    fill(f, x, y + h - 1, w, 1, c);
    fill(f, x, y, 1, h, c);
    fill(f, x + w - 1, y, 1, h, c);
}

void draw_glyph(const struct frame *f, int x, int y, const struct glyph *g, lv_color_t c) {
    for (int r = 0; r < g->h; r++) {
        for (int col = 0; col < g->w; col++) {
            if (g->rows[r] & BIT(g->w - 1 - col)) {
                put_px(f, x + col, y + r, c);
            }
        }
    }
}

// Distance from the top of an LVGL line box to the top of the font's capitals (or digits).
int cap_top(const lv_font_t *font) {
    lv_font_glyph_dsc_t g;
    if (!lv_font_get_glyph_dsc(font, &g, 'H', 0) && !lv_font_get_glyph_dsc(font, &g, '0', 0)) {
        return 0;
    }
    return font->line_height - font->base_line - g.box_h - g.ofs_y;
}

// Draw text aligned within [x, x + w), with the top of its capitals at cap_y. Text never wraps:
// LVGL would otherwise break an overlong string onto a second line (':' counts as a break).
void draw_text(const struct frame *f, const lv_font_t *font, int x, int w, int cap_y,
                      lv_text_align_t align, lv_color_t c, const char *text) {
    lv_draw_label_dsc_t dsc;
    init_label_dsc(&dsc, c, font, align);
    dsc.flag |= LV_TEXT_FLAG_EXPAND;
    lv_canvas_draw_text(f->canvas, x, cap_y - cap_top(font) - f->y0, w, &dsc, text);
}

// Whether the first len characters of s fit in w px.
bool text_fits(const lv_font_t *font, const char *s, size_t len, int w) {
    if (len == 0) {
        return true;
    }
    lv_font_glyph_dsc_t g;
    int trailing = 0; // the last glyph's advance past its ink is spacing, not ink
    if (lv_font_get_glyph_dsc(font, &g, (uint8_t)s[len - 1], 0)) {
        trailing = g.adv_w - (g.ofs_x + g.box_w);
    }
    return lv_txt_get_width(s, len, font, 0, LV_TEXT_FLAG_EXPAND) - trailing <= w;
}

// Copy text into out, dropping characters from the end until it fits w px, then any '-', '_', '.'
// or space left dangling. Mirrors lv_fit() in art/concepts.py.
void fit_text(const lv_font_t *font, const char *text, int w, char *out, size_t size) {
    snprintf(out, size, "%s", text);
    size_t len = strlen(out);
    bool cut = false;
    while (!text_fits(font, out, len, w)) {
        out[--len] = '\0';
        cut = true;
    }
    while (cut && len > 0 && strchr("-_. ", out[len - 1])) {
        out[--len] = '\0';
    }
}
