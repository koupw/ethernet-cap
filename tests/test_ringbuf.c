/* ================================================================
 * 环形缓冲区单元测试
 * ================================================================ */
#include "test_common.h"
#include "../src/ringbuf.h"

/* 测试基本 push/pop */
void test_ringbuf_basic(void)
{
    ringbuf_t *rb = ringbuf_create(1024);
    TEST_ASSERT(rb != NULL, "创建环形缓冲区失败");

    uint8_t data[] = {0xAA, 0xBB, 0xCC, 0xDD};
    size_t pushed = ringbuf_push(rb, data, 4);
    TEST_ASSERT_EQ(pushed, 4, "%zu");

    size_t avail = ringbuf_available(rb);
    TEST_ASSERT_EQ(avail, 4, "%zu");

    TEST_ASSERT(!ringbuf_is_empty(rb), "缓冲区不应为空");

    uint8_t out[16];
    size_t popped = ringbuf_pop(rb, out, 16);
    TEST_ASSERT_EQ(popped, 4, "%zu");
    TEST_ASSERT(memcmp(out, data, 4) == 0, "数据不匹配");

    TEST_ASSERT(ringbuf_is_empty(rb), "缓冲区应为空");

    ringbuf_destroy(rb);
}

/* 测试缓冲区满时的行为 */
void test_ringbuf_full(void)
{
    ringbuf_t *rb = ringbuf_create(128);
    TEST_ASSERT(rb != NULL, "创建环形缓冲区失败");

    uint8_t data[128];
    memset(data, 0x5A, sizeof(data));

    /* 填满（留1字节间隔，实际最多写127） */
    size_t pushed = ringbuf_push(rb, data, 128);
    TEST_ASSERT_EQ(pushed, 127, "%zu");

    /* 再写入应返回0 */
    uint8_t extra[] = {0xFF};
    pushed = ringbuf_push(rb, extra, 1);
    TEST_ASSERT_EQ(pushed, 0, "%zu");

    /* 读取部分 */
    uint8_t out[64];
    size_t popped = ringbuf_pop(rb, out, 50);
    TEST_ASSERT_EQ(popped, 50, "%zu");

    /* 现在应该可以写入50字节 */
    pushed = ringbuf_push(rb, data, 50);
    TEST_ASSERT_EQ(pushed, 50, "%zu");

    ringbuf_destroy(rb);
}

/* 测试环绕写入 */
void test_ringbuf_wrap(void)
{
    ringbuf_t *rb = ringbuf_create(16);
    TEST_ASSERT(rb != NULL, "创建环形缓冲区失败");

    uint8_t data_a[10];
    uint8_t data_b[10];
    memset(data_a, 0xA0, 10);
    memset(data_b, 0xB0, 10);

    /* 写入10字节 A */
    ringbuf_push(rb, data_a, 10);

    /* 读取5字节 */
    uint8_t out[20];
    ringbuf_pop(rb, out, 5);

    /* 写入10字节 B（应环绕） */
    size_t pushed = ringbuf_push(rb, data_b, 10);
    TEST_ASSERT_EQ(pushed, 10, "%zu");

    /* 总可用 = 5(A剩余) + 10(B) = 15 */
    size_t avail = ringbuf_available(rb);
    TEST_ASSERT_EQ(avail, 15, "%zu");

    /* 读取全部 */
    size_t popped = ringbuf_pop(rb, out, 20);
    TEST_ASSERT_EQ(popped, 15, "%zu");

    /* 前5字节应为A剩余部分 */
    TEST_ASSERT(memcmp(out, data_a + 5, 5) == 0, "A剩余数据不匹配");
    /* 后10字节应为B */
    TEST_ASSERT(memcmp(out + 5, data_b, 10) == 0, "B数据不匹配");

    ringbuf_destroy(rb);
}

/* 测试空缓冲区 */
void test_ringbuf_empty(void)
{
    ringbuf_t *rb = ringbuf_create(64);
    TEST_ASSERT(rb != NULL, "创建环形缓冲区失败");

    TEST_ASSERT(ringbuf_is_empty(rb), "新缓冲区应为空");
    TEST_ASSERT_EQ(ringbuf_available(rb), 0, "%zu");

    uint8_t out[16];
    size_t popped = ringbuf_pop(rb, out, 16);
    TEST_ASSERT_EQ(popped, 0, "%zu");

    ringbuf_destroy(rb);
}

/* 测试单生产者单消费者模式 */
void test_ringbuf_sp_sc(void)
{
    ringbuf_t *rb = ringbuf_create(256);
    TEST_ASSERT(rb != NULL, "创建环形缓冲区失败");

    uint8_t pattern[256];
    for (int i = 0; i < 256; i++)
        pattern[i] = (uint8_t)i;

    /* 模拟交替 push/pop */
    size_t total_pushed = 0;
    size_t total_popped = 0;
    uint8_t out[256];

    for (int round = 0; round < 5; round++) {
        /* push 一批 */
        size_t push_size = 10 + (size_t)(round * 7);
        if (push_size > sizeof(pattern) - total_pushed)
            push_size = sizeof(pattern) - total_pushed;

        size_t avail_before = ringbuf_available(rb);
        size_t pushed = ringbuf_push(rb, pattern + total_pushed, push_size);
        TEST_ASSERT_EQ(pushed, push_size, "%zu");
        total_pushed += pushed;

        size_t avail_after = ringbuf_available(rb);
        TEST_ASSERT_EQ(avail_after, avail_before + pushed, "%zu");

        /* pop 一批 */
        size_t pop_size = 3 + (size_t)(round * 5);
        size_t avail = ringbuf_available(rb);
        if (pop_size > avail) pop_size = avail;

        if (pop_size > 0) {
            size_t popped = ringbuf_pop(rb, out + total_popped, pop_size);
            TEST_ASSERT_EQ(popped, pop_size, "%zu");
            total_popped += popped;
        }
    }

    /* 排空 */
    while (!ringbuf_is_empty(rb)) {
        size_t avail = ringbuf_available(rb);
        size_t popped = ringbuf_pop(rb, out + total_popped, avail);
        total_popped += popped;
    }

    TEST_ASSERT_EQ(total_popped, total_pushed, "%zu");

    /* 验证数据完整性 */
    TEST_ASSERT(memcmp(out, pattern, total_pushed) == 0,
                "SPSC 数据完整性校验失败");

    ringbuf_destroy(rb);
}
