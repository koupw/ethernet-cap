/* ================================================================
 * 统计模块单元测试
 * ================================================================ */
#include "test_common.h"
#include "../src/stats.h"

/* 测试基本统计功能 */
void test_stats_basic(void)
{
    stats_init();

    size_t total = stats_total_bytes();
    TEST_ASSERT_EQ(total, 0, "%zu");

    stats_add(10, 1024);
    total = stats_total_bytes();
    TEST_ASSERT_EQ(total, 1024, "%zu");

    stats_add(5, 512);
    total = stats_total_bytes();
    TEST_ASSERT_EQ(total, 1536, "%zu");

    /* 速率函数此时应为 0（stats_print_loop 未运行） */
    double pps = stats_packets_per_sec();
    TEST_ASSERT(pps >= 0.0, "pps 不应为负数");

    double mbps = stats_mbps();
    TEST_ASSERT(mbps >= 0.0, "mbps 不应为负数");
}

/* 测试 stats_init 重置 */
void test_stats_init(void)
{
    stats_init();
    stats_add(1, 100);

    stats_init();
    size_t total = stats_total_bytes();
    TEST_ASSERT_EQ(total, 0, "%zu");
}
