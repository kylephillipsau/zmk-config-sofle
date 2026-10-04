/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <lvgl.h>
#include <stdbool.h>

#define TETRIS_LAYER 3 // the keymap's GAME layer

// Create the game's canvases over the legend art (call after creating the art).
void tetris_create(lv_obj_t *parent, lv_obj_t *art);

// Show the game in place of the legend while the GAME layer is on. Display thread only.
void tetris_set_active(bool active);
