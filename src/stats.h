#ifndef STATS_H
#define STATS_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

void stats_init(void);
void stats_add(size_t packets, size_t bytes);
void stats_print_loop(volatile bool *running);
size_t stats_total_bytes(void);
double stats_packets_per_sec(void);
double stats_mbps(void);

#endif /* STATS_H */
