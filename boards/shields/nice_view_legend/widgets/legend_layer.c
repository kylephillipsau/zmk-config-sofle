/*
 *
 * SPDX-License-Identifier: MIT
 *
 */

#include <string.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#include <zmk/event_manager.h>

#include "legend_layer.h"

ZMK_EVENT_IMPL(zmk_legend_layer_changed);

#if !IS_ENABLED(CONFIG_ZMK_SPLIT) || IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)

#include <zmk/keymap.h>
#include <zmk/events/layer_state_changed.h>
#if IS_ENABLED(CONFIG_ZMK_SPLIT_RELAY_EVENT)
#include <zmk/split/central.h>
#endif

static int legend_layer_listener(const zmk_event_t *eh) {
    static int last_layer = -1;
    zmk_keymap_layer_index_t layer = zmk_keymap_highest_layer_active();

    // Several layer events can fire for one key press; only relay real changes.
    if (layer != last_layer) {
        last_layer = layer;
        raise_zmk_legend_layer_changed((struct zmk_legend_layer_changed){.layer = layer});
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(legend_layer, legend_layer_listener);
ZMK_SUBSCRIPTION(legend_layer, zmk_layer_state_changed);

#if IS_ENABLED(CONFIG_ZMK_SPLIT_RELAY_EVENT)
ZMK_RELAY_EVENT_CENTRAL_TO_PERIPHERAL(zmk_legend_layer_changed, lyr, );
#endif

#elif IS_ENABLED(CONFIG_ZMK_SPLIT_RELAY_EVENT)

// Peripheral: re-raise the relayed event locally for the display widget.
ZMK_RELAY_EVENT_HANDLE(zmk_legend_layer_changed, lyr, );

#endif
