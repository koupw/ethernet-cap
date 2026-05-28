#include "coe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <windows.h>

#define INITIAL_CAP 4096

/* 大小写不敏感查找 */
static const char *strcasestr_local(const char *haystack, const char *needle)
{
    size_t nlen = strlen(needle);
    for (const char *p = haystack; *p; p++) {
        if (_strnicmp(p, needle, nlen) == 0) return p;
    }
    return NULL;
}

/* 跳过空白 */
static const char *skip_ws(const char *p)
{
    while (*p && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
        p++;
    return p;
}

/* 解析一个 hex token 为字节，追加到 buffer */
static int append_hex_token(const char *token, size_t tlen,
                            uint8_t **buf, size_t *len, size_t *cap)
{
    /* 跳过前导空白 */
    while (tlen > 0 && (*token == ' ' || *token == '\t')) { token++; tlen--; }
    /* 去掉尾部空白 */
    while (tlen > 0 && (token[tlen-1] == ' ' || token[tlen-1] == '\t')) tlen--;

    if (tlen == 0) return 0;

    /* 奇数长度补前导0 */
    char hex[3] = {0};
    if (tlen % 2 != 0) {
        hex[0] = '0';
        hex[1] = token[0];
        token++; tlen--;
        unsigned int byte;
        if (sscanf(hex, "%2x", &byte) != 1) return 0;
        if (*len >= *cap) {
            size_t new_cap = *cap * 2;
            uint8_t *tmp = realloc(*buf, new_cap);
            if (!tmp) return -1;
            *buf = tmp;
            *cap = new_cap;
        }
        (*buf)[(*len)++] = (uint8_t)byte;
    }

    for (size_t i = 0; i < tlen; i += 2) {
        unsigned int byte;
        if (sscanf(token + i, "%2x", &byte) != 1) return 0;
        if (*len >= *cap) {
            size_t new_cap = *cap * 2;
            uint8_t *tmp = realloc(*buf, new_cap);
            if (!tmp) return -1;
            *buf = tmp;
            *cap = new_cap;
        }
        (*buf)[(*len)++] = (uint8_t)byte;
    }
    return 0;
}

int coe_parse(const char *filepath, coe_data_t *coe_data)
{
    FILE *fp = fopen(filepath, "rb");
    if (!fp) {
        {
            int wlen = MultiByteToWideChar(CP_ACP, 0, filepath, -1, NULL, 0);
            wchar_t *wbuf = malloc((size_t)wlen * sizeof(wchar_t));
            if (wbuf) {
                MultiByteToWideChar(CP_ACP, 0, filepath, -1, wbuf, wlen);
                int u8len = WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, NULL, 0, NULL, NULL);
                char *u8buf = malloc((size_t)u8len);
                if (u8buf) {
                    WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, u8buf, u8len, NULL, NULL);
                    fprintf(stderr, "无法打开 COE 文件: %s\n", u8buf);
                    free(u8buf);
                } else {
                    fprintf(stderr, "无法打开 COE 文件: %s\n", filepath);
                }
                free(wbuf);
            } else {
                fprintf(stderr, "无法打开 COE 文件: %s\n", filepath);
            }
        }
        return -1;
    }

    /* 获取文件大小 */
    fseek(fp, 0, SEEK_END);
    long fsize = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    if (fsize <= 0) {
        fprintf(stderr, "COE 文件为空\n");
        fclose(fp);
        return -1;
    }

    /* 读取整个文件 */
    char *content = malloc((size_t)fsize + 1);
    if (!content) {
        fprintf(stderr, "分配内存失败\n");
        fclose(fp);
        return -1;
    }
    size_t nread = fread(content, 1, (size_t)fsize, fp);
    fclose(fp);
    content[nread] = '\0';

    /* 跳过 UTF-8 BOM */
    char *text = content;
    if ((unsigned char)text[0] == 0xEF &&
        (unsigned char)text[1] == 0xBB &&
        (unsigned char)text[2] == 0xBF) {
        text += 3;
    }

    /* 查找 memory_initialization_vector */
    const char *data_start = strcasestr_local(text, "memory_initialization_vector");
    if (!data_start) {
        /* 回退：尝试把整个文件当 hex 数据解析 */
        data_start = text;
    } else {
        /* 跳过关键字和后面的 = 或 : */
        data_start += strlen("memory_initialization_vector");
        data_start = skip_ws(data_start);
        if (*data_start == '=' || *data_start == ':') {
            data_start++;
            data_start = skip_ws(data_start);
        }
    }

    /* 分配输出 buffer */
    size_t cap = INITIAL_CAP;
    size_t len = 0;
    uint8_t *buf = malloc(cap);
    if (!buf) {
        fprintf(stderr, "分配内存失败\n");
        free(content);
        return -1;
    }

    /* 按逗号和分号分割 token */
    const char *p = data_start;
    while (*p) {
        p = skip_ws(p);
        if (*p == '\0') break;

        /* 找 token 结尾（逗号、分号或文件结尾） */
        const char *token = p;
        while (*p && *p != ',' && *p != ';' && *p != '\r' && *p != '\n')
            p++;

        size_t tlen = (size_t)(p - token);
        if (tlen > 0) {
            if (append_hex_token(token, tlen, &buf, &len, &cap) != 0) {
                fprintf(stderr, "解析 COE 数据时内存不足\n");
                free(buf);
                free(content);
                return -1;
            }
        }

        if (*p == ',' || *p == ';') p++;
    }

    free(content);

    if (len == 0) {
        fprintf(stderr, "COE 文件中未解析到数据\n");
        free(buf);
        return -1;
    }

    coe_data->data = buf;
    coe_data->len  = len;
    fprintf(stderr, "[COE] 解析完成: %zu 字节\n", len);
    return 0;
}

void coe_free(coe_data_t *coe_data)
{
    if (coe_data && coe_data->data) {
        free(coe_data->data);
        coe_data->data = NULL;
        coe_data->len  = 0;
    }
}
