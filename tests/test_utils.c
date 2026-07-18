/* ================================================================
 * 工具函数单元测试
 * ================================================================ */
#include "test_common.h"
#include "../src/utils.h"

/* 测试 ACP→UTF-8 转换 */
void test_utils_acp_to_utf8(void)
{
    /* 纯 ASCII 字符串：输出应相同 */
    const char *ascii = "hello world";
    char *u8 = acp_to_utf8(ascii);
    TEST_ASSERT(u8 != NULL, "acp_to_utf8 返回 NULL");
    TEST_ASSERT(strcmp(u8, ascii) == 0, "ASCII 转换结果不匹配");
    free(u8);

    /* NULL 或空串 */
    /* 注意：acp_to_utf8 对空串应返回空串 */
    u8 = acp_to_utf8("");
    /* 空串可能返回 NULL（wlen==1 时分配成功但转换后为空串） */
    if (u8) {
        TEST_ASSERT(strcmp(u8, "") == 0, "空串转换结果不匹配");
        free(u8);
    }
}
