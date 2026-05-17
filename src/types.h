#ifndef TYPES_H
#define TYPES_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* 命令定义 */
#define CMD_START  0x01
#define CMD_STOP   0x00

/* 默认配置 */
#define DEFAULT_DATA_PORT    9001
#define DEFAULT_CMD_PORT     9002
#define DEFAULT_FILE_SIZE_MB 10
#define DEFAULT_BUF_SIZE_MB  32
#define DEFAULT_TIMEOUT_SEC  5
#define MAX_FILE_SIZE_MB       10
#define DEFAULT_TOTAL_SIZE_MB  0

/* 输出文件名格式 */
#define FILE_NAME_FORMAT    "%s_%04zu.bin"
#define TIME_FMT            "%Y%m%d_%H%M%S"

typedef struct {
    char   target_ip[64];        /* 下位机 IP 地址 */
    char   output_dir[512];      /* 输出目录 */
    uint16_t data_port;          /* 数据接收端口 */
    uint16_t cmd_port;           /* 命令发送端口 */
    uint32_t file_size_mb;       /* 单文件最大 MB */
    uint32_t buf_size_mb;        /* 环形缓冲区 MB */
    uint32_t timeout_sec;        /* 接收超时秒数 */
    char     local_ip[64];       /* 本机 IP 地址 (空串 = INADDR_ANY) */
    uint32_t total_size_mb;      /* 总采集量上限 MB (0 = 无限制) */
} config_t;

#endif /* TYPES_H */
