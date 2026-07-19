"""波形显示组件 — PyQtGraph 可嵌入 Widget

数据格式: int16 big-endian, 14-bit ADC, ±5V, 250 MHz 采样率
可嵌入到任何 QWidget 层级中。
"""

import os
import threading

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont

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
# 降采样
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
# 波形组件
# ---------------------------------------------------------------------------
class WaveformWidget(QWidget):
    """可嵌入的波形显示组件。

    公开方法:
        load_file(path)      -- 加载 .bin 文件
        clear_data()         -- 清除数据和显示
        export_png(path)     -- 导出截图
        set_fs(fs)           -- 设置采样率

    信号:
        data_loaded(str)     -- 数据加载完成，参数为文件路径
        status_message(str)  -- 状态/统计信息
    """

    data_loaded = Signal(str)
    status_message = Signal(str)
    _data_ready = Signal(object)  # 内部：子线程→主线程

    def __init__(self, parent=None, fs=DEFAULT_FS):
        super().__init__(parent)
        self._fs = fs
        self._data: np.ndarray | None = None
        self._loading = False
        self._filepath: str | None = None

        # 渲染缓存
        self._raw_time: np.ndarray | None = None
        self._raw_data: np.ndarray | None = None
        self._envelope_t: np.ndarray | None = None
        self._envelope_ymin: np.ndarray | None = None
        self._envelope_ymax: np.ndarray | None = None
        self._envelope_ymid: np.ndarray | None = None
        self._time_scale = 1.0
        self._time_unit = "s"
        self._title = ""
        self._first_render = True
        self._in_range_handler = False

        self._build_ui()
        self._data_ready.connect(self._on_data_ready_slot)

    # ── UI ──────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # pyqtgraph 画布
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.setLabel("bottom", "时间", units="s")
        self.plot_widget.setLabel("left", "电压", units="V")
        self.plot_widget.setMouseEnabled(x=True, y=True)
        layout.addWidget(self.plot_widget)

        # 游标
        self.cursor_a = pg.InfiniteLine(angle=90, movable=True,
                                         pen=pg.mkPen(color="#ffd700", width=2))
        self.cursor_b = pg.InfiniteLine(angle=90, movable=True,
                                         pen=pg.mkPen(color="#ff6b6b", width=2))
        self.cursor_a.setVisible(False)
        self.cursor_b.setVisible(False)
        self.plot_widget.addItem(self.cursor_a)
        self.plot_widget.addItem(self.cursor_b)

        self.cursor_a.sigPositionChanged.connect(self._on_cursor_moved)
        self.cursor_b.sigPositionChanged.connect(self._on_cursor_moved)

        # 双击添加游标
        self.plot_widget.scene().sigMouseClicked.connect(self._on_plot_clicked)
        self.plot_widget.setFocusPolicy(Qt.StrongFocus)
        self.plot_widget.keyPressEvent = self._on_key_press

        # 视图范围变化 → 自适应渲染
        self._in_range_handler = False
        self.plot_widget.getViewBox().sigRangeChanged.connect(self._on_range_changed)

    # ── 公共方法 ────────────────────────────────────────────

    def load_file(self, filepath: str) -> None:
        """加载 .bin 文件并在后台线程解析。"""
        filepath = os.path.abspath(filepath)
        if self._loading and filepath == self._filepath:
            return
        if self._filepath and os.path.normpath(filepath) == os.path.normpath(self._filepath):
            return

        self._loading = True
        self._filepath = filepath
        self.status_message.emit("加载中...")

        def worker():
            try:
                raw = np.fromfile(filepath, dtype=SAMPLE_DTYPE)
                if len(raw) == 0:
                    raise ValueError("文件为空或格式不正确")
                result = raw.astype(np.float64)
                result *= SCALE_FACTOR
                self._data_ready.emit(result)
            except Exception as e:
                self._data_ready.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def clear_data(self) -> None:
        """清除数据和显示。"""
        self._data = None
        self._filepath = None
        self._raw_data = None
        self._clear_cursors()
        self.plot_widget.clear()
        self.status_message.emit("就绪")

    def export_png(self, path: str) -> None:
        """导出当前波形为 PNG。"""
        exporter = pg.exporters.ImageExporter(self.plot_widget.plotItem)
        exporter.export(path)

    def set_fs(self, fs: float) -> None:
        self._fs = fs
        if self._data is not None:
            self._replot()

    @property
    def has_data(self) -> bool:
        return self._data is not None and len(self._data) > 0

    @property
    def loaded_path(self) -> str | None:
        return self._filepath

    # ── 内部：数据加载回调 ─────────────────────────────────

    @Slot(object)
    def _on_data_ready_slot(self, result):
        self._loading = False
        if isinstance(result, str):
            self.status_message.emit(f"加载失败: {result}")
            return
        self._data = result
        self._replot()
        self.data_loaded.emit(self._filepath)

    # ── 渲染 ────────────────────────────────────────────────

    def _replot(self):
        data = self._data
        if data is None or len(data) == 0:
            return

        n = len(data)

        view = self.plot_widget.getViewBox()
        screen_w = max(800, int(view.width()) if view.width() > 0 else 1920)
        xs, ymin, ymax = downsample(data, int(screen_w))

        self._time_scale = 1e6 if self._fs >= 1e6 else 1
        self._time_unit  = "µs" if self._fs >= 1e6 else "s"

        self._raw_time = np.arange(n, dtype=np.float64) / self._fs * self._time_scale
        self._raw_data = data

        self._envelope_t    = xs / self._fs * self._time_scale
        self._envelope_ymin = ymin
        self._envelope_ymax = ymax
        self._envelope_ymid = (ymin + ymax) / 2.0

        duration = n / self._fs
        if duration < 0.001:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration*1e6:.1f} µs)"
        elif duration < 1:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration*1e3:.1f} ms)"
        else:
            self._title = f"AD 采样波形  ({n:,} 样本, {duration:.3f} s)"

        self._first_render = True
        self._render_adaptive()

    def _on_range_changed(self):
        if self._data is None:
            return
        self._render_adaptive()

    def _render_adaptive(self):
        if self._in_range_handler:
            return
        self._in_range_handler = True

        try:
            self.plot_widget.clear()
            self.plot_widget.addItem(self.cursor_a)
            self.plot_widget.addItem(self.cursor_b)

            vr = self.plot_widget.viewRange()
            x_min, x_max = vr[0]
            visible_samples = int((x_max - x_min) * self._fs / self._time_scale)

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
        return np.array_equal(self._envelope_ymin, self._envelope_ymax)

    def _render_envelope(self):
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
        start_idx = max(0, int(x_min * self._fs / self._time_scale))
        end_idx   = min(len(self._raw_data),
                        int(x_max * self._fs / self._time_scale) + 1)

        margin = max(1, (end_idx - start_idx) // 20)
        start_idx = max(0, start_idx - margin)
        end_idx   = min(len(self._raw_data), end_idx + margin)

        t = self._raw_time[start_idx:end_idx]
        v = self._raw_data[start_idx:end_idx]
        self.plot_widget.plot(t, v, pen=pg.mkPen(color="#4e9ce8", width=0.8))

        anchor = pg.PlotDataItem(
            [self._envelope_t[0], self._envelope_t[-1]], [0, 0],
            pen=pg.mkPen(color=(0, 0, 0, 0)))
        self.plot_widget.addItem(anchor)

    def _update_status(self):
        data = self._raw_data
        if data is None:
            return
        vmin, vmax = float(data.min()), float(data.max())
        self.status_message.emit(
            f"Vmin={vmin:.3f}V  Vmax={vmax:.3f}V  "
            f"Vpp={vmax-vmin:.3f}V  样本={len(data):,}")

    # ── 游标 ────────────────────────────────────────────────

    def _on_plot_clicked(self, event):
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

    def _update_cursor_info(self):
        if not self.cursor_a.isVisible() or not self.cursor_b.isVisible():
            return

        xa = self.cursor_a.pos().x()
        xb = self.cursor_b.pos().x()
        dt = abs(xb - xa)
        dt_sec = dt / self._time_scale

        time_str = format_time(dt_sec)
        freq_str = ""
        if dt_sec > 0:
            freq = 1.0 / dt_sec
            if freq >= 1e9: freq_str = f"  f={freq/1e9:.3f}GHz"
            elif freq >= 1e6: freq_str = f"  f={freq/1e6:.3f}MHz"
            elif freq >= 1e3: freq_str = f"  f={freq/1e3:.3f}kHz"
            else: freq_str = f"  f={freq:.3f}Hz"

        dv_str = ""
        if self._data is not None:
            idx_a = int(xa * self._fs / self._time_scale)
            idx_b = int(xb * self._fs / self._time_scale)
            n = len(self._data)
            idx_a = max(0, min(n - 1, idx_a))
            idx_b = max(0, min(n - 1, idx_b))
            va, vb = self._data[idx_a], self._data[idx_b]
            dv = vb - va
            dv_str = f"  ΔV={dv:.3f}V (A={va:.3f} B={vb:.3f})"

        self.status_message.emit(f"Δt={time_str}{freq_str}{dv_str}")

    def _on_key_press(self, event):
        if event.key() == Qt.Key_Delete:
            self._clear_cursors()
        else:
            pg.PlotWidget.keyPressEvent(self.plot_widget, event)
