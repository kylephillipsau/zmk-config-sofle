/*
 * SPDX-License-Identifier: MIT
 *
 * Speeds up the Bluetooth link while host/sofle-status sends frames.
 *
 * ZMK asks the host for a peripheral latency of 30, so while it has nothing to send, the keyboard
 * listens only every 30th connection event, and each LED report from the host waits up to ~360 ms
 * to get through. While frames arrive, this asks for latency 0, and asks for latency 30 again once
 * they stop, so idle power use doesn't change.
 *
 * macOS ignores requests outside Apple's accessory guidelines: the interval range must be at least
 * 15 ms wide, unless both ends are exactly 15 ms. ZMK's own range (7.5-15 ms) is neither, so both
 * requests fix the interval at 15 ms, up from the 11.25 ms macOS picks when it connects.
 */

#include <errno.h>

#include <zephyr/bluetooth/conn.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zmk/ble.h>
#include <zmk/endpoints.h>

#include "host_link_ble.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define RESTORE_AFTER K_SECONDS(2) // after the last frame report
#define RETRY_MS 4000              // ask again if the latency is still up this long after asking

#define INTERVAL 12 // 1.25 ms units: 15 ms

static const struct bt_le_conn_param fast_params =
    BT_LE_CONN_PARAM_INIT(INTERVAL, INTERVAL, 0, CONFIG_BT_PERIPHERAL_PREF_TIMEOUT);
static const struct bt_le_conn_param idle_params = BT_LE_CONN_PARAM_INIT(
    INTERVAL, INTERVAL, CONFIG_BT_PERIPHERAL_PREF_LATENCY, CONFIG_BT_PERIPHERAL_PREF_TIMEOUT);

static int64_t last_request_ms = -RETRY_MS;

static void request(struct bt_conn *conn, const struct bt_le_conn_param *params) {
    int err = bt_conn_le_param_update(conn, params);
    if (err && err != -EALREADY) {
        LOG_WRN("connection parameter update failed: %d", err);
    }
}

static void restore(struct k_work *work) {
    struct bt_conn *conn = zmk_ble_active_profile_conn();
    if (conn != NULL) {
        request(conn, &idle_params);
        bt_conn_unref(conn);
    }
}

static K_WORK_DELAYABLE_DEFINE(restore_work, restore);

void host_link_ble_frame_report(void) {
    if (zmk_endpoints_selected().transport != ZMK_TRANSPORT_BLE) {
        return;
    }
    k_work_reschedule(&restore_work, RESTORE_AFTER);

    // macOS takes a few seconds to apply a request, and Zephyr's own update 5 s after connecting
    // can put the latency back mid-transfer, so check again now and then rather than asking once.
    int64_t now = k_uptime_get();
    if (now - last_request_ms < RETRY_MS) {
        return;
    }
    struct bt_conn *conn = zmk_ble_active_profile_conn();
    if (conn == NULL) {
        return;
    }
    struct bt_conn_info info;
    if (bt_conn_get_info(conn, &info) == 0 && info.le.latency != 0) {
        request(conn, &fast_params);
        last_request_ms = now;
    }
    bt_conn_unref(conn);
}
