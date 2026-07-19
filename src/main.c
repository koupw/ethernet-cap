#include "types.h"
#include "ringbuf.h"
#include "udp.h"
#include "writer.h"
#include "stats.h"
#include "coe.h"
#include "utils.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <time.h>
#include <conio.h>
#include <windows.h>

/* 接收缓冲区大小（UDP 最大载荷 65507） */
#define RECV_BUF_SIZE 65536

/* 传递给线程的参数 */
typedef struct {
    ringbuf_t    *rb;
    sock_handle_t data_sock;
    atomic_bool  *running;
    bool           timeout_exit;
} recv_thread_arg_t;

typedef struct {
    writer_t     *writer;
    atomic_bool  *running;
} writer_thread_arg_t;

/* 全局运行标志，供信号处理器修改 */
static atomic_bool g_running = true;

/* ================================================================
 * 控制台信号处理器
 * ================================================================ */
static BOOL WINAPI ctrl_handler(DWORD ctrl_type)
{
    switch (ctrl_type) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
        LOG_INFO("[EXIT] 收到退出信号 (code=%lu)，正在停止...", ctrl_type);
        atomic_store(&g_running, false);
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
        atomic_store(arg->running, false);
        return 1;
    }

    int      buffer_full_warn = 0;
    size_t   total_packets    = 0;

    while (atomic_load(arg->running)) {
        size_t bytes_received = 0;
        int rc = udp_recv_data(arg->data_sock, recv_buf, RECV_BUF_SIZE,
                               &bytes_received);

        if (rc < 0) {
            /* 致命错误 */
            fprintf(stderr, "\n[ERR] recvfrom 致命错误，退出接收\n");
            atomic_store(arg->running, false);
            break;
        }
        if (rc > 0) {
            /* 超时 */
            fprintf(stderr, "\n[WARN] 接收超时！(%d 秒无数据)\n", 0);
            atomic_store(arg->running, false);
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
    if (writer_run(arg->writer, arg->running) != 0) {
        fprintf(stderr, "[WRITE] 写盘线程异常退出\n");
        atomic_store(arg->running, false);
        return 1;
    }
    fprintf(stderr, "[WRITE] 写盘线程退出\n");
    return 0;
}

/* ================================================================
 * 统计线程：每秒打印收包速率
 * ================================================================ */
static DWORD WINAPI stats_thread_proc(LPVOID param)
{
    atomic_bool *running = (atomic_bool *)param;
    stats_print_loop(running);
    return 0;
}

/* ================================================================
 * Packet 构建辅助函数
 * ================================================================ */
static size_t build_data_packet(const uint8_t *preamble, uint8_t data_addr,
    uint8_t seq, const uint8_t *payload, size_t payload_len, uint8_t *buf)
{
    memcpy(buf, preamble, 8);
    buf[8] = data_addr;
    buf[9] = seq;
    memcpy(buf + 10, payload, payload_len);
    return 10 + payload_len;
}

static size_t build_cmd_packet(const uint8_t *preamble, uint8_t cmd_addr,
    const uint8_t *start_signal, uint8_t signal_len, uint8_t *buf)
{
    memcpy(buf, preamble, 8);
    buf[8] = cmd_addr;
    memcpy(buf + 9, start_signal, signal_len);
    return 9 + signal_len;
}

/* ================================================================
 * 等待用户按 Enter，兼容终端（_kbhit）和管道（PeekNamedPipe）输入
 * ================================================================ */
static void wait_for_enter(void)
{
    HANDLE h_stdin = GetStdHandle(STD_INPUT_HANDLE);
    DWORD stdin_type = (h_stdin == INVALID_HANDLE_VALUE)
                     ? FILE_TYPE_UNKNOWN
                     : GetFileType(h_stdin);
    bool stdin_is_pipe = (stdin_type == FILE_TYPE_PIPE);

    while (atomic_load(&g_running)) {
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
        "  -s <MB>         (已废弃) 单文件大小 (默认: %d)\n"
        "  -b <MB>         环形缓冲区大小, MB (默认: %d)\n"
        "  -t <sec>        接收超时, 秒 (默认: %d)\n"
        "  -T <MB>         总采集量上限, MB (0=无限制, 默认: %d)\n"
        "  --local-ip <ip>  本机 IP 地址 (默认: INADDR_ANY)\n"
        "  --cmd-start <hex> 自定义开始命令 (默认: 01, 示例: 01 02 03)\n"
        "  --cmd-stop <hex>  自定义停止命令 (默认: 00)\n"
        "\n"
        "COE 发送参数:\n"
        "  --coe-file <path>   COE 文件路径 (进入发送模式)\n"
        "  --tx-interval <ms>  发送间隔 (默认: %d ms)\n"
        "  --preamble <hex>    引导码 8字节 (默认: A5 A5 A5 A5 A5 A5 A5 D5)\n"
        "  --data-addr <hex>   数据地址 (默认: %02X)\n"
        "  --cmd-addr <hex>    命令地址 (默认: %02X)\n"
        "  -h              显示本帮助\n",
        prog,
        DEFAULT_DATA_PORT, DEFAULT_CMD_PORT,
        DEFAULT_FILE_SIZE_MB,
        DEFAULT_BUF_SIZE_MB, DEFAULT_TIMEOUT_SEC,
        DEFAULT_TOTAL_SIZE_MB,
        DEFAULT_TX_INTERVAL_MS,
        DEFAULT_DATA_ADDR, DEFAULT_CMD_ADDR);
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
    cfg->cmd_stop[0]    = CMD_STOP;
    cfg->cmd_stop_len   = 1;
    cfg->coe_file[0]    = '\0';
    cfg->tx_interval_ms = DEFAULT_TX_INTERVAL_MS;
    {
        uint8_t default_preamble[8] = {0xA5, 0xA5, 0xA5, 0xA5, 0xA5, 0xA5, 0xA5, 0xD5};
        memcpy(cfg->preamble, default_preamble, 8);
    }
    cfg->data_addr      = DEFAULT_DATA_ADDR;
    cfg->cmd_addr       = DEFAULT_CMD_ADDR;
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
            fprintf(stderr, "[WARN] -s 参数已废弃，不再切分文件，始终产出单个 .bin\n");
            cfg->file_size_mb = (uint32_t)atoi(argv[++i]);  /* 保留兼容 */
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
        } else if (strcmp(argv[i], "--cmd-stop") == 0 && i + 1 < argc) {
            const char *hex = argv[++i];
            size_t len = 0;
            if (parse_hex_string(hex, cfg->cmd_stop, CMD_START_MAX_LEN, &len) != 0
                || len == 0) {
                fprintf(stderr, "错误: --cmd-stop 无效的十六进制字符串: %s\n", hex);
                return -1;
            }
            cfg->cmd_stop_len = (uint8_t)len;
        } else if (strcmp(argv[i], "--coe-file") == 0 && i + 1 < argc) {
            strncpy(cfg->coe_file, argv[++i], sizeof(cfg->coe_file) - 1);
        } else if (strcmp(argv[i], "--tx-interval") == 0 && i + 1 < argc) {
            cfg->tx_interval_ms = (uint32_t)atoi(argv[++i]);
            if (cfg->tx_interval_ms == 0) cfg->tx_interval_ms = 1;
        } else if (strcmp(argv[i], "--preamble") == 0 && i + 1 < argc) {
            size_t len = 0;
            if (parse_hex_string(argv[++i], cfg->preamble, 8, &len) != 0 || len != 8) {
                fprintf(stderr, "错误: --preamble 必须为8字节十六进制\n");
                return -1;
            }
        } else if (strcmp(argv[i], "--data-addr") == 0 && i + 1 < argc) {
            unsigned int val;
            if (sscanf(argv[++i], "%x", &val) != 1 || val > 0xFF) {
                fprintf(stderr, "错误: --data-addr 无效的十六进制值\n");
                return -1;
            }
            cfg->data_addr = (uint8_t)val;
        } else if (strcmp(argv[i], "--cmd-addr") == 0 && i + 1 < argc) {
            unsigned int val;
            if (sscanf(argv[++i], "%x", &val) != 1 || val > 0xFF) {
                fprintf(stderr, "错误: --cmd-addr 无效的十六进制值\n");
                return -1;
            }
            cfg->cmd_addr = (uint8_t)val;
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
        char *u8 = acp_to_utf8(cfg.output_dir);
        fprintf(stderr, "  输出目录:     %s\n", u8 ? u8 : cfg.output_dir);
        free(u8);
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

    /* ================================================================
     * COE 数据发送模式
     * ================================================================ */
    if (cfg.coe_file[0] != '\0') {
        sock_handle_t tx_sock = udp_create_tx_socket(cfg.local_ip, cfg.target_ip, cfg.cmd_port);
        if (tx_sock == (sock_handle_t)INVALID_SOCKET) {
            udp_cleanup();
            return 1;
        }

        coe_data_t coe_data;
        if (coe_parse(cfg.coe_file, &coe_data) != 0) {
            udp_close(tx_sock);
            udp_cleanup();
            return 1;
        }

        size_t total_pkts = (coe_data.len + COE_DATA_MAX_PER_PKT - 1) / COE_DATA_MAX_PER_PKT;
        {
            char *u8 = acp_to_utf8(cfg.coe_file);
            fprintf(stderr, "[COE] 文件: %s\n", u8 ? u8 : cfg.coe_file);
            free(u8);
        }
        fprintf(stderr, "[COE] 数据: %zu 字节, %zu 包\n", coe_data.len, total_pkts);
        fprintf(stderr, "[COE] 发送间隔: %u ms\n", cfg.tx_interval_ms);
        fprintf(stderr, "\n按 Enter 开始发送... [__GUI_PROMPT__]\n");
        fflush(stderr);

        /* 等待 Enter */
        atomic_store(&g_running, true);
        wait_for_enter();

        if (!atomic_load(&g_running)) {
            fprintf(stderr, "[COE] 发送已取消\n");
            coe_free(&coe_data);
            udp_close(tx_sock);
            udp_cleanup();
            return 0;
        }

        /* 发送数据包 */
        uint8_t pkt_buf[10 + COE_DATA_MAX_PER_PKT];
        uint8_t seq = 1;
        size_t sent_pkts = 0;
        size_t offset = 0;

        fprintf(stderr, "[COE] 开始发送...\n");
        while (offset < coe_data.len && atomic_load(&g_running)) {
            size_t chunk = coe_data.len - offset;
            if (chunk > COE_DATA_MAX_PER_PKT) chunk = COE_DATA_MAX_PER_PKT;

            size_t pkt_len = build_data_packet(cfg.preamble, cfg.data_addr,
                                               seq, coe_data.data + offset, chunk, pkt_buf);
            int ret = send((SOCKET)tx_sock, (const char *)pkt_buf, (int)pkt_len, 0);
            if (ret == SOCKET_ERROR) {
                fprintf(stderr, "\n[COE] 发送失败: %d\n", WSAGetLastError());
                break;
            }

            sent_pkts++;
            offset += chunk;
            seq++;

            if (sent_pkts % 100 == 0 || offset >= coe_data.len) {
                fprintf(stderr, "\r[COE] 已发送: %zu/%zu 包  ", sent_pkts, total_pkts);
                fflush(stderr);
            }

            Sleep(cfg.tx_interval_ms);
        }

        fprintf(stderr, "\n[COE] 发送完成: %zu 包, %zu 字节\n", sent_pkts, offset);
        coe_free(&coe_data);
        udp_close(tx_sock);
        udp_cleanup();
        return 0;
    }

    /* ================================================================
     * 采集模式
     * ================================================================ */
    /* 创建 socket */
    sock_handle_t data_sock = udp_create_data_socket(cfg.local_ip, cfg.data_port, cfg.timeout_sec);
    if (data_sock == (sock_handle_t)INVALID_SOCKET) {
        udp_cleanup();
        return 1;
    }

    sock_handle_t tx_sock = udp_create_tx_socket(cfg.local_ip, cfg.target_ip, cfg.cmd_port);
    if (tx_sock == (sock_handle_t)INVALID_SOCKET) {
        udp_close(data_sock);
        udp_cleanup();
        return 1;
    }

    /* 创建环形缓冲区 */
    size_t buf_bytes = (size_t)cfg.buf_size_mb * 1024 * 1024;
    ringbuf_t *rb = ringbuf_create(buf_bytes);
    if (!rb) {
        fprintf(stderr, "创建环形缓冲区失败\n");
        udp_close(tx_sock);
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
        udp_close(tx_sock);
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

    atomic_store(&g_running, true);
    wait_for_enter();

    if (!atomic_load(&g_running)) {
        fprintf(stderr, "[MAIN] 采集已取消\n");
        writer_destroy(writer);
        ringbuf_destroy(rb);
        udp_close(tx_sock);
        udp_close(data_sock);
        udp_cleanup();
        fprintf(stderr, "[MAIN] 程序正常退出\n");
        return 0;
    }

    /* 发送开始采集命令（新格式：引导码 + 命令地址 + 开始信号） */
    {
        uint8_t cmd_pkt[9 + CMD_START_MAX_LEN];
        size_t cmd_len = build_cmd_packet(cfg.preamble, cfg.cmd_addr,
                                          cfg.cmd_start, cfg.cmd_start_len, cmd_pkt);
        send((SOCKET)tx_sock, (const char *)cmd_pkt, (int)cmd_len, 0);
        fprintf(stderr, "[CMD] 已发送命令包 (%zu 字节):", cmd_len);
        for (size_t j = 0; j < cmd_len; j++)
            fprintf(stderr, " %02X", cmd_pkt[j]);
        fprintf(stderr, "\n");
    }

    /* 接收线程参数 */
    recv_thread_arg_t recv_arg = { rb, data_sock, &g_running, false };

    /* 写盘线程参数 */
    writer_thread_arg_t writer_arg = { writer, &g_running };

    HANDLE h_recv  = CreateThread(NULL, 0, recv_thread_proc, &recv_arg, 0, NULL);
    HANDLE h_writer = CreateThread(NULL, 0, writer_thread_proc, &writer_arg, 0, NULL);
    HANDLE h_stats  = CreateThread(NULL, 0, stats_thread_proc, (LPVOID)&g_running, 0, NULL);

    if (!h_recv || !h_writer || !h_stats) {
        fprintf(stderr, "创建线程失败\n");
        atomic_store(&g_running, false);
        if (h_recv)  CloseHandle(h_recv);
        if (h_writer) CloseHandle(h_writer);
        if (h_stats)  CloseHandle(h_stats);
    } else {
        fprintf(stderr, "[MAIN] 采集已启动，按 Ctrl+C 停止\n");

        /* 等待退出信号（Ctrl+C / 超时 / 总量上限 / 管道输入） */
        while (atomic_load(&g_running)) {
            if (cfg.total_size_mb > 0) {
                size_t total = stats_total_bytes();
                if (total >= (size_t)cfg.total_size_mb * 1024ULL * 1024ULL) {
                    fprintf(stderr, "\n[LIMIT] 已达到总采集量上限 %u MB (累计 %zu MB)，停止采集\n",
                            cfg.total_size_mb, total / (1024 * 1024));
                    atomic_store(&g_running, false);
                    break;
                }
            }
            /* 检测管道输入（GUI 通过 stdin 发送换行来停止） */
            {
                DWORD avail = 0;
                if (PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), NULL, 0, NULL, &avail, NULL)
                    && avail > 0) {
                    char c;
                    DWORD read;
                    if (ReadFile(GetStdHandle(STD_INPUT_HANDLE), &c, 1, &read, NULL)
                        && read == 1 && (c == '\r' || c == '\n')) {
                        fprintf(stderr, "\n[MAIN] 收到停止信号，正在退出...\n");
                        atomic_store(&g_running, false);
                        break;
                    }
                }
            }
            Sleep(1);
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

    /* 发送停止采集命令并等待设备确认（向后兼容） */
    {
        uint8_t stop_pkt[9 + CMD_START_MAX_LEN];
        size_t stop_len = build_cmd_packet(cfg.preamble, cfg.cmd_addr,
                                           cfg.cmd_stop, cfg.cmd_stop_len, stop_pkt);

        /* 临时设置短超时用于 ACK 等待 */
        DWORD ack_timeout = 200; /* 200ms */
        setsockopt((SOCKET)data_sock, SOL_SOCKET, SO_RCVTIMEO,
                   (const char *)&ack_timeout, sizeof(ack_timeout));

        int ack_received = 0;
        for (int i = 0; i < 3 && !ack_received; i++) {
            send((SOCKET)tx_sock, (const char *)stop_pkt, (int)stop_len, 0);

            /* 尝试接收设备确认 */
            uint8_t ack_buf[64];
            size_t ack_bytes = 0;
            int rc = udp_recv_data(data_sock, ack_buf, sizeof(ack_buf), &ack_bytes);
            if (rc == 0 && ack_bytes > 0) {
                LOG_INFO("[CMD] 收到停止确认 (%zu 字节)", ack_bytes);
                ack_received = 1;
            } else {
                if (i < 2) Sleep(100);
            }
        }

        if (!ack_received) {
            LOG_WARN("[CMD] 未收到停止确认（已尝试 3 次）");
        }

        /* 恢复原超时设置 */
        DWORD orig_timeout = cfg.timeout_sec * 1000;
        setsockopt((SOCKET)data_sock, SOL_SOCKET, SO_RCVTIMEO,
                   (const char *)&orig_timeout, sizeof(orig_timeout));

        LOG_INFO("[CMD] 已发送停止命令包 (%zu 字节)", stop_len);
    }

    /* 排空缓冲区中剩余数据 */
    fprintf(stderr, "[MAIN] 排空缓冲区剩余数据...\n");
    writer_flush_remaining(writer);

    /* 释放资源 */
    writer_destroy(writer);
    ringbuf_destroy(rb);
    udp_close(tx_sock);
    udp_close(data_sock);
    udp_cleanup();

    fprintf(stderr, "[MAIN] 程序正常退出\n");
    return 0;
}
