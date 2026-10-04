/*
 * SPDX-License-Identifier: MIT
 */

#include <string.h>
#include <zephyr/fatal.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/linker/section_tags.h>
#include <zephyr/sys/reboot.h>

#include "crash.h"

#define CRASH_MAGIC 0x50a2c4a5u

// Not cleared at startup, and a software reset leaves RAM alone, so this outlives the reboot.
static __noinit struct crash_record record;
static bool valid; // decided once at boot, before anything can overwrite the record

static bool record_ok(void) {
    return record.magic == CRASH_MAGIC && record.check == (~CRASH_MAGIC ^ record.count);
}

void k_sys_fatal_error_handler(unsigned int reason, const z_arch_esf_t *esf) {
    uint32_t count = record_ok() ? record.count + 1 : 1;
    const char *name = k_thread_name_get(k_current_get());

    record.reason = reason;
    record.pc = esf ? esf->basic.pc : 0;
    record.lr = esf ? esf->basic.lr : 0;
    record.count = count;
    memset(record.thread, 0, sizeof(record.thread));
    strncpy(record.thread, name ? name : "?", sizeof(record.thread) - 1);
    record.magic = CRASH_MAGIC;
    record.check = ~CRASH_MAGIC ^ count;
    sys_reboot(SYS_REBOOT_COLD);
    CODE_UNREACHABLE;
}

static int crash_init(void) {
    valid = record_ok();
    return 0;
}

SYS_INIT(crash_init, PRE_KERNEL_1, 0);

const struct crash_record *crash_last(void) { return valid ? &record : NULL; }

// Keep the count for the next crash, but stop showing this one.
void crash_forget(void) { valid = false; }
