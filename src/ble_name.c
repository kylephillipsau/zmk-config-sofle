/*
 * Keep the Bluetooth name in sync with CONFIG_BT_DEVICE_NAME (set from CONFIG_ZMK_KEYBOARD_NAME).
 *
 * With CONFIG_BT_DEVICE_NAME_DYNAMIC, Zephyr saves any runtime rename to settings ("bt/name") and
 * loads it at boot, overriding the configured name. This board shipped with "Eyelash Sofle"
 * stored there, so changing the name in the .conf had no effect over Bluetooth. Once settings
 * have loaded, a stale stored name is replaced with the configured one (which also saves it).
 *
 * SPDX-License-Identifier: MIT
 */

#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/settings/settings.h>

#include <zephyr/logging/log.h>
LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#include <zmk/ble.h>

static void sync_ble_name(struct k_work *work) {
    static char name[] = CONFIG_BT_DEVICE_NAME;
    const char *current = bt_get_name();

    if (strcmp(current, name) == 0) {
        return;
    }
    LOG_INF("Replacing stored BLE name \"%s\" with \"%s\"", current, name);
    zmk_ble_set_device_name(name);
}

static K_WORK_DELAYABLE_DEFINE(sync_ble_name_work, sync_ble_name);

// Runs once settings_load() has finished. The rename waits briefly so ZMK's own BLE startup,
// which is also kicked off from a settings commit, has started advertising first.
static int ble_name_settings_commit(void) {
    k_work_schedule(&sync_ble_name_work, K_MSEC(500));
    return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(kyles_ble_name, "kyles_ble_name", NULL, NULL,
                               ble_name_settings_commit, NULL);
