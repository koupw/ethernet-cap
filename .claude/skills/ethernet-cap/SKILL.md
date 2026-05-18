---
name: ethernet-cap
description: |
  以太网上位机项目开发技能。当用户在此项目中请求开发、修改、讨论以太网上位机相关功能时触发。
  涵盖 UDP 通信、AD 数据采集、环形缓冲区、bin 文件落盘、Windows C 语言开发。
  关键词：以太网、上位机、UDP、AD采集、数据采集、收包、环形缓冲、bin文件。
  本技能仅适用于当前项目目录。
---

# 以太网上位机（Ethernet Capture）项目开发指引

## 项目概述

通过以太网（UDP 单播）与下位机（AD 采集设备）进行双向通信的 Windows 上位机程序。下发采集控制命令，接收 AD 采样数据并以 bin 格式直接存盘。

## 需求摘要

- **语言/平台**：C 语言，Windows
- **传输协议**：UDP 单播
- **端口分离**：数据端口 9001（收）、命令端口 9002（发），可分别指定本机IP和远端IP
- **数据存储**：UDP 载荷直接写 bin 文件，不解析协议
- **文件切分**：每 10MB 切换新文件（可配置）
- **文件命名**：`<采集时间>_<序号>.bin`，如 `20260517_153000_0001.bin`
- **收包方式**：`recvfrom` 高效收包
- **缓冲区**：32MB 环形缓冲区，解耦收包与写盘
- **超时处理**：接收超时报警并退出
- **总量限制**：可设定采集总量上限（-T），达到后自动停止
- **启动方式**：手动按 Enter 开始采集（Ctrl+C 可在等待期取消），退出时自动发送 STOP 命令
- **本机 IP 绑定**：`--local-ip` 指定本机绑定 IP，默认 INADDR_ANY
- **优雅退出**：响应 SIGINT/SIGTERM/SIGBREAK，发送停止命令后释放资源

## 已确认的设计决策

### 命令格式
- **二进制**格式，不使用文本命令
- 命令通过 UDP 端口 9002 发送至下位机

### 下位机数据
- 纯采样信号数据，无协议头，无包序号
- 无需去重处理
- UDP 载荷 = 原始 AD 采样数据，直接写入 bin 文件

### 环形缓冲区
- 默认大小：**32MB**
- 通过命令行参数可调整
- 单生产者（收包线程）、单消费者（写盘线程）

### 网络
- **单播**模式，不支持组播
- 数据接收端口：9001（默认，`--data-port` 可配置）
- 命令发送端口：9002（默认，`--cmd-port` 可配置）
- 本机 IP：`--local-ip` 指定（空串 = INADDR_ANY）
- 远端 IP：`-d` 指定（必需），既是数据来源也是命令目标
- 数据 socket 绑定本机 IP:data_port，命令 socket bind 本机 IP 后 connect 远端
- 内核 UDP 接收缓冲：`SO_RCVBUF` 设为 64MB（`bind` 之前设置），减少千兆线速下内核丢包

### 文件输出
- 命名格式：`<启动时间>_<序号>.bin`
- 启动时间格式：`YYYYMMDD_HHmmss`
- 序号从 0001 递增，4 位补零
- 每达到配置大小（默认 10MB）切换新文件

## 架构设计

### 线程模型

```
┌────────────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│      主线程         │   │  收包线程     │   │  写盘线程     │   │  统计线程     │
│                    │   │              │   │              │   │              │
│ CLI 解析           │   │ recvfrom()  │   │ ringbuf_pop  │   │ Sleep(1000)  │
│ 初始化             │   │ ringbuf_push│   │ fwrite(.bin) │   │ 打印 pps     │
│ 信号处理           │   │ stats_add() │   │ 文件切分     │   │ 带宽 Mbps    │
│ _kbhit 等 Enter    │   │ 超时检测     │   │              │   │ 累计 MB      │
│ 发 START / 创建线程 │   │              │   │              │   │              │
│ 每 10ms 检查总量   │   │              │   │              │   │              │
│ 等待退出 / 清理     │   │              │   │              │   │              │
└────────────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

### 模块划分

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口/配置 | `main.c` | CLI 解析、初始化、`_kbhit`+`PeekNamedPipe` 双重 stdin 检测、`SetConsoleOutputCP(CP_UTF8)` 编码、主循环 |
| UDP 通信 | `udp.c` / `udp.h` | socket 创建、bind、sendto/recvfrom 封装 |
| 环形缓冲区 | `ringbuf.c` / `ringbuf.h` | 固定大小环形缓冲，线程安全 push/pop |
| 文件写入 | `writer.c` / `writer.h` | 从环形缓冲取数据，按大小切分写 bin 文件 |
| 统计上报 | `stats.c` / `stats.h` | 收包计数、速率计算、`stats_total_bytes()` 供主线程查询累计量 |
| GUI 启动器 | `gui/launcher.py` | Python tkinter GUI，`subprocess.Popen` 启动 CLI（`CREATE_NO_WINDOW`）、参数持久化 `gui_config.json`、实时日志、自动 Enter |
| 一键启动 | `run_gui.vbs` / `run_gui.bat` | VBS 无终端窗口启动（推荐桌面快捷方式）/ BAT 终端启动 |

### 数据流

```
下位机 ──UDP 数据端口──▶ recvfrom() ──▶ ringbuf_push() ──▶ stats_add()
                                        │
                                        ▼
                                   ringbuf_pop() ──▶ fwrite(.bin)
                                                        │
                                                  size >= 10MB?
                                                  切换新文件

主线程每 10ms:
  if (stats_total_bytes() >= total_size_mb * 1024^2) → g_running = false
```

### 生命周期

```
启动 → 解析CLI参数 → 创建socket → 绑定端口 → 创建环形缓冲 → 创建写入器
  → stats_init() → 显示配置 → "按 Enter 开始采集..."
      ↓ (Ctrl+C 取消则直接退出，不发送任何命令)
  用户按 Enter → 发送START命令(0x01)
  → 启动收包线程 → 启动写盘线程 → 启动统计线程
  → [运行中: 收包 → 缓冲 → 写盘 → 统计打印]
      ↓ 主线程每 10ms 检查总量上限
  → 退出条件: Ctrl+C / 接收超时 / 总量达到上限
  → 发送STOP命令(0x00) → 等待线程退出 → 排空缓冲
  → 关闭文件 → 释放资源 → 退出
```

### GUI 启动器

`gui/launcher.py` 是独立的 Python tkinter 程序，作为 CLI 的图形前端：

**启动方式：**
- 终端：`venv\Scripts\python.exe gui\launcher.py`（或用 `pythonw.exe` 无终端窗口）
- 一键启动：双击 `run_gui.vbs`（推荐桌面快捷方式）或 `run_gui.bat`
- 进程启动标志：`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`（无终端弹窗）

**核心机制：**
- `subprocess.Popen` 启动 `ethernet-cap.exe`，`stdin/stdout/stderr` 全管道连接
- `__GUI_PROMPT__` 标记：CLI 在等 Enter 提示中输出此标记，GUI 检测后自动向 stdin 写回车
- **世代计数器**：每次 `start()` 递增 `_gen`，所有 `after()` 回调检查世代，防止快速启停时的竞态条件
- **日志缓冲**：100ms 批量刷新，限制 10000 行防内存溢出
- **参数持久化**：点击"开始采集"时自动保存到 `gui_config.json`，下次启动自动加载
- 停止信号：`CTRL_BREAK_EVENT`（`CREATE_NEW_PROCESS_GROUP`），失败回退 `terminate()`

**协议标记：**
- CLI stderr 输出 `[__GUI_PROMPT__]` → GUI 500ms 后自动发送 Enter
- 修改 CLI 等待提示时，需保留此标记

## 编码约定

### C 语言标准
- C11 标准
- Windows 平台，使用 Winsock2 API
- 线程使用 Windows 原生 `CreateThread` 或 C11 `thrd_create`

### 命名约定
- 函数：`snake_case`，模块前缀（如 `udp_init`、`ringbuf_push`）
- 结构体：`snake_case`，`_t` 后缀（如 `ringbuf_t`、`udp_socket_t`）
- 常量/宏：`UPPER_SNAKE_CASE`
- 文件名：小写 + 下划线

### 命令行参数设计

```
ethernet-cap.exe [选项]
  -d <ip>        下位机 IP 地址（必需）
  -o <path>      输出目录（默认：当前目录）
  --data-port N   数据接收端口（默认：9001）
  --cmd-port N    命令发送端口（默认：9002）
  -s <MB>         单文件大小（默认：10，最大 10）
  -b <MB>         环形缓冲区大小（默认：32）
  -t <sec>        接收超时秒数（默认：5）
  -T <MB>         总采集量上限（0=无限制，默认：0）
  --total <MB>    同 -T
  --local-ip <ip> 本机 IP 地址（默认：INADDR_ANY）
  -h              显示帮助
```

### config_t 结构体

```c
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
```

### 退出信号处理

Windows 下使用 `SetConsoleCtrlHandler` 注册回调，捕获 `CTRL_C_EVENT`、`CTRL_BREAK_EVENT`、`CTRL_CLOSE_EVENT`。设置 `g_running = false` 后主线程轮询检测到标志变化即退出。两个轮询循环：等 Enter 循环 `Sleep(50)`，采集监控循环 `Sleep(10)`。

### UDP API（`udp.h`）

```c
sock_handle_t udp_create_data_socket(const char *local_ip, uint16_t port, uint32_t timeout_sec);
sock_handle_t udp_create_cmd_socket(const char *local_ip, const char *target_ip, uint16_t port);
int udp_send_cmd(sock_handle_t sock, uint8_t cmd);
int udp_recv_data(sock_handle_t sock, uint8_t *buf, size_t buf_len, size_t *bytes_received);
```

- `local_ip` 空串 → `INADDR_ANY`，非空则 `inet_pton` → `bind`
- `udp_create_cmd_socket` 先 bind 本机IP:0 再 connect 远端
- `udp_recv_data` 返回：0=成功, 1=超时, -1=错误

### 统计 API（`stats.h`）

```c
void   stats_init(void);
void   stats_add(size_t packets, size_t bytes);
size_t stats_total_bytes(void);    /* 查询累计字节，主线程用于总量限制检查 */
void   stats_print_loop(volatile bool *running);
```

## 关键约束

- **不实现应用层重传**：依赖网络质量保证
- **不做协议解析**：UDP 载荷即 AD 原始数据，透明存储
- **纯采样数据**：无包头、无序号、无校验
- **单文件最大 10MB**：确保小数据量场景下内存可控
- **Windows 无 `recvmmsg`**：使用 `recvfrom` 单包接收
- **无锁或低锁**：环形缓冲区使用原子变量或临界区控制读写指针
