# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概要

Windows C 语言以太网上位机，UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式直接存盘。Python tkinter GUI 启动器提供图形化控制。

## 构建与运行

```bash
# 编译（C11 / MinGW GCC / Winsock2）
gcc -std=c11 -Wall -Wextra -Isrc -o build/ethernet-cap.exe src/*.c -lws2_32

# 命令行运行
build/ethernet-cap.exe -d <下位机IP> [选项]

# GUI 运行（Python 3，仅需内置 tkinter）
venv\Scripts\python.exe gui\launcher.py
```

VS Code: `Ctrl+Shift+B` 编译，`Ctrl+Shift+P` → Run Task → `launch-gui` 启动 GUI。

## 架构

**4 线程模型：** 主线程 — 收包线程 — 写盘线程 — 统计线程

```
下位机 ──UDP:9001──▶ recvfrom() ──▶ ringbuf_push() ──▶ stats_add()
                                      │
                                      ▼
                                 ringbuf_pop() ──▶ fwrite(.bin)
```

| 模块 | 职责 |
|------|------|
| `main.c` | CLI 解析、初始化、`_kbhit` 等 Enter 手动启动、每 100ms 检查总量上限 |
| `udp.c` | socket 创建（数据口 bind + 命令口 connect）、recvfrom/sendto 封装 |
| `ringbuf.c` | SPSC 环形缓冲区，`CRITICAL_SECTION` 保护 |
| `writer.c` | 从缓冲区取数据写 bin 文件，按大小自动切分 |
| `stats.c` | 收包计数、速率/带宽计算、`stats_total_bytes()` 供总量限制查询 |
| `gui/launcher.py` | Python tkinter GUI，`subprocess.Popen` 启动 CLI，管道捕获输出 |

## 关键设计决策

- **数据格式**：UDP 载荷 = 原始 AD 采样数据，无协议头，无序号，透明写盘
- **命令格式**：二进制单字节，`0x01` = START，`0x00` = STOP，通过 UDP 9002 发送
- **文件命名**：`<启动时间YYYYMMDD_HHmmss>_<序号0001起>.bin`，每 10MB 切分
- **退出信号**：`SetConsoleCtrlHandler` 捕获 CTRL_C/BREAK/CLOSE，设 `g_running = false`
- **GUI ↔ CLI 协议**：CLI 输出 `[__GUI_PROMPT__]` 标记，GUI 检测后自动向 stdin 写回车

完整的编码约定、API 签名、设计决策细节见 `.claude/skills/ethernet-cap/SKILL.md`。
