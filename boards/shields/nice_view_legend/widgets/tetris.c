/*
 * SPDX-License-Identifier: MIT
 *
 * Tetris on the right screen while the GAME layer is on, played with the joystick, which is on
 * this half: left and right move, up rotates, down drops faster, and pressing it drops at once.
 * The rules are in tetris_game.c; this file draws them (mirroring spec_tetris*() in
 * art/concepts.py) and drives them.
 *
 * Everything runs on the display work queue: key events only queue an input, and gravity and
 * auto-repeat are delayable work on the same queue, so the game state has one thread.
 */

#include <stdio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/random/random.h>
#include <zephyr/settings/settings.h>
#include <zmk/display.h>
#include <zmk/event_manager.h>
#include <zmk/events/position_state_changed.h>

#include "draw.h"
#include "tetris.h"
#include "tetris_game.h"
#include "util.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

LV_FONT_DECLARE(lv_font_silkscreen_8);
LV_FONT_DECLARE(lv_font_silkscreen_bold_8);
LV_FONT_DECLARE(lv_font_jersey_1x);

// Joystick key positions in the keymap (the middle column, which is this half's column 0)
#define POS_UP 6
#define POS_DOWN 19
#define POS_LEFT 32
#define POS_RIGHT 45
#define POS_PRESS 58

#define REPEAT_DELAY_MS 170 // holding left or right: first repeat after this...
#define REPEAT_MS 50        // ...then this often
#define SOFT_DROP_MS 50     // holding down

#define SCREEN_W 68
#define WELL_X 3 // portrait coordinates of the well's border, as in art/concepts.py
#define WELL_Y 38
#define CELL 6

enum stick { STICK_UP = BIT(0), STICK_DOWN = BIT(1), STICK_LEFT = BIT(2), STICK_RIGHT = BIT(3), STICK_PRESS = BIT(4) };

struct input {
    uint8_t stick; // enum stick
    bool pressed;
};

K_MSGQ_DEFINE(input_q, sizeof(struct input), 16, 1);

static struct tetris game;
static bool started;            // game initialised
static volatile bool active;    // GAME layer on and the game on screen
static uint8_t held;            // enum stick bits held down
static bool await_release;      // after a game over, until the stick is let go
static uint32_t best_saved;     // best score in settings
static uint32_t best_at_start;  // best before this game, to spot a new one

static lv_obj_t *canvases[3];
static lv_obj_t *legend_art;
static lv_color_t bufs[3][CANVAS_SIZE * CANVAS_SIZE];
static const int canvas_y0[3] = {20, 88, 156}; // portrait rows of each canvas: the art area

/* ---------------------------------------------------------------------------------------------
 * Best score in settings
 */

static int tetris_settings_set(const char *name, size_t len, settings_read_cb read_cb,
                               void *cb_arg) {
    if (settings_name_steq(name, "best", NULL) && len == sizeof(best_saved)) {
        int rc = read_cb(cb_arg, &best_saved, sizeof(best_saved));
        return rc < 0 ? rc : 0;
    }
    return -ENOENT;
}

SETTINGS_STATIC_HANDLER_DEFINE(tetris, "tetris", NULL, tetris_settings_set, NULL, NULL);

static void save_best(void) {
    if (game.best > best_saved) {
        best_saved = game.best;
        settings_save_one("tetris/best", &best_saved, sizeof(best_saved));
    }
}

/* ---------------------------------------------------------------------------------------------
 * Drawing
 */

enum block_style { BLOCK_SOLID, BLOCK_HOLLOW, BLOCK_GHOST };

static void draw_block(const struct frame *f, int x, int y, enum block_style style) {
    lv_color_t ink = LVGL_FOREGROUND;
    switch (style) {
    case BLOCK_SOLID:
        fill(f, x, y, 5, 5, ink);
        break;
    case BLOCK_HOLLOW:
        outline(f, x, y, 5, 5, ink);
        put_px(f, x + 2, y + 2, ink);
        break;
    case BLOCK_GHOST:
        put_px(f, x, y, ink);
        put_px(f, x + 4, y, ink);
        put_px(f, x, y + 4, ink);
        put_px(f, x + 4, y + 4, ink);
        put_px(f, x + 2, y + 2, ink);
        break;
    }
}

static void draw_cell(const struct frame *f, int column, int row, enum block_style style) {
    draw_block(f, WELL_X + 1 + column * CELL, WELL_Y + 1 + row * CELL, style);
}

static void draw_piece(const struct frame *f, int x, int y, enum block_style style) {
    struct tetris_cell cells[4];
    tetris_cells(game.piece, game.rot, cells);
    for (int i = 0; i < 4; i++) {
        draw_cell(f, x + cells[i].x, y + cells[i].y, style);
    }
}

static void draw_well(const struct frame *f) {
    outline(f, WELL_X, WELL_Y, TETRIS_W * CELL + 2, TETRIS_H * CELL + 2, LVGL_FOREGROUND);
}

static void draw_title(const struct frame *f) {
    static const struct { uint8_t c, r, piece; } stack[] = {{1, 0, TETRIS_T}, {5, 1, TETRIS_S}, {2, 2, TETRIS_L}};
    lv_color_t ink = LVGL_FOREGROUND;
    char best[12];

    draw_well(f);
    draw_text(f, &lv_font_jersey_1x, 0, SCREEN_W, 54, LV_TEXT_ALIGN_CENTER, ink, "TETRIS");
    for (unsigned i = 0; i < ARRAY_SIZE(stack); i++) {
        struct tetris_cell cells[4];
        tetris_cells(stack[i].piece, 0, cells);
        for (int k = 0; k < 4; k++) {
            draw_block(f, 10 + (stack[i].c + cells[k].x) * CELL, 72 + (stack[i].r + cells[k].y) * CELL,
                       BLOCK_HOLLOW);
        }
    }
    snprintf(best, sizeof(best), "%u", game.best);
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 100, LV_TEXT_ALIGN_CENTER, ink, "BEST");
    draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 109, LV_TEXT_ALIGN_CENTER, ink, best);
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 126, LV_TEXT_ALIGN_CENTER, ink, "PRESS THE");
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 134, LV_TEXT_ALIGN_CENTER, ink, "STICK");
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 147, LV_TEXT_ALIGN_CENTER, ink, "ESC TO QUIT");
}

static void draw_play(const struct frame *f) {
    lv_color_t ink = LVGL_FOREGROUND;
    char text[12];
    struct tetris_cell next[4];

    snprintf(text, sizeof(text), "%u", game.score);
    draw_text(f, &lv_font_silkscreen_bold_8, 1, 44, 23, LV_TEXT_ALIGN_LEFT, ink, text);
    snprintf(text, sizeof(text), "LEVEL %u", game.level);
    draw_text(f, &lv_font_silkscreen_8, 1, 44, 31, LV_TEXT_ALIGN_LEFT, ink, text);
    tetris_cells(game.next, 0, next);
    for (int i = 0; i < 4; i++) {
        fill(f, 48 + next[i].x * 4, 24 + next[i].y * 4, 3, 3, ink);
    }

    draw_well(f);
    for (int r = 0; r < TETRIS_H; r++) {
        for (int c = 0; c < TETRIS_W; c++) {
            if (game.rows[r] & BIT(c)) {
                draw_cell(f, c, r, BLOCK_HOLLOW);
            }
        }
    }
    if (game.state == TETRIS_PLAYING) {
        draw_piece(f, game.x, tetris_ghost_y(&game), BLOCK_GHOST);
        draw_piece(f, game.x, game.y, BLOCK_SOLID);
    }
}

static void draw_over(const struct frame *f) {
    lv_color_t ink = LVGL_FOREGROUND, paper = LVGL_BACKGROUND;
    char text[16];

    draw_play(f);
    fill(f, 0, 66, SCREEN_W, 60, paper);
    outline(f, 0, 66, SCREEN_W, 60, ink);
    fill(f, 0, 66, SCREEN_W, 12, ink);
    draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 70, LV_TEXT_ALIGN_CENTER, paper, "GAME OVER");
    snprintf(text, sizeof(text), "%u", game.score);
    draw_text(f, &lv_font_silkscreen_bold_8, 0, SCREEN_W, 83, LV_TEXT_ALIGN_CENTER, ink, text);
    if (game.score > best_at_start) {
        snprintf(text, sizeof(text), "NEW BEST");
    } else {
        snprintf(text, sizeof(text), "BEST %u", game.best);
    }
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 92, LV_TEXT_ALIGN_CENTER, ink, text);
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 107, LV_TEXT_ALIGN_CENTER, ink, "PRESS TO");
    draw_text(f, &lv_font_silkscreen_8, 0, SCREEN_W, 115, LV_TEXT_ALIGN_CENTER, ink, "PLAY AGAIN");
}

static void redraw(void) {
    for (int i = 0; i < 3; i++) {
        struct frame f = {.canvas = canvases[i], .buf = bufs[i], .y0 = canvas_y0[i]};
        fill(&f, 0, f.y0, CANVAS_SIZE, CANVAS_SIZE, LVGL_BACKGROUND);
        switch (game.state) {
        case TETRIS_TITLE:
            draw_title(&f);
            break;
        case TETRIS_PLAYING:
            draw_play(&f);
            break;
        case TETRIS_OVER:
            draw_over(&f);
            break;
        }
        rotate_canvas(f.canvas, f.buf);
    }
}

/* ---------------------------------------------------------------------------------------------
 * Driving the game
 */

static void gravity(struct k_work *work);
static void repeat(struct k_work *work);
static void handle_input(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(gravity_work, gravity);
static K_WORK_DELAYABLE_DEFINE(repeat_work, repeat);
static K_WORK_DEFINE(input_work, handle_input);

static void schedule_gravity(void) {
    k_work_reschedule_for_queue(zmk_display_work_q(), &gravity_work, K_MSEC(tetris_tick_ms(&game)));
}

// After a move: a lock gives the next piece a full tick, a game over saves the best score.
static void after(enum tetris_step step) {
    if (step == TETRIS_LOCKED) {
        schedule_gravity();
    } else if (step == TETRIS_GAME_OVER) {
        k_work_cancel_delayable(&gravity_work);
        k_work_cancel_delayable(&repeat_work);
        await_release = held != 0;
        save_best();
    }
    redraw();
}

static void gravity(struct k_work *work) {
    if (!active || game.state != TETRIS_PLAYING) {
        return;
    }
    enum tetris_step step = tetris_tick(&game);
    if (step == TETRIS_MOVED) {
        schedule_gravity();
    }
    after(step);
}

// Held left, right or down keeps moving the piece.
static void repeat(struct k_work *work) {
    if (!active || game.state != TETRIS_PLAYING) {
        return;
    }
    if (held & (STICK_LEFT | STICK_RIGHT)) {
        tetris_shift(&game, (held & STICK_LEFT) ? -1 : 1);
        k_work_reschedule_for_queue(zmk_display_work_q(), &repeat_work, K_MSEC(REPEAT_MS));
        redraw();
    } else if (held & STICK_DOWN) {
        enum tetris_step step = tetris_soft_drop(&game);
        if (step != TETRIS_GAME_OVER) {
            k_work_reschedule_for_queue(zmk_display_work_q(), &repeat_work, K_MSEC(SOFT_DROP_MS));
        }
        after(step);
    }
}

static void start(void) {
    best_at_start = game.best;
    tetris_start(&game);
    schedule_gravity();
    redraw();
}

static void press(uint8_t stick) {
    switch (game.state) {
    case TETRIS_TITLE:
        if (stick == STICK_PRESS) {
            start();
        }
        return;
    case TETRIS_OVER:
        if (stick == STICK_PRESS && !await_release) {
            start();
        }
        return;
    }

    // The 5-way stick can close two contacts on a diagonal: while left or right is held, ignore
    // up and down rather than rotating or dropping by surprise.
    bool sideways = held & (STICK_LEFT | STICK_RIGHT) & ~stick;
    switch (stick) {
    case STICK_LEFT:
    case STICK_RIGHT:
        tetris_shift(&game, stick == STICK_LEFT ? -1 : 1);
        k_work_reschedule_for_queue(zmk_display_work_q(), &repeat_work, K_MSEC(REPEAT_DELAY_MS));
        redraw();
        break;
    case STICK_UP:
        if (!sideways && tetris_rotate(&game)) {
            redraw();
        }
        break;
    case STICK_DOWN:
        if (!sideways) {
            enum tetris_step step = tetris_soft_drop(&game);
            if (step != TETRIS_GAME_OVER) {
                k_work_reschedule_for_queue(zmk_display_work_q(), &repeat_work, K_MSEC(SOFT_DROP_MS * 3));
            }
            after(step);
        }
        break;
    case STICK_PRESS:
        after(tetris_hard_drop(&game));
        break;
    }
}

static void handle_input(struct k_work *work) {
    struct input in;
    while (k_msgq_get(&input_q, &in, K_NO_WAIT) == 0) {
        if (!active) {
            continue;
        }
        if (in.pressed) {
            held |= in.stick;
            press(in.stick);
        } else {
            held &= ~in.stick;
            if (held == 0) {
                await_release = false;
            }
            if (!(held & (STICK_LEFT | STICK_RIGHT | STICK_DOWN))) {
                k_work_cancel_delayable(&repeat_work);
            }
        }
    }
}

static int tetris_position_listener(const zmk_event_t *eh) {
    const struct zmk_position_state_changed *ev = as_zmk_position_state_changed(eh);
    if (ev == NULL || !active) {
        return ZMK_EV_EVENT_BUBBLE;
    }
    struct input in = {.pressed = ev->state};
    switch (ev->position) {
    case POS_UP:
        in.stick = STICK_UP;
        break;
    case POS_DOWN:
        in.stick = STICK_DOWN;
        break;
    case POS_LEFT:
        in.stick = STICK_LEFT;
        break;
    case POS_RIGHT:
        in.stick = STICK_RIGHT;
        break;
    case POS_PRESS:
        in.stick = STICK_PRESS;
        break;
    default:
        return ZMK_EV_EVENT_BUBBLE;
    }
    k_msgq_put(&input_q, &in, K_NO_WAIT);
    k_work_submit_to_queue(zmk_display_work_q(), &input_work);
    // The left half still gets the key; the GAME layer maps the stick to nothing.
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(tetris, tetris_position_listener);
ZMK_SUBSCRIPTION(tetris, zmk_position_state_changed);

void tetris_create(lv_obj_t *parent, lv_obj_t *art) {
    legend_art = art;
    for (int i = 0; i < 3; i++) {
        canvases[i] = lv_canvas_create(parent);
        // portrait row r is native column 159 - r, as on the left screen
        lv_obj_align(canvases[i], LV_ALIGN_TOP_LEFT, 92 - canvas_y0[i], 0);
        lv_canvas_set_buffer(canvases[i], bufs[i], CANVAS_SIZE, CANVAS_SIZE, LV_IMG_CF_TRUE_COLOR);
        lv_obj_add_flag(canvases[i], LV_OBJ_FLAG_HIDDEN);
    }
}

void tetris_set_active(bool on) {
    if (on == active || canvases[0] == NULL) {
        return;
    }
    active = on;
    held = 0;
    if (!on) {
        // pause: keep the game, stop the clock
        k_work_cancel_delayable(&gravity_work);
        k_work_cancel_delayable(&repeat_work);
        for (int i = 0; i < 3; i++) {
            lv_obj_add_flag(canvases[i], LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_clear_flag(legend_art, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    if (!started) {
        tetris_init(&game, sys_rand32_get() | 1, best_saved);
        started = true;
    }
    lv_obj_add_flag(legend_art, LV_OBJ_FLAG_HIDDEN);
    for (int i = 0; i < 3; i++) {
        lv_obj_clear_flag(canvases[i], LV_OBJ_FLAG_HIDDEN);
    }
    if (game.state == TETRIS_PLAYING) {
        schedule_gravity();
    }
    redraw();
}
