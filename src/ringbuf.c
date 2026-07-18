#include "ringbuf.h"
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <windows.h>

struct ringbuf_t {
    uint8_t        *buf;
    size_t          capacity;
    _Atomic size_t  write_pos;
    _Atomic size_t  read_pos;
    HANDLE          data_event;   /* 自动重置事件，生产者推送数据后唤醒消费者 */
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
    atomic_init(&rb->write_pos, 0);
    atomic_init(&rb->read_pos, 0);
    rb->data_event = CreateEventA(NULL, FALSE, FALSE, NULL); /* auto-reset */
    if (!rb->data_event) {
        free(rb->buf);
        free(rb);
        return NULL;
    }
    return rb;
}

void ringbuf_destroy(ringbuf_t *rb)
{
    if (!rb) return;
    CloseHandle(rb->data_event);
    free(rb->buf);
    free(rb);
}

size_t ringbuf_push(ringbuf_t *rb, const uint8_t *data, size_t len)
{
    /* 生产者读取消费者位置（acquire），确保能看到消费者已消费的空间 */
    size_t rpos = atomic_load_explicit(&rb->read_pos, memory_order_acquire);
    size_t wpos = atomic_load_explicit(&rb->write_pos, memory_order_relaxed);

    /* 计算可用空间，保留1字节避免 write_pos==read_pos 歧义 */
    size_t used = (wpos >= rpos)
        ? (wpos - rpos)
        : (rb->capacity - rpos + wpos);
    size_t free_space = rb->capacity - used - 1;

    if (len > free_space) len = free_space;
    if (len == 0) return 0;

    /* 写入数据 */
    size_t first = rb->capacity - wpos;
    if (len <= first) {
        memcpy(rb->buf + wpos, data, len);
        wpos += len;
        if (wpos >= rb->capacity) wpos = 0;
    } else {
        memcpy(rb->buf + wpos, data, first);
        size_t second = len - first;
        memcpy(rb->buf, data + first, second);
        wpos = second;
    }

    /* 发布写入位置（release），确保数据写入对消费者可见 */
    atomic_store_explicit(&rb->write_pos, wpos, memory_order_release);

    /* 唤醒消费者 */
    SetEvent(rb->data_event);

    return len;
}

size_t ringbuf_pop(ringbuf_t *rb, uint8_t *buf, size_t max_len)
{
    /* 消费者读取生产者位置（acquire），确保能看到生产者写入的数据 */
    size_t wpos = atomic_load_explicit(&rb->write_pos, memory_order_acquire);
    size_t rpos = atomic_load_explicit(&rb->read_pos, memory_order_relaxed);

    size_t available = (wpos >= rpos)
        ? (wpos - rpos)
        : (rb->capacity - rpos + wpos);

    if (max_len > available) max_len = available;
    if (max_len == 0) return 0;

    /* 读取数据 */
    size_t first = rb->capacity - rpos;
    if (max_len <= first) {
        memcpy(buf, rb->buf + rpos, max_len);
        rpos += max_len;
        if (rpos >= rb->capacity) rpos = 0;
    } else {
        memcpy(buf, rb->buf + rpos, first);
        size_t second = max_len - first;
        memcpy(buf + first, rb->buf, second);
        rpos = second;
    }

    /* 发布读取位置（release），确保数据读取完成后才更新位置 */
    atomic_store_explicit(&rb->read_pos, rpos, memory_order_release);

    return max_len;
}

size_t ringbuf_available(ringbuf_t *rb)
{
    size_t wpos = atomic_load_explicit(&rb->write_pos, memory_order_acquire);
    size_t rpos = atomic_load_explicit(&rb->read_pos, memory_order_relaxed);
    return (wpos >= rpos) ? (wpos - rpos) : (rb->capacity - rpos + wpos);
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

void ringbuf_wait_data(ringbuf_t *rb, uint32_t timeout_ms)
{
    WaitForSingleObject(rb->data_event, (DWORD)timeout_ms);
}
