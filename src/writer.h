#ifndef WRITER_H
#define WRITER_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdatomic.h>
#include "ringbuf.h"

typedef struct writer_t writer_t;

writer_t *writer_create(ringbuf_t *rb, const char *output_dir,
                        uint32_t file_size_mb, const char *start_time);
void      writer_destroy(writer_t *w);
int       writer_run(writer_t *w, atomic_bool *running);
void      writer_flush_remaining(writer_t *w);

#endif /* WRITER_H */
