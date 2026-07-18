#include "coe.h"
#include "utils.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define INITIAL_CAP  4096

/* 确保输出 buffer 有空间容纳额外 need 字节，自动扩容 */
static int ensure_cap(uint8_t **buf, size_t *cap, size_t len, size_t need)
{
    if (len + need <= *cap) return 0;
    size_t new_cap = *cap * 2;
    while (new_cap < len + need) new_cap *= 2;
    uint8_t *tmp = realloc(*buf, new_cap);
    if (!tmp) return -1;
    *buf = tmp;
    *cap = new_cap;
    return 0;
}

/* 将 hex 字符串解析为字节追加到 buffer */
static int append_hex_bytes(const char *hex, size_t hlen,
                             uint8_t **buf, size_t *len, size_t *cap)
{
    if (hlen == 0) return 0;
    if (hlen % 2 != 0) return -1;

    size_t nbytes = hlen / 2;
    if (ensure_cap(buf, cap, *len, nbytes) != 0) return -1;

    for (size_t i = 0; i < hlen; i += 2) {
        char pair[3] = { hex[i], hex[i + 1], '\0' };
        char *end = NULL;
        unsigned long val = strtoul(pair, &end, 16);
        if (end != pair + 2) return -1;
        (*buf)[(*len)++] = (uint8_t)val;
    }
    return 0;
}

int coe_parse(const char *filepath, coe_data_t *coe_data)
{
    FILE *fp = fopen(filepath, "rb");
    if (!fp) {
        char *u8 = acp_to_utf8(filepath);
        fprintf(stderr, "无法打开 COE 文件: %s\n", u8 ? u8 : filepath);
        free(u8);
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
    if (nread >= 3 &&
        (unsigned char)text[0] == 0xEF &&
        (unsigned char)text[1] == 0xBB &&
        (unsigned char)text[2] == 0xBF) {
        text += 3;
    }

    /* 查找 memory_initialization_vector（大小写不敏感） */
    const char *data_start = NULL;
    const char *kw = "memory_initialization_vector";
    size_t kw_len = strlen(kw);

    for (const char *p = text; *p; p++) {
        /* 手动大小写不敏感比较（避免依赖 _strnicmp） */
        int match = 1;
        for (size_t k = 0; k < kw_len; k++) {
            char ca = p[k];
            char cb = kw[k];
            if (ca >= 'A' && ca <= 'Z') ca += 32;
            if (cb >= 'A' && cb <= 'Z') cb += 32;
            if (ca != cb || ca == '\0') { match = 0; break; }
        }
        if (match) {
            data_start = p + kw_len;
            break;
        }
    }

    if (!data_start) {
        /* 回退：把整个文件当 hex 数据解析 */
        data_start = text;
    } else {
        /* 跳过 = 或 : */
        while (*data_start && (*data_start == ' ' || *data_start == '\t' ||
               *data_start == '\r' || *data_start == '\n' ||
               *data_start == '=' || *data_start == ':'))
            data_start++;
    }

    /* 预估输出 buffer 容量 */
    size_t remain = strlen(data_start);
    size_t est_bytes = remain / 3;
    size_t cap = INITIAL_CAP;
    while (cap < est_bytes && cap < 1024 * 1024) cap *= 2;
    size_t len = 0;
    uint8_t *buf = malloc(cap);
    if (!buf) {
        fprintf(stderr, "分配内存失败\n");
        free(content);
        return -1;
    }

    /* 解析 hex token */
    const char *p = data_start;
    char token[256];
    size_t token_len = 0;

    while (*p) {
        /* 跳过空白 */
        while (*p && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
            p++;
        if (!*p) break;

        /* 收集 hex 字符 */
        token_len = 0;
        while (*p) {
            char c = *p;
            if (c == ',' || c == ';') {
                /* 分隔符：结束当前 token */
                if (append_hex_bytes(token, token_len, &buf, &len, &cap) != 0) {
                    fprintf(stderr, "COE 解析失败：无效 hex 字符\n");
                    free(buf);
                    free(content);
                    return -1;
                }
                token_len = 0;
                p++;
                break;
            }
            if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
                /* 空白：结束当前 token */
                if (token_len > 0) {
                    if (append_hex_bytes(token, token_len, &buf, &len, &cap) != 0) {
                        fprintf(stderr, "COE 解析失败：无效 hex 字符\n");
                        free(buf);
                        free(content);
                        return -1;
                    }
                    token_len = 0;
                }
                p++;
                break;
            }
            if (isxdigit((unsigned char)c)) {
                if (token_len < sizeof(token) - 1)
                    token[token_len++] = c;
            } else {
                /* 非 hex、非分隔符、非空白：可能是注释字符，跳过 */
                if (token_len > 0) {
                    if (append_hex_bytes(token, token_len, &buf, &len, &cap) != 0) {
                        fprintf(stderr, "COE 解析失败：无效 hex 字符\n");
                        free(buf);
                        free(content);
                        return -1;
                    }
                    token_len = 0;
                }
            }
            p++;
        }
    }

    /* 最后残留的 token */
    if (token_len > 0) {
        if (append_hex_bytes(token, token_len, &buf, &len, &cap) != 0) {
            fprintf(stderr, "COE 解析失败：无效 hex 字符\n");
            free(buf);
            free(content);
            return -1;
        }
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
