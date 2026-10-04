/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

// Call for every frame report (Num Lock on) from the host: keeps the Bluetooth link fast until the
// frames stop. See host_link_ble.c.
void host_link_ble_frame_report(void);
