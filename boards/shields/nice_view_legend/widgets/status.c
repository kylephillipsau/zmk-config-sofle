/*
 *
 * Copyright (c) 2025 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 * Left (central) screen: a status area (both batteries, layer, Bluetooth slots, held modifiers,
 * Claude Code badge) above a live WPM chart, whose header turns into a Claude Code banner. The layout mirrors spec_left() in art/concepts.py, and the
 * fonts and icons are generated from the same sources, so the mockups match the device.
 *
 * The screen is three 68x68 canvases stacked in portrait order (rows 0-67, 68-135, 136-159),
 * each drawn upright and then rotated into the panel's landscape orientation.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#include <dt-bindings/zmk/hid_usage.h>
#include <dt-bindings/zmk/hid_usage_pages.h>
#include <dt-bindings/zmk/modifiers.h>
#include <zmk/battery.h>
#include <zmk/display.h>
#include "status.h"
#include "status_glyphs.h"
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/event_manager.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/events/ble_active_profile_changed.h>
#include <zmk/events/endpoint_changed.h>
#include <zmk/events/keycode_state_changed.h>
#include <zmk/events/wpm_state_changed.h>
#include <zmk/events/layer_state_changed.h>
#include <zmk/usb.h>
#include <zmk/ble.h>
#include <zmk/endpoints.h>
#include <zmk/keymap.h>
#include <zmk/wpm.h>
#if IS_ENABLED(CONFIG_ZMK_HID_INDICATORS)
#include <zmk/hid_indicators.h>
#include <zmk/events/hid_indicators_changed.h>
#endif
#if IS_ENABLED(CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING)
#include <zmk/split/central.h>
#endif

LV_FONT_DECLARE(lv_font_silkscreen_8);
LV_FONT_DECLARE(lv_font_silkscreen_bold_8);
LV_FONT_DECLARE(lv_font_jersey_1x);
LV_FONT_DECLARE(lv_font_jersey_2x);

#define SCREEN_W 68
#define MIDDLE_Y 68 // first portrait row of the middle canvas
#define BOTTOM_Y 136

#define CHART_TOP 96
#define CHART_BOTTOM 156

static sys_slist_t widgets = SYS_SLIST_STATIC_INIT(&widgets);

struct output_status_state {
    struct zmk_endpoint_instance selected_endpoint;
    int active_profile_index;
    bool active_profile_connected;
    bool active_profile_bonded;
    bool profiles_connected[NICEVIEW_PROFILE_COUNT];
    bool profiles_bonded[NICEVIEW_PROFILE_COUNT];
};

struct layer_status_state {
    zmk_keymap_layer_index_t index;
    const char *label;
};

struct wpm_status_state {
    uint8_t wpm;
};

struct peripheral_battery_state {
    int16_t level;
};

struct mods_state {
    uint8_t mods;
};

struct agent_state {
    uint8_t agent;
};

/* ---------------------------------------------------------------------------------------------
 * Drawing in portrait coordinates. A frame is one canvas covering rows y0..y0+67; anything
 * outside it is clipped, so a shape can be drawn into every frame it might touch.
 */

struct frame {
    lv_obj_t *canvas;
    lv_color_t *buf;
    int y0;
};

static void fill(const struct frame *f, int x, int y, int w, int h, lv_color_t c) {
    lv_draw_rect_dsc_t dsc;
    init_rect_dsc(&dsc, c);
    lv_canvas_draw_rect(f->canvas, x, y - f->y0, w, h, &dsc);
}

static void put_px(const struct frame *f, int x, int y, lv_color_t c) {
    y -= f->y0;
    if (x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE) {
        return;
    }
    // Written straight to the buffer; rotate_canvas() invalidates the canvas afterwards.
    f->buf[y * CANVAS_SIZE + x] = c;
}

static void outline(const struct frame *f, int x, int y, int w, int h, lv_color_t c) {
    fill(f, x, y, w, 1, c);
    fill(f, x, y + h - 1, w, 1, c);
    fill(f, x, y, 1, h, c);
    fill(f, x + w - 1, y, 1, h, c);
}

static void dashed_square(const struct frame *f, int x, int y, int size, lv_color_t c) {
    for (int k = 0; k < size; k += 2) {
        put_px(f, x + k, y, c);
        put_px(f, x + k, y + size - 1, c);
        put_px(f, x, y + k, c);
        put_px(f, x + size - 1, y + k, c);
    }
}

static void draw_glyph(const struct frame *f, int x, int y, const struct glyph *g, lv_color_t c) {
    for (int r = 0; r < g->h; r++) {
        for (int col = 0; col < g->w; col++) {
            if (g->rows[r] & BIT(g->w - 1 - col)) {
                put_px(f, x + col, y + r, c);
            }
        }
    }
}

// Distance from the top of an LVGL line box to the top of the font's capitals (or digits).
static int cap_top(const lv_font_t *font) {
    lv_font_glyph_dsc_t g;
    if (!lv_font_get_glyph_dsc(font, &g, 'H', 0) && !lv_font_get_glyph_dsc(font, &g, '0', 0)) {
        return 0;
    }
    return font->line_height - font->base_line - g.box_h - g.ofs_y;
}

// Draw text aligned within [x, x + w), with the top of its capitals at cap_y.
static void draw_text(const struct frame *f, const lv_font_t *font, int x, int w, int cap_y,
                      lv_text_align_t align, lv_color_t c, const char *text) {
    lv_draw_label_dsc_t dsc;
    init_label_dsc(&dsc, c, font, align);
    lv_canvas_draw_text(f->canvas, x, cap_y - cap_top(font) - f->y0, w, &dsc, text);
}

static void draw_line(const struct frame *f, int x0, int y0, int x1, int y1, lv_color_t c) {
    int dx = abs(x1 - x0), dy = -abs(y1 - y0);
    int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    while (true) {
        put_px(f, x0, y0, c);
        if (x0 == x1 && y0 == y1) {
            break;
        }
        int e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

static int floor_div(int a, int b) {
    int q = a / b;
    return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q;
}

static struct frame frame_for(lv_obj_t *widget, struct zmk_widget_status *w, int index) {
    static const int y0[] = {0, MIDDLE_Y, BOTTOM_Y};
    lv_color_t *bufs[] = {w->cbuf, w->cbuf2, w->cbuf3};
    return (struct frame){.canvas = lv_obj_get_child(widget, index), .buf = bufs[index],
                          .y0 = y0[index]};
}

/* ---------------------------------------------------------------------------------------------
 * Status area (top canvas)
 */

static void draw_battery_column(const struct frame *f, int x, char label, int level,
                                bool charging) {
    lv_color_t ink = LVGL_FOREGROUND;
    char text[12] = {label, '\0'};

    if (charging) {
        draw_glyph(f, x, 0, &glyph_bolt, ink); // replaces the letter, leaving room for "100%"
    } else {
        draw_text(f, &lv_font_silkscreen_bold_8, x, 31, 0, LV_TEXT_ALIGN_LEFT, ink, text);
    }

    if (level < 0) {
        strcpy(text, "--");
    } else {
        snprintf(text, sizeof(text), "%d%%", level);
    }
    draw_text(f, &lv_font_silkscreen_8, x, 31, 0, LV_TEXT_ALIGN_RIGHT, ink, text);

    for (int i = 0; i < 10; i++) {
        bool on = level >= 0 && i < (level + 5) / 10;
        fill(f, x + i * 3, on ? 8 : 11, 2, on ? 4 : 1, ink);
    }
}

static void draw_slots(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;

    if (state->selected_endpoint.transport == ZMK_TRANSPORT_USB) {
        fill(f, 0, 34, SCREEN_W, 12, ink);
        draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 38, LV_TEXT_ALIGN_CENTER, paper,
                  "USB");
        return;
    }

    for (int i = 0; i < NICEVIEW_PROFILE_COUNT; i++) {
        int x = 1 + i * 13, y = 34;
        bool active = i == state->active_profile_index;
        bool solid = active && state->profiles_connected[i];
        char digit[2] = {'1' + i, '\0'};

        if (solid) {
            fill(f, x, y, 12, 12, ink);
        } else if (active) {
            // selected but not connected yet: double outline
            outline(f, x, y, 12, 12, ink);
            outline(f, x + 1, y + 1, 10, 10, ink);
        } else if (state->profiles_connected[i]) {
            outline(f, x, y, 12, 12, ink);
        } else if (state->profiles_bonded[i]) {
            dashed_square(f, x, y, 12, ink);
        }
        const struct glyph *icon = i < ARRAY_SIZE(slot_icons) ? slot_icons[i] : NULL;
        if (icon != NULL) {
            draw_glyph(f, x + (12 - icon->w) / 2, y + (12 - icon->h) / 2, icon,
                       solid ? paper : ink);
        } else {
            draw_text(f, &lv_font_silkscreen_bold_8, x, 12, y + 3, LV_TEXT_ALIGN_CENTER,
                      solid ? paper : ink, digit);
        }
    }
}

static void draw_badges(const struct frame *f, const struct status_state *state) {
    static const struct {
        const struct glyph *glyph;
        uint8_t mods;
    } badges[] = {
        {&glyph_cmd, MOD_LGUI | MOD_RGUI},  {&glyph_opt, MOD_LALT | MOD_RALT},
        {&glyph_ctrl, MOD_LCTL | MOD_RCTL}, {&glyph_shift, MOD_LSFT | MOD_RSFT},
        {&glyph_claude, 0},
    };
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;

    for (int i = 0; i < ARRAY_SIZE(badges); i++) {
        const struct glyph *g = badges[i].glyph;
        int x = i * 14;
        bool on = badges[i].mods ? (state->mods & badges[i].mods) != 0
                                 : (state->agent == AGENT_WORKING || state->agent == AGENT_NEEDS);

        if (on) {
            fill(f, x, 50, 12, 13, ink);
        } else {
            outline(f, x, 50, 12, 13, ink);
        }
        draw_glyph(f, x + (12 - g->w) / 2, 50 + (13 - g->h) / 2, g, on ? paper : ink);
    }
}

static void draw_status(lv_obj_t *widget, struct zmk_widget_status *w) {
    const struct status_state *state = &w->state;
    struct frame f = frame_for(widget, w, 0);
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    char layer[12];

    fill(&f, 0, 0, CANVAS_SIZE, CANVAS_SIZE, paper);

    draw_battery_column(&f, 0, 'L', state->battery, state->charging);
    draw_battery_column(&f, 36, 'R', state->peripheral_battery, false);

    if (state->layer_label != NULL && state->layer_label[0] != '\0') {
        snprintf(layer, sizeof(layer), "%s", state->layer_label);
    } else {
        snprintf(layer, sizeof(layer), "LAYER %d", state->layer_index);
    }
    fill(&f, 0, 15, SCREEN_W, 16, ink);
    draw_text(&f, &lv_font_jersey_1x, 0, SCREEN_W, 18, LV_TEXT_ALIGN_CENTER, paper, layer);

    draw_slots(&f, state);
    draw_badges(&f, state);
    fill(&f, 0, 65, SCREEN_W, 1, ink);

    rotate_canvas(f.canvas, f.buf);
}

/* ---------------------------------------------------------------------------------------------
 * WPM module (middle and bottom canvases)
 */

// The WPM header, or a Claude Code banner while Claude needs you (solid) or has finished (outlined).
static void draw_agent_header(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    char number[4];

    if (state->agent == AGENT_NEEDS || state->agent == AGENT_DONE) {
        bool solid = state->agent == AGENT_NEEDS;
        lv_color_t text = solid ? paper : ink;

        if (solid) {
            fill(f, 0, 67, SCREEN_W, 26, ink);
        } else {
            outline(f, 0, 67, SCREEN_W, 26, ink);
        }
        draw_text(f, &lv_font_jersey_1x, 0, SCREEN_W, 71, LV_TEXT_ALIGN_CENTER, text, "CLAUDE");
        draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 84, LV_TEXT_ALIGN_CENTER, text,
                  solid ? "NEEDS YOU" : "DONE");
        return;
    }

    draw_text(f, &lv_font_silkscreen_bold_8, 1, 30, 71, LV_TEXT_ALIGN_LEFT, ink, "WPM");
    snprintf(number, sizeof(number), "%d", state->wpm[WPM_HISTORY - 1]);
    draw_text(f, &lv_font_jersey_2x, 0, SCREEN_W, 71, LV_TEXT_ALIGN_RIGHT, ink, number);
}

static void draw_wpm_into(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    const uint8_t *hist = state->wpm;
    int hi = 10; // floor for the chart scale, so near-zero typing doesn't fill the chart
    int px[WPM_HISTORY], py[WPM_HISTORY];

    fill(f, 0, f->y0, CANVAS_SIZE, CANVAS_SIZE, paper);
    draw_agent_header(f, state);

    for (int i = 0; i < WPM_HISTORY; i++) {
        hi = MAX(hi, hist[i]);
    }
    for (int i = 0; i < WPM_HISTORY; i++) {
        px[i] = i * (SCREEN_W - 1) / (WPM_HISTORY - 1);
        py[i] = CHART_BOTTOM - hist[i] * (CHART_BOTTOM - CHART_TOP) / hi;
    }

    // checkerboard fill under the line, then the line itself
    for (int i = 0; i < WPM_HISTORY - 1; i++) {
        int x_end = px[i + 1] + (i == WPM_HISTORY - 2 ? 1 : 0);
        for (int x = px[i]; x < x_end; x++) {
            int y_line = py[i] + floor_div((py[i + 1] - py[i]) * (x - px[i]),
                                           MAX(1, px[i + 1] - px[i]));
            for (int y = y_line + 1; y <= CHART_BOTTOM; y++) {
                if ((x + y) % 2 == 0) {
                    put_px(f, x, y, ink);
                }
            }
        }
    }
    for (int i = 0; i < WPM_HISTORY - 1; i++) {
        draw_line(f, px[i], py[i], px[i + 1], py[i + 1], ink);
    }
    fill(f, 0, CHART_BOTTOM + 1, SCREEN_W, 1, ink);
}

static void draw_wpm(lv_obj_t *widget, struct zmk_widget_status *w) {
    for (int i = 1; i <= 2; i++) {
        struct frame f = frame_for(widget, w, i);
        draw_wpm_into(&f, &w->state);
        rotate_canvas(f.canvas, f.buf);
    }
}

/* ---------------------------------------------------------------------------------------------
 * State listeners
 */

static void battery_status_update_cb(struct battery_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
        widget->state.charging = state.usb_present;
#endif
        widget->state.battery = state.level;
        draw_status(widget->obj, widget);
    }
}

static struct battery_status_state battery_status_get_state(const zmk_event_t *eh) {
    const struct zmk_battery_state_changed *ev = eh ? as_zmk_battery_state_changed(eh) : NULL;

    return (struct battery_status_state){
        .level = (ev != NULL) ? ev->state_of_charge : zmk_battery_state_of_charge(),
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
        .usb_present = zmk_usb_is_powered(),
#endif /* IS_ENABLED(CONFIG_USB_DEVICE_STACK) */
    };
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_battery_status, struct battery_status_state,
                            battery_status_update_cb, battery_status_get_state)

ZMK_SUBSCRIPTION(widget_battery_status, zmk_battery_state_changed);
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
ZMK_SUBSCRIPTION(widget_battery_status, zmk_usb_conn_state_changed);
#endif /* IS_ENABLED(CONFIG_USB_DEVICE_STACK) */

static void peripheral_battery_update_cb(struct peripheral_battery_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        widget->state.peripheral_battery = state.level;
        draw_status(widget->obj, widget);
    }
}

static struct peripheral_battery_state peripheral_battery_get_state(const zmk_event_t *eh) {
    static int16_t level = -1;
#if IS_ENABLED(CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING)
    const struct zmk_peripheral_battery_state_changed *ev =
        eh ? as_zmk_peripheral_battery_state_changed(eh) : NULL;
    uint8_t fetched;

    if (ev != NULL) {
        if (ev->source == 0) {
            level = ev->state_of_charge;
        }
    } else if (zmk_split_central_get_peripheral_battery_level(0, &fetched) == 0) {
        level = fetched;
    }
#endif
    return (struct peripheral_battery_state){.level = level};
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_peripheral_battery, struct peripheral_battery_state,
                            peripheral_battery_update_cb, peripheral_battery_get_state)
#if IS_ENABLED(CONFIG_ZMK_SPLIT_BLE_CENTRAL_BATTERY_LEVEL_FETCHING)
ZMK_SUBSCRIPTION(widget_peripheral_battery, zmk_peripheral_battery_state_changed);
#endif

static void output_status_update_cb(struct output_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        widget->state.selected_endpoint = state.selected_endpoint;
        widget->state.active_profile_index = state.active_profile_index;
        widget->state.active_profile_connected = state.active_profile_connected;
        widget->state.active_profile_bonded = state.active_profile_bonded;
        for (int i = 0; i < NICEVIEW_PROFILE_COUNT; ++i) {
            widget->state.profiles_connected[i] = state.profiles_connected[i];
            widget->state.profiles_bonded[i] = state.profiles_bonded[i];
        }
        draw_status(widget->obj, widget);
    }
}

static struct output_status_state output_status_get_state(const zmk_event_t *_eh) {
    struct output_status_state state = {
        .selected_endpoint = zmk_endpoints_selected(),
        .active_profile_index = zmk_ble_active_profile_index(),
        .active_profile_connected = zmk_ble_active_profile_is_connected(),
        .active_profile_bonded = !zmk_ble_active_profile_is_open(),
    };
    for (int i = 0; i < MIN(NICEVIEW_PROFILE_COUNT, ZMK_BLE_PROFILE_COUNT); ++i) {
        state.profiles_connected[i] = zmk_ble_profile_is_connected(i);
        state.profiles_bonded[i] = !zmk_ble_profile_is_open(i);
    }
    return state;
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_output_status, struct output_status_state,
                            output_status_update_cb, output_status_get_state)
ZMK_SUBSCRIPTION(widget_output_status, zmk_endpoint_changed);

#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
ZMK_SUBSCRIPTION(widget_output_status, zmk_usb_conn_state_changed);
#endif
#if defined(CONFIG_ZMK_BLE)
ZMK_SUBSCRIPTION(widget_output_status, zmk_ble_active_profile_changed);
#endif

static void layer_status_update_cb(struct layer_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        widget->state.layer_index = state.index;
        widget->state.layer_label = state.label;
        draw_status(widget->obj, widget);
    }
}

static struct layer_status_state layer_status_get_state(const zmk_event_t *eh) {
    zmk_keymap_layer_index_t index = zmk_keymap_highest_layer_active();
    return (struct layer_status_state){
        .index = index, .label = zmk_keymap_layer_name(zmk_keymap_layer_index_to_id(index))};
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_layer_status, struct layer_status_state, layer_status_update_cb,
                            layer_status_get_state)

ZMK_SUBSCRIPTION(widget_layer_status, zmk_layer_state_changed);

static void mods_update_cb(struct mods_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        // this fires for every key press, so only redraw when a modifier actually changed
        if (widget->state.mods != state.mods) {
            widget->state.mods = state.mods;
            draw_status(widget->obj, widget);
        }
    }
}

// Track held modifier keys from key events. ZMK doesn't raise zmk_modifiers_state_changed, and
// reading the HID report here could race the HID listener handling the same event.
static struct mods_state mods_get_state(const zmk_event_t *eh) {
    static uint8_t held;
    const struct zmk_keycode_state_changed *ev = eh ? as_zmk_keycode_state_changed(eh) : NULL;

    if (ev != NULL && ev->usage_page == HID_USAGE_KEY &&
        ev->keycode >= HID_USAGE_KEY_KEYBOARD_LEFTCONTROL &&
        ev->keycode <= HID_USAGE_KEY_KEYBOARD_RIGHT_GUI) {
        uint8_t bit = BIT(ev->keycode - HID_USAGE_KEY_KEYBOARD_LEFTCONTROL);
        held = ev->state ? (held | bit) : (held & ~bit);
    }
    return (struct mods_state){.mods = held};
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_mods, struct mods_state, mods_update_cb, mods_get_state)
ZMK_SUBSCRIPTION(widget_mods, zmk_keycode_state_changed);

static void agent_update_cb(struct agent_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        if (widget->state.agent != state.agent) {
            widget->state.agent = state.agent;
            draw_status(widget->obj, widget); // badge
            draw_wpm(widget->obj, widget);    // banner
        }
    }
}

// host/sofle-status sends Claude Code's state in the Compose and Kana indicator lights.
static struct agent_state agent_get_state(const zmk_event_t *eh) {
#if IS_ENABLED(CONFIG_ZMK_HID_INDICATORS)
    zmk_hid_indicators_t leds = zmk_hid_indicators_get_current_profile();
    return (struct agent_state){
        .agent = ((leds & BIT(HID_USAGE_LED_COMPOSE - 1)) ? 1 : 0) |
                 ((leds & BIT(HID_USAGE_LED_KANA - 1)) ? 2 : 0),
    };
#else
    return (struct agent_state){.agent = AGENT_IDLE};
#endif
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_agent, struct agent_state, agent_update_cb, agent_get_state)
#if IS_ENABLED(CONFIG_ZMK_HID_INDICATORS)
ZMK_SUBSCRIPTION(widget_agent, zmk_hid_indicators_changed);
#endif

static void wpm_status_update_cb(struct wpm_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        memmove(widget->state.wpm, widget->state.wpm + 1, WPM_HISTORY - 1);
        widget->state.wpm[WPM_HISTORY - 1] = state.wpm;
        draw_wpm(widget->obj, widget);
    }
}

struct wpm_status_state wpm_status_get_state(const zmk_event_t *eh) {
    return (struct wpm_status_state){.wpm = zmk_wpm_get_state()};
};

ZMK_DISPLAY_WIDGET_LISTENER(widget_wpm_status, struct wpm_status_state, wpm_status_update_cb,
                            wpm_status_get_state)
ZMK_SUBSCRIPTION(widget_wpm_status, zmk_wpm_state_changed);

int zmk_widget_status_init(struct zmk_widget_status *widget, lv_obj_t *parent) {
    widget->obj = lv_obj_create(parent);
    lv_obj_set_size(widget->obj, 160, 68);
    lv_obj_t *top = lv_canvas_create(widget->obj);
    lv_obj_align(top, LV_ALIGN_TOP_RIGHT, 0, 0);
    lv_canvas_set_buffer(top, widget->cbuf, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    lv_obj_t *middle = lv_canvas_create(widget->obj);
    lv_obj_align(middle, LV_ALIGN_TOP_LEFT, 24, 0);
    lv_canvas_set_buffer(middle, widget->cbuf2, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
    lv_obj_t *bottom = lv_canvas_create(widget->obj);
    lv_obj_align(bottom, LV_ALIGN_TOP_LEFT, -44, 0);
    lv_canvas_set_buffer(bottom, widget->cbuf3, CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);

    widget->state.peripheral_battery = -1;

    sys_slist_append(&widgets, &widget->node);
    widget_battery_status_init();
    widget_peripheral_battery_init();
    widget_output_status_init();
    widget_layer_status_init();
    widget_mods_init();
    widget_agent_init();
    widget_wpm_status_init();

    return 0;
}

lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget) { return widget->obj; }
