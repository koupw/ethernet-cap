# 以太网上位机 (Ethernet Capture)

Windows C11 以太网上位机，UDP 单播与 AD 采集下位机双向通信。下发 START/STOP 命令，接收 AD 采样数据以 bin 格式单文件存盘。支持 COE 文件发送。PySide6 统一 Qt GUI。

## 快速开始

### 编译 C 引擎

```bash
mingw32-make
```

### Python 依赖

```bash
venv\Scripts\pip.exe install pyqtgraph PySide6 numpy
```

### 运行

```bash
# GUI 启动（开发）
venv\Scripts\python.exe gui\main_window.py

# 波形查看器（独立）
venv\Scripts\python.exe gui\waveform_viewer.py --dir <输出目录>

# 打包为单文件 exe
venv\Scripts\pyinstaller.exe ethernet-cap.spec --noconfirm
# → dist/ethernet-cap.exe (63 MB, 无需 Python 环境)
```

### 运行测试

```bash
mingw32-make test
```

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-d <ip>` | 必需 | 下位机 IP 地址 |
| `-o <path>` | `.` | 输出目录 |
| `--data-port N` | `1234` | 数据接收端口 |
| `--cmd-port N` | `9002` | 命令发送端口 |
| `-b <MB>` | `128` | 环形缓冲区大小 |
| `-t <sec>` | `3` | 接收超时秒数 |
| `-T <MB>` | `0` | 采集阈值（0=不限制） |
| `--local-ip <ip>` | `INADDR_ANY` | 本机绑定 IP |
| `--cmd-start <hex>` | `01` | 开始命令信号 |
| `--cmd-stop <hex>` | `00` | 停止命令信号 |
| `--coe-file <path>` | — | COE 文件路径（发送模式） |
| `--tx-interval <ms>` | `1` | COE 发送间隔 |
| `--preamble <hex>` | `A5...D5` | 引导码（8 字节） |
| `--data-addr <hex>` | `01` | 数据包地址域 |
| `--cmd-addr <hex>` | `02` | 命令包地址域 |

> `-s` 已废弃。文件始终产出单个 `{时间}.bin`，不切分。

## 架构

### 线程模型

```
采集模式（RX）:
下位机 ──UDP:1234──▶ recvfrom() ──▶ ringbuf_push() ──▶ stats_add()
                                      │
                                      ▼
                                 ringbuf_pop() ──▶ fwrite(.bin)

发送模式（TX）:
coe_parse() ──▶ build_data_packet() ──▶ send() ──▶ Sleep(interval) ──▶ loop
```

**4 线程**：主线程 — 收包线程 — 写盘线程 — 统计线程。停止方式：阈值触发 / 超时 / stdin 换行 / Ctrl+C。

### 模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 主窗口 | `gui/main_window.py` | QMainWindow，三页切换（采集/波形/文件） |
| 采集面板 | `gui/widgets/capture_panel.py` | 参数输入 + COE 折叠 + 按钮 |
| 波形组件 | `gui/widgets/waveform_widget.py` | PyQtGraph 可嵌入波形（自适应渲染/游标） |
| 文件浏览器 | `gui/widgets/file_browser.py` | QTreeView 浏览 .bin |
| 日志面板 | `gui/widgets/log_panel.py` | 搜索高亮 + 自动滚动 |
| 进程管理 | `gui/engine/process_manager.py` | QProcess 封装，`__GUI_PROMPT__` 检测 |
| 配置模型 | `gui/models/config.py` | QSettings 持久化 |
| C 入口 | `src/main.c` | CLI 解析、采集/发送双模式、stdin 检测 |
| UDP 通信 | `src/udp.c` | socket 创建、收发封装 |
| 环形缓冲 | `src/ringbuf.c` | 无锁 SPSC（`_Atomic` + Event） |
| 文件写入 | `src/writer.c` | 单文件输出 |
| 统计 | `src/stats.c` | 速率/带宽/累计字节 |
| COE 解析 | `src/coe.c` | Xilinx .coe 流式解析 |
| 工具 | `src/utils.c` | ACP→UTF-8 + 日志宏 |

### 数据格式

- **RX**：UDP 载荷 = 原始 AD 采样数据，int16 big-endian，14-bit ADC，±5V，250MHz
- **TX**：引导码(8B) + 数据地址(1B) + 序号(1B) + 载荷(≤1200B)
- **命令包**：引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)
- **文件命名**：`{启动时间}.bin`，单文件无切分

## GUI

### 采集控制

- 🎨 深色主题（VS Code Dark+ 风格）
- 📊 采集/COE 参数并排，COE 可折叠
- 🔍 日志面板：搜索高亮 + 自动滚动
- 📡 阈值自动停 / 超时自动停 / 手动停止
- ☑ 停止后自动加载波形

### 波形显示

- 🚀 PyQtGraph OpenGL 硬件加速
- 🎯 游标测量：双击 A/B，拖拽显示 Δt/ΔV/频率
- 🔍 自适应缩放：放大 <5000 样本切换原始线
- 📁 文件浏览器：双击加载 .bin
- 🖼️ PNG 导出

## 技术要点

- C11 `_Atomic` 无锁 SPSC 环形缓冲
- `_kbhit()` + `PeekNamedPipe()` 双重 stdin 检测
- QProcess 管理 C 引擎，stdin 写入优雅停止
- ACP→UTF-8 中文路径兼容
- QSettings 参数持久化
- 单元测试 11/11

## 依赖

- **C**：MinGW GCC（C11）+ Winsock2
- **Python**：PySide6 + numpy + pyqtgraph
- **打包**：PyInstaller
