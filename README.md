# 以太网上位机 (Ethernet Capture)

Windows C 语言以太网上位机，通过 UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式直接存盘。支持读取 Xilinx .coe 文件数据发送到下位机。Python tkinter GUI 提供图形化控制。

## 快速开始

### 编译

```bash
gcc -std=c11 -Wall -Wextra -Isrc -o build/ethernet-cap.exe src/*.c -lws2_32
```

需要 MinGW GCC（或 MSVC），Windows 平台，链接 Winsock2。

### 运行

```bash
# 命令行 — 采集模式
build/ethernet-cap.exe -d 192.168.1.10

# 命令行 — COE 发送模式
build/ethernet-cap.exe -d 192.168.1.10 --coe-file signal.coe

# GUI 启动（Python 3，仅需内置 tkinter）
venv\Scripts\python.exe gui\launcher.py

# 一键启动（双击，无终端窗口）
run_gui.vbs
```

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-d <ip>` | 必需 | 下位机 IP 地址 |
| `-o <path>` | `.` | 输出目录 |
| `--data-port N` | `9001` | PC 端数据接收端口 |
| `--cmd-port N` | `9002` | 命令/数据发送端口 |
| `-s <MB>` | `10` | 单文件切分大小 |
| `-b <MB>` | `32` | 环形缓冲区大小 |
| `-t <sec>` | `5` | 接收超时秒数 |
| `-T <MB>` | `0` | 总采集量上限（0=无限制） |
| `--local-ip <ip>` | `INADDR_ANY` | 本机绑定 IP |
| `--cmd-start <hex>` | `01` | 自定义开始命令信号 |
| `--cmd-stop <hex>` | `00` | 自定义停止命令信号 |
| `--coe-file <path>` | — | COE 文件路径（进入发送模式） |
| `--tx-interval <ms>` | `1` | COE 发送间隔 |
| `--preamble <hex>` | `A5 A5 A5 A5 A5 A5 A5 D5` | 引导码（8 字节） |
| `--data-addr <hex>` | `01` | 数据包地址域 |
| `--cmd-addr <hex>` | `02` | 命令包地址域 |

## 架构

### 线程模型

```
采集模式（RX）:
下位机 ──UDP:9001──▶ recvfrom() ──▶ ringbuf_push() ──▶ stats_add()
                                      │
                                      ▼
                                 ringbuf_pop() ──▶ fwrite(.bin)

发送模式（TX）:
coe_parse() ──▶ build_data_packet() ──▶ send() ──▶ Sleep(interval) ──▶ loop
```

4 线程：主线程（CLI/GUI 交互 + 总量检查）— 收包线程（recvfrom 循环）— 写盘线程（环形缓冲消费）— 统计线程（每秒速率打印）

### 模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口/配置 | `src/main.c` | CLI 解析、初始化、采集/发送双模式、Packet 构建 |
| UDP 通信 | `src/udp.c` | socket 创建（bind/connect 分离）、收发封装 |
| 环形缓冲区 | `src/ringbuf.c` | SPSC 环形缓冲，`CRITICAL_SECTION` 保护 |
| 文件写入 | `src/writer.c` | 缓冲消费，按大小切分写 bin |
| 统计上报 | `src/stats.c` | 收包计数、速率/带宽计算、累计字节查询 |
| COE 解析 | `src/coe.c` | Xilinx .coe 文件解析，提取 hex 数据为字节数组 |
| GUI 启动器 | `gui/launcher.py` | tkinter 图形界面，参数持久化，实时日志 |
| 一键启动 | `run_gui.vbs` | VBS 无终端窗口启动 |

## 数据格式

### RX 模式（采集）

UDP 载荷 = 原始 AD 采样数据，无协议头，透明写盘。文件命名 `<时间>_<序号>.bin`（如 `20260528_153000_0001.bin`），每 10MB 切分。

### TX 模式（发送）

**数据包**：引导码(8B) + 数据地址(1B) + 序号(1B, 从1递增) + 载荷(≤1200B)

**命令包**：引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)

## GUI

![GUI Screenshot](gui_screenshot_20260511_230218.png)

- 参数持久化到 `gui_config.json`，下次启动自动加载
- 实时日志输出，暗色主题
- CLI 进程 `CREATE_NO_WINDOW` 启动，无终端弹窗
- 运行时自动检测 `__GUI_PROMPT__` 标记并发送 Enter

## 目录结构

```
ethernet-cap/
├── src/                 # C 源代码
│   ├── main.c           # 入口、CLI、采集/发送控制
│   ├── udp.c / udp.h    # UDP socket 封装
│   ├── ringbuf.c / .h   # 环形缓冲区
│   ├── writer.c / .h    # 文件写入
│   ├── stats.c / .h     # 统计
│   ├── coe.c / coe.h    # COE 解析
│   └── types.h          # 公共类型与常量
├── gui/
│   └── launcher.py      # tkinter GUI 启动器
├── build/               # 编译输出
├── run_gui.vbs          # 一键启动脚本
├── gui_config.json      # GUI 参数持久化（gitignore）
└── .claude/             # Claude Code 项目配置
```

## 技术要点

- **C11** 标准，Windows Winsock2 API
- **UDP 单播**，不实现应用层重传
- **SO_RCVBUF 64MB** 内核缓冲，减少千兆线速下丢包
- **双重 stdin 检测**：`_kbhit()` + `PeekNamedPipe()`，兼容终端与 GUI 管道
- **控制台编码**：`SetConsoleOutputCP(CP_UTF8)` + ACP→UTF-8 路径转换
- **优雅退出**：`SetConsoleCtrlHandler` 捕获信号，自动发送 STOP 命令
