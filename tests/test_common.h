/* ================================================================
 * 测试公共宏和工具
 * ================================================================ */
#ifndef TEST_COMMON_H
#define TEST_COMMON_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* 全局计数器（在 runtests.c 中定义） */
extern int g_total;
extern int g_passed;
extern int g_failed;

/* 断言宏 */
#define TEST_ASSERT(cond, msg) do { \
    if (!(cond)) { \
        fprintf(stderr, "  FAIL at %s:%d: %s\n", __FILE__, __LINE__, msg); \
        g_failed++; \
        return; \
    } \
} while(0)

#define TEST_ASSERT_EQ(a, b, fmt) do { \
    __typeof__(a) _a = (a); \
    __typeof__(b) _b = (b); \
    if (_a != _b) { \
        fprintf(stderr, "  FAIL at %s:%d: expected " fmt ", got " fmt "\n", \
                __FILE__, __LINE__, _b, _a); \
        g_failed++; \
        return; \
    } \
} while(0)

#define TEST_ASSERT_STREQ(a, b) do { \
    if (strcmp((a), (b)) != 0) { \
        fprintf(stderr, "  FAIL at %s:%d: expected \"%s\", got \"%s\"\n", \
                __FILE__, __LINE__, (b), (a)); \
        g_failed++; \
        return; \
    } \
} while(0)

#endif /* TEST_COMMON_H */
