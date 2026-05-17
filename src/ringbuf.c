#include "ringbuf.h"
#include <stdlib.h>
#include <string.h>
#include <windows.h>

struct ringbuf_t {
    uint8_t *buf;
    size_t   capacity;
    size_t   write_pos;
    size_t   read_pos;
    CRITICAL_SECTION cs;
};

ringbuf_t *ringbuf_create(size_t capacity)
{
    ringbuf_t *rb = malloc(sizeof(*rb));
    if (!rb) return NULL;

    rb->buf = malloc(capacity);
    if (!rb->buf) {
        free(rb);
        return NULL;
    }

    rb->capacity   = capacity;
    rb->write_pos  = 0;
    rb->read_pos   = 0;
    InitializeCriticalSection(&rb->cs);
    return rb;
}

void ringbuf_destroy(ringbuf_t *rb)
{
    if (!rb) return;
    DeleteCriticalSection(&rb->cs);
    free(rb->buf);
    free(rb);
}

size_t ringbuf_push(ringbuf_t *rb, const uint8_t *data, size_t len)
{
    EnterCriticalSection(&rb->cs);

    /* 计算可用空间，保留1字节避免write_pos==read_pos歧义 */
    size_t used = (rb->write_pos >= rb->read_pos)
        ? (rb->write_pos - rb->read_pos)
        : (rb->capacity - rb->read_pos + rb->write_pos);
    size_t free_space = rb->capacity - used - 1;

    if (len > free_space) len = free_space;
    if (len == 0) {
        LeaveCriticalSection(&rb->cs);
        return 0;
    }

    size_t first = rb->capacity - rb->write_pos;
    if (len <= first) {
        memcpy(rb->buf + rb->write_pos, data, len);
        rb->write_pos += len;
        if (rb->write_pos >= rb->capacity) rb->write_pos = 0;
    } else {
        memcpy(rb->buf + rb->write_pos, data, first);
        size_t second = len - first;
        memcpy(rb->buf, data + first, second);
        rb->write_pos = second;
    }

    LeaveCriticalSection(&rb->cs);
    return len;
}

size_t ringbuf_pop(ringbuf_t *rb, uint8_t *buf, size_t max_len)
{
    EnterCriticalSection(&rb->cs);

    size_t available = (rb->write_pos >= rb->read_pos)
        ? (rb->write_pos - rb->read_pos)
        : (rb->capacity - rb->read_pos + rb->write_pos);

    if (max_len > available) max_len = available;
    if (max_len == 0) {
        LeaveCriticalSection(&rb->cs);
        return 0;
    }

    size_t first = rb->capacity - rb->read_pos;
    if (max_len <= first) {
        memcpy(buf, rb->buf + rb->read_pos, max_len);
        rb->read_pos += max_len;
        if (rb->read_pos >= rb->capacity) rb->read_pos = 0;
    } else {
        memcpy(buf, rb->buf + rb->read_pos, first);
        size_t second = max_len - first;
        memcpy(buf + first, rb->buf, second);
        rb->read_pos = second;
    }

    LeaveCriticalSection(&rb->cs);
    return max_len;
}

size_t ringbuf_available(ringbuf_t *rb)
{
    EnterCriticalSection(&rb->cs);
    size_t avail = (rb->write_pos >= rb->read_pos)
        ? (rb->write_pos - rb->read_pos)
        : (rb->capacity - rb->read_pos + rb->write_pos);
    LeaveCriticalSection(&rb->cs);
    return avail;
}

size_t ringbuf_free_space(ringbuf_t *rb)
{
    size_t avail = ringbuf_available(rb);
    return (avail >= rb->capacity - 1) ? 0 : (rb->capacity - 1 - avail);
}

bool ringbuf_is_empty(ringbuf_t *rb)
{
    return ringbuf_available(rb) == 0;
}
