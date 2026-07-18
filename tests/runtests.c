/* ================================================================
 * 简易单元测试运行器
 * ================================================================ */
#include "test_common.h"
#include <time.h>

int g_total   = 0;
int g_passed  = 0;
int g_failed  = 0;
static const char *g_current_test = NULL;

#define RUN_TEST(func) do { \
    g_current_test = #func; \
    fprintf(stderr, "[TEST] %s ... ", #func); \
    g_total++; \
    int prev_failed = g_failed; \
    func(); \
    if (g_failed == prev_failed) { \
        g_passed++; \
        fprintf(stderr, "PASS\n"); \
    } \
} while(0)

/* 各模块测试声明 */
void test_ringbuf_basic(void);
void test_ringbuf_full(void);
void test_ringbuf_wrap(void);
void test_ringbuf_empty(void);
void test_ringbuf_sp_sc(void);

void test_coe_parse_basic(void);
void test_coe_parse_no_keyword(void);
void test_coe_parse_empty(void);

void test_utils_acp_to_utf8(void);

void test_stats_basic(void);
void test_stats_init(void);

int main(void)
{
    fprintf(stderr, "========================================\n");
    fprintf(stderr, "  以太网上位机 — 单元测试\n");
    fprintf(stderr, "========================================\n\n");

    /* 环形缓冲区测试 */
    RUN_TEST(test_ringbuf_basic);
    RUN_TEST(test_ringbuf_full);
    RUN_TEST(test_ringbuf_wrap);
    RUN_TEST(test_ringbuf_empty);
    RUN_TEST(test_ringbuf_sp_sc);

    /* COE 解析器测试 */
    RUN_TEST(test_coe_parse_basic);
    RUN_TEST(test_coe_parse_no_keyword);
    RUN_TEST(test_coe_parse_empty);

    /* 工具函数测试 */
    RUN_TEST(test_utils_acp_to_utf8);

    /* 统计模块测试 */
    RUN_TEST(test_stats_basic);
    RUN_TEST(test_stats_init);

    fprintf(stderr, "\n========================================\n");
    fprintf(stderr, "  结果: %d/%d 通过, %d 失败\n",
            g_passed, g_total, g_failed);
    fprintf(stderr, "========================================\n");

    return g_failed > 0 ? 1 : 0;
}
