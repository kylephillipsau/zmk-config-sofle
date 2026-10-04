// Plays random Tetris games with the right screen's rules (widgets/tetris_game.c) and checks them.
//
//   ./test_tetris          play 5000 random games and 200 by a simple placement player, check
//                          every step, and print the rotations and a board
//
// Build: cc -I ../boards/shields/nice_view_legend/widgets -o test_tetris test_tetris.c \
//            ../boards/shields/nice_view_legend/widgets/tetris_game.c

#include <stdio.h>
#include <stdlib.h>

#include "tetris_game.h"

static const char names[] = "IOTSZJL";

static int count_cells(const struct tetris *t) {
    int n = 0;
    for (int r = 0; r < TETRIS_H; r++) {
        n += __builtin_popcount(t->rows[r]);
    }
    return n;
}

static void fail(const char *what, int game, long step) {
    printf("FAIL game %d step %ld: %s\n", game, step, what);
    exit(1);
}

// Everything that must hold between moves.
static void check(const struct tetris *t, int game, long step) {
    for (int r = 0; r < TETRIS_H; r++) {
        if (t->rows[r] & ~TETRIS_FULL_ROW) {
            fail("a cell outside the well", game, step);
        }
        if (t->rows[r] == TETRIS_FULL_ROW) {
            fail("a full row left uncleared", game, step);
        }
    }
    if (t->state == TETRIS_PLAYING) {
        struct tetris_cell c[4];
        tetris_cells(t->piece, t->rot, c);
        for (int i = 0; i < 4; i++) {
            int x = t->x + c[i].x, y = t->y + c[i].y;
            if (x < 0 || x >= TETRIS_W || y < 0 || y >= TETRIS_H) {
                fail("the piece outside the well", game, step);
            }
            if (t->rows[y] & (1 << x)) {
                fail("the piece overlapping the stack", game, step);
            }
        }
        if (tetris_ghost_y(t) < t->y) {
            fail("the ghost above the piece", game, step);
        }
    }
    if (t->level != 1 + t->lines / 10 || t->score > TETRIS_MAX_SCORE || t->best < t->score) {
        fail("level, score or best inconsistent", game, step);
    }
}

static void print_board(const struct tetris *t) {
    struct tetris_cell c[4];
    tetris_cells(t->piece, t->rot, c);
    for (int r = 0; r < TETRIS_H; r++) {
        printf("  |");
        for (int x = 0; x < TETRIS_W; x++) {
            char ch = (t->rows[r] & (1 << x)) ? '#' : '.';
            for (int i = 0; i < 4; i++) {
                if (t->state == TETRIS_PLAYING && t->x + c[i].x == x && t->y + c[i].y == r) {
                    ch = '@';
                }
            }
            putchar(ch);
        }
        printf("|\n");
    }
}

// A placement player, so lines actually get cleared: try every rotation and column, and pick the
// one with the fewest holes, then the lowest stack. Returns the moves as rotations and a shift.
static void plan(const struct tetris *t, int *rotations, int *shift) {
    long best = -1;
    for (int rot = 0; rot < 4; rot++) {
        for (int dx = -5; dx <= 5; dx++) {
            struct tetris s = *t;
            int r = 0;
            while (r < rot && tetris_rotate(&s)) {
                r++;
            }
            if (r < rot) {
                continue;
            }
            int moved = 0;
            while (moved != dx && tetris_shift(&s, dx > 0 ? 1 : -1)) {
                moved += dx > 0 ? 1 : -1;
            }
            if (moved != dx) {
                continue;
            }
            uint16_t lines = s.lines;
            tetris_hard_drop(&s);
            int holes = 0, height = 0;
            for (int x = 0; x < TETRIS_W; x++) {
                int top = -1;
                for (int y = 0; y < TETRIS_H; y++) {
                    if (s.rows[y] & (1 << x)) {
                        if (top < 0) {
                            top = y;
                        }
                    } else if (top >= 0) {
                        holes++;
                    }
                }
                if (top >= 0 && TETRIS_H - top > height) {
                    height = TETRIS_H - top;
                }
            }
            long value = 1000000L - holes * 1000 - height * 10 + (s.lines - lines) * 50;
            if (s.state != TETRIS_PLAYING) {
                value = 0;
            }
            if (value > best) {
                best = value;
                *rotations = rot;
                *shift = dx;
            }
        }
    }
}

int main(void) {
    // the four rotations of each piece, to eyeball
    for (int p = 0; p < TETRIS_PIECES; p++) {
        printf("%c ", names[p]);
        for (int row = 0; row < 4; row++) {
            for (int rot = 0; rot < 4; rot++) {
                struct tetris_cell c[4];
                tetris_cells(p, rot, c);
                for (int x = 0; x < 4; x++) {
                    char ch = '.';
                    for (int i = 0; i < 4; i++) {
                        if (c[i].x == x && c[i].y == row) {
                            ch = '#';
                        }
                    }
                    putchar(ch);
                }
                printf("  ");
            }
            printf("\n  ");
        }
        printf("\n");
    }

    long total_steps = 0, total_lines = 0, max_lines = 0;
    int counts[TETRIS_PIECES] = {0};
    for (int game = 0; game < 5000; game++) {
        struct tetris t;
        tetris_init(&t, 0x9e3779b9u * (game + 1), 0);
        tetris_start(&t);
        srand(game);
        long step = 0;
        while (t.state == TETRIS_PLAYING) {
            if (++step > 1000000) {
                fail("a game that never ends", game, step);
            }
            uint32_t score = t.score, pieces = t.pieces;
            int cells = count_cells(&t);
            uint16_t lines = t.lines;
            uint8_t piece = t.piece;
            switch (rand() % 8) { // mostly moves, with drops often enough to clear lines
            case 0: tetris_shift(&t, -1); break;
            case 1: tetris_shift(&t, 1); break;
            case 2: tetris_rotate(&t); break;
            case 3: tetris_soft_drop(&t); break;
            case 4: tetris_hard_drop(&t); break;
            default: tetris_tick(&t); break;
            }
            if (t.score < score) {
                fail("the score went down", game, step);
            }
            if (t.pieces != pieces && t.state == TETRIS_PLAYING) {
                counts[piece]++;
                // a lock adds the piece's 4 cells and removes 10 for each cleared row
                if (count_cells(&t) != cells + 4 - 10 * (t.lines - lines)) {
                    fail("cleared rows weren't exactly the full ones", game, step);
                }
            }
            check(&t, game, step);
        }
        total_steps += step;
        total_lines += t.lines;
        if (t.lines > max_lines) {
            max_lines = t.lines;
        }
        if (game == 4999) {
            printf("last game: %ld steps, %u pieces, %u lines, score %u, final board:\n", step,
                   t.pieces, t.lines, t.score);
            print_board(&t);
        }
    }
    printf("5000 random games, %ld steps, %ld lines (best game %ld), all checks passed\n",
           total_steps, total_lines, max_lines);

    // The placement player, moving like a person would, with gravity ticks in between.
    long played_lines = 0, by_count[5] = {0};
    int top_level = 1;
    for (int game = 0; game < 200; game++) {
        struct tetris t;
        tetris_init(&t, 0x85ebca6bu * (game + 1), 0);
        tetris_start(&t);
        long step = 0;
        while (t.state == TETRIS_PLAYING && t.pieces < 2000) {
            int rotations = 0, shift = 0;
            plan(&t, &rotations, &shift);
            for (int r = 0; r < rotations; r++) {
                tetris_rotate(&t);
                check(&t, game, ++step);
            }
            while (shift != 0 && tetris_shift(&t, shift > 0 ? 1 : -1)) {
                shift += shift > 0 ? -1 : 1;
                check(&t, game, ++step);
            }
            int cells = count_cells(&t);
            uint16_t lines = t.lines;
            uint32_t score = t.score, pieces = t.pieces;
            while (t.pieces == pieces) { // let gravity bring it down
                tetris_tick(&t);
                check(&t, game, ++step);
            }
            if (t.state == TETRIS_PLAYING) {
                int cleared = t.lines - lines;
                if (count_cells(&t) != cells + 4 - 10 * cleared) {
                    fail("cleared rows weren't exactly the full ones", game, step);
                }
                if (cleared > 4 || t.score < score) {
                    fail("too many rows at once, or the score went down", game, step);
                }
                by_count[cleared]++;
            }
        }
        played_lines += t.lines;
        if (t.level > top_level) {
            top_level = t.level;
        }
        if (game == 0) {
            printf("placement player, first game: %u pieces, %u lines, level %u, score %u, %d ms "
                   "a row\n",
                   t.pieces, t.lines, t.level, t.score, tetris_tick_ms(&t));
            print_board(&t);
        }
    }
    printf("200 placement games, %ld lines, highest level %d; locks clearing 0-4 rows: %ld %ld %ld "
           "%ld %ld, all checks passed\n",
           played_lines, top_level, by_count[0], by_count[1], by_count[2], by_count[3],
           by_count[4]);
    printf("pieces locked:");
    for (int p = 0; p < TETRIS_PIECES; p++) {
        printf(" %c %d", names[p], counts[p]);
    }
    printf("\n");
    return 0;
}
