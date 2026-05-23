#include "types.h"
#include "ringbuf.h"
#include "udp.h"
#include "writer.h"
#include "stats.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <conio.h>
#include <windows.h>

/* 接收缓冲区大小（UDP 最大载荷 65507） */
#define RECV_BUF_SIZE 65536

/* 传递给线程的参数 */
typedef struct {
    ringbuf_t    *rb;
    sock_handle_t data_sock;
    volatile bool *running;
    bool           timeout_exit;
} recv_thread_arg_t;

typedef struct {
    writer_t     *writer;
    volatile bool *running;
} writer_thread_arg_t;

/* 全局运行标志，供信号处理器修改 */
static volatile bool g_running = true;

/* ================================================================
 * 控制台信号处理器
 * ================================================================ */
static BOOL WINAPI ctrl_handler(DWORD ctrl_type)
{
    switch (ctrl_type) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
        fprintf(stderr, "\n[EXIT] 收到退出信号 (code=%lu)，正在停止...\n", ctrl_type);
        g_running = false;
        return TRUE;
    default:
        return FALSE;
    }
}

/* ================================================================
 * 接收线程：recvfrom 循环，数据写入环形缓冲区
 * ================================================================ */
static DWORD WINAPI recv_thread_proc(LPVOID param)
{
    recv_thread_arg_t *arg = (recv_thread_arg_t *)param;
    uint8_t *recv_buf = malloc(RECV_BUF_SIZE);
    if (!recv_buf) {
        fprintf(stderr, "接收线程分配缓冲失败\n");
        *arg->running = false;
        return 1;
    }

    int      buffer_full_warn = 0;
    size_t   total_packets    = 0;

    while (*arg->running) {
        size_t bytes_received = 0;
        int rc = udp_recv_data(arg->data_sock, recv_buf, RECV_BUF_SIZE,
                               &bytes_received);

        if (rc < 0) {
            /* 致命错误 */
            fprintf(stderr, "\n[ERR] recvfrom 致命错误，退出接收\n");
            *arg->running = false;
            break;
        }
        if (rc > 0) {
            /* 超时 */
            fprintf(stderr, "\n[WARN] 接收超时！(%d 秒无数据)\n", 0);
            *arg->running = false;
            arg->timeout_exit = true;
            break;
        }

        /* 数据写入环形缓冲区 */
        size_t pushed = ringbuf_push(arg->rb, recv_buf, bytes_received);
        if (pushed < bytes_received) {
            if (buffer_full_warn == 0) {
                fprintf(stderr, "\n[WARN] 环形缓冲区满，丢弃 %zu 字节\n",
                        bytes_received - pushed);
                buffer_full_warn = 1;
            }
        } else {
            buffer_full_warn = 0;
        }

        stats_add(1, bytes_received);
        total_packets++;
    }

    fprintf(stderr, "[RECV] 接收线程退出，总收包: %zu\n", total_packets);
    free(recv_buf);
    return 0;
}

/* ================================================================
 * 写盘线程：从环形缓冲区取数据，写入 .bin 文件
 * ================================================================ */
static DWORD WINAPI writer_thread_proc(LPVOID param)
{
    writer_thread_arg_t *arg = (writer_thread_arg_t *)param;
    writer_run(arg->writer, arg->running);
    fprintf(stderr, "[WRITE] 写盘线程退出\n");
    return 0;
}

/* ================================================================
 * 统计线程：每秒打印收包速率
 * ================================================================ */
static DWORD WINAPI stats_thread_proc(LPVOID param)
{
    volatile bool *running = (volatile bool *)param;
    stats_print_loop(running);
    return 0;
}

/* ================================================================
 * 打印使用帮助
 * ================================================================ */
static void print_usage(const char *prog)
{
    fprintf(stderr,
        "以太网上位机 - UDP AD 采集数据接收与存储\n"
        "\n"
        "用法: %s -d <下位机IP> [选项]\n"
        "\n"
        "必需参数:\n"
        "  -d <ip>        下位机 IP 地址\n"
        "\n"
        "可选参数:\n"
        "  -o <path>      输出目录 (默认: 当前目录)\n"
        "  --data-port N   数据接收端口 (默认: %d)\n"
        "  --cmd-port N    命令发送端口 (默认: %d)\n"
        "  -s <MB>         单文件大小, MB (默认: %d, 最大: %d)\n"
        "  -b <MB>         环形缓冲区大小, MB (默认: %d)\n"
        "  -t <sec>        接收超时, 秒 (默认: %d)\n"
        "  -T <MB>         总采集量上限, MB (0=无限制, 默认: %d)\n"
        "  --local-ip <ip>  本机 IP 地址 (默认: INADDR_ANY)\n"
        "  --cmd-start <hex> 自定义开始命令 (默认: 01, 示例: 01 02 03)\n"
        "  -h              显示本帮助\n",
        prog,
        DEFAULT_DATA_PORT, DEFAULT_CMD_PORT,
        DEFAULT_FILE_SIZE_MB, MAX_FILE_SIZE_MB,
        DEFAULT_BUF_SIZE_MB, DEFAULT_TIMEOUT_SEC,
        DEFAULT_TOTAL_SIZE_MB);
}

/* ================================================================
 * 十六进制字符串解析：支持 "01" / "01 02 03" / "010203"
 * ================================================================ */
static int parse_hex_string(const char *str, uint8_t *out, size_t out_max, size_t *out_len)
{
    /* 先收集所有十六进制字符（跳过空格） */
    char hex[CMD_START_MAX_LEN * 2 + 1];
    size_t hlen = 0;
    for (const char *p = str; *p; p++) {
        if (*p == ' ' || *p == '\t') continue;
        if (hlen >= sizeof(hex) - 1) return -1;
        hex[hlen++] = *p;
    }
    hex[hlen] = '\0';

    if (hlen == 0 || hlen % 2 != 0) return -1;

    size_t nbytes = hlen / 2;
    if (nbytes > out_max) return -1;

    for (size_t i = 0; i < nbytes; i++) {
        unsigned int byte;
        if (sscanf(hex + i * 2, "%2x", &byte) != 1) return -1;
        out[i] = (uint8_t)byte;
    }
    *out_len = nbytes;
    return 0;
}

/* ================================================================
 * 解析命令行参数
 * ================================================================ */
static int parse_args(int argc, char *argv[], config_t *cfg)
{
    /* 设置默认值 */
    memset(cfg, 0, sizeof(*cfg));
    cfg->data_port   = DEFAULT_DATA_PORT;
    cfg->cmd_port    = DEFAULT_CMD_PORT;
    cfg->file_size_mb = DEFAULT_FILE_SIZE_MB;
    cfg->buf_size_mb  = DEFAULT_BUF_SIZE_MB;
    cfg->timeout_sec   = DEFAULT_TIMEOUT_SEC;
    cfg->total_size_mb  = DEFAULT_TOTAL_SIZE_MB;
    cfg->local_ip[0]    = '\0';
    cfg->cmd_start[0]   = CMD_START;
    cfg->cmd_start_len  = 1;
    strcpy(cfg->output_dir, ".");

    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return -1;
        } else if (strcmp(argv[i], "-d") == 0 && i + 1 < argc) {
            strncpy(cfg->target_ip, argv[++i], sizeof(cfg->target_ip) - 1);
        } else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
            strncpy(cfg->output_dir, argv[++i], sizeof(cfg->output_dir) - 1);
        } else if (strcmp(argv[i], "--data-port") == 0 && i + 1 < argc) {
            cfg->data_port = (uint16_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--cmd-port") == 0 && i + 1 < argc) {
            cfg->cmd_port = (uint16_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "-s") == 0 && i + 1 < argc) {
            cfg->file_size_mb = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "-b") == 0 && i + 1 < argc) {
            cfg->buf_size_mb = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "-t") == 0 && i + 1 < argc) {
            cfg->timeout_sec = (uint32_t)atoi(argv[++i]);
        } else if ((strcmp(argv[i], "-T") == 0 || strcmp(argv[i], "--total") == 0)
                   && i + 1 < argc) {
            cfg->total_size_mb = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--local-ip") == 0 && i + 1 < argc) {
            strncpy(cfg->local_ip, argv[++i], sizeof(cfg->local_ip) - 1);
        } else if (strcmp(argv[i], "--cmd-start") == 0 && i + 1 < argc) {
            const char *hex = argv[++i];
            size_t len = 0;
            if (parse_hex_string(hex, cfg->cmd_start, CMD_START_MAX_LEN, &len) != 0
                || len == 0) {
                fprintf(stderr, "错误: --cmd-start 无效的十六进制字符串: %s\n", hex);
                return -1;
            }
            cfg->cmd_start_len = (uint8_t)len;
        } else {
            fprintf(stderr, "未知参数: %s\n", argv[i]);
            print_usage(argv[0]);
            return -1;
        }
        i++;
    }

    if (cfg->target_ip[0] == '\0') {
        fprintf(stderr, "错误: 必须指定下位机 IP (-d)\n");
        print_usage(argv[0]);
        return -1;
    }

    if (cfg->file_size_mb > MAX_FILE_SIZE_MB || cfg->file_size_mb == 0) {
        fprintf(stderr, "错误: 文件大小须在 1-%d MB 之间\n", MAX_FILE_SIZE_MB);
        return -1;
    }

    return 0;
}

/* ================================================================
 * 主函数
 * ================================================================ */
int main(int argc, char *argv[])
{
    config_t cfg;
    if (parse_args(argc, argv, &cfg) != 0) return 1;

    /* 控制台设为 UTF-8，解决中文乱码 */
    SetConsoleOutputCP(CP_UTF8);

    /* 打印配置 */
    fprintf(stderr, "========================================\n");
    fprintf(stderr, "  以太网上位机\n");
    fprintf(stderr, "========================================\n");
    fprintf(stderr, "  下位机 IP:    %s\n", cfg.target_ip);
    fprintf(stderr, "  数据端口:     %hu\n", cfg.data_port);
    fprintf(stderr, "  命令端口:     %hu\n", cfg.cmd_port);
    {
        /* 路径来自 ACP 命令行参数，转为 UTF-8 再打印 */
        int wlen = MultiByteToWideChar(CP_ACP, 0, cfg.output_dir, -1, NULL, 0);
        wchar_t *wbuf = malloc((size_t)wlen * sizeof(wchar_t));
        if (wbuf) {
            MultiByteToWideChar(CP_ACP, 0, cfg.output_dir, -1, wbuf, wlen);
            int u8len = WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, NULL, 0, NULL, NULL);
            char *u8buf = malloc((size_t)u8len);
            if (u8buf) {
                WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, u8buf, u8len, NULL, NULL);
                fprintf(stderr, "  输出目录:     %s\n", u8buf);
                free(u8buf);
            } else {
                fprintf(stderr, "  输出目录:     %s\n", cfg.output_dir);
            }
            free(wbuf);
        } else {
            fprintf(stderr, "  输出目录:     %s\n", cfg.output_dir);
        }
    }
    fprintf(stderr, "  文件大小:     %u MB\n", cfg.file_size_mb);
    fprintf(stderr, "  缓冲大小:     %u MB\n", cfg.buf_size_mb);
    fprintf(stderr, "  接收超时:     %u 秒\n", cfg.timeout_sec);
    fprintf(stderr, "  本机 IP:      %s\n",
            cfg.local_ip[0] ? cfg.local_ip : "INADDR_ANY (默认)");
    fprintf(stderr, "  总采集上限:   %u MB%s\n",
            cfg.total_size_mb,
            cfg.total_size_mb == 0 ? " (无限制)" : "");
    {
        fprintf(stderr, "  开始命令:    ");
        for (uint8_t j = 0; j < cfg.cmd_start_len; j++)
            fprintf(stderr, " %02X", cfg.cmd_start[j]);
        fprintf(stderr, "\n");
    }
    fprintf(stderr, "========================================\n");

    /* 注册信号处理器 */
    if (!SetConsoleCtrlHandler(ctrl_handler, TRUE)) {
        fprintf(stderr, "注册信号处理器失败\n");
        return 1;
    }

    /* 初始化 Winsock */
    if (udp_init() != 0) return 1;

    /* 创建 socket */
    sock_handle_t data_sock = udp_create_data_socket(cfg.local_ip, cfg.data_port, cfg.timeout_sec);
    if (data_sock == (sock_handle_t)INVALID_SOCKET) {
        udp_cleanup();
        return 1;
    }

    sock_handle_t cmd_sock = udp_create_cmd_socket(cfg.local_ip, cfg.target_ip, cfg.cmd_port);
    if (cmd_sock == (sock_handle_t)INVALID_SOCKET) {
        udp_close(data_sock);
        udp_cleanup();
        return 1;
    }

    /* 创建环形缓冲区 */
    size_t buf_bytes = (size_t)cfg.buf_size_mb * 1024 * 1024;
    ringbuf_t *rb = ringbuf_create(buf_bytes);
    if (!rb) {
        fprintf(stderr, "创建环形缓冲区失败\n");
        udp_close(cmd_sock);
        udp_close(data_sock);
        udp_cleanup();
        return 1;
    }

    /* 捕获启动时间（用于文件命名） */
    char start_time[32];
    {
        time_t t = time(NULL);
        struct tm local_tm;
        localtime_s(&local_tm, &t);
        strftime(start_time, sizeof(start_time), "%Y%m%d_%H%M%S", &local_tm);
    }

    /* 创建文件写入器 */
    writer_t *writer = writer_create(rb, cfg.output_dir, cfg.file_size_mb, start_time);
    if (!writer) {
        fprintf(stderr, "创建文件写入器失败\n");
        ringbuf_destroy(rb);
        udp_close(cmd_sock);
        udp_close(data_sock);
        udp_cleanup();
        return 1;
    }

    /* 初始化统计模块 */
    stats_init();

    /* ================================================================
     * 手动启动：轮询等待用户按 Enter
     * ================================================================ */
    fprintf(stderr, "\n按 Enter 开始采集... [__GUI_PROMPT__]\n");
    fflush(stderr);

    g_running = true;
    {
        HANDLE h_stdin = GetStdHandle(STD_INPUT_HANDLE);
        DWORD stdin_type = (h_stdin == INVALID_HANDLE_VALUE)
                         ? FILE_TYPE_UNKNOWN
                         : GetFileType(h_stdin);
        bool stdin_is_pipe = (stdin_type == FILE_TYPE_PIPE);

        while (g_running) {
            int ch = -1;

            /* 控制台输入（终端直接运行） */
            if (_kbhit()) {
                ch = _getch();
            }

            /* 管道输入（GUI 通过 subprocess.PIPE 启动） */
            if (ch < 0 && stdin_is_pipe) {
                DWORD avail = 0;
                if (PeekNamedPipe(h_stdin, NULL, 0, NULL, &avail, NULL)
                    && avail > 0) {
                    char c;
                    DWORD nread = 0;
                    if (ReadFile(h_stdin, &c, 1, &nread, NULL) && nread == 1)
                        ch = (unsigned char)c;
                }
            }

            if (ch >= 0 && (ch == '\r' || ch == '\n'))
                break;

            Sleep(50);
        }
    }

    if (!g_running) {
        fprintf(stderr, "[MAIN] 采集已取消\n");
        writer_destroy(writer);
        ringbuf_destroy(rb);
        udp_close(cmd_sock);
        udp_close(data_sock);
        udp_cleanup();
        fprintf(stderr, "[MAIN] 程序正常退出\n");
        return 0;
    }

    /* 发送开始采集命令 */
    udp_send_cmd_bytes(cmd_sock, cfg.cmd_start, cfg.cmd_start_len);

    /* 接收线程参数 */
    recv_thread_arg_t recv_arg = { rb, data_sock, &g_running, false };

    /* 写盘线程参数 */
    writer_thread_arg_t writer_arg = { writer, &g_running };

    HANDLE h_recv  = CreateThread(NULL, 0, recv_thread_proc, &recv_arg, 0, NULL);
    HANDLE h_writer = CreateThread(NULL, 0, writer_thread_proc, &writer_arg, 0, NULL);
    HANDLE h_stats  = CreateThread(NULL, 0, stats_thread_proc, (LPVOID)&g_running, 0, NULL);

    if (!h_recv || !h_writer || !h_stats) {
        fprintf(stderr, "创建线程失败\n");
        g_running = false;
        if (h_recv)  CloseHandle(h_recv);
        if (h_writer) CloseHandle(h_writer);
        if (h_stats)  CloseHandle(h_stats);
    } else {
        fprintf(stderr, "[MAIN] 采集已启动，按 Ctrl+C 停止\n");

        /* 等待退出信号（Ctrl+C / 超时 / 总量上限） */
        while (g_running) {
            if (cfg.total_size_mb > 0) {
                size_t total = stats_total_bytes();
                if (total >= (size_t)cfg.total_size_mb * 1024ULL * 1024ULL) {
                    fprintf(stderr, "\n[LIMIT] 已达到总采集量上限 %u MB (累计 %zu MB)，停止采集\n",
                            cfg.total_size_mb, total / (1024 * 1024));
                    g_running = false;
                    break;
                }
            }
            Sleep(10);
        }

        /* 等待各线程退出 */
        fprintf(stderr, "[MAIN] 等待线程退出...\n");
        WaitForSingleObject(h_recv, 5000);
        WaitForSingleObject(h_writer, 10000);
        WaitForSingleObject(h_stats, 2000);

        CloseHandle(h_recv);
        CloseHandle(h_writer);
        CloseHandle(h_stats);
    }

    /* 发送停止采集命令（最多重试 10 次，间隔 50ms） */
    for (int i = 0; i < 10; i++) {
        udp_send_cmd(cmd_sock, CMD_STOP);
        Sleep(5);
    }

    /* 排空缓冲区中剩余数据 */
    fprintf(stderr, "[MAIN] 排空缓冲区剩余数据...\n");
    writer_flush_remaining(writer);

    /* 释放资源 */
    writer_destroy(writer);
    ringbuf_destroy(rb);
    udp_close(cmd_sock);
    udp_close(data_sock);
    udp_cleanup();

    fprintf(stderr, "[MAIN] 程序正常退出\n");
    return 0;
}
