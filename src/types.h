#ifndef TYPES_H
#define TYPES_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* 命令定义 */
#define CMD_START  0x01
#define CMD_STOP   0x00
#define CMD_START_MAX_LEN 32

/* .coe 发送参数 */
#define COE_DATA_MAX_PER_PKT    1200
#define DEFAULT_TX_INTERVAL_MS  1
#define DEFAULT_DATA_ADDR       0x01
#define DEFAULT_CMD_ADDR        0x02

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
    uint8_t  cmd_start[CMD_START_MAX_LEN]; /* 自定义开始命令字节 */
    uint8_t  cmd_start_len;                /* 开始命令字节长度 */
    uint8_t  cmd_stop[CMD_START_MAX_LEN];  /* 自定义停止命令字节 */
    uint8_t  cmd_stop_len;                 /* 停止命令字节长度 */
    /* .coe 发送模式参数 */
    char     coe_file[512];                /* .coe 文件路径 (空串=不使用) */
    uint32_t tx_interval_ms;               /* 发送间隔 ms (默认1) */
    uint8_t  preamble[8];                  /* 引导码 (默认 AA55交替) */
    uint8_t  data_addr;                    /* 数据地址 (默认 0x01) */
    uint8_t  cmd_addr;                     /* 命令地址 (默认 0x02) */
} config_t;

#endif /* TYPES_H */
