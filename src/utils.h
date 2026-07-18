#ifndef UTILS_H
#define UTILS_H

#include <stdio.h>

/* ACP（系统默认编码） → UTF-8 转换。
 * 返回 malloc 分配的字符串，调用者负责 free。
 * 失败返回 NULL。 */
char *acp_to_utf8(const char *acp_str);

/* ================================================================
 * 简易日志系统
 * 格式: [HH:MM:SS] [LEVEL] 消息
 * ================================================================ */
void log_msg(const char *level, const char *fmt, ...);

#define LOG_DEBUG(fmt, ...) log_msg("DEBUG", fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)  log_msg("INFO",  fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  log_msg("WARN",  fmt, ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...) log_msg("ERROR", fmt, ##__VA_ARGS__)

#endif /* UTILS_H */
