# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概要

Windows C 语言以太网上位机，UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式直接存盘。支持读取 .coe 文件数据发送到下位机。Python tkinter GUI 启动器提供图形化控制。

## 构建与运行

```bash
# 编译（C11 / MinGW GCC / Winsock2）
gcc -std=c11 -Wall -Wextra -Isrc -o build/ethernet-cap.exe src/*.c -lws2_32

# 命令行运行
build/ethernet-cap.exe -d <下位机IP> [选项]

# GUI 运行（Python 3，仅需内置 tkinter）
venv\Scripts\python.exe gui\launcher.py

# 一键启动（双击即可，无终端窗口）
run_gui.vbs
```

VS Code: `Ctrl+Shift+B` 编译。

## 架构

**4 线程模型：** 主线程 — 收包线程 — 写盘线程 — 统计线程

```
采集模式（RX）:
下位机 ──UDP:9001──▶ recvfrom() ──▶ ringbuf_push() ──▶ stats_add()
                                      │
                                      ▼
                                 ringbuf_pop() ──▶ fwrite(.bin)

发送模式（TX）:
coe_parse() ──▶ build_data_packet() ──▶ send() ──▶ Sleep(interval) ──▶ loop
```

| 模块 | 职责 |
|------|------|
| `main.c` | CLI 解析、初始化、采集/发送双模式、`_kbhit`+`PeekNamedPipe` 双重 stdin 检测、Packet 构建 |
| `udp.c` | socket 创建（数据口 bind + 命令口 connect + TX 口 connect）、recvfrom/sendto 封装 |
| `ringbuf.c` | SPSC 环形缓冲区，`CRITICAL_SECTION` 保护 |
| `writer.c` | 从缓冲区取数据写 bin 文件，按大小自动切分 |
| `stats.c` | 收包计数、速率/带宽计算、`stats_total_bytes()` 供总量限制查询 |
| `coe.c` | .coe 文件解析，提取 memory_initialization_vector hex 数据为字节数组 |
| `gui/launcher.py` | Python tkinter GUI，`subprocess.Popen` 启动 CLI（`CREATE_NO_WINDOW` 无终端弹窗），管道捕获输出，参数持久化，COE 发送 |

## 关键设计决策

- **数据格式**：RX 模式：UDP 载荷 = 原始 AD 采样数据，无协议头，透明写盘。TX 模式：数据包 = 引导码(8B) + 数据地址(1B) + 序号(1B) + coe数据(≤1200B)
- **命令格式**：二进制，START/STOP 命令包 = 引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)，通过 UDP 9002 发送。`--cmd-start` 指定开始信号（默认01），`--cmd-stop` 指定停止信号（默认00）
- **端口约定**：`--data-port` = PC 端 `bind()` 监听端口（下位机→PC 收数据）；`--cmd-port` = 发送端口（PC→下位机 发命令+coe数据）
- **文件命名**：`<启动时间YYYYMMDD_HHmmss>_<序号0001起>.bin`，每 10MB 切分（可自定义，最大 1024MB）
- **退出信号**：`SetConsoleCtrlHandler` 捕获 CTRL_C/BREAK/CLOSE，设 `g_running = false`
- **GUI ↔ CLI 协议**：CLI 输出 `[__GUI_PROMPT__]` 标记，GUI 检测后自动向 stdin 写回车
- **stdin 双重检测**：CLI 启动轮询同时检测控制台 `_kbhit()` 和管道 `PeekNamedPipe()`，兼容终端直接运行和 GUI `subprocess.PIPE` 启动
- **控制台编码**：`SetConsoleOutputCP(CP_UTF8)` + ACP→UTF-8 路径转换，解决 Windows 控制台中文乱码
- **参数持久化**：点击"开始采集"时自动保存 GUI 参数到 `gui_config.json`，下次启动自动加载
- **无终端启动**：`run_gui.vbs` 使用 VBS `WScript.Shell.Run(,0)` 完全隐藏终端；CLI 进程以 `CREATE_NO_WINDOW` 启动不弹窗
- **内核 UDP 接收缓冲**：`SO_RCVBUF` 设为 128MB，减少千兆线速下内核丢包
- **COE 发送模式**：`--coe-file` 指定 .coe 文件进入发送模式，解析 Xilinx .coe 格式 hex 数据，按 1200B 分包发送，可配置引导码/地址/发送间隔
- **Packet 构建**：`build_data_packet()` 构建数据包，`build_cmd_packet()` 构建命令包，均在 main.c 中

完整的编码约定、API 签名、设计决策细节见 `.claude/skills/ethernet-cap/SKILL.md`。
