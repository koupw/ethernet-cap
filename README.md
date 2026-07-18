# 以太网上位机 (Ethernet Capture)

Windows C 语言以太网上位机，通过 UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式直接存盘。支持读取 Xilinx .coe 文件数据发送到下位机。Python tkinter GUI 提供图形化控制，PyQtGraph 提供 GPU 加速波形查看。

## 快速开始

### 编译

```bash
# C 主程序（C11 / MinGW GCC / Winsock2）
gcc -std=c11 -Wall -Wextra -Isrc -o build/ethernet-cap.exe src/*.c -lws2_32

# 或使用 Makefile
make
```

### 安装 Python 依赖

```bash
venv\Scripts\pip.exe install pyqtgraph PySide6 numpy
```

### 运行

```bash
# 命令行 — 采集模式
build/ethernet-cap.exe -d 192.168.1.10

# 命令行 — COE 发送模式
build/ethernet-cap.exe -d 192.168.1.10 --coe-file signal.coe

# GUI 启动
venv\Scripts\python.exe gui\launcher.py

# 一键启动（双击，无终端窗口）
run_gui.vbs
```

### 运行测试

```bash
make test
# 或手动:
gcc -std=c11 -Wall -Wextra -Isrc -Itests -o tests/runtests.exe tests/*.c src/ringbuf.c src/coe.c src/stats.c src/utils.c -lws2_32
./tests/runtests.exe
```

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-d <ip>` | 必需 | 下位机 IP 地址 |
| `-o <path>` | `.` | 输出目录 |
| `--data-port N` | `9001` | PC 端数据接收端口 |
| `--cmd-port N` | `9002` | 命令/数据发送端口 |
| `-s <MB>` | `10` | 单文件切分大小（最大 1024MB） |
| `-b <MB>` | `128` | 环形缓冲区大小 |
| `-t <sec>` | `5` | 接收超时秒数 |
| `-T <MB>` | `0` | 总采集量上限（0=无限制） |
| `--local-ip <ip>` | `INADDR_ANY` | 本机绑定 IP |
| `--cmd-start <hex>` | `01` | 自定义开始命令信号 |
| `--cmd-stop <hex>` | `00` | 自定义停止命令信号 |
| `--coe-file <path>` | — | COE 文件路径（进入发送模式） |
| `--tx-interval <ms>` | `1` | COE 发送间隔 |
| `--preamble <hex>` | `A5...D5` | 引导码（8 字节） |
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

**4 线程**：主线程（CLI/GUI 交互 + 总量检查）— 收包线程（recvfrom 循环）— 写盘线程（环形缓冲消费 + 自动切分）— 统计线程（每秒速率/带宽打印）

### 模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口/配置 | `src/main.c` | CLI 解析、初始化、采集/发送双模式、Packet 构建、`wait_for_enter` 双重 stdin |
| UDP 通信 | `src/udp.c` | socket 创建（bind/connect 分离）、收发封装 |
| 环形缓冲区 | `src/ringbuf.c` | 无锁 SPSC 环形缓冲（`_Atomic size_t` + Event 唤醒） |
| 文件写入 | `src/writer.c` | 缓冲消费，预分配 chunk，按大小切分写 bin |
| 统计上报 | `src/stats.c` | 收包计数、速率/带宽计算、累计字节查询 |
| COE 解析 | `src/coe.c` | Xilinx .coe 文件流式解析（strtoul 优化），提取 hex 数据 |
| 工具函数 | `src/utils.c` | ACP→UTF-8 路径转换、简易日志系统（LOG_INFO/WARN/ERROR） |
| 深色主题 | `gui/dark_theme.py` | 统一 clam 主题 + VS Code Dark+ 配色（共享于上位机和波形查看器） |
| GUI 启动器 | `gui/launcher.py` | tkinter 深色界面，参数折叠/Spinbox，状态栏，日志搜索 |
| 波形查看器 | `gui/waveform_viewer.py` | PyQtGraph GPU 加速渲染，游标测量，自适应缩放，文件浏览器 |
| 一键启动 | `run_gui.vbs` | VBS 无终端窗口启动 |

### 数据格式

**RX 模式（采集）**：UDP 载荷 = 原始 AD 采样数据，无协议头，透明写盘。
- 文件命名：`<时间>_<序号>.bin`（如 `20260528_153000_0001.bin`）
- 文件切分：默认 10MB，`-s` 可自定义（最大 1024MB）
- 数据编码：int16 big-endian，14-bit ADC (±8192 → ±5V)，250MHz 采样率

**TX 模式（发送）**：
- 数据包：引导码(8B) + 数据地址(1B) + 序号(1B, 从1递增) + 载荷(≤1200B)
- 命令包：引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)

## GUI

### 上位机（launcher.py）

- 🎨 **深色专业主题**（VS Code Dark+ 风格，clam 引擎）
- ✅ **参数分页折叠**：COE 参数默认折叠，减少视觉杂乱
- 📊 **底部状态栏**：● 运行/就绪 | IP | 累计数据量
- 🔍 **日志搜索**：关键词高亮，可清空
- 🔢 **Spinbox 数字输入**：端口范围 1-65535，文件大小 1-1024MB 等
- 💾 参数持久化到 `gui_config.json`，下次启动自动加载
- 🟦 开始采集（蓝）+ 停止（红）强调色按钮

### 波形查看器（waveform_viewer.py）— PyQtGraph 独立进程

- 🚀 **OpenGL 硬件加速渲染**，远超 matplotlib 性能
- 🎯 **游标测量**：左键双击 A，右键双击 B，可拖拽，实时显示 Δt/ΔV/频率
- 🔍 **自适应缩放**：放大 <~5000 样本自动切换为原始采样线；缩小显示 min/max 包络
- 📋 **侧边文件列表**：自动列出目录中所有 .bin，点击切换
- 🔄 **自动刷新**：勾选后每秒检测新文件
- ⚡ **原生 zoom/pan**：滚轮缩放 + 右键拖拽平移（无需工具栏）
- 🖼️ PNG 导出
- 🎨 深色主题（与上位机统一）
- 🧵 独立进程运行（subprocess.Popen），不阻塞上位机

## 目录结构

```
ethernet-cap/
├── src/                    # C 源代码
│   ├── main.c              # 入口、CLI、采集/发送控制
│   ├── udp.c / udp.h       # UDP socket 封装
│   ├── ringbuf.c / .h      # 无锁 SPSC 环形缓冲区 (_Atomic + Event)
│   ├── writer.c / .h       # 文件写入 + 自动切分
│   ├── stats.c / .h        # 统计（包数/速率/带宽/累计）
│   ├── coe.c / coe.h       # COE 流式解析
│   ├── utils.c / utils.h   # ACP→UTF-8 + 日志系统
│   └── types.h             # 公共类型与常量
├── gui/
│   ├── launcher.py         # tkinter 深色上位机 GUI
│   ├── dark_theme.py       # 统一深色主题色板
│   └── waveform_viewer.py  # PyQtGraph 波形查看器（独立进程）
├── tests/
│   ├── runtests.c          # 测试运行器
│   ├── test_common.h       # 测试断言宏
│   ├── test_ringbuf.c      # 环形缓冲测试 (5项)
│   ├── test_coe.c          # COE 解析测试 (3项)
│   ├── test_utils.c        # 工具函数测试 (1项)
│   └── test_stats.c        # 统计模块测试 (2项)
├── build/                  # 编译输出
├── Makefile
├── run_gui.vbs             # 一键启动脚本
├── gui_config.json         # GUI 参数持久化（gitignore）
└── .claude/                # Claude Code 项目配置
```

## 技术要点

- **C11** 标准，`_Atomic` 原子操作，`stdatomic.h`
- **无锁 SPSC 环形缓冲**：`_Atomic size_t` + memory_order acquire/release + Windows Event 唤醒，替代 CRITICAL_SECTION
- **UDP 单播**，不实现应用层重传，`SO_RCVBUF` 128MB 内核缓冲
- **停止命令 ACK**：发送后等待设备确认（3次重试 × 200ms 超时，向后兼容）
- **双重 stdin 检测**：`_kbhit()` + `PeekNamedPipe()`，兼容终端与 GUI 管道
- **控制台编码**：`SetConsoleOutputCP(CP_UTF8)` + `acp_to_utf8()` 路径转换
- **简易日志系统**：`LOG_INFO/WARN/ERROR` 带时间戳
- **优雅退出**：`SetConsoleCtrlHandler` 捕获信号，自动发送 STOP 命令
- **单元测试 11/11**：环形缓冲 (5) + COE 解析 (3) + 工具函数 (1) + 统计 (2)

## 依赖

### C 编译
- MinGW GCC（C11）或 MSVC
- Windows Winsock2（系统自带）

### Python GUI
- `tkinter`（Python 3 内置）
- `numpy` — 波形数据处理
- `pyqtgraph` — GPU 加速波形渲染
- `PySide6` — Qt 绑定（pyqtgraph 依赖）
