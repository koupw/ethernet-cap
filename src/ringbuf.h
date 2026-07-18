#ifndef RINGBUF_H
#define RINGBUF_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

typedef struct ringbuf_t ringbuf_t;

ringbuf_t *ringbuf_create(size_t capacity);
void       ringbuf_destroy(ringbuf_t *rb);
size_t     ringbuf_push(ringbuf_t *rb, const uint8_t *data, size_t len);
size_t     ringbuf_pop(ringbuf_t *rb, uint8_t *buf, size_t max_len);
size_t     ringbuf_available(ringbuf_t *rb);
size_t     ringbuf_free_space(ringbuf_t *rb);
bool       ringbuf_is_empty(ringbuf_t *rb);
void       ringbuf_wait_data(ringbuf_t *rb, uint32_t timeout_ms);

#endif /* RINGBUF_H */
