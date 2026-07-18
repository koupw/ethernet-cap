---
name: ethernet-cap
description: |
  以太网上位机项目开发技能。当用户在此项目中请求开发、修改、讨论以太网上位机相关功能时触发。
  涵盖 UDP 通信、AD 数据采集、环形缓冲区、bin 文件落盘、COE 文件发送、Windows C 语言开发、
  PyQtGraph 波形查看、深色主题 GUI、自适应渲染。
  关键词：以太网、上位机、UDP、AD采集、数据采集、收包、环形缓冲、bin文件、coe、发送、
  波形查看、PyQtGraph、深色主题、游标测量。
  本技能仅适用于当前项目目录。
---

# 以太网上位机（Ethernet Capture）项目开发指引

## 项目概述

通过以太网（UDP 单播）与下位机（AD 采集设备）进行双向通信的 Windows 上位机程序。下发采集控制命令，接收 AD 采样数据并以 bin 格式直接存盘。Python tkinter 深色 GUI 启动器 + PyQtGraph 独立进程 GPU 加速波形查看器。

## 需求摘要

- **语言/平台**：C 语言（C11），Windows；Python 3 GUI
- **传输协议**：UDP 单播
- **端口分离**：数据端口 9001（收 AD 数据）、命令端口 9002（发命令+coe数据）
- **数据存储**：RX：UDP 载荷直接写 bin 文件，不解析协议。TX：发送带协议头的数据包
- **数据格式**：int16 big-endian，14-bit ADC (±8192 → ±5V)，250MHz 采样率
- **文件切分**：默认 10MB/文件（可配置，最大 1024MB）
- **文件命名**：`<启动时间YYYYMMDD_HHmmss>_<序号0001>.bin`
- **缓冲区**：128MB 无锁 SPSC 环形缓冲区（`_Atomic size_t` + Event 唤醒）
- **超时处理**：接收超时报警并退出
- **总量限制**：可设定采集总量上限（-T），达到后自动停止，1ms 精度检查
- **启动方式**：手动按 Enter 开始采集（Ctrl+C 可在等待期取消）
- **停止命令 ACK**：发送停止命令后等待设备确认（3次重试 × 200ms 超时，向后兼容）

## 已确认的设计决策

### 命令格式
- **二进制**格式，不使用文本命令
- START/STOP 命令包：引导码(8B) + 命令地址(1B=0x02) + 信号(1~NB)
- 命令通过 UDP 端口 9002 发送至下位机

### 数据包格式（TX 模式）
- **数据包**：引导码(8B) + 数据地址(1B=0x01) + 序号(1B, 从1递增) + coe数据(≤1200B)
- **命令包**：引导码(8B) + 命令地址(1B=0x02) + 开始信号(1~NB)
- 引导码默认：`A5 A5 A5 A5 A5 A5 A5 D5`

### 下位机数据（RX 模式）
- int16 big-endian，14-bit ADC (±8192 → ±5V)
- 单通道，250MHz 采样率
- 纯采样信号数据，无协议头，无包序号，透明写盘

### 环形缓冲区
- 默认大小：**128MB**
- **无锁 SPSC**：`_Atomic size_t` + memory_order acquire/release + Windows Event 唤醒消费者
- 单生产者（收包线程）、单消费者（写盘线程）

### 网络
- **单播**模式，不支持组播
- 数据接收端口 9001，发送端口 9002（均可配置）
- `SO_RCVBUF` 128MB 内核缓冲，减少千兆线速下丢包

### 线程安全
- `atomic_bool g_running`（C11 `_Atomic bool`）替代 `volatile bool`
- 收包线程 `while (atomic_load(&g_running))`，Ctrl+C 触发 `atomic_store(&g_running, false)`

## 架构设计

### 线程模型

```
┌────────────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│      主线程         │   │  收包线程     │   │  写盘线程     │   │  统计线程     │
│                    │   │              │   │              │   │              │
│ CLI 解析           │   │ recvfrom()  │   │ ringbuf_pop  │   │ Sleep(1000)  │
│ 初始化             │   │ ringbuf_push│   │ fwrite(.bin) │   │ 打印 pps     │
│ 信号处理           │   │ stats_add() │   │ 文件切分     │   │ 带宽 Mbps    │
│ wait_for_enter     │   │ 超时检测     │   │ Event 等待   │   │ 累计 MB      │
│ 发 START / 创建线程 │   │              │   │              │   │              │
│ 每 1ms 检查总量     │   │              │   │              │   │              │
│ 等待退出 / 清理     │   │              │   │              │   │              │
└────────────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

### 模块划分

| 模块 | 文件 | 职责 |
|------|------|------|
| 入口/配置 | `src/main.c` | CLI 解析、`wait_for_enter()` 双重 stdin、Packet 构建、总量检查(1ms) |
| UDP 通信 | `src/udp.c/h` | socket 创建（data bind + tx connect）、recvfrom/send 封装 |
| 环形缓冲区 | `src/ringbuf.c/h` | **无锁 SPSC**：`_Atomic size_t` + Event 唤醒 |
| 文件写入 | `src/writer.c/h` | 预分配 chunk，按大小切分写 bin |
| 统计上报 | `src/stats.c/h` | 速率/带宽缓存（`stats_packets_per_sec/mbps`） |
| COE 解析 | `src/coe.c/h` | 流式解析（strtoul 优化），kw_len 28 修正 |
| 工具函数 | `src/utils.c/h` | `acp_to_utf8()` 路径转换 + 简易日志系统 |
| 深色主题 | `gui/dark_theme.py` | 统一 clam + VS Code Dark+ 配色 |
| GUI 启动器 | `gui/launcher.py` | tkinter 深色界面，参数折叠/Spinbox/状态栏/日志搜索 |
| 波形查看器 | `gui/waveform_viewer.py` | PyQtGraph 独立进程，自适应缩放 + 游标测量 |
| 一键启动 | `run_gui.vbs` | VBS 无终端窗口启动 |
| 单元测试 | `tests/` | 11 项测试（ringbuf×5, coe×3, utils×1, stats×2） |

### GUI 启动器

`gui/launcher.py` 是 tkinter 深色 GUI：

**核心特性：**
- 🎨 深色主题（clam 引擎 + VS Code Dark+ 配色）
- ✅ COE 参数区可折叠（▶/▼ 切换）
- 📊 底部状态栏：● 运行/就绪 | IP | 累计数据量
- 🔍 日志搜索框：关键词高亮，可清空，滚动跟随开关
- 🔢 Spinbox 数字输入（端口 1-65535、文件大小 1-1024MB 等）
- 🟦 开始采集（蓝按钮）/ 停止（红按钮）
- 💾 参数持久化 `gui_config.json`
- **独立进程波形查看器**：`subprocess.Popen` 启动 `gui/waveform_viewer.py`

### 波形查看器

`gui/waveform_viewer.py` 是 PyQtGraph 独立应用程序：

**核心特性：**
- 🚀 OpenGL 硬件加速渲染（远超 matplotlib）
- 🔍 **自适应缩放**：可视样本 <5000 → 原始采样线；≥5000 → min/max 包络
- 🎯 **游标测量**：左键双击 A / 右键双击 B，可拖拽，实时显示 Δt/ΔV/频率
- 📋 左侧文件列表（QListWidget），点击切换
- 🔄 自动刷新监控新文件（QTimer 1s）
- ⚡ 原生 zoom/pan（滚轮缩放 + 右键拖拽，无需工具栏）
- 🖼️ PNG 导出

**线程安全：**
- `data_loaded` Signal（QObject）跨线程传递数据
- `_in_range_handler` 递归防护（try/finally 包裹 _render_adaptive）
- Worker 线程不调用 QTimer.singleShot（仅 emit Signal）

## 编码约定

### C 语言标准
- C11 标准，`_Atomic` 原子操作，`stdatomic.h`
- Windows 平台，Winsock2 API
- 线程使用 Windows 原生 `CreateThread`

### 命名约定
- 函数：`snake_case`，模块前缀（如 `udp_init`、`ringbuf_push`）
- 结构体：`snake_case`，`_t` 后缀
- 常量/宏：`UPPER_SNAKE_CASE`
- Python：PascalCase 类名，snake_case 方法/变量

## 关键约束

- **不实现应用层重传**：依赖网络质量保证
- **RX 模式不做协议解析**：UDP 载荷即 AD 原始数据，透明存储
- **TX 模式带协议头**：数据包 = 引导码+地址+序号+数据，命令包 = 引导码+地址+信号
- **单文件最大 1024MB**：通过 `-s` 参数自定义，默认 10MB
- **Windows 无 `recvmmsg`**：使用 `recvfrom` 单包接收
- **无锁 SPSC 环形缓冲**：`_Atomic size_t` + memory_order acquire/release
- **波形查看器独立进程**：避免 tkinter 与 Qt 事件循环冲突
- **Python 依赖**：numpy, pyqtgraph, PySide6（不含 matplotlib）
