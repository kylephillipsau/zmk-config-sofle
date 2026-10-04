/*
 * SPDX-License-Identifier: MIT
 *
 * Tetris rules for the right screen, in plain C with no ZMK, Zephyr or LVGL includes, so
 * host/test_tetris.c can play thousands of games on the Mac. widgets/tetris.c draws and drives it.
 *
 *   - 10 x 20 well. Pieces spawn with their box's top-left at column 3, row 0; a collision there
 *     ends the game.
 *   - Rotation turns the piece clockwise inside its box (3 cells for J L S T Z, 4 for I; O doesn't
 *     turn), trying horizontal kicks of 0, -1, +1, -2, +2 cells.
 *   - Gravity moves the piece down a row per tick; a tick that can't locks it, so a landed piece
 *     can still slide for one tick. A hard drop locks at once.
 *   - Pieces come from a shuffled bag of all 7. Level = 1 + lines / 10, and the drop speed
 *     follows the original's table, floored at 50 ms a row.
 *   - Score: 100, 300, 500 or 800 x level for 1-4 lines, 1 a row for a soft drop, 2 a row for a
 *     hard drop, capped at 999999.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define TETRIS_W 10
#define TETRIS_H 20
#define TETRIS_FULL_ROW ((1 << TETRIS_W) - 1)
#define TETRIS_MAX_SCORE 999999

enum tetris_piece { TETRIS_I, TETRIS_O, TETRIS_T, TETRIS_S, TETRIS_Z, TETRIS_J, TETRIS_L, TETRIS_PIECES };

enum tetris_state { TETRIS_TITLE, TETRIS_PLAYING, TETRIS_OVER };

enum tetris_step { TETRIS_MOVED, TETRIS_LOCKED, TETRIS_GAME_OVER };

struct tetris_cell {
    int8_t x, y;
};

struct tetris {
    uint16_t rows[TETRIS_H]; // bit x set = column x filled
    uint8_t state;           // enum tetris_state
    uint8_t piece, rot;      // the falling piece and its rotation, 0-3
    int8_t x, y;             // its box's top-left in the well
    uint8_t next;
    uint8_t bag[TETRIS_PIECES], bag_left;
    uint32_t score, best;
    uint16_t lines;
    uint8_t level;
    uint32_t pieces;         // pieces locked this game
    uint32_t rng;            // xorshift32 state, never 0
};

// Title screen state with a best score from earlier games. seed must not be 0.
void tetris_init(struct tetris *t, uint32_t seed, uint32_t best);
void tetris_start(struct tetris *t);

// Player moves, each returning whether the piece moved.
bool tetris_shift(struct tetris *t, int dx);
bool tetris_rotate(struct tetris *t);
// Down one row for a point, or lock if it can't go further.
enum tetris_step tetris_soft_drop(struct tetris *t);
enum tetris_step tetris_hard_drop(struct tetris *t);

// Gravity: down one row, or lock if it can't go further.
enum tetris_step tetris_tick(struct tetris *t);
int tetris_tick_ms(const struct tetris *t);

// The cells of a piece in a rotation, relative to its box's top-left.
void tetris_cells(uint8_t piece, uint8_t rot, struct tetris_cell out[4]);
// The row the falling piece would land on.
int tetris_ghost_y(const struct tetris *t);
