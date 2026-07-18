#include "writer.h"
#include "utils.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define WRITE_CHUNK_SIZE (64 * 1024)

/* ACP→UTF-8 转换后打印路径 */
static void fprintf_path(const char *label, const char *path)
{
    char *u8 = acp_to_utf8(path);
    fprintf(stderr, "%s%s\n", label, u8 ? u8 : path);
    free(u8);
}

struct writer_t {
    ringbuf_t  *rb;
    char        output_dir[512];
    char        start_time[32];
    uint32_t    file_size_limit;    /* 单文件字节上限 */
    FILE       *file;
    size_t      seq;                /* 当前文件序号 */
    size_t      file_bytes;         /* 当前文件已写字节数 */
    uint8_t    *chunk;              /* 预分配写缓冲，避免循环内 malloc */
};

writer_t *writer_create(ringbuf_t *rb, const char *output_dir,
                        uint32_t file_size_mb, const char *start_time)
{
    writer_t *w = malloc(sizeof(*w));
    if (!w) return NULL;

    w->rb         = rb;
    strncpy(w->output_dir, output_dir, sizeof(w->output_dir) - 1);
    strncpy(w->start_time, start_time, sizeof(w->start_time) - 1);
    w->file_size_limit = file_size_mb * 1024ULL * 1024ULL;
    w->file       = NULL;
    w->seq        = 0;
    w->file_bytes = 0;
    w->chunk      = malloc(WRITE_CHUNK_SIZE);
    if (!w->chunk) {
        free(w);
        return NULL;
    }
    return w;
}

void writer_destroy(writer_t *w)
{
    if (!w) return;
    if (w->file) {
        fclose(w->file);
        w->file = NULL;
    }
    free(w->chunk);
    free(w);
}

static int writer_open_next(writer_t *w)
{
    if (w->file) {
        fclose(w->file);
        w->file = NULL;
    }
    w->seq++;
    w->file_bytes = 0;

    /* 确保输出目录存在 */
    CreateDirectoryA(w->output_dir, NULL);

    char path[640];
    snprintf(path, sizeof(path), "%s\\%s_%04zu.bin",
             w->output_dir, w->start_time, w->seq);

    w->file = fopen(path, "wb");
    if (!w->file) {
        fprintf_path("无法创建文件: ", path);
        return -1;
    }

    fprintf_path("[FILE] 创建文件: ", path);
    return 0;
}

int writer_run(writer_t *w, atomic_bool *running)
{
    if (writer_open_next(w) != 0) return -1;

    while (atomic_load(running)) {
        size_t avail = ringbuf_available(w->rb);

        if (avail == 0) {
            ringbuf_wait_data(w->rb, 100);
            continue;
        }

        size_t to_read = avail;
        if (to_read > WRITE_CHUNK_SIZE) to_read = WRITE_CHUNK_SIZE;
        if (w->file_bytes + to_read > w->file_size_limit) {
            to_read = w->file_size_limit - w->file_bytes;
        }

        size_t got = ringbuf_pop(w->rb, w->chunk, to_read);
        if (got == 0) continue;

        size_t written = fwrite(w->chunk, 1, got, w->file);
        if (written != got) {
            fprintf(stderr, "写入文件失败: 期望 %zu, 实际 %zu\n", got, written);
            return -1;
        }
        w->file_bytes += written;

        if (w->file_bytes >= w->file_size_limit) {
            if (writer_open_next(w) != 0) {
                return -1;
            }
        }
    }

    return 0;
}

void writer_flush_remaining(writer_t *w)
{
    while (!ringbuf_is_empty(w->rb)) {
        size_t avail = ringbuf_available(w->rb);
        size_t to_read = avail;
        if (to_read > WRITE_CHUNK_SIZE) to_read = WRITE_CHUNK_SIZE;
        if (w->file_bytes + to_read > w->file_size_limit) {
            to_read = w->file_size_limit - w->file_bytes;
        }

        size_t got = ringbuf_pop(w->rb, w->chunk, to_read);
        if (got == 0) break;

        size_t written = fwrite(w->chunk, 1, got, w->file);
        if (written != got) {
            fprintf(stderr, "排空写入失败\n");
            break;
        }
        w->file_bytes += written;

        if (w->file_bytes >= w->file_size_limit) {
            if (writer_open_next(w) != 0) break;
        }
    }

    if (w->file_bytes > 0 && w->file) {
        fclose(w->file);
        w->file = NULL;
        fprintf(stderr, "[FILE] 已关闭 (排空完成)\n");
    }
}
