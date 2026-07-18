"""
波形查看器 — PyQtGraph 版（GPU 加速、原生 zoom/pan、拖拽游标）

数据格式: int16 big-endian, 14-bit ADC, ±5V, 250 MHz 采样率
使用方法: 从 launcher.py 点击"查看波形"，或独立运行本文件。
"""

import os
import re
import sys
import threading
import time

import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QCheckBox, QStatusBar, QFileDialog, QMessageBox,
    QToolBar, QStyle
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont, QPalette, QColor

import pyqtgraph as pg

# pyqtgraph 全局配置
pg.setConfigOptions(background="#1e1e1e", foreground="#e6e6e6",
                     antialias=True, useOpenGL=True)

# ---------------------------------------------------------------------------
# ADC 常量
# ---------------------------------------------------------------------------
SAMPLE_DTYPE  = ">i2"
ADC_MAX       = 8192.0
VOLTAGE_RANGE = 5.0
SCALE_FACTOR  = VOLTAGE_RANGE / ADC_MAX
DEFAULT_FS    = 250e6  # Hz

# ---------------------------------------------------------------------------
# 深色 Qt 样式表
# ---------------------------------------------------------------------------
DARK_QSS = """
QMainWindow, QWidget, QSplitter, QToolBar {
    background-color: #1e1e1e; color: #e6e6e6;
}
QPushButton {
    background-color: #2d2d30; color: #e6e6e6; border: 1px solid #3f3f46;
    padding: 6px 14px; border-radius: 3px;
}
QPushButton:hover { background-color: #3f3f46; }
QPushButton:pressed { background-color: #007acc; }
QPushButton:disabled { background-color: #252526; color: #717171; }
QLineEdit {
    background-color: #252526; color: #e6e6e6; border: 1px solid #3f3f46;
    padding: 4px; border-radius: 3px;
}
QListWidget {
    background-color: #252526; color: #e6e6e6; border: 1px solid #3f3f46;
    outline: none;
}
QListWidget::item:selected {
    background-color: #264f78; color: #ffffff;
}
QListWidget::item:hover { background-color: #2a2d2e; }
QCheckBox { color: #e6e6e6; spacing: 6px; }
QStatusBar {
    background-color: #007acc; color: #ffffff;
}
QLabel { color: #e6e6e6; }
QToolBar {
    border-bottom: 1px solid #3f3f46; padding: 4px;
}
QSplitter::handle { background-color: #3f3f46; width: 2px; }
"""


# ---------------------------------------------------------------------------
# 降采样（与之前逻辑相同，向量化）
# ---------------------------------------------------------------------------
def downsample(data, target_width):
    n = len(data)
    target_width = int(target_width)
    if n <= target_width * 2:
        xs = np.arange(n, dtype=np.float64)
        return xs, data.copy(), data.copy()

    block = max(1, n // target_width)
    cols = n // block
    truncated = data[:cols * block].reshape(cols, block)
    xs = np.arange(cols, dtype=np.float64) * block + (block - 1) / 2.0
    return xs, truncated.min(axis=1), truncated.max(axis=1)


# ---------------------------------------------------------------------------
# 格式工具
# ---------------------------------------------------------------------------
def format_fs(fs):
    if fs >= 1e9: return f"{fs/1e9:g}G"
    if fs >= 1e6: return f"{fs/1e6:g}M"
    if fs >= 1e3: return f"{fs/1e3:g}k"
    return f"{fs:g}"


def parse_fs(s):
    s = s.strip()
    if not s: return 1.0
    mult = 1.0
    if s[-1] in "gG": mult = 1e9; s = s[:-1]
    elif s[-1] in "mM": mult = 1e6; s = s[:-1]
    elif s[-1] in "kK": mult = 1e3; s = s[:-1]
    return float(s) * mult


def format_time(t):
    if t >= 1:       return f"{t:.3f} s"
    if t >= 1e-3:    return f"{t*1e3:.3f} ms"
    if t >= 1e-6:    return f"{t*1e6:.3f} µs"
    return f"{t*1e9:.3f} ns"


def format_size(n):
    for u in ["B", "K", "M", "G"]:
        if n < 1024: return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.1f}T"


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class WaveformViewer(QMainWindow):
    """PyQtGraph 波形查看器窗口。"""

    data_loaded = Signal(object)  # 子线程 → 主线程: 成功时传 np.ndarray, 失败时传 str

    def __init__(self, filepath=None, output_dir=None, fs=DEFAULT_FS):
        super().__init__()
        self._fs = fs
        self._filepath = None
        self._output_dir = output_dir
        self._data = None
        self._loading = False
        self._auto_refresh = False

        self._init_ui()
        self._apply_dark_theme()

        # 初始加载
        if filepath and os.path.isfile(filepath):
            self._load_file(filepath)
        elif output_dir:
            latest = self._find_latest(output_dir)
            if latest:
                self._load_file(latest)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_ui(self):
        self.setWindowTitle("波形查看器 — PyQtGraph")
        self.resize(1300, 780)
        self.setMinimumSize(900, 550)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # --- 工具栏 ---
        self._init_toolbar(root)

        # --- 主体：文件列表 + 波形图 ---
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # 左侧文件列表
        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(220)
        self.file_list.itemClicked.connect(self._on_file_clicked)
        splitter.addWidget(self.file_list)
        self._refresh_file_list()

        # 右侧 pyqtgraph 画布
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        self.plot_widget.setLabel("left", "电压", units="V")
        self.plot_widget.setMouseEnabled(x=True, y=True)
        # 滚轮缩放、右键框选/平移（pyqtgraph 内置）
        splitter.addWidget(self.plot_widget)

        # --- 游标: InfiniteLine（可拖拽 + 信号）---
        self.cursor_a = pg.InfiniteLine(angle=90, movable=True,
                                         pen=pg.mkPen(color="#ffd700", width=2))
        self.cursor_b = pg.InfiniteLine(angle=90, movable=True,
                                         pen=pg.mkPen(color="#ff6b6b", width=2))
        self.cursor_a.setVisible(False)
        self.cursor_b.setVisible(False)
        self.plot_widget.addItem(self.cursor_a)
        self.plot_widget.addItem(self.cursor_b)

        # 游标拖拽信号 → 更新测量信息
        self.cursor_a.sigPositionChanged.connect(self._on_cursor_moved)
        self.cursor_b.sigPositionChanged.connect(self._on_cursor_moved)

        # 双击空白处添加游标A，右键添加游标B
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_clicked)
        # 键盘 Del 清除游标
        self.plot_widget.setFocusPolicy(Qt.StrongFocus)
        self.plot_widget.keyPressEvent = self._on_key_press

        # 视图范围变化 → 自适应渲染
        self._in_range_handler = False  # 防递归
        self.plot_widget.getViewBox().sigRangeChanged.connect(self._on_range_changed)

        # --- 状态栏 ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪 | 左键双击放游标A  右键双击放游标B  Del清除")
        self.status_bar.addWidget(self.status_label, 1)

        # 子线程数据加载信号 → 主线程处理
        self.data_loaded.connect(self._on_data_loaded_slot)

    def _init_toolbar(self, parent_layout):
        bar = QToolBar()
        bar.setMovable(False)

        btn_open = QPushButton("打开文件")
        btn_open.clicked.connect(self._on_open)
        bar.addWidget(btn_open)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._on_refresh)
        bar.addWidget(btn_refresh)

        btn_export = QPushButton("导出PNG")
        btn_export.clicked.connect(self._on_export)
        bar.addWidget(btn_export)

        btn_clear = QPushButton("清游标")
        btn_clear.clicked.connect(self._clear_cursors)
        bar.addWidget(btn_clear)

        bar.addSeparator()

        bar.addWidget(QLabel(" 采样率:"))
        self.fs_edit = QLineEdit(format_fs(self._fs))
        self.fs_edit.setMaximumWidth(70)
        self.fs_edit.returnPressed.connect(self._on_fs_changed)
        bar.addWidget(self.fs_edit)

        btn_apply = QPushButton("应用")
        btn_apply.clicked.connect(self._on_fs_changed)
        bar.addWidget(btn_apply)

        bar.addSeparator()

        self.auto_cb = QCheckBox("自动刷新")
        self.auto_cb.toggled.connect(self._toggle_auto_refresh)
        bar.addWidget(self.auto_cb)

        self.file_label = QLabel("")
        self.file_label.setStyleSheet("color: #808080;")
        bar.addWidget(self.file_label)

        parent_layout.addWidget(bar)

    def _apply_dark_theme(self):
        self.setStyleSheet(DARK_QSS)

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------
    def _find_latest(self, directory):
        try:
            files = [f for f in os.listdir(directory) if f.endswith(".bin")]
            if not files: return None
            files.sort(key=lambda f: os.path.getmtime(
                os.path.join(directory, f)), reverse=True)
            return os.path.join(directory, files[0])
        except OSError:
            return None

    def _refresh_file_list(self):
        self.file_list.clear()
        if not self._output_dir:
            return
        try:
            files = sorted(f for f in os.listdir(self._output_dir)
                           if f.endswith(".bin"))
        except OSError:
            return
        for f in files:
            full = os.path.join(self._output_dir, f)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            item = QListWidgetItem(f"{f}  [{format_size(size)}]")
            item.setData(Qt.UserRole, full)
            self.file_list.addItem(item)

    def _on_file_clicked(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self._load_file(path)

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 .bin 文件",
            self._output_dir or os.getcwd(),
            "BIN 文件 (*.bin);;所有文件 (*.*)")
        if path:
            self._output_dir = os.path.dirname(path)
            self._refresh_file_list()
            self._load_file(path)

    def _on_refresh(self):
        self._refresh_file_list()
        if self._output_dir:
            latest = self._find_latest(self._output_dir)
            if latest:
                self._load_file(latest)
            else:
                QMessageBox.information(self, "提示", "输出目录中未找到 .bin 文件")

    def _on_export(self):
        if self._data is None:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出波形图片", self._output_dir or os.getcwd(),
            "PNG 图片 (*.png);;所有文件 (*.*)")
        if path:
            exporter = pg.exporters.ImageExporter(self.plot_widget.plotItem)
            exporter.export(path)
            QMessageBox.information(self, "提示", f"已保存到:\n{path}")

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def _load_file(self, filepath):
        filepath = os.path.abspath(filepath)
        if self._loading and filepath == self._filepath:
            return
        if self._filepath and os.path.normpath(filepath) == os.path.normpath(self._filepath):
            return

        self._loading = True
        self._filepath = filepath
        self.file_label.setText(f"加载中: {os.path.basename(filepath)}")
        self.status_label.setText("加载中...")
        self.setCursor(Qt.WaitCursor)

        def worker():
            try:
                raw = np.fromfile(filepath, dtype=SAMPLE_DTYPE)
                if len(raw) == 0:
                    raise ValueError("文件为空或格式不正确")
                result = raw.astype(np.float64)
                result *= SCALE_FACTOR
                self.data_loaded.emit(result)  # 成功: np.ndarray
            except Exception as e:
                self.data_loaded.emit(str(e))  # 失败: str 错误信息

        threading.Thread(target=worker, daemon=True).start()

    @Slot(object)
    def _on_data_loaded_slot(self, result):
        """信号回调：主线程处理加载结果。result 为 str=错误, ndarray=成功"""
        self._loading = False
        self.setCursor(Qt.ArrowCursor)

        if isinstance(result, str):
            self.file_label.setText("加载失败")
            QMessageBox.critical(self, "加载失败", result)
            self.status_label.setText(result)
            return

        self._data = result
        self.file_label.setText(os.path.basename(self._filepath))
        self._update_fs_display()
        self._replot()  # 内部已调用 _update_status()
        self._refresh_file_list()

    # ------------------------------------------------------------------
    # 采样率
    # ------------------------------------------------------------------
    def _update_fs_display(self):
        self.fs_edit.setText(format_fs(self._fs))

    def _on_fs_changed(self):
        try:
            self._fs = parse_fs(self.fs_edit.text())
        except ValueError:
            self._fs = DEFAULT_FS
        self.fs_edit.setText(format_fs(self._fs))
        self._replot()

    # ------------------------------------------------------------------
    # 绘图（两级自适应：放大看原始线，缩小看包络）
    # ------------------------------------------------------------------
    def _replot(self):
        """全量重绘：计算全时间轴 + 降采样包络，存储后交给 _render_adaptive 决策。"""
        data = self._data
        if data is None or len(data) == 0:
            return

        n = len(data)

        # --- 降采样包络（全局缩放用）---
        view = self.plot_widget.getViewBox()
        screen_w = max(800, int(view.width()) if view.width() > 0 else 1920)
        xs, ymin, ymax = downsample(data, int(screen_w))

        # 时间轴
        self._time_scale = 1e6 if self._fs >= 1e6 else 1
        self._time_unit  = "µs" if self._fs >= 1e6 else "s"

        # 全量时间轴（原始采样点索引用）
        self._raw_time = np.arange(n, dtype=np.float64) / self._fs * self._time_scale
        self._raw_data = data

        # 降采样包络数据
        self._envelope_t    = xs / self._fs * self._time_scale
        self._envelope_ymin = ymin
        self._envelope_ymax = ymax
        self._envelope_ymid = (ymin + ymax) / 2.0

        # 标题信息
        duration = n / self._fs
        if duration < 0.001:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration*1e6:.1f} µs)"
        elif duration < 1:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration*1e3:.1f} ms)"
        else:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration:.3f} s)"

        # 自适应渲染
        self._first_render = True
        self._render_adaptive()

    def _on_range_changed(self):
        """视图范围变化 → 自适应切换渲染模式。"""
        if self._data is None:
            return
        self._render_adaptive()

    def _render_adaptive(self):
        """根据可视样本数选择渲染模式（内置递归防护）。"""
        if self._in_range_handler:
            return
        self._in_range_handler = True

        try:
            self.plot_widget.clear()

            # 恢复游标（clear 后需要重新添加）
            self.plot_widget.addItem(self.cursor_a)
            self.plot_widget.addItem(self.cursor_b)

            vr = self.plot_widget.viewRange()
            x_min, x_max = vr[0]
            visible_samples = int((x_max - x_min) * self._fs / self._time_scale)

            # 首次渲染强制全貌包络
            if getattr(self, '_first_render', False):
                self._first_render = False
                self._render_envelope()
                self.plot_widget.autoRange()
            elif visible_samples < 5000 and not self._is_envelope_uniform():
                self._render_raw_line(x_min, x_max)
            else:
                self._render_envelope()

            self.plot_widget.setLabel("bottom", f"时间 ({self._time_unit})")
            self.plot_widget.setTitle(self._title)
            self._update_status()
        finally:
            self._in_range_handler = False

    def _is_envelope_uniform(self):
        """包络是否均一（ymin==ymax，说明是极小数据无需切换）。"""
        return np.array_equal(self._envelope_ymin, self._envelope_ymax)

    def _render_envelope(self):
        """降采样 min/max 包络（全局视图）。"""
        if self._is_envelope_uniform():
            self.plot_widget.plot(self._envelope_t, self._envelope_ymin,
                                  pen=pg.mkPen(color="#4e9ce8", width=1))
        else:
            fill = pg.FillBetweenItem(
                pg.PlotCurveItem(self._envelope_t, self._envelope_ymin, pen=None),
                pg.PlotCurveItem(self._envelope_t, self._envelope_ymax, pen=None),
                brush=pg.mkBrush(78, 156, 232, 80))
            self.plot_widget.addItem(fill)
            self.plot_widget.plot(self._envelope_t, self._envelope_ymid,
                                  pen=pg.mkPen(color="#2d7dd2", width=1))

    def _render_raw_line(self, x_min, x_max):
        """放大视图：切片绘制原始采样线，看到每个样本点。"""
        start_idx = max(0, int(x_min * self._fs / self._time_scale))
        end_idx   = min(len(self._raw_data),
                        int(x_max * self._fs / self._time_scale) + 1)

        margin = max(1, (end_idx - start_idx) // 20)
        start_idx = max(0, start_idx - margin)
        end_idx   = min(len(self._raw_data), end_idx + margin)

        t = self._raw_time[start_idx:end_idx]
        v = self._raw_data[start_idx:end_idx]
        self.plot_widget.plot(t, v, pen=pg.mkPen(color="#4e9ce8", width=0.8))

        # 透明锚点：让 autoRange 知道完整数据范围
        anchor = pg.PlotDataItem(
            [self._envelope_t[0], self._envelope_t[-1]], [0, 0],
            pen=pg.mkPen(color=(0, 0, 0, 0)))  # 全透明但占位
        self.plot_widget.addItem(anchor)

    def _update_status(self):
        """更新统计信息。"""
        data = self._raw_data
        if data is None:
            return
        vmin, vmax = float(data.min()), float(data.max())
        self.status_label.setText(
            f"Vmin={vmin:.3f}V  Vmax={vmax:.3f}V  "
            f"Vpp={vmax-vmin:.3f}V  样本={len(data):,}")

    # ------------------------------------------------------------------
    # 游标
    # ------------------------------------------------------------------
    def _on_plot_clicked(self, event):
        """左键双击 → 游标A, 右键双击 → 游标B"""
        if event.double():
            pos = self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos())
            x = pos.x()
            if event.button() == Qt.LeftButton:
                self.cursor_a.setPos(x)
                self.cursor_a.setVisible(True)
            elif event.button() == Qt.RightButton:
                self.cursor_b.setPos(x)
                self.cursor_b.setVisible(True)
            self._update_cursor_info()

    def _on_cursor_moved(self):
        self._update_cursor_info()

    def _clear_cursors(self):
        self.cursor_a.setVisible(False)
        self.cursor_b.setVisible(False)
        self.status_label.setText("就绪")

    def _update_cursor_info(self):
        if not self.cursor_a.isVisible() or not self.cursor_b.isVisible():
            return

        xa = self.cursor_a.pos().x()
        xb = self.cursor_b.pos().x()
        dt = abs(xb - xa)

        # 转回秒
        dt_sec = dt / (self._time_scale if hasattr(self, '_time_scale') else 1.0)

        time_str = format_time(dt_sec)
        freq_str = ""
        if dt_sec > 0:
            freq = 1.0 / dt_sec
            if freq >= 1e9: freq_str = f"  f={freq/1e9:.3f}GHz"
            elif freq >= 1e6: freq_str = f"  f={freq/1e6:.3f}MHz"
            elif freq >= 1e3: freq_str = f"  f={freq/1e3:.3f}kHz"
            else: freq_str = f"  f={freq:.3f}Hz"

        # 电压
        dv_str = ""
        if self._data is not None:
            idx_a = int(xa * self._fs / getattr(self, '_time_scale', 1.0))
            idx_b = int(xb * self._fs / getattr(self, '_time_scale', 1.0))
            n = len(self._data)
            idx_a = max(0, min(n - 1, idx_a))
            idx_b = max(0, min(n - 1, idx_b))
            va, vb = self._data[idx_a], self._data[idx_b]
            dv = vb - va
            dv_str = f"  ΔV={dv:.3f}V (A={va:.3f} B={vb:.3f})"

        self.status_label.setText(f"Δt={time_str}{freq_str}{dv_str}")

    def _on_key_press(self, event):
        if event.key() == Qt.Key_Delete:
            self._clear_cursors()
        else:
            pg.PlotWidget.keyPressEvent(self.plot_widget, event)

    # ------------------------------------------------------------------
    # 自动刷新
    # ------------------------------------------------------------------
    def _toggle_auto_refresh(self, checked):
        self._auto_refresh = checked
        if checked:
            self._auto_refresh_timer = QTimer()
            self._auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
            self._auto_refresh_timer.start(1000)
        else:
            if hasattr(self, "_auto_refresh_timer"):
                self._auto_refresh_timer.stop()

    def _auto_refresh_tick(self):
        self._refresh_file_list()
        if self._output_dir:
            latest = self._find_latest(self._output_dir)
            if latest and os.path.normpath(latest) != os.path.normpath(self._filepath or ""):
                self._load_file(latest)

    def closeEvent(self, event):
        if hasattr(self, "_auto_refresh_timer"):
            self._auto_refresh_timer.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# 便捷入口（从 tkinter 启动器调用）
# ---------------------------------------------------------------------------
_app = None  # 全局 QApplication 引用，防止被 GC

def show(filepath=None, output_dir=None, fs=DEFAULT_FS):
    """从 launcher.py 调用的入口。创建 QApplication 和窗口。"""
    global _app
    existing = QApplication.instance()
    if existing is None:
        _app = QApplication(sys.argv)
        _app.setStyleSheet(DARK_QSS)
    viewer = WaveformViewer(filepath=filepath, output_dir=output_dir, fs=fs)
    viewer.show()
    # 如果 QApplication 不存在则启动事件循环，否则复用已有的
    if existing is None:
        _app.exec()
    else:
        # 确保窗口不被立即回收
        viewer.setAttribute(Qt.WA_DeleteOnClose)


if __name__ == "__main__":
    # 独立运行
    import argparse
    ap = argparse.ArgumentParser(description="PyQtGraph 波形查看器")
    ap.add_argument("file", nargs="?", help=".bin 文件路径")
    ap.add_argument("--dir", "-d", help="输出目录（自动加载最新 .bin）")
    ap.add_argument("--fs", type=float, default=DEFAULT_FS, help="采样率 (Hz)")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    viewer = WaveformViewer(filepath=args.file, output_dir=args.dir, fs=args.fs)
    viewer.show()
    sys.exit(app.exec())