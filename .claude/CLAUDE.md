# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概要

Windows C 语言以太网上位机，UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式直接存盘。支持读取 .coe 文件数据发送到下位机。Python tkinter GUI 提供图形化控制，PyQtGraph 提供 GPU 加速波形查看。

## 构建与运行

```bash
# 编译（C11 / MinGW GCC / Winsock2）
gcc -std=c11 -Wall -Wextra -Isrc -o build/ethernet-cap.exe src/*.c -lws2_32
# 或 make

# Python 依赖
venv\Scripts\pip.exe install pyqtgraph PySide6 numpy

# 命令行运行
build/ethernet-cap.exe -d <下位机IP> [选项]

# GUI 运行
venv\Scripts\python.exe gui\launcher.py

# 一键启动（双击即可，无终端窗口）
run_gui.vbs

# 单元测试
make test
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
| `main.c` | CLI 解析、初始化、采集/发送双模式、`_kbhit`+`PeekNamedPipe` 双重 stdin 检测、Packet 构建、`wait_for_enter()` |
| `udp.c` | socket 创建（数据口 bind + TX 口 connect）、recvfrom/sendto 封装 |
| `ringbuf.c` | **无锁 SPSC 环形缓冲区**（`_Atomic size_t` + memory_order + Event 唤醒） |
| `writer.c` | 从缓冲区取数据写 bin 文件，按大小自动切分，预分配 chunk |
| `stats.c` | 收包计数、速率/带宽计算、`stats_total_bytes()` 供总量限制查询；`stats_packets_per_sec()`/`stats_mbps()` 返回缓存值 |
| `coe.c` | .coe 文件流式解析（strtoul 优化），提取 memory_initialization_vector hex 数据为字节数组 |
| `utils.c` | **ACP→UTF-8 路径转换** (`acp_to_utf8()`)、**简易日志系统** (`LOG_INFO/WARN/ERROR` + 时间戳) |
| `types.h` | 公共类型与常量（config_t、默认值、包大小限制等） |
| `gui/dark_theme.py` | **统一深色主题**（clam + VS Code Dark+ 配色），共享于上位机和波形查看器 |
| `gui/launcher.py` | tkinter 深色 GUI，参数折叠/Spinbox/状态栏/日志搜索，`subprocess.Popen` 启动 CLI |
| `gui/waveform_viewer.py` | **PyQtGraph 独立进程**波形查看器（GPU 加速、自适应缩放、游标测量、文件浏览器） |

## 关键设计决策

- **数据格式**：RX：UDP 载荷 = 原始 AD 采样数据（int16 big-endian, 14-bit ADC, ±5V, 250MHz），无协议头，透明写盘。TX：数据包 = 引导码(8B) + 数据地址(1B) + 序号(1B) + coe数据(≤1200B)
- **命令格式**：二进制，START/STOP 命令包 = 引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)，通过 UDP 9002 发送。支持 `--cmd-start`/`--cmd-stop` 自定义信号
- **端口约定**：`--data-port` = PC 端 `bind()` 监听端口（下位机→PC 收数据）；`--cmd-port` = 发送端口（PC→下位机 发命令+coe数据）
- **文件命名**：`<启动时间YYYYMMDD_HHmmss>_<序号0001起>.bin`，每 10MB 切分（可自定义，最大 1024MB）
- **线程安全**：`atomic_bool g_running` (C11 `_Atomic`) 替代 `volatile bool`；无锁 SPSC 环形缓冲替代 CRITICAL_SECTION
- **退出信号**：`SetConsoleCtrlHandler` 捕获 CTRL_C/BREAK/CLOSE，设 `g_running = false`
- **停止命令 ACK**：发送停止命令后等待设备确认（3次重试 × 200ms 超时，向后兼容）
- **GUI ↔ CLI 协议**：CLI 输出 `[__GUI_PROMPT__]` 标记，GUI 检测后自动向 stdin 写回车
- **stdin 双重检测**：`wait_for_enter()` 同时检测 `_kbhit()` 和 `PeekNamedPipe()`，兼容终端和 GUI 管道
- **控制台编码**：`SetConsoleOutputCP(CP_UTF8)` + `acp_to_utf8()` 统一路径转换
- **参数持久化**：点击"开始采集"时自动保存 GUI 参数到 `gui_config.json`，下次启动自动加载
- **无终端启动**：`run_gui.vbs` 使用 VBS `WScript.Shell.Run(,0)` 完全隐藏终端；CLI 进程以 `CREATE_NO_WINDOW` 启动
- **SO_RCVBUF 128MB** 内核缓冲，减少千兆线速下内核丢包
- **COE 发送模式**：`--coe-file` 指定 .coe 文件进入发送模式，解析 Xilinx .coe 格式 hex 数据，按 1200B 分包发送
- **波形查看器独立进程**：`subprocess.Popen` 启动 PyQtGraph 查看器，彻底解耦 tkinter 和 Qt 事件循环
- **自适应渲染**：可视样本 <5000 → 原始采样线（放大看细节）；≥5000 → min/max 包络（缩放看全貌）
- **深色主题**：clam ttk 引擎 + VS Code Dark+ 配色，上位机和波形查看器统一风格

完整的编码约定、API 签名、设计决策细节见 `.claude/skills/ethernet-cap/SKILL.md`。
