#include "utils.h"
#include <stdlib.h>
#include <stdarg.h>
#include <time.h>
#include <windows.h>

char *acp_to_utf8(const char *acp_str)
{
    int wlen = MultiByteToWideChar(CP_ACP, 0, acp_str, -1, NULL, 0);
    if (wlen <= 0) return NULL;

    wchar_t *wbuf = malloc((size_t)wlen * sizeof(wchar_t));
    if (!wbuf) return NULL;

    MultiByteToWideChar(CP_ACP, 0, acp_str, -1, wbuf, wlen);

    int u8len = WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, NULL, 0, NULL, NULL);
    if (u8len <= 0) {
        free(wbuf);
        return NULL;
    }

    char *u8buf = malloc((size_t)u8len);
    if (u8buf) {
        WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, u8buf, u8len, NULL, NULL);
    }

    free(wbuf);
    return u8buf;
}

void log_msg(const char *level, const char *fmt, ...)
{
    /* 时间戳 */
    time_t now = time(NULL);
    struct tm local_tm;
    localtime_s(&local_tm, &now);
    fprintf(stderr, "[%02d:%02d:%02d] [%s] ",
            local_tm.tm_hour, local_tm.tm_min, local_tm.tm_sec, level);

    /* 消息体 */
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);

    fprintf(stderr, "\n");
    fflush(stderr);
}
