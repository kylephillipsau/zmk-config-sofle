/*
 * SPDX-License-Identifier: MIT
 *
 * When the firmware hits a fatal error, Zephyr's default handler halts the chip: the keyboard
 * freezes until someone presses reset. crash.c replaces that handler: it records what happened in
 * RAM that survives a reset, then reboots. The left screen shows the record for a while after.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define CRASH_SHOW_MS (5 * 60 * 1000) // how long after the reboot the screen shows it

struct crash_record {
    uint32_t magic;
    uint32_t reason; // K_ERR_*: 0 CPU exception, 2 stack check, 3 kernel oops, 4 kernel panic
    uint32_t pc;     // where it happened
    uint32_t lr;     // who called that
    uint32_t count;  // crashes since power-on
    char thread[16];
    uint32_t check;  // ~magic ^ count, so RAM noise after power-on isn't read as a crash
};

// The crash that caused the last reboot, or NULL.
const struct crash_record *crash_last(void);
void crash_forget(void);
