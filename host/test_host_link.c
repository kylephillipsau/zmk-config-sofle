// Runs the keyboard's decoder (boards/shields/nice_view_legend/widgets/host_link.c) on the Mac.
//
//   sofle-status encode | ./test_host_link          decode what the host would send
//   sofle-status encode | ./test_host_link --damage  also check that every dropped, merged or
//                                                   flipped report loses data, never garbles it
//
// Build: cc -I ../boards/shields/nice_view_legend/widgets -o test_host_link test_host_link.c \
//            ../boards/shields/nice_view_legend/widgets/host_link.c

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host_link.h"

#define MAX_REPORTS 4096

// Reports arrive 300 ms apart, about what a Bluetooth link with peripheral latency manages.
static void decode(const unsigned char *reports, int n, struct host_link *link) {
    host_link_init(link);
    for (int i = 0; i < n; i++) {
        host_link_feed(link, reports[i], 1000 + 300LL * i);
    }
}

static void print_link(const struct host_link *l) {
    if (l->clock_base_s < 0) {
        printf("clock   --:--\n");
    } else {
        printf("clock   %02d:%02d:%02d  synced at %lld ms\n", l->clock_base_s / 3600,
               l->clock_base_s / 60 % 60, l->clock_base_s % 60, (long long)l->clock_sync_ms);
    }
    printf("flags   %s%s\n", l->agent & AGENT_WORKING ? "working " : "",
           l->agent & AGENT_NEEDS ? "needs" : "");
    const char *names[] = {"5H", "WK"};
    for (int i = 0; i < HOST_USAGE_ROWS && l->card.has_usage; i++) {
        const struct host_usage *u = &l->card.usage[i];
        printf("usage   %s %3d%%  reset at %lld min  label \"%s\"\n", names[i],
               u->pct == HOST_PCT_UNKNOWN ? -1 : u->pct,
               u->reset_ms ? (long long)u->reset_ms / 60000 : -1LL, u->label);
    }
    const char *ci[] = {"-", "ok", "FAIL", "running"};
    for (int i = 0; i < HOST_REPO_ROWS && l->card.has_repos; i++) {
        printf("repo %d  %-12s %s\n", i, l->card.repos[i].name, ci[l->card.repos[i].ci]);
    }
    const struct host_event *e = &l->card.event;
    if (e->set) {
        printf("event   \"%s\" at %s, starts at %lld s, shows %lld-%lld s\n", e->title, e->label,
               (long long)e->start_ms / 1000, (long long)e->from_ms / 1000,
               (long long)e->until_ms / 1000);
    }
}

// Each part of a damaged decode must match the clean decode or still be empty.
static int same_or_empty(const struct host_link *got, const struct host_link *clean) {
    struct host_link empty;
    host_link_init(&empty);
    if (got->clock_base_s != clean->clock_base_s && got->clock_base_s != empty.clock_base_s) {
        return 0;
    }
    // reset times count from the frame's first report, which shifts when a report is dropped
    for (int i = 0; got->card.has_usage && i < HOST_USAGE_ROWS; i++) {
        const struct host_usage *g = &got->card.usage[i], *c = &clean->card.usage[i];
        if (g->pct != c->pct || strcmp(g->label, c->label) != 0 ||
            (g->reset_ms == 0) != (c->reset_ms == 0)) {
            return 0;
        }
    }
    const struct host_event *ge = &got->card.event, *ce = &clean->card.event;
    if (ge->set && (strcmp(ge->title, ce->title) != 0 || strcmp(ge->label, ce->label) != 0 ||
                    ge->until_ms - ge->start_ms != ce->until_ms - ce->start_ms ||
                    ge->start_ms - ge->from_ms != ce->start_ms - ce->from_ms)) {
        return 0;
    }
    for (int i = 0; i < HOST_REPO_ROWS; i++) {
        if (memcmp(&got->card.repos[i], &clean->card.repos[i], sizeof(got->card.repos[i])) != 0 &&
            memcmp(&got->card.repos[i], &empty.card.repos[i], sizeof(got->card.repos[i])) != 0) {
            return 0;
        }
    }
    return 1;
}

int main(int argc, char **argv) {
    static unsigned char reports[MAX_REPORTS], damaged[MAX_REPORTS];
    unsigned int value;
    int n = 0;
    while (n < MAX_REPORTS && scanf("%x", &value) == 1) {
        reports[n++] = (unsigned char)value;
    }

    struct host_link clean, got;
    decode(reports, n, &clean);
    printf("%d reports\n", n);
    print_link(&clean);
    if (argc < 2 || strcmp(argv[1], "--damage") != 0) {
        return 0;
    }

    int runs = 0, bad = 0, lost = 0;
    for (int i = 0; i < n; i++) {
        // drop report i (also what a merge of reports i and i+1 looks like)
        memcpy(damaged, reports, i);
        memcpy(damaged + i, reports + i + 1, n - i - 1);
        decode(damaged, n - 1, &got);
        runs++;
        bad += !same_or_empty(&got, &clean);
        lost += got.card.has_usage != clean.card.has_usage || got.card.event.set != clean.card.event.set ||
                memcmp(got.card.repos, clean.card.repos, sizeof(got.card.repos)) != 0 ||
                got.clock_base_s != clean.clock_base_s;
        // flip each bit of report i
        for (int bit = 0; bit < 5; bit++) {
            memcpy(damaged, reports, n);
            damaged[i] ^= 1 << bit;
            decode(damaged, n, &got);
            runs++;
            if (!same_or_empty(&got, &clean)) {
                bad++;
                printf("garbled: report %d bit %d\n", i, bit);
            }
        }
    }
    printf("damage: %d runs, %d garbled, %d drops lost a frame\n", runs, bad, lost);
    return bad ? 1 : 0;
}
