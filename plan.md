# 方案 A：统一 Qt 架构 — 详细实施计划

> 状态：计划阶段，未实施
> 更新：2025-07-19（最终版）

---

## 一、目标

用 PySide6 统一主窗口，替代当前 tkinter 启动器 + 独立 PyQtGraph 波形查看器的双进程模式。

## 二、架构总览

```
┌─────────────────────────────────────────────────────────┐
│  QMainWindow — unified_app                              │
│  ┌──────────┬──────────────────────────────────────────┐│
│  │ Sidebar  │  QStackedWidget                          ││
│  │          │  ┌─ Page 1: 采集控制 ──────────────────┐ ││
│  │ 📊 采集  │  │  CapturePanel（参数 + COE折叠）      │ ││
│  │          │  │  [开始采集] [停止] [发送COE数据]     │ ││
│  │ 📈 波形  │  ├──────────────────────────────────────┤ ││
│  │          │  │  LogPanel（日志 + 搜索）             │ ││
│  │ 📁 文件  │  └──────────────────────────────────────┘ ││
│  │          │  ┌─ Page 2: 波形显示 ──────────────────┐ ││
│  │          │  │  WaveformWidget（嵌入 PyQtGraph）    │ ││
│  │          │  │  纯离线模式：mmap + 视口切片         │ ││
│  │          │  │  自适应渲染 + 游标 + 导出            │ ││
│  │          │  └──────────────────────────────────────┘ ││
│  │          │  ┌─ Page 3: 文件管理 ──────────────────┐ ││
│  │          │  │  FileBrowser（QTreeView + 自动刷新） │ ││
│  │          │  └──────────────────────────────────────┘ ││
│  └──────────┴──────────────────────────────────────────┘│
│  StatusBar: ● 就绪 | 192.168.1.10 | 累计: 16MB | …      │
└─────────────────────────────────────────────────────────┘
```

## 三、统一采集模式

不区分模式一/二，合并为单一采集流程。停止触发条件：**阈值 / 超时 / 手动停止，谁先到谁停。**

```
FPGA 发数据 ──▶ C 引擎收 ──▶ 累计达到阈值?
                                  │  是 → 自动发送 STOP → 退出
                                  │  否 → 继续
                              超时无数据?
                                  │  是 → 自动退出
                                  │  否 → 继续
                              用户点 [停止]?
                                  │  是 → CTRL_BREAK → 退出
                                  ↓
                          ringbuf 排空 → 写盘完成
                                  ↓
                          xxx.bin（单文件，无序号）
                                  ↓
                          C 进程退出(return 0)
                                  ↓
                  ☑ 自动显示波形 → 打开 xxx.bin（离线模式）
```

| 参数 | 说明 |
|------|------|
| 采集阈值（`-T`） | 累计收到 N MB 后自动停。0 = 不限制，靠超时或手动 |
| 超时（`-t`） | N 秒无数据自动停 |
| 文件不切分 | 始终产出单个 xxx.bin，无 `_0001` 序号后缀 |

| 场景示例 | 阈值 | 超时 | 结果 |
|----------|------|------|------|
| FPGA 发 5MB 后停 | 0 | 3s | 超时触发，xxx.bin（5MB） |
| FPGA 连续发送 | 16MB | — | 阈值触发，xxx.bin（16MB） |
| 用户手动停 | — | — | 立即退出，xxx.bin |
| FPGA 发 10MB 后停 | 16MB | 3s | 超时触发，xxx.bin（10MB） |

## 四、文件保存策略

| 当前行为 | 改为 |
|---------|------|
| 按 `-s` 自动切分成多个 .bin | **不切分**，始终单个文件 |
| `xxx_0001.bin, xxx_0002.bin...` | `xxx.bin`（无序号后缀） |
| `-s` 控制切分大小 | `-s` 废弃，改用 `-T` 阈值控制停止 |

**C 端改动（writer.c）：**

```c
// 移除自动切分逻辑，始终写同一个文件
// 文件名不拼接序号
snprintf(path, sizeof(path), "%s\\%s.bin", w->output_dir, w->start_time);

// 写完立即刷到 OS 缓存（后续可选）
fflush(w->file);
```

## 五、文件结构

```
gui/
├── main_window.py           # QMainWindow — 统一入口（新建）
├── dark_theme.py            # 不动（色板字典 + QSS 常量）
├── widgets/
│   ├── __init__.py
│   ├── capture_panel.py     # 采集参数 + COE 折叠（新建）
│   ├── waveform_widget.py   # 波形组件（新建，从 viewer 提取）
│   ├── file_browser.py      # 文件浏览器（新建）
│   └── log_panel.py         # 日志面板 + 搜索高亮（新建）
├── engine/
│   ├── __init__.py
│   └── process_manager.py   # QProcess 管理 C 引擎（新建）
├── models/
│   ├── __init__.py
│   └── config.py            # QSettings 配置（新建）
├── waveform_viewer.py       # 保留独立运行入口（修改，委托 WaveformWidget）
└── launcher.py              # 兼容入口（修改，调 main_window）
```

## 六、实施阶段

---

### 阶段 1：主窗口骨架 + Process 管理（约 2h）

**新建文件：**

| 文件 | 内容 |
|------|------|
| `gui/main_window.py` | `class MainWindow(QMainWindow)`：<br>• 侧边栏 QListWidget（图标 + 文字导航：采集 / 波形 / 文件）<br>• QStackedWidget（3 页占位）<br>• StatusBar（状态灯 + IP + 累计数据 + 速率）<br>• 菜单栏（文件 / 视图 / 帮助）<br>• 全局深色主题（QSS + pyqtgraph 配置）<br>• `show()` 入口函数 |
| `gui/engine/process_manager.py` | `class ProcessManager(QObject)`：<br>• QProcess 替代 subprocess.Popen<br>• 信号：`log_received(str)`, `process_finished(int)`, `status_changed(bool)`<br>• `__GUI_PROMPT__` 检测：`readyReadStandardError` → 匹配 sentinel → `write(b"\n")`<br>• `start_capture(config)` / `start_tx_mode(coefile, config)` / `stop()`<br>• 停止时发送终止信号（terminate / CTRL_BREAK） |
| `gui/widgets/log_panel.py` | `class LogPanel(QWidget)`：<br>• QPlainTextEdit（只读，Consolas 等宽字体）<br>• 搜索 QLineEdit + QSyntaxHighlighter 高亮<br>• 清空按钮 + 自动滚动 toggle<br>• 行数上限 10000 自动裁剪 |

**验证标准：**
- 启动主窗口 → 深色主题正常渲染
- 点击侧边栏 → QStackedWidget 正确切换 3 个占位页
- 日志面板：写入文本 → 自动滚动 → 搜索高亮 → 清空

---

### 阶段 2：采集面板 + 单文件模式（约 2h）

**新建文件：**

| 文件 | 内容 |
|------|------|
| `gui/widgets/capture_panel.py` | `class CapturePanel(QWidget)`：<br><br>**基本参数：**<br>• 下位机 IP：QLineEdit（必填，红色星号）<br>• 本机 IP：QLineEdit（可选）<br>• 数据端口：QSpinBox（1-65535，默认 9001）<br>• 命令端口：QSpinBox（1-65535，默认 9002）<br>• 输出目录：QLineEdit + "…" → QFileDialog.getExistingDirectory<br>• 采集阈值：QSpinBox（0-1024 MB，默认 16，0=不限制）<br>• 缓冲大小：QSpinBox（1-4096 MB，默认 128）<br>• 超时时间：QSpinBox（1-3600 秒，默认 3）<br>• 开始命令：QLineEdit（hex，默认 01）<br>• 停止命令：QLineEdit（hex，默认 00）<br><br>**COE 参数（QGroupBox，默认折叠）：**<br>• COE 文件：QLineEdit + "…" → QFileDialog.getOpenFileName(*.coe)<br>• 发送间隔：QSpinBox（1-60000 ms，默认 1）<br>• 引导码：QLineEdit（hex，默认 A5 A5 A5 A5 A5 A5 A5 D5）<br>• 数据地址：QLineEdit（hex，默认 01）<br>• 命令地址：QLineEdit（hex，默认 02）<br><br>**按钮：**<br>• [开始采集]：蓝色强调按钮 → ProcessManager.start_capture()<br>• [停止]：红色按钮 → ProcessManager.stop()<br>• [发送COE数据]：→ ProcessManager.start_tx_mode()<br><br>**选项：**<br>• ☑ 停止后自动显示波形 |

| `gui/models/config.py` | `class ConfigModel(QObject)`：<br>• QSettings 替代 gui_config.json<br>• `save()` / `load()`：遍历参数自动序列化<br>• `get_args()`：返回 CLI 参数列表（复用 FLAG_SPEC 逻辑）<br>• 信号：`config_changed()` |

**C 端微调：**

| 文件 | 改动 |
|------|------|
| `src/types.h` | 新增 `MAX_FILE_SIZE_MB = 0` 表示不切分 |
| `src/writer.c` | 移除切分逻辑，文件名不加序号，始终单文件，统计 bytes_written |
| `src/main.c` | CLI 参数 `-s` 废弃，打印提示；`-T` 保持现有逻辑（阈值触发 stop + ACK） |

**tkinter → Qt 控件映射：**

| tkinter 控件 | Qt 控件 |
|-------------|---------|
| `ttk.Entry` | `QLineEdit` |
| `ttk.Spinbox` | `QSpinBox` |
| `ttk.Checkbutton` | `QCheckBox` |
| `ttk.Button` | `QPushButton` |
| `tk.Text` | `QPlainTextEdit` |
| `filedialog.askdirectory` | `QFileDialog.getExistingDirectory` |
| `filedialog.askopenfilename` | `QFileDialog.getOpenFileName` |

**验证标准：**
- 所有参数正确映射到 Qt 控件
- 输入参数 → 开始采集 → QProcess 启动 → 日志实时输出
- `__GUI_PROMPT__` 自动触发回车
- 累计达到阈值 → C 进程自动退出 → 状态栏恢复
- 超时无数据 → C 进程自动退出
- COE 折叠面板正常展开/折叠
- COE 文件发送正常
- 关闭窗口 → QSettings 自动保存参数
- 重新打开 → 参数自动恢复

---

### 阶段 3：波形组件（约 1.5h）

**纯离线模式，不需实时 mmap 轮询。**

**新建文件：**

| 文件 | 内容 |
|------|------|
| `gui/widgets/waveform_widget.py` | `class WaveformWidget(QWidget)`：从 waveform_viewer.py 提取核心渲染逻辑<br><br>**加载：**<br>• `load_file(filepath)` → mmap 文件（零全量加载）→ `_replot()`<br>• 文件大小无上限<br><br>**渲染：**<br>• `_replot()` → downsample → `_render_adaptive()`<br>• `_render_envelope()`：FillBetweenItem min/max 包络<br>• `_render_raw_line()`：视口切片原始采样线<br>• 递归守卫 `_in_range_handler`<br><br>**游标：**<br>• 左键双击 → 游标 A / 右键双击 → 游标 B<br>• 拖拽 → 实时 Δt / ΔV / 频率<br>• Delete 键清除<br><br>**导出：**<br>• PNG 导出<br><br>**保留全部已有功能：** 自适应渲染、zoom/pan、所有信号/槽 |
| `gui/waveform_viewer.py` | **修改**：<br>• 简化为 ~50 行：创建 QMainWindow + 嵌入 WaveformWidget<br>• 保留 `show(filepath, output_dir, fs)` 入口<br>• 保留 `--dir` CLI 参数和独立运行能力 |

**验证标准：**
- 打开任意大小 .bin → 缩放流畅，自适应切换正确
- 游标测量正确
- PNG 导出正确
- 独立运行：`python waveform_viewer.py --dir <path>` 正常
- 停止采集后 → 自动打开 .bin → 波形显示

---

### 阶段 4：文件浏览器 + 全局联动（约 2h）

**新建文件：**

| 文件 | 内容 |
|------|------|
| `gui/widgets/file_browser.py` | `class FileBrowser(QWidget)`：<br>• QTreeView + QFileSystemModel（过滤 *.bin）<br>• 列：文件名 / 大小 / 修改时间<br>• 双击 → 信号 `file_selected(path)`<br>• 右键菜单：打开 / 在资源管理器显示 / 删除<br>• ☑ 自动刷新 → QTimer(1s) |

**修改文件：**

| 文件 | 修改 |
|------|------|
| `gui/main_window.py` | 全局信号联动：<br>• 采集开始 → 自动切换到波形页<br>• `capture_started` → 记录输出目录<br>• `process_finished(0)` → 检测 checkbox → 自动打开 .bin<br>• `FileBrowser.file_selected(path)` → 波形页离线加载<br>• 侧边栏 → QStackedWidget 切换<br>• `ProcessManager.log_received` → LogPanel + StatusBar |

**验证标准：**
- 采集启动 → 文件列表出现新 .bin
- 双击文件 → 波形页加载
- 右键菜单正常
- 采集结束 → 自动打开波形（勾选时）
- 侧边栏切换流畅

---

### 阶段 5：打磨 + 文档（约 1.5h）

| 内容 | 说明 |
|------|------|
| 菜单栏完善 | 文件（打开项目/最近文件/退出）、视图（采集/波形/文件）、帮助（关于） |
| 快捷键 | `Ctrl+O` 打开文件，`F5` 采集，`Esc` 停止，`Ctrl+W` 查看波形 |
| 状态栏增强 | 实时速率（MB/s）、采集时长、累计数据量 |
| 窗口状态保持 | QSettings 保存窗口大小/位置/侧边栏宽度/当前页面 |
| `launcher.py` 更新 | 保留兼容入口：`from main_window import main; main()` |
| `run_gui.vbs` 更新 | 指向 main_window.py |
| `README.md` 更新 | 反映统一 Qt 架构、新参数、合并模式 |
| `AGENTS.md` 更新 | 更新架构说明和文件列表 |

---

## 七、功能保留清单

以下现有功能**全部保留**，仅迁移控件：

| 功能 | 当前实现 | 迁移目标 |
|------|---------|---------|
| 参数输入（标准+COE） | tkinter Entry/Spinbox | QLineEdit/QSpinBox |
| COE 文件发送 | subprocess + --coe-file | QProcess + 相同 CLI |
| 日志实时输出 + 搜索 | tkinter Text + tag | QPlainTextEdit + QSyntaxHighlighter |
| `__GUI_PROMPT__` 自动回车 | stderr 行检测 + stdin.write | readyReadStandardError 信号 + write |
| 参数持久化 | gui_config.json | QSettings |
| COE 参数折叠 | tkinter Frame toggle | QGroupBox checkable |
| 状态栏（状态灯/IP/数据量） | tkinter Label | QStatusBar + QLabel |
| 离线波形查看 | waveform_viewer 全部功能 | WaveformWidget（完整迁移） |
| 自适应渲染 + 游标 | 完整逻辑 | 完整迁移 |
| 文件浏览器 | QListWidget + auto-refresh | QTreeView + QFileSystemModel |
| 采集完成自动打开波形 | Checkbox + after(300) | QCheckBox + 信号联动 |

## 八、未来扩展预留

| 功能 | 预留方式 |
|------|---------|
| **项目工程 (.ecp)** | `models/` 目录已建，ConfigModel 可被子类化 |
| **设备自动发现** | ProcessManager 可扩展广播监听 |
| **实时 FFT 频谱** | WaveformWidget 新增 `_render_spectrum()`，侧边栏加"频谱"页 |
| **批量 COE 队列** | CapturePanel COE 区域预留列表控件占位 |
| **采集历史面板** | FileBrowser 扩展 QSortFilterProxyModel |
| **打包 (PyInstaller)** | 主入口 main_window.py，spec 指向 `main_window:main` |
| **NSIS 安装器** | 目录结构：runtime/ + app/ + ethernet-cap.exe |

---

## 九、不修改的部分

| 文件/目录 | 状态 |
|-----------|------|
| `src/main.c` | **微调**：`-s` 参数废弃提示 |
| `src/writer.c` | **微调**：移除切分逻辑，单文件无序号 |
| `src/types.h` | **微调**：允许 file_size = 0 |
| `src/udp.c/h` | 不动 |
| `src/ringbuf.c/h` | 不动 |
| `src/stats.c/h` | 不动 |
| `src/coe.c/h` | 不动 |
| `src/utils.c/h` | 不动 |
| `Makefile` | 不动 |
| `gui/dark_theme.py` | 不动（色板被新代码引用） |
| `tests/` | 不动 |
| `requirements.txt` | 无新增依赖 |

---

## 十、工时汇总

| 阶段 | 工时 | 依赖 |
|------|:--:|------|
| 1. 主窗口骨架 + Process 管理 | 2h | 无 |
| 2. 采集面板 + 单文件模式 | 2h | 阶段 1 |
| 3. 波形组件 | 1.5h | 阶段 1 |
| 4. 文件浏览器 + 全局联动 | 2h | 阶段 2+3 |
| 5. 打磨 + 文档 | 1.5h | 全部 |
| **合计** | **9h** | |
