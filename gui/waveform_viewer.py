"""
波形查看器 — 读取 .bin 文件并按 AD 采样格式渲染波形

数据格式（从 MATLAB phase_analys 确认）:
  - int16, big-endian
  - 14-bit ADC, 满量程 ±8192 对应 ±5V
  - 单通道
  - 采样率 250 MHz（可在 GUI 中修改）

功能：
  - 深色专业主题
  - 游标测量（ΔV / Δt / 频率估算）
  - 侧边栏文件列表浏览
  - 自动刷新监控新文件
  - 峰值保留降采样渲染（保留毛刺细节）
  - 鼠标滚轮/框选缩放、平移
  - PNG 导出
"""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# --- 深色主题统一配置 ---
from dark_theme import apply_dark_theme, DARK_BG, DARK_PANEL, DARK_BORDER, ACCENT, TEXT, GRID_COLOR, CURSOR_COLOR

# --- 中文字体配置（Windows）---
import matplotlib.font_manager as fm

_CHINESE_FONTS = [
    "Microsoft YaHei",   # 微软雅黑
    "SimHei",            # 黑体
    "SimSun",            # 宋体
    "KaiTi",             # 楷体
    "FangSong",          # 仿宋
]

_available = {f.name for f in fm.fontManager.ttflist}
_chinese_font = None
for _fn in _CHINESE_FONTS:
    if _fn in _available:
        _chinese_font = _fn
        break

if _chinese_font:
    matplotlib.rcParams["font.family"]      = ["sans-serif"]
    matplotlib.rcParams["font.sans-serif"]  = [_chinese_font, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

# ---------------------------------------------------------------------------
# ADC / 数据格式常量（与 MATLAB 代码保持一致）
# ---------------------------------------------------------------------------
SAMPLE_DTYPE   = ">i2"    # big-endian int16
ADC_MAX        = 8192.0   # 14-bit
VOLTAGE_RANGE  = 5.0      # ±5V
SCALE_FACTOR   = VOLTAGE_RANGE / ADC_MAX


def downsample_for_display(data, target_width):
    """对大数据做峰值保留降采样（向量化版），每个像素列取 min/max pair。"""
    n = len(data)
    if n <= target_width * 2:
        return np.arange(n, dtype=np.float64), data, data

    block = max(1, n // target_width)
    cols = n // block
    truncated = data[:cols * block].reshape(cols, block)
    xs = (np.arange(cols, dtype=np.float64) * block + (block - 1) / 2.0)
    return xs, truncated.min(axis=1), truncated.max(axis=1)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class WaveformViewer:
    """独立的波形查看窗口。"""

    def __init__(self, parent=None, filepath=None, output_dir=None,
                 fs=250e6, theme=None):
        """
        Parameters
        ----------
        parent : tk.Widget or None
            父窗口。
        filepath : str or None
            直接打开的 .bin 文件路径。
        output_dir : str or None
            输出目录，用于自动检测最新 .bin。
        fs : float
            采样率 (Hz)，用于时间轴刻度。默认 250 MHz。
        theme : dict or None
            dark_theme.apply_dark_theme() 返回的色板。
        """
        self._fs = fs
        self._filepath = filepath
        self._output_dir = output_dir
        self._data = None

        # 游标状态
        self._cursor_a = None     # x 坐标（时间轴单位）
        self._cursor_b = None
        self._cursor_line_a = None
        self._cursor_line_b = None
        self._cursor_label_a = None
        self._cursor_label_b = None
        self._cursor_dragging = None  # None | "A" | "B"

        # 游标拖拽节流：防止 motion 事件密集触发重绘
        self._cursor_redraw_pending = False

        # 缓存数据统计（避免每次拖拽扫全数据）
        self._vmin_cache = None
        self._vmax_cache = None

        # 自动刷新状态
        self._auto_refresh = tk.BooleanVar(value=False)
        self._refresh_id = None
        self._last_file_mtime = 0

        # 程序化选择防护：防止 selection_set → TreeviewSelect 事件 →
        # _on_file_select → _load_and_display → _refresh_file_list 死循环
        self._suppress_select = False

        # 当前正在加载的文件路径：避免相同文件重复加载
        self._loading_path = None

        # 顶层窗口
        self.win = tk.Toplevel(parent)
        self.win.title("波形查看器")
        self.win.geometry("1280x780")
        self.win.minsize(900, 600)

        # 主题
        if theme:
            self.theme = theme
        else:
            from dark_theme import apply_dark_theme
            self.theme = apply_dark_theme(self.win)

        self.win.configure(bg=DARK_BG)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

        # 加载数据
        if filepath and os.path.isfile(filepath):
            self._load_and_display(filepath)
        elif output_dir:
            latest = self._find_latest_bin(output_dir)
            if latest:
                self._load_and_display(latest)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        # -- 顶部工具栏 --
        toolbar = ttk.Frame(self.win, padding=(8, 6))
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="打开文件",
                   command=self._on_open).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="刷新",
                   command=self._on_refresh).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="导出PNG",
                   command=self._on_export).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Button(toolbar, text="清游标",
                   command=self._clear_cursors).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(toolbar, text="采样率:").pack(side=tk.LEFT)
        self.fs_var = tk.StringVar(value=self._format_fs(self._fs))
        fs_entry = ttk.Entry(toolbar, textvariable=self.fs_var, width=8)
        fs_entry.pack(side=tk.LEFT, padx=(4, 2))
        fs_entry.bind("<Return>", lambda e: self._replot())

        ttk.Button(toolbar, text="应用",
                   command=self._replot).pack(side=tk.LEFT, padx=(2, 12))

        ttk.Checkbutton(toolbar, text="自动刷新",
                        variable=self._auto_refresh,
                        command=self._toggle_auto_refresh).pack(side=tk.LEFT,
                                                                 padx=(0, 12))

        self.file_label = ttk.Label(toolbar, text="", style="Note.TLabel")
        self.file_label.pack(side=tk.LEFT, padx=(0, 12))

        # -- 底部信息栏（统计 + 游标测量）--
        self.stats_label = ttk.Label(toolbar, text="", style="Note.TLabel")
        self.stats_label.pack(side=tk.RIGHT)

        # -- 主体：左侧文件列表 + 右侧图表 --
        body = ttk.Frame(self.win)
        body.pack(fill=tk.BOTH, expand=True)

        # 左侧文件列表
        sidebar = ttk.Frame(body, width=180)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        sidebar.pack_propagate(False)

        ttk.Label(sidebar, text="文件列表", style="Section.TLabel").pack(
            anchor=tk.W, padx=8, pady=(6, 4))

        list_frame = ttk.Frame(sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.file_tree = ttk.Treeview(list_frame, columns=("size",),
                                       show="tree headings", height=15)
        self.file_tree.heading("#0", text="文件名")
        self.file_tree.heading("size", text="大小")
        self.file_tree.column("#0", width=140)
        self.file_tree.column("size", width=50, anchor=tk.E)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tree_sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        # 初始填充文件列表
        self._refresh_file_list()

        # 右侧图表区
        chart_frame = ttk.Frame(body)
        chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(10, 5), dpi=100)
        self.fig.patch.set_facecolor(DARK_BG)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # matplotlib 导航工具栏
        nav_frame = ttk.Frame(self.win)
        nav_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, nav_frame)
        self.toolbar.update()
        self._style_nav_toolbar()

        # 鼠标事件绑定游标
        self.canvas.mpl_connect("button_press_event", self._on_canvas_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_canvas_motion)
        self.canvas.mpl_connect("button_release_event", self._on_canvas_release)

    def _style_axes(self):
        """配置 matplotlib axes 深色风格。"""
        self.ax.set_facecolor(DARK_BG)
        self.ax.tick_params(colors=TEXT, labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color(DARK_BORDER)
        self.ax.xaxis.label.set_color(TEXT)
        self.ax.yaxis.label.set_color(TEXT)
        self.ax.title.set_color(TEXT)
        self.ax.grid(True, alpha=0.2, color=GRID_COLOR, linestyle="-")

    def _style_nav_toolbar(self):
        """将 matplotlib NavigationToolbar2Tk 的按钮着色为深色。"""
        for child in self.toolbar.winfo_children():
            try:
                child.config(bg=DARK_PANEL, fg=TEXT, relief=tk.FLAT,
                             borderwidth=0, highlightthickness=0,
                             activebackground=DARK_BORDER,
                             activeforeground=TEXT)
            except tk.TclError:
                pass
        try:
            self.toolbar.config(bg=DARK_BG)
        except tk.TclError:
            pass
        try:
            self.toolbar._message_label.config(bg=DARK_BG, fg=TEXT)
        except (AttributeError, tk.TclError):
            pass

    # ------------------------------------------------------------------
    # 文件查找与列表管理
    # ------------------------------------------------------------------
    def _find_latest_bin(self, directory):
        """在目录中找最新的 .bin 文件。"""
        try:
            files = [f for f in os.listdir(directory) if f.endswith(".bin")]
            if not files:
                return None
            files.sort(key=lambda f: os.path.getmtime(
                os.path.join(directory, f)), reverse=True)
            return os.path.join(directory, files[0])
        except OSError:
            return None

    def _refresh_file_list(self):
        """刷新左侧文件列表。"""
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        if not self._output_dir:
            return

        try:
            files = [f for f in os.listdir(self._output_dir) if f.endswith(".bin")]
        except OSError:
            return

        # 按文件名排序
        files.sort()

        for f in files:
            full = os.path.join(self._output_dir, f)
            try:
                size = os.path.getsize(full)
                size_str = self._format_size(size)
            except OSError:
                size_str = "?"
            self.file_tree.insert("", tk.END, text=f, values=(size_str,))

        # 选中当前加载的文件（抑制事件以防止死循环）
        if self._filepath:
            current_name = os.path.basename(self._filepath)
            for item in self.file_tree.get_children():
                if self.file_tree.item(item, "text") == current_name:
                    self._suppress_select = True
                    self.file_tree.selection_set(item)
                    self.file_tree.focus(item)
                    self._suppress_select = False
                    break

    @staticmethod
    def _format_size(n):
        for unit in ["B", "K", "M", "G"]:
            if n < 1024:
                return f"{n:.0f}{unit}"
            n /= 1024
        return f"{n:.1f}T"

    def _on_file_select(self, event=None):
        """文件列表点击事件（程序化选择时跳过，避免死循环）。"""
        if self._suppress_select:
            return
        sel = self.file_tree.selection()
        if not sel:
            return
        fname = self.file_tree.item(sel[0], "text")
        if not self._output_dir:
            return
        full = os.path.join(self._output_dir, fname)
        # 防止相同文件重复加载（已加载则跳过）
        if self._filepath and os.path.normpath(self._filepath) == os.path.normpath(full):
            return
        if os.path.isfile(full):
            self._load_and_display(full)

    # ------------------------------------------------------------------
    # 自动刷新监控
    # ------------------------------------------------------------------
    def _toggle_auto_refresh(self):
        if self._auto_refresh.get():
            self._auto_refresh_loop()
        else:
            if self._refresh_id:
                self.win.after_cancel(self._refresh_id)
                self._refresh_id = None

    def _auto_refresh_loop(self):
        """每秒检测 output_dir 中新增 .bin 文件。"""
        if not self._auto_refresh.get():
            return

        # 刷新文件列表
        self._refresh_file_list()

        # 检查新文件
        if self._output_dir:
            latest = self._find_latest_bin(self._output_dir)
            if latest:
                mtime = os.path.getmtime(latest)
                if mtime > self._last_file_mtime:
                    self._last_file_mtime = mtime
                    # 如果当前没有数据或文件变了，自动加载最新文件
                    if self._filepath != latest:
                        self._load_and_display(latest)

        self._refresh_id = self.win.after(1000, self._auto_refresh_loop)

    # ------------------------------------------------------------------
    # 采样率格式化/解析
    # ------------------------------------------------------------------
    def _guess_fs_from_filename(self, filepath):
        """尝试从文件名推断采样率。默认返回预设采样率。"""
        return self._fs

    @staticmethod
    def _format_fs(fs):
        """将采样率格式化为友好字符串，如 250M、1.5G、500k。"""
        if fs >= 1e9:
            return f"{fs/1e9:g}G"
        if fs >= 1e6:
            return f"{fs/1e6:g}M"
        if fs >= 1e3:
            return f"{fs/1e3:g}k"
        return f"{fs:g}"

    @staticmethod
    def _parse_fs(s):
        """解析采样率字符串，支持 250M/2.5G/500k/1000000 等格式。"""
        s = s.strip()
        if not s:
            return 1.0
        mult = 1.0
        if s[-1] in "gG":
            mult = 1e9; s = s[:-1]
        elif s[-1] in "mM":
            mult = 1e6; s = s[:-1]
        elif s[-1] in "kK":
            mult = 1e3; s = s[:-1]
        return float(s) * mult

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def _load_and_display(self, filepath):
        """后台线程加载数据，完成后在主线程渲染。
        防止同一文件重复加载或并发加载。"""
        filepath = os.path.abspath(filepath)

        # 防重复：同一文件已加载则跳过（_data 非空才算已加载）
        if filepath == self._loading_path:
            return
        if (self._filepath and self._data is not None
                and os.path.normpath(filepath) == os.path.normpath(self._filepath)):
            return

        self._loading_path = filepath
        self.file_label.config(text="加载中...")
        self.win.config(cursor="watch")

        def worker():
            err_msg = None
            try:
                data = self._load_bin(filepath)
            except Exception as e:
                data = None
                err_msg = str(e)

            self.win.after(0, lambda: self._on_data_loaded(
                filepath, data, err_msg if data is None else None))

        threading.Thread(target=worker, daemon=True).start()

    def _load_bin(self, filepath):
        """读取 .bin 文件，返回电压数组 (float64)。

        优化：int16→float64 转换 + 电压缩放合并为一次分配，
        避免 intermediate copies。16MB 文件仅需 ~64MB 内存。"""
        filepath = os.path.abspath(filepath)
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"文件不存在: {filepath}")

        raw = np.fromfile(filepath, dtype=SAMPLE_DTYPE)
        if len(raw) == 0:
            raise ValueError("文件为空或格式不正确")

        # in-place 缩放：一次 float64 分配 + 乘法，避免 astype 产生临时副本
        result = raw.astype(np.float64, copy=False)
        result *= SCALE_FACTOR
        return result

    def _on_data_loaded(self, filepath, data, err_msg):
        """主线程回调：渲染数据。"""
        self.win.config(cursor="")
        self._loading_path = None
        if err_msg:
            self.file_label.config(text="加载失败", foreground=self.theme["text_red"])
            messagebox.showerror("加载失败", err_msg, parent=self.win)
            return

        self._filepath = filepath
        self._data = data
        self.file_label.config(
            text=os.path.basename(filepath), foreground=TEXT)
        self._fs = self._guess_fs_from_filename(filepath)
        self.fs_var.set(self._format_fs(self._fs))
        self._clear_cursors()
        self._plot()

        # 更新文件列表中的选中项
        self._refresh_file_list()
        self._last_file_mtime = os.path.getmtime(filepath)

    # ------------------------------------------------------------------
    # 绘图
    # ------------------------------------------------------------------
    def _replot(self):
        """用户修改参数后重新绘图。"""
        try:
            self._fs = self._parse_fs(self.fs_var.get())
        except ValueError:
            self._fs = 250e6
        self.fs_var.set(self._format_fs(self._fs))
        if self._data is not None:
            self._plot()

    def _plot(self):
        """核心绘图逻辑。"""
        data = self._data
        if data is None or len(data) == 0:
            return

        self.ax.clear()
        self._style_axes()

        n = len(data)

        # 确定降采样目标宽度
        dpi = self.fig.get_dpi()
        bbox = self.ax.get_window_extent().transformed(
            self.fig.dpi_scale_trans.inverted())
        target_w = max(800, int(bbox.width * dpi))

        # 降采样
        xs, ymin, ymax = downsample_for_display(data, target_w)

        # 时间轴（自动选择合适的单位）
        t = xs / self._fs
        time_scale = 1.0
        time_unit = "s"
        if self._fs >= 1e9:
            time_scale = 1e9; time_unit = "ns"
        elif self._fs >= 1e6:
            time_scale = 1e6; time_unit = "µs"
        elif self._fs >= 1e3:
            time_scale = 1e3; time_unit = "ms"

        t_display = t * time_scale
        duration = n / self._fs

        if np.array_equal(ymin, ymax):
            self.ax.plot(t_display, ymin, linewidth=0.6, color="#4e9ce8")
        else:
            self.ax.fill_between(t_display, ymin, ymax,
                                 step="mid", alpha=0.4, color="#4e9ce8",
                                 linewidth=0)
            ymid = (ymin + ymax) / 2.0
            self.ax.plot(t_display, ymid, linewidth=0.5, color="#2d7dd2")

        self.ax.set_xlabel(f"时间 ({time_unit})")
        self.ax.set_ylabel("电压 (V)")

        if duration < 0.001:
            title = f"AD 采样波形  ({n:,} 样本, {duration*1e6:.1f} µs)"
        elif duration < 1:
            title = f"AD 采样波形  ({n:,} 样本, {duration*1e3:.1f} ms)"
        else:
            title = f"AD 采样波形  ({n:,} 样本, {duration:.3f} s)"
        self.ax.set_title(title)

        # 统计信息（这里扫描一次并缓存，供游标拖拽复用）
        vmin = float(np.min(data))
        vmax = float(np.max(data))
        self._vmin_cache = vmin
        self._vmax_cache = vmax
        vpp = vmax - vmin
        self._update_stats_label(vmin, vmax, vpp, n)

        # 重绘游标
        self._redraw_cursors()

        self.canvas.draw()

    def _update_stats_label(self, vmin, vmax, vpp, n):
        """更新底部统计+游标测量信息。"""
        base = (f"Vmin={vmin:.3f}V  Vmax={vmax:.3f}V  Vpp={vpp:.3f}V  "
                f"样本={n:,}")
        cursor_info = self._cursor_info()
        if cursor_info:
            base += "  |  " + cursor_info
        self.stats_label.config(text=base)

    # ------------------------------------------------------------------
    # 游标测量
    # ------------------------------------------------------------------
    def _on_canvas_click(self, event):
        """鼠标左键放置/拖拽游标A，右键放置/拖拽游标B。"""
        if event.inaxes != self.ax:
            return
        if event.xdata is None:
            return

        if event.button == 1:  # 左键 → 游标A
            self._cursor_a = event.xdata
            self._cursor_dragging = "A"
            self._redraw_cursors()
        elif event.button == 3:  # 右键 → 游标B
            self._cursor_b = event.xdata
            self._cursor_dragging = "B"
            self._redraw_cursors()

    def _on_canvas_motion(self, event):
        """鼠标移动时拖拽游标（节流：最多每 33ms 重绘一次 ≈ 30fps）。"""
        if self._cursor_dragging is None:
            return
        if event.inaxes != self.ax or event.xdata is None:
            return

        if self._cursor_dragging == "A":
            self._cursor_a = event.xdata
        elif self._cursor_dragging == "B":
            self._cursor_b = event.xdata

        # 节流：已有 pending 重绘则跳过，避免拖拽时事件洪水
        if self._cursor_redraw_pending:
            return
        self._cursor_redraw_pending = True
        self.win.after(33, self._do_cursor_redraw)

    def _do_cursor_redraw(self):
        """实际执行游标重绘（由 motion 节流调用）。"""
        self._cursor_redraw_pending = False
        self._redraw_cursors()

    def _on_canvas_release(self, event):
        """鼠标释放结束拖拽。"""
        self._cursor_dragging = None

    def _redraw_cursors(self):
        """重绘游标线并更新测量信息（不累积 Text 对象）。"""
        # 移除旧线 + 旧标签
        for attr in ("_cursor_line_a", "_cursor_line_b",
                     "_cursor_label_a", "_cursor_label_b"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try: obj.remove()
                except Exception: pass
                setattr(self, attr, None)

        # 画新线 + 标签
        ylim = self.ax.get_ylim()
        if self._cursor_a is not None:
            self._cursor_line_a = self.ax.axvline(
                self._cursor_a, color=CURSOR_COLOR, linewidth=1.2,
                linestyle="-", alpha=0.9)
            self._cursor_label_a = self.ax.text(
                self._cursor_a, ylim[1], " A",
                color=CURSOR_COLOR, fontsize=9, fontweight="bold",
                va="top", ha="left")
        if self._cursor_b is not None:
            self._cursor_line_b = self.ax.axvline(
                self._cursor_b, color="#ff6b6b", linewidth=1.2,
                linestyle="-", alpha=0.9)
            self._cursor_label_b = self.ax.text(
                self._cursor_b, ylim[1], " B",
                color="#ff6b6b", fontsize=9, fontweight="bold",
                va="top", ha="left")

        # 更新统计信息（使用缓存的 vmin/vmax，避免每次拖拽扫全数据）
        if self._data is not None:
            if not hasattr(self, "_vmin_cache") or self._vmin_cache is None:
                self._vmin_cache = float(np.min(self._data))
                self._vmax_cache = float(np.max(self._data))
            vpp = self._vmax_cache - self._vmin_cache
            self._update_stats_label(self._vmin_cache, self._vmax_cache,
                                     vpp, len(self._data))

        self.canvas.draw_idle()

    def _cursor_info(self):
        """生成游标测量信息文字。

        注意: self._cursor_a / _cursor_b 存储的是显示坐标值
        （µs、ms 或 ns），需按当前 time_scale 转回秒。
        """
        if self._cursor_a is None or self._cursor_b is None:
            return ""

        # 当前显示时间轴的缩放因子
        time_scale = 1.0
        if self._fs >= 1e9: time_scale = 1e9
        elif self._fs >= 1e6: time_scale = 1e6
        elif self._fs >= 1e3: time_scale = 1e3

        # 转回秒
        dt = abs(self._cursor_b - self._cursor_a) / time_scale
        if dt == 0:
            return ""

        time_str = self._format_time(dt)

        # 频率估算
        freq = 1.0 / dt
        if freq >= 1e9:
            freq_str = f"  f={freq/1e9:.3f}GHz"
        elif freq >= 1e6:
            freq_str = f"  f={freq/1e6:.3f}MHz"
        elif freq >= 1e3:
            freq_str = f"  f={freq/1e3:.3f}kHz"
        else:
            freq_str = f"  f={freq:.3f}Hz"

        # 电压测量：在游标位置取采样值
        dv_str = ""
        if self._data is not None and self._fs > 0:
            idx_a = int(self._cursor_a * self._fs / time_scale)
            idx_b = int(self._cursor_b * self._fs / time_scale)
            n = len(self._data)
            idx_a = max(0, min(n - 1, idx_a))
            idx_b = max(0, min(n - 1, idx_b))
            va = self._data[idx_a]
            vb = self._data[idx_b]
            dv = vb - va
            dv_str = f"  ΔV={dv:.3f}V (A={va:.3f} B={vb:.3f})"

        return f"Δt={time_str}{freq_str}{dv_str}"

    @staticmethod
    def _format_time(t):
        """格式化时间值，选择合适的单位。"""
        if t >= 1:
            return f"{t:.3f}s"
        if t >= 1e-3:
            return f"{t*1e3:.3f}ms"
        if t >= 1e-6:
            return f"{t*1e6:.3f}µs"
        if t >= 1e-9:
            return f"{t*1e9:.3f}ns"
        return f"{t*1e12:.1f}ps"

    def _clear_cursors(self):
        """清除游标。"""
        self._cursor_a = None
        self._cursor_b = None
        self._cursor_line_a = None
        self._cursor_line_b = None
        self._cursor_dragging = None
        if self._data is not None:
            self._plot()

    # ------------------------------------------------------------------
    # 按钮事件
    # ------------------------------------------------------------------
    def _on_open(self):
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.after(100, lambda: self.win.attributes("-topmost", False))

        path = filedialog.askopenfilename(
            parent=self.win,
            title="选择 .bin 文件",
            filetypes=[("BIN 文件", "*.bin"), ("所有文件", "*.*")],
            initialdir=self._output_dir or os.getcwd(),
        )
        if path:
            self._output_dir = os.path.dirname(path)
            self._load_and_display(path)
            self._refresh_file_list()

    def _on_refresh(self):
        if self._output_dir:
            latest = self._find_latest_bin(self._output_dir)
            if latest:
                self._load_and_display(latest)
            else:
                messagebox.showinfo("提示", "输出目录中未找到 .bin 文件",
                                    parent=self.win)
            self._refresh_file_list()
        elif self._filepath:
            self._load_and_display(self._filepath)
        else:
            self._on_open()

    def _on_export(self):
        if self._data is None:
            messagebox.showinfo("提示", "没有可导出的数据", parent=self.win)
            return
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="导出波形图片",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
            initialdir=self._output_dir or ".",
        )
        if path:
            self.fig.savefig(path, dpi=150, bbox_inches="tight",
                             facecolor=DARK_BG)
            messagebox.showinfo("提示", f"已保存到:\n{path}", parent=self.win)

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    def _on_close(self):
        if self._refresh_id:
            self.win.after_cancel(self._refresh_id)
            self._refresh_id = None
        self.win.destroy()


# ---------------------------------------------------------------------------
# 便捷入口：独立运行
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    viewer = WaveformViewer(parent=root)
    root.mainloop()