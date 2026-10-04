/*
 * SPDX-License-Identifier: MIT
 *
 * Drawing in portrait coordinates, shared by both screens. A frame is one 68x68 canvas covering
 * portrait rows y0..y0+67; anything outside it is clipped, so a shape can be drawn into every
 * frame it might touch, and the canvas is rotated into the panel's landscape orientation after.
 */

#pragma once

#include <lvgl.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Row bitmaps, most significant used bit = leftmost pixel. art/make_glyphs.py writes them.
struct glyph {
    uint8_t w;
    uint8_t h;
    const uint16_t *rows;
};

struct frame {
    lv_obj_t *canvas;
    lv_color_t *buf;
    int y0;
};

void fill(const struct frame *f, int x, int y, int w, int h, lv_color_t c);
void put_px(const struct frame *f, int x, int y, lv_color_t c);
void outline(const struct frame *f, int x, int y, int w, int h, lv_color_t c);
void draw_glyph(const struct frame *f, int x, int y, const struct glyph *g, lv_color_t c);

// Distance from the top of an LVGL line box to the top of the font's capitals (or digits).
int cap_top(const lv_font_t *font);

// Draw text aligned within [x, x + w), with the top of its capitals at cap_y. Text never wraps.
void draw_text(const struct frame *f, const lv_font_t *font, int x, int w, int cap_y,
               lv_text_align_t align, lv_color_t c, const char *text);

// Whether the first len characters of s fit in w px.
bool text_fits(const lv_font_t *font, const char *s, size_t len, int w);

// Copy text into out, trimmed from the end to fit w px. Mirrors lv_fit() in art/concepts.py.
void fit_text(const lv_font_t *font, const char *text, int w, char *out, size_t size);
