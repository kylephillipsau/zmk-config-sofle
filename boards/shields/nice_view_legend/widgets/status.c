/*
 *
 * Copyright (c) 2025 The ZMK Contributors
 * SPDX-License-Identifier: MIT
 *
 * Left (central) screen: a status area (both batteries, layer, Bluetooth slots, held modifiers,
 * Claude Code badge) above the clock, WPM, and either a card fed by host/sofle-status (Claude
 * usage limits and CI for recent repos) or, when nothing is feeding it, a live WPM chart. The layout mirrors spec_left() and spec_usage_ci() in
 * art/concepts.py, and the fonts and icons are generated from the same sources, so the mockups
 * match the device.
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
#include "host_link.h"
#include "host_link_ble.h"
#include "crash.h"
#include "draw.h"
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

#define USAGE_Y 108 // capitals of the first usage row; rows are 14 px apart
#define REPOS_Y 139 // capitals of the first repo row; rows are 7 px apart
#define CHART_TOP 106
#define CHART_BOTTOM 156

// The host resends every card every 10 minutes, so a card older than this has lost its feed.
#define CARD_STALE_MS (15 * 60 * 1000)

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

struct host_state {
    uint8_t agent;
    int32_t clock_base_s;
    int64_t clock_sync_ms;
    struct host_card card;
    int64_t card_ms;
    struct zmk_endpoint_instance card_endpoint;
};

/* ---------------------------------------------------------------------------------------------
 * Drawing in portrait coordinates: struct frame and the helpers in draw.h.
 */

static void dashed_square(const struct frame *f, int x, int y, int size, lv_color_t c) {
    for (int k = 0; k < size; k += 2) {
        put_px(f, x + k, y, c);
        put_px(f, x + k, y + size - 1, c);
        put_px(f, x, y + k, c);
        put_px(f, x + size - 1, y + k, c);
    }
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

// Word-wrap text into two lines of w px: whole words on the first line (a word too long for it is
// cut there), the rest on the second, ending on a whole word if it has to be cut. Mirrors
// lv_wrap() in art/concepts.py, which expects single spaces between words.
static void wrap_text(const lv_font_t *font, const char *text, int w, char *line1, char *line2,
                      size_t size) {
    const char *rest;
    size_t first = strcspn(text, " ");

    line1[0] = line2[0] = '\0';
    if (!text_fits(font, text, first, w)) {
        char word[HOST_EVENT_TITLE + 1];
        snprintf(word, MIN(sizeof(word), first + 1), "%s", text);
        fit_text(font, word, w, line1, size);
        rest = text + strlen(line1);
    } else {
        size_t len = first;
        while (text[len] == ' ') {
            size_t next = len + 1 + strcspn(text + len + 1, " ");
            if (!text_fits(font, text, next, w)) {
                break;
            }
            len = next;
        }
        snprintf(line1, MIN(size, len + 1), "%s", text);
        rest = text + len + (text[len] == ' ' ? 1 : 0);
    }

    fit_text(font, rest, w, line2, size);
    size_t n = strlen(line2);
    char *space = strrchr(line2, ' ');
    if (n < strlen(rest) && space != NULL && rest[n] != ' ') {
        *space = '\0'; // end on a whole word rather than a fragment
    }
    for (n = strlen(line2); n > 0 && line2[n - 1] == ' '; n--) {
        line2[n - 1] = '\0';
    }
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
                                 : (state->agent & (AGENT_WORKING | AGENT_NEEDS)) != 0;

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
 * Module (middle and bottom canvases): clock, WPM and the card
 */

// Big time of day in the module header. The keyboard keeps time from the last sync with the host.
static void draw_clock(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND;
    char text[8];

    if (state->clock_base_s < 0) {
        draw_text(f, &lv_font_jersey_2x, 0, SCREEN_W, 71, LV_TEXT_ALIGN_LEFT, ink, "--:--");
        return;
    }

    int64_t now_s = state->clock_base_s + (k_uptime_get() - state->clock_sync_ms) / 1000;
    int minute_of_day = (int)((now_s / 60) % (24 * 60));
    int hour = minute_of_day / 60, minute = minute_of_day % 60;

    // The widest times ("12:22", "22:22") need the full width, so AM/PM sits in the row below.
#if IS_ENABLED(CONFIG_NICE_VIEW_LEGEND_CLOCK_24H)
    snprintf(text, sizeof(text), "%d:%02d", hour, minute);
#else
    snprintf(text, sizeof(text), "%d:%02d", hour % 12 == 0 ? 12 : hour % 12, minute);
#endif
    draw_text(f, &lv_font_jersey_2x, 0, SCREEN_W, 71, LV_TEXT_ALIGN_LEFT, ink, text);
}

// The small row under the clock: "WPM 61" on the left, AM/PM on the right.
static void draw_wpm_label(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND;
    char number[4];

    draw_text(f, &lv_font_silkscreen_8, 1, 30, 97, LV_TEXT_ALIGN_LEFT, ink, "WPM");
    snprintf(number, sizeof(number), "%d", state->wpm[WPM_HISTORY - 1]);
    draw_text(f, &lv_font_silkscreen_bold_8, 22, 30, 97, LV_TEXT_ALIGN_LEFT, ink, number);

#if !IS_ENABLED(CONFIG_NICE_VIEW_LEGEND_CLOCK_24H)
    if (state->clock_base_s >= 0) {
        int64_t now_s = state->clock_base_s + (k_uptime_get() - state->clock_sync_ms) / 1000;
        int hour = (int)((now_s / 3600) % 24);
        draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 97, LV_TEXT_ALIGN_RIGHT, ink,
                  hour < 12 ? "AM" : "PM");
    }
#endif
}

// One usage limit: name, percent used and when it resets, over a bar filled to the percent.
static void draw_usage_row(const struct frame *f, int y, const char *name,
                           const struct host_usage *u) {
    lv_color_t ink = LVGL_FOREGROUND;
    char text[6];

    draw_text(f, &lv_font_silkscreen_bold_8, 1, 14, y, LV_TEXT_ALIGN_LEFT, ink, name);
    if (u->pct == HOST_PCT_UNKNOWN) {
        draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, y, LV_TEXT_ALIGN_RIGHT, ink, "--");
        return;
    }
    int pct = MIN(u->pct, 100);
    const char *label = u->label;
    if (u->reset_ms != 0 && k_uptime_get() >= u->reset_ms) {
        pct = 0; // the limit has reset since the host last said
        label = "";
    }
    // at 100% the reset time matters most, and "100%" would run into a time like 12:55
    if (pct >= 100) {
        snprintf(text, sizeof(text), "MAX");
    } else {
        snprintf(text, sizeof(text), "%d%%", pct);
    }
    draw_text(f, &lv_font_silkscreen_bold_8, 16, 24, y, LV_TEXT_ALIGN_LEFT, ink, text);
    if (label[0] != '\0') {
        draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, y, LV_TEXT_ALIGN_RIGHT, ink, label);
    }
    outline(f, 0, y + 7, SCREEN_W, 4, ink);
    if (pct > 0) {
        fill(f, 0, y + 7, (SCREEN_W - 1) * pct / 100 + 1, 4, ink);
    }
}

// The next event, over the repo rows: a bar with how soon it starts and when, then its title.
static void draw_event(const struct frame *f, const struct host_event *e) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    char when[8], line1[HOST_EVENT_TITLE + 1], line2[HOST_EVENT_TITLE + 1];
    int64_t until_start = e->start_ms - k_uptime_get();

    if (until_start > 0) {
        snprintf(when, sizeof(when), "IN %dM", (int)((until_start + 59999) / 60000));
    } else {
        snprintf(when, sizeof(when), "NOW");
    }
    fill(f, 0, 136, SCREEN_W, 10, ink);
    draw_text(f, &lv_font_silkscreen_bold_8, 1, 40, 139, LV_TEXT_ALIGN_LEFT, paper, when);
    draw_text(f, &lv_font_silkscreen_8, 40, SCREEN_W - 41, 139, LV_TEXT_ALIGN_RIGHT, paper,
              e->label);
    wrap_text(&lv_font_silkscreen_8, e->title, SCREEN_W - 2, line1, line2, sizeof(line1));
    draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 148, LV_TEXT_ALIGN_LEFT, ink, line1);
    if (line2[0] != '\0') {
        draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 155, LV_TEXT_ALIGN_LEFT, ink, line2);
    }
}

static bool event_showing(const struct host_event *e) {
    int64_t now = k_uptime_get();
    return e->set && now >= e->from_ms && now < e->until_ms;
}

// The card under the clock: Claude's 5 hour and weekly limits, then CI for 3 recent repos, or the
// next event while it's close.
static void draw_card(const struct frame *f, const struct status_state *state) {
    static const struct glyph *const ci_glyphs[] = {
        [HOST_CI_OK] = &glyph_ci_ok,
        [HOST_CI_FAIL] = &glyph_ci_fail,
        [HOST_CI_RUNNING] = &glyph_ci_running,
    };
    static const char *const usage_names[HOST_USAGE_ROWS] = {"5H", "WK"};
    const struct host_card *card = &state->card;
    lv_color_t ink = LVGL_FOREGROUND;
    char name[HOST_REPO_NAME + 1];

    fill(f, 0, 104, SCREEN_W, 1, ink);
    for (int i = 0; i < HOST_USAGE_ROWS; i++) {
        draw_usage_row(f, USAGE_Y + i * 14, usage_names[i], &card->usage[i]);
    }

    fill(f, 0, 135, SCREEN_W, 1, ink);
    if (event_showing(&card->event)) {
        draw_event(f, &card->event);
        return;
    }
    for (int i = 0; i < HOST_REPO_ROWS; i++) {
        const struct host_repo *repo = &card->repos[i];
        int y = REPOS_Y + i * 7;
        if (repo->name[0] != '\0') {
            fit_text(&lv_font_silkscreen_8, repo->name, 58, name, sizeof(name));
            draw_text(f, &lv_font_silkscreen_8, 1, 58, y, LV_TEXT_ALIGN_LEFT, ink, name);
        }
        const struct glyph *g = repo->ci < ARRAY_SIZE(ci_glyphs) ? ci_glyphs[repo->ci] : NULL;
        if (g != NULL) {
            draw_glyph(f, SCREEN_W - 1 - g->w, y, g, ink);
        }
    }
}

// Live WPM over the last 30 changes, when there's no card to show.
static void draw_chart(const struct frame *f, const struct status_state *state) {
    lv_color_t ink = LVGL_FOREGROUND;
    const uint8_t *hist = state->wpm;
    int hi = 10; // floor for the chart scale, so near-zero typing doesn't fill the chart
    int px[WPM_HISTORY], py[WPM_HISTORY];

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

// The card shows while sofle-status is feeding it: a frame arrived recently, from the endpoint the
// keyboard is using now. On another device, or once the Mac goes quiet, the WPM chart is back.
static bool card_live(const struct status_state *state) {
    return state->card_ms != 0 && k_uptime_get() - state->card_ms < CARD_STALE_MS &&
           zmk_endpoint_instance_eq(state->card_endpoint, state->selected_endpoint);
}

// After a crash and reboot: what crashed, where, for a few minutes in place of the card.
static void draw_crash(const struct frame *f, const struct crash_record *c) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    char text[24], name[sizeof(c->thread) + 1];

    fill(f, 0, 104, SCREEN_W, 11, ink);
    draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 107, LV_TEXT_ALIGN_CENTER, paper, "CRASHED");
    snprintf(text, sizeof(text), "WHY %u  #%u", c->reason, c->count);
    draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 119, LV_TEXT_ALIGN_LEFT, ink, text);
    snprintf(text, sizeof(text), "PC %08X", c->pc);
    draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 128, LV_TEXT_ALIGN_LEFT, ink, text);
    snprintf(text, sizeof(text), "LR %08X", c->lr);
    draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 137, LV_TEXT_ALIGN_LEFT, ink, text);
    fit_text(&lv_font_silkscreen_8, c->thread, SCREEN_W - 2, name, sizeof(name));
    draw_text(f, &lv_font_silkscreen_8, 1, SCREEN_W - 2, 146, LV_TEXT_ALIGN_LEFT, ink, name);
}

static void draw_module_into(const struct frame *f, const struct status_state *state) {
    const struct crash_record *crash = crash_last();
    fill(f, 0, f->y0, CANVAS_SIZE, CANVAS_SIZE, LVGL_BACKGROUND);
    draw_clock(f, state);
    draw_wpm_label(f, state);
    if (crash != NULL && k_uptime_get() < CRASH_SHOW_MS) {
        draw_crash(f, crash);
        return;
    }
    if (crash != NULL) {
        crash_forget();
    }
    if (card_live(state)) {
        draw_card(f, state);
    } else {
        draw_chart(f, state);
    }
}

static void draw_module(lv_obj_t *widget, struct zmk_widget_status *w) {
    for (int i = 1; i <= 2; i++) {
        struct frame f = frame_for(widget, w, i);
        draw_module_into(&f, &w->state);
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
        draw_module(widget->obj, widget); // the card belongs to the endpoint that sent it
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

// Redraw the clock at each minute boundary once it has been synced.
static void clock_tick(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(clock_tick_work, clock_tick);

static void schedule_clock_tick(const struct status_state *state) {
    if (state->clock_base_s < 0) {
        return;
    }
    int64_t now_ms = (int64_t)state->clock_base_s * 1000 + (k_uptime_get() - state->clock_sync_ms);
    int64_t until_next_minute = 60000 - (now_ms % 60000);
    k_work_schedule_for_queue(zmk_display_work_q(), &clock_tick_work,
                              K_MSEC(until_next_minute + 20));
}

static void clock_tick(struct k_work *work) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        draw_module(widget->obj, widget);
        schedule_clock_tick(&widget->state);
    }
}

static void host_update_cb(struct host_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        bool agent_changed = widget->state.agent != state.agent;
        bool clock_changed = widget->state.clock_sync_ms != state.clock_sync_ms ||
                             widget->state.clock_base_s != state.clock_base_s;
        bool card_changed = memcmp(&widget->state.card, &state.card, sizeof(state.card)) != 0 ||
                            widget->state.card_ms != state.card_ms ||
                            !zmk_endpoint_instance_eq(widget->state.card_endpoint,
                                                      state.card_endpoint);
        if (!agent_changed && !clock_changed && !card_changed) {
            continue;
        }
        widget->state.agent = state.agent;
        widget->state.clock_base_s = state.clock_base_s;
        widget->state.clock_sync_ms = state.clock_sync_ms;
        widget->state.card = state.card;
        widget->state.card_ms = state.card_ms;
        widget->state.card_endpoint = state.card_endpoint;
        if (agent_changed) {
            draw_status(widget->obj, widget); // badge
        }
        if (clock_changed || card_changed) {
            draw_module(widget->obj, widget);
        }
        if (clock_changed) {
            schedule_clock_tick(&widget->state);
        }
    }
}

// host/sofle-status sends Claude Code's flags, the time and the card in indicator lights macOS
// doesn't use (see host_link.h). Caps Lock is masked out, so it never disturbs them.
static struct host_state host_get_state(const zmk_event_t *eh) {
    static struct host_link link;
    static bool initialized;
    static int64_t seen_frame_ms;
    static struct zmk_endpoint_instance frame_endpoint; // where the last frame came from
    if (!initialized) {
        host_link_init(&link);
        initialized = true;
    }
#if IS_ENABLED(CONFIG_ZMK_HID_INDICATORS)
    zmk_hid_indicators_t leds = zmk_hid_indicators_get_current_profile();
#if IS_ENABLED(CONFIG_ZMK_BLE)
    if (leds & HOST_LED_NUM) {
        host_link_ble_frame_report();
    }
#endif
    host_link_feed(&link, leds, k_uptime_get());
#endif
    if (link.last_frame_ms != seen_frame_ms) {
        seen_frame_ms = link.last_frame_ms;
        frame_endpoint = zmk_endpoints_selected();
    }
    return (struct host_state){.agent = link.agent,
                               .clock_base_s = link.clock_base_s,
                               .clock_sync_ms = link.clock_sync_ms,
                               .card = link.card,
                               .card_ms = link.last_frame_ms,
                               .card_endpoint = frame_endpoint};
}

ZMK_DISPLAY_WIDGET_LISTENER(widget_host, struct host_state, host_update_cb, host_get_state)
#if IS_ENABLED(CONFIG_ZMK_HID_INDICATORS)
ZMK_SUBSCRIPTION(widget_host, zmk_hid_indicators_changed);
#endif

static void wpm_status_update_cb(struct wpm_status_state state) {
    struct zmk_widget_status *widget;
    SYS_SLIST_FOR_EACH_CONTAINER(&widgets, widget, node) {
        memmove(widget->state.wpm, widget->state.wpm + 1, WPM_HISTORY - 1);
        widget->state.wpm[WPM_HISTORY - 1] = state.wpm;
        draw_module(widget->obj, widget);
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
    widget->state.clock_base_s = -1;
    for (int i = 0; i < HOST_USAGE_ROWS; i++) {
        widget->state.card.usage[i].pct = HOST_PCT_UNKNOWN;
    }

    sys_slist_append(&widgets, &widget->node);
    widget_battery_status_init();
    widget_peripheral_battery_init();
    widget_output_status_init();
    widget_layer_status_init();
    widget_mods_init();
    widget_host_init();
    widget_wpm_status_init();

    return 0;
}

lv_obj_t *zmk_widget_status_obj(struct zmk_widget_status *widget) { return widget->obj; }
