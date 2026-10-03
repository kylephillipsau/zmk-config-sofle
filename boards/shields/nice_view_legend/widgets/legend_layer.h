/*
 *
 * SPDX-License-Identifier: MIT
 *
 */

#pragma once

#include <zephyr/kernel.h>
#include <zmk/event_manager.h>

/*
 * Highest active keymap layer, raised on the central whenever it changes and relayed to the
 * peripheral so the right-hand screen can show the matching legend. Kept to one byte so it fits
 * the split relay payload (CONFIG_ZMK_SPLIT_RELAY_EVENT_DATA_LEN, 14 bytes by default).
 */
struct zmk_legend_layer_changed {
    uint8_t layer;
};

ZMK_EVENT_DECLARE(zmk_legend_layer_changed);
