/*
 * SPDX-License-Identifier: MIT
 *
 * Decoder for what host/sofle-status sends in keyboard indicator lights macOS doesn't use. Plain C
 * with no ZMK or Zephyr includes, so host/test_host_link.c can run it on the Mac.
 *
 * Every LED output report is one byte, bit n = HID LED usage n + 1:
 *
 *   Num Lock off   resting report: Scroll Lock, Compose and Kana are Claude Code's flags.
 *                  It also ends a frame.
 *   Num Lock on    one frame report: Scroll Lock and Compose carry 2 bits, most significant
 *                  first, and Kana alternates 0, 1, 0, ... so every report differs from the last.
 *
 * A frame is bytes: type, a payload whose length the type fixes, and a CRC-8 (polynomial 0x07)
 * over both. A frame with the wrong length, a broken Kana sequence or a bad CRC is dropped whole,
 * and the host sends everything again later, so a lost report never shows up as wrong data.
 *
 *   type 1  clock   3 bytes: minute of day (11 bits) << 6 | second (6 bits), the host's time
 *                   when it sent the frame's first report
 *   type 2  usage   2 x (percent, minutes to reset (u16)), then 2 x 5-byte reset label
 *   type 3  repo    row, CI state, 12-byte name
 *
 * Percent 0xff = unknown, minutes 0xffff = no reset time. Text is ASCII padded with NULs.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define HOST_LED_NUM (1 << 0)
#define HOST_LED_SCROLL (1 << 2)
#define HOST_LED_COMPOSE (1 << 3)
#define HOST_LED_KANA (1 << 4)

// Claude Code flags, summed over every session by the host
#define AGENT_WORKING (1 << 0) // some session is working
#define AGENT_NEEDS (1 << 1)   // some session needs you
#define AGENT_DONE (1 << 2)    // a session finished since your last prompt

#define HOST_FRAME_CLOCK 1
#define HOST_FRAME_USAGE 2
#define HOST_FRAME_REPO 3

#define HOST_USAGE_ROWS 2 // 5 hour and weekly limits
#define HOST_USAGE_LABEL 5
#define HOST_REPO_ROWS 3
#define HOST_REPO_NAME 12
#define HOST_FRAME_MAX 18 // bytes in the longest frame, usage

#define HOST_PCT_UNKNOWN 0xff

enum host_ci {
    HOST_CI_NONE,    // no row, or no CI runs
    HOST_CI_OK,      // latest runs passed
    HOST_CI_FAIL,    // a latest run failed
    HOST_CI_RUNNING, // a latest run is queued or in progress
};

struct host_usage {
    uint8_t pct;      // HOST_PCT_UNKNOWN until the host knows
    int64_t reset_ms; // uptime when the limit resets, or 0 if unknown
    char label[HOST_USAGE_LABEL + 1];
};

struct host_repo {
    uint8_t ci; // enum host_ci
    char name[HOST_REPO_NAME + 1];
};

struct host_card {
    bool has_usage;
    bool has_repos;
    struct host_usage usage[HOST_USAGE_ROWS];
    struct host_repo repos[HOST_REPO_ROWS];
};

struct host_link {
    // decoded
    uint8_t agent;         // AGENT_* flags
    int32_t clock_base_s;  // host time of day in seconds at clock_sync_ms, or -1 if unknown
    int64_t clock_sync_ms; // uptime of the last clock sync
    int64_t last_frame_ms; // uptime of the last good frame of any type, or 0
    struct host_card card;

    // decoder state
    int last;               // last report seen, or -1
    int nbits;              // bits of the current frame so far, or -1 once it's malformed
    int64_t frame_start_ms; // uptime of the current frame's first report
    uint8_t buf[HOST_FRAME_MAX];
};

void host_link_init(struct host_link *link);

// Feed one LED report. Repeats of the previous report are ignored, because a report for another
// endpoint re-raises the current value.
void host_link_feed(struct host_link *link, uint8_t leds, int64_t now_ms);
