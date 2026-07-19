# AGENTS.md (项目级)

> 全局行为准则见 `~/.zcode/AGENTS.md`。本文仅包含本项目特有的编码事实与规则。

## 项目概要

Windows C11 以太网上位机：UDP 采集 AD 数据存盘 + COE 发送 + Python GUI。
**两语言混合：C 引擎（CLI 进程）+ Python GUI（PySide6 统一界面）。**

## 快速命令

```bash
# C 编译（零警告要求）
mingw32-make                            # → ethernet-cap.exe

# 运行测试（11 项，必须全过）
mingw32-make test

# Python 依赖（在项目 venv 中）
venv\Scripts\pip.exe install pyqtgraph PySide6 numpy

# GUI 启动
venv\Scripts\python.exe gui\main_window.py

# 波形查看器单独启动
venv\Scripts\python.exe gui\waveform_viewer.py --dir <输出目录>

# 打包 exe
venv\Scripts\pyinstaller.exe ethernet-cap.spec --noconfirm
# → dist/ethernet-cap.exe (自包含，无需 Python 环境)
```

## 架构边界（不可违反）

| 边界 | 规则 |
|------|------|
| **C ↔ Python** | C 是独立 CLI 进程，Python 通过 QProcess 启动。**两者不能直接链接或导入。** |
| **线程模型** | C 端 4 线程：主线程、收包线程、写盘线程、统计线程。写盘线程通过 `ringbuf_wait_data()` 阻塞等待，不轮询。 |
| **环形缓冲** | SPSC（单生产者单消费者），`_Atomic size_t` + acquire/release 无锁。**不要改回 CRITICAL_SECTION。** |
| **文件产出** | 单文件模式，无切分，无序号。文件名格式：`{时间}.bin`。 |
| **停止机制** | C 端主循环用 `PeekNamedPipe` 检测 stdin 换行；GUI 通过 QProcess 写入 `\n` 优雅停止。 | 

## C 编码约定

- `stdatomic.h` 的 `atomic_bool` / `_Atomic size_t`，不用 `volatile` 做线程同步。
- 所有路径参数先过 `acp_to_utf8()` 再传 Windows API（中文路径兼容）。
- 日志统一用 `LOG_INFO/WARN/ERROR` 宏（`utils.h`），不用 `printf` 裸打。
- 编译必须 `-Wall -Wextra` 零警告（源码层面，test 警告属已知豁免）。
- `_kbhit()` + `PeekNamedPipe()` 双重检测 stdin，兼容终端和 GUI 管道。
- 写盘循环内**不要加 `fflush`**（严重拖慢吞吐）。

## Python 编码约定

- GUI 入口：`gui/main_window.py`，QMainWindow + 侧边栏 + QStackedWidget
- 进程管理：`gui/engine/process_manager.py`，QProcess 封装，`__GUI_PROMPT__` 检测
- 波形组件：`gui/widgets/waveform_widget.py`，可嵌入 QWidget + 独立运行
- 配置持久化：QSettings，key 与 CLI 参数对齐
- 波形查看器中的 np 数组一律用 `">i2"` dtype（int16 big-endian），电压转换 `value * 5.0 / 8192.0`
- 深色主题：main_window.py 内嵌 DARK_QSS；waveform_viewer.py 独立携带
- PyInstaller 路径：`sys._MEIPASS` 下取 `ethernet-cap-engine.exe`

## 已知坑点（切勿重犯）

1. **自适应渲染递归**：`_render_adaptive` 触发 `sigRangeChanged` 又回调自身。解决：`_in_range_handler` 递归守卫 + `try/finally`。
2. **PyQtGraph 跨线程信号**：工作线程不能用 `QTimer.singleShot`，必须用 `Signal.emit()`。
3. **COE kw_len 硬编码错误**：实际 `strlen("memory_initialization_vector")` = 28，不是 29。
4. **`_strnicmp` 在 C11 模式不可用**：需手写大小写不敏感循环。
5. **QFileSystemModel 替换顺序**：先建新模型 → `setModel()` → 再 `deleteLater()` 旧模型，否则悬空指针。
6. **CTRL_BREAK_EVENT 对子进程无效**：改用 stdin 写入 `\n` + C 端 `PeekNamedPipe` 检测。

## 关键文件索引

| 当需要了解… | 先读… |
|-------------|-------|
| 完整架构、设计决策 | `plan.md` |
| 用户文档、命令行参数 | `README.md` |
| CLI 入口与双模式逻辑 | `src/main.c` |
| 无锁环形缓冲实现 | `src/ringbuf.c` |
| 数据格式（RX/TX 包结构） | `src/types.h`、`src/main.c` 中 `build_data_packet()` |
| 文件写入（单文件模式） | `src/writer.c` |
| 主窗口 UI 布局 | `gui/main_window.py` |
| 采集面板 | `gui/widgets/capture_panel.py` |
| 波形渲染逻辑 | `gui/widgets/waveform_widget.py` |
| 配置持久化 | `gui/models/config.py` |
| C 引擎进程管理 | `gui/engine/process_manager.py` |
| PyInstaller 打包配置 | `ethernet-cap.spec` |
