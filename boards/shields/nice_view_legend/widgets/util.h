/*
 *
 * Copyright (c) 2025 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 */

#include <lvgl.h>
#include <zmk/endpoints.h>

#define NICEVIEW_PROFILE_COUNT 5
#define WPM_HISTORY 30

#define CANVAS_SIZE 68

#define LVGL_BACKGROUND                                                                            \
    IS_ENABLED(CONFIG_NICE_VIEW_WIDGET_INVERTED) ? lv_color_black() : lv_color_white()
#define LVGL_FOREGROUND                                                                            \
    IS_ENABLED(CONFIG_NICE_VIEW_WIDGET_INVERTED) ? lv_color_white() : lv_color_black()

struct status_state {
    uint8_t battery;
    bool charging;
#if !IS_ENABLED(CONFIG_ZMK_SPLIT) || IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)
    struct zmk_endpoint_instance selected_endpoint;
    int active_profile_index;
    bool active_profile_connected;
    bool active_profile_bonded;
    bool profiles_connected[NICEVIEW_PROFILE_COUNT];
    bool profiles_bonded[NICEVIEW_PROFILE_COUNT];
    uint8_t layer_index;
    const char *layer_label;
    uint8_t wpm[WPM_HISTORY];
    int16_t peripheral_battery; // -1 until the right half reports its level
    uint8_t mods;               // held modifier keys, MOD_* bits
    uint8_t agent;              // Claude Code flags from the host, AGENT_* below
    int32_t clock_base_s;       // host time of day in seconds at clock_sync_ms, or -1 if unknown
    int64_t clock_sync_ms;
#else
    bool connected;
#endif
};

// Claude Code flags, summed over every session by host/sofle-status and sent in indicator lights
// macOS doesn't use: Scroll Lock, Compose and Kana.
#define AGENT_WORKING BIT(0) // some session is working
#define AGENT_NEEDS BIT(1)   // some session needs you
#define AGENT_DONE BIT(2)    // a session finished since your last prompt

struct battery_status_state {
    uint8_t level;
#if IS_ENABLED(CONFIG_USB_DEVICE_STACK)
    bool usb_present;
#endif
};

void rotate_canvas(lv_obj_t *canvas, lv_color_t cbuf[]);
void draw_battery(lv_obj_t *canvas, const struct status_state *state);
void init_label_dsc(lv_draw_label_dsc_t *label_dsc, lv_color_t color, const lv_font_t *font,
                    lv_text_align_t align);
void init_rect_dsc(lv_draw_rect_dsc_t *rect_dsc, lv_color_t bg_color);
void init_line_dsc(lv_draw_line_dsc_t *line_dsc, lv_color_t color, uint8_t width);
void init_arc_dsc(lv_draw_arc_dsc_t *arc_dsc, lv_color_t color, uint8_t width);
