/* ================================================================
 * COE 解析器单元测试
 * ================================================================ */
#include "test_common.h"
#include "../src/coe.h"
#include <stdio.h>

/* 辅助：写临时 .coe 文件并解析 */
static int parse_coe_str(const char *content, coe_data_t *out)
{
    const char *tmppath = "test_temp.coe";
    FILE *fp = fopen(tmppath, "wb");
    if (!fp) return -1;
    fwrite(content, 1, strlen(content), fp);
    fclose(fp);

    int rc = coe_parse(tmppath, out);
    remove(tmppath);
    return rc;
}

/* 测试基本 COE 解析 */
void test_coe_parse_basic(void)
{
    const char *coe =
        "memory_initialization_vector =\n"
        "00, 01, 02, 03, FF, FE;\n";

    coe_data_t coe_data;
    int rc = parse_coe_str(coe, &coe_data);
    TEST_ASSERT(rc == 0, "COE 解析失败");
    TEST_ASSERT_EQ(coe_data.len, 6, "%zu");

    uint8_t expected[] = {0x00, 0x01, 0x02, 0x03, 0xFF, 0xFE};
    TEST_ASSERT(memcmp(coe_data.data, expected, 6) == 0, "COE 数据不匹配");

    coe_free(&coe_data);
}

/* 测试无 memory_initialization_vector 关键字时的回退 */
void test_coe_parse_no_keyword(void)
{
    /* 纯 hex 数据应被解析（回退模式） */
    const char *coe = "AA BB CC DD";

    coe_data_t coe_data;
    int rc = parse_coe_str(coe, &coe_data);
    /* 新实现需要至少一个有效 token */
    TEST_ASSERT(rc == 0, "纯 hex COE 解析失败");
    TEST_ASSERT_EQ(coe_data.len, 4, "%zu");

    uint8_t expected[] = {0xAA, 0xBB, 0xCC, 0xDD};
    TEST_ASSERT(memcmp(coe_data.data, expected, 4) == 0, "纯 hex 数据不匹配");

    coe_free(&coe_data);
}

/* 测试空文件 */
void test_coe_parse_empty(void)
{
    const char *coe = "";

    coe_data_t coe_data;
    int rc = parse_coe_str(coe, &coe_data);
    TEST_ASSERT(rc != 0, "空文件应返回错误");
}
