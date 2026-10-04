/*
 * SPDX-License-Identifier: MIT
 */

#include <string.h>

#include "tetris_game.h"

// Spawn orientation, matching TETROMINOES in art/concepts.py, and each piece's box size.
static const struct tetris_cell spawn_cells[TETRIS_PIECES][4] = {
    [TETRIS_I] = {{0, 1}, {1, 1}, {2, 1}, {3, 1}}, [TETRIS_O] = {{1, 0}, {2, 0}, {1, 1}, {2, 1}},
    [TETRIS_T] = {{1, 0}, {0, 1}, {1, 1}, {2, 1}}, [TETRIS_S] = {{1, 0}, {2, 0}, {0, 1}, {1, 1}},
    [TETRIS_Z] = {{0, 0}, {1, 0}, {1, 1}, {2, 1}}, [TETRIS_J] = {{0, 0}, {0, 1}, {1, 1}, {2, 1}},
    [TETRIS_L] = {{2, 0}, {0, 1}, {1, 1}, {2, 1}},
};
static const uint8_t box_size[TETRIS_PIECES] = {4, 0, 3, 3, 3, 3, 3}; // 0: doesn't rotate

// ms per row by level, from the original's frames per row at 60 Hz
static const uint16_t tick_ms[] = {800, 717, 633, 550, 467, 383, 300, 217, 133, 100,
                                   83,  83,  83,  67,  67,  67,  50};

static const uint16_t line_points[] = {0, 100, 300, 500, 800};

static uint32_t next_random(struct tetris *t) {
    uint32_t x = t->rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return t->rng = x;
}

static uint8_t draw_piece(struct tetris *t) {
    if (t->bag_left == 0) {
        for (int i = 0; i < TETRIS_PIECES; i++) {
            t->bag[i] = i;
        }
        for (int i = TETRIS_PIECES - 1; i > 0; i--) { // Fisher-Yates
            int j = next_random(t) % (i + 1);
            uint8_t tmp = t->bag[i];
            t->bag[i] = t->bag[j];
            t->bag[j] = tmp;
        }
        t->bag_left = TETRIS_PIECES;
    }
    return t->bag[--t->bag_left];
}

void tetris_cells(uint8_t piece, uint8_t rot, struct tetris_cell out[4]) {
    int n = box_size[piece];
    memcpy(out, spawn_cells[piece], sizeof(spawn_cells[piece]));
    for (int r = 0; n > 0 && r < (rot & 3); r++) {
        for (int i = 0; i < 4; i++) { // clockwise: (x, y) -> (n - 1 - y, x)
            int8_t x = out[i].x;
            out[i].x = n - 1 - out[i].y;
            out[i].y = x;
        }
    }
}

static bool fits(const struct tetris *t, uint8_t piece, uint8_t rot, int x, int y) {
    struct tetris_cell cells[4];
    tetris_cells(piece, rot, cells);
    for (int i = 0; i < 4; i++) {
        int cx = x + cells[i].x, cy = y + cells[i].y;
        if (cx < 0 || cx >= TETRIS_W || cy < 0 || cy >= TETRIS_H || (t->rows[cy] & (1 << cx))) {
            return false;
        }
    }
    return true;
}

static void add_score(struct tetris *t, uint32_t points) {
    t->score = t->score + points > TETRIS_MAX_SCORE ? TETRIS_MAX_SCORE : t->score + points;
    if (t->score > t->best) {
        t->best = t->score;
    }
}

static bool spawn(struct tetris *t) {
    t->piece = t->next;
    t->next = draw_piece(t);
    t->rot = 0;
    t->x = 3;
    t->y = 0;
    return fits(t, t->piece, t->rot, t->x, t->y);
}

// Lock the piece, clear full rows and spawn the next one.
static enum tetris_step lock(struct tetris *t) {
    struct tetris_cell cells[4];
    tetris_cells(t->piece, t->rot, cells);
    for (int i = 0; i < 4; i++) {
        t->rows[t->y + cells[i].y] |= 1 << (t->x + cells[i].x);
    }
    t->pieces++;

    int cleared = 0;
    for (int r = TETRIS_H - 1; r >= 0; r--) {
        if (t->rows[r] == TETRIS_FULL_ROW) {
            memmove(&t->rows[1], &t->rows[0], r * sizeof(t->rows[0]));
            t->rows[0] = 0;
            cleared++;
            r++; // look at the row that moved into place
        }
    }
    add_score(t, (uint32_t)line_points[cleared] * t->level);
    t->lines += cleared;
    t->level = 1 + t->lines / 10;

    if (!spawn(t)) {
        t->state = TETRIS_OVER;
        return TETRIS_GAME_OVER;
    }
    return TETRIS_LOCKED;
}

void tetris_init(struct tetris *t, uint32_t seed, uint32_t best) {
    memset(t, 0, sizeof(*t));
    t->rng = seed ? seed : 1;
    t->best = best;
    t->state = TETRIS_TITLE;
}

void tetris_start(struct tetris *t) {
    memset(t->rows, 0, sizeof(t->rows));
    t->score = 0;
    t->lines = 0;
    t->level = 1;
    t->pieces = 0;
    t->bag_left = 0;
    t->next = draw_piece(t);
    t->state = spawn(t) ? TETRIS_PLAYING : TETRIS_OVER;
}

bool tetris_shift(struct tetris *t, int dx) {
    if (t->state != TETRIS_PLAYING || !fits(t, t->piece, t->rot, t->x + dx, t->y)) {
        return false;
    }
    t->x += dx;
    return true;
}

bool tetris_rotate(struct tetris *t) {
    static const int8_t kicks[] = {0, -1, 1, -2, 2};
    if (t->state != TETRIS_PLAYING || box_size[t->piece] == 0) {
        return false;
    }
    uint8_t rot = (t->rot + 1) & 3;
    for (unsigned i = 0; i < sizeof(kicks); i++) {
        if (fits(t, t->piece, rot, t->x + kicks[i], t->y)) {
            t->rot = rot;
            t->x += kicks[i];
            return true;
        }
    }
    return false;
}

enum tetris_step tetris_soft_drop(struct tetris *t) {
    if (t->state != TETRIS_PLAYING) {
        return TETRIS_MOVED;
    }
    if (fits(t, t->piece, t->rot, t->x, t->y + 1)) {
        t->y++;
        add_score(t, 1);
        return TETRIS_MOVED;
    }
    return lock(t);
}

enum tetris_step tetris_hard_drop(struct tetris *t) {
    if (t->state != TETRIS_PLAYING) {
        return TETRIS_MOVED;
    }
    int rows = tetris_ghost_y(t) - t->y;
    t->y += rows;
    add_score(t, 2 * rows);
    return lock(t);
}

enum tetris_step tetris_tick(struct tetris *t) {
    if (t->state != TETRIS_PLAYING) {
        return TETRIS_MOVED;
    }
    if (fits(t, t->piece, t->rot, t->x, t->y + 1)) {
        t->y++;
        return TETRIS_MOVED;
    }
    return lock(t);
}

int tetris_tick_ms(const struct tetris *t) {
    int i = t->level - 1;
    int last = sizeof(tick_ms) / sizeof(tick_ms[0]) - 1;
    return tick_ms[i < last ? i : last];
}

int tetris_ghost_y(const struct tetris *t) {
    int y = t->y;
    while (fits(t, t->piece, t->rot, t->x, y + 1)) {
        y++;
    }
    return y;
}
