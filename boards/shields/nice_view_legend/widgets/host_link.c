/*
 * SPDX-License-Identifier: MIT
 */

#include <string.h>

#include "host_link.h"

// Total bytes in each frame type: type, payload, CRC. 0 = unknown type.
static int frame_length(uint8_t type) {
    switch (type) {
    case HOST_FRAME_CLOCK:
        return 1 + 3 + 1;
    case HOST_FRAME_USAGE:
        return 1 + HOST_USAGE_ROWS * 3 + HOST_USAGE_ROWS * HOST_USAGE_LABEL + 1;
    case HOST_FRAME_REPO:
        return 1 + 2 + HOST_REPO_NAME + 1;
    case HOST_FRAME_EVENT:
        return 1 + 6 + HOST_EVENT_LABEL + HOST_EVENT_TITLE + 1;
    default:
        return 0;
    }
}

static uint8_t crc8(const uint8_t *data, int len) {
    uint8_t crc = 0;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

// Copy NUL-padded text, keeping printable ASCII only.
static void copy_text(char *dst, const uint8_t *src, int len) {
    int n = 0;
    for (int i = 0; i < len && src[i]; i++) {
        if (src[i] >= 0x20 && src[i] < 0x7f) {
            dst[n++] = (char)src[i];
        }
    }
    dst[n] = '\0';
}

// Times in a frame count from its first report: over Bluetooth a report can take a few hundred ms
// to get through, but the host knows when it sent the first one.
static void apply_frame(struct host_link *link, const uint8_t *f) {
    switch (f[0]) {
    case HOST_FRAME_CLOCK: {
        uint32_t bits = (uint32_t)f[1] << 16 | (uint32_t)f[2] << 8 | f[3];
        int minute_of_day = bits >> 6, second = bits & 0x3f;
        if (minute_of_day < 24 * 60 && second < 60) {
            link->clock_base_s = minute_of_day * 60 + second;
            link->clock_sync_ms = link->frame_start_ms;
        }
        break;
    }
    case HOST_FRAME_USAGE: {
        const uint8_t *label = f + 1 + HOST_USAGE_ROWS * 3;
        for (int i = 0; i < HOST_USAGE_ROWS; i++) {
            struct host_usage *u = &link->card.usage[i];
            uint16_t minutes = (uint16_t)(f[2 + i * 3] << 8 | f[3 + i * 3]);
            u->pct = f[1 + i * 3];
            u->reset_ms = minutes == 0xffff ? 0 : link->frame_start_ms + (int64_t)minutes * 60000;
            copy_text(u->label, label + i * HOST_USAGE_LABEL, HOST_USAGE_LABEL);
        }
        link->card.has_usage = true;
        break;
    }
    case HOST_FRAME_REPO: {
        uint8_t row = f[1], ci = f[2];
        if (row < HOST_REPO_ROWS && ci <= HOST_CI_RUNNING) {
            link->card.repos[row].ci = ci;
            copy_text(link->card.repos[row].name, f + 3, HOST_REPO_NAME);
            link->card.has_repos = true;
        }
        break;
    }
    case HOST_FRAME_EVENT: {
        struct host_event *e = &link->card.event;
        int32_t start_s = (int32_t)((uint32_t)f[1] << 24 | (uint32_t)f[2] << 16 |
                                    (uint32_t)f[3] << 8 | f[4]);
        e->start_ms = link->frame_start_ms + (int64_t)start_s * 1000;
        e->from_ms = e->start_ms - (int64_t)f[5] * 60000;
        e->until_ms = e->start_ms + (int64_t)f[6] * 60000;
        copy_text(e->label, f + 7, HOST_EVENT_LABEL);
        copy_text(e->title, f + 7 + HOST_EVENT_LABEL, HOST_EVENT_TITLE);
        e->set = e->title[0] != '\0';
        break;
    }
    }
}

void host_link_init(struct host_link *link) {
    memset(link, 0, sizeof(*link));
    link->clock_base_s = -1;
    link->last = -1;
    for (int i = 0; i < HOST_USAGE_ROWS; i++) {
        link->card.usage[i].pct = HOST_PCT_UNKNOWN;
    }
}

void host_link_feed(struct host_link *link, uint8_t leds, int64_t now_ms) {
    leds &= HOST_LED_NUM | HOST_LED_SCROLL | HOST_LED_COMPOSE | HOST_LED_KANA;
    if (leds == link->last) {
        return;
    }
    link->last = leds;

    if (leds & HOST_LED_NUM) {
        int n = link->nbits;
        bool kana = (leds & HOST_LED_KANA) != 0;
        if (n < 0 || n >= HOST_FRAME_MAX * 8 || kana != ((n / 2) & 1)) {
            link->nbits = -1; // malformed: ignore the rest of this frame
            return;
        }
        if (n == 0) {
            link->frame_start_ms = now_ms;
        }
        uint8_t *byte = &link->buf[n / 8];
        *byte = (uint8_t)((n % 8 ? *byte << 2 : 0) | ((leds & HOST_LED_SCROLL) ? 2 : 0) |
                          ((leds & HOST_LED_COMPOSE) ? 1 : 0));
        link->nbits = n + 2;
        return;
    }

    int len = link->nbits > 0 && link->nbits % 8 == 0 ? link->nbits / 8 : 0;
    if (len > 0 && len == frame_length(link->buf[0]) && crc8(link->buf, len) == 0) {
        apply_frame(link, link->buf);
        link->last_frame_ms = now_ms;
    }
    link->nbits = 0;

    link->agent = ((leds & HOST_LED_SCROLL) ? AGENT_WORKING : 0) |
                  ((leds & HOST_LED_COMPOSE) ? AGENT_NEEDS : 0);
}
