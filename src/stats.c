#include "stats.h"
#include <stdio.h>
#include <time.h>
#include <windows.h>

static volatile size_t g_total_packets = 0;
static volatile size_t g_total_bytes   = 0;

void stats_init(void)
{
    g_total_packets = 0;
    g_total_bytes   = 0;
}

void stats_add(size_t packets, size_t bytes)
{
    g_total_packets += packets;
    g_total_bytes   += bytes;
}

size_t stats_total_bytes(void)
{
    return g_total_bytes;
}

double stats_packets_per_sec(void)
{
    /* 由 print_loop 内部使用，外部可调用获取瞬时速率 */
    return 0.0;
}

double stats_mbps(void)
{
    return 0.0;
}

void stats_print_loop(volatile bool *running)
{
    size_t prev_packets = 0;
    size_t prev_bytes   = 0;
    time_t prev_time    = time(NULL);

    while (*running) {
        Sleep(1000);

        time_t now         = time(NULL);
        double elapsed     = difftime(now, prev_time);
        if (elapsed < 0.1) elapsed = 1.0;

        size_t cur_packets = g_total_packets;
        size_t cur_bytes   = g_total_bytes;

        double pps     = (cur_packets - prev_packets) / elapsed;
        double mbps    = (cur_bytes - prev_bytes) * 8.0 / (elapsed * 1000000.0);
        size_t total_mb = cur_bytes / (1024 * 1024);

        fprintf(stderr, "\r[STATS] 包: %zu | 速率: %.0f pps | 带宽: %.2f Mbps | 累计: %zu MB  ",
                cur_packets, pps, mbps, total_mb);
        fflush(stderr);

        prev_packets = cur_packets;
        prev_bytes   = cur_bytes;
        prev_time    = now;
    }

    fprintf(stderr, "\n");
}
