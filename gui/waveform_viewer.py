"""波形查看器 — 独立运行入口（委托 WaveformWidget）

数据格式: int16 big-endian, 14-bit ADC, ±5V, 250 MHz 采样率
使用方法: 从 launcher.py 点击"查看波形"，或独立运行本文件。
"""

import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLineEdit, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QCheckBox, QStatusBar, QFileDialog, QMessageBox,
    QToolBar,
)
from PySide6.QtCore import Qt, QTimer, Signal

from widgets.waveform_widget import (
    WaveformWidget, DEFAULT_FS, format_fs, parse_fs, format_size,
)

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
QListWidget::item:selected { background-color: #264f78; color: #ffffff; }
QListWidget::item:hover { background-color: #2a2d2e; }
QCheckBox { color: #e6e6e6; spacing: 6px; }
QStatusBar { background-color: #007acc; color: #ffffff; }
QLabel { color: #e6e6e6; }
QToolBar { border-bottom: 1px solid #3f3f46; padding: 4px; }
QSplitter::handle { background-color: #3f3f46; width: 2px; }
"""


class WaveformViewer(QMainWindow):
    """独立波形查看器窗口（含工具栏 + 文件列表 + 波形组件）。"""

    def __init__(self, filepath=None, output_dir=None, fs=DEFAULT_FS):
        super().__init__()
        self._fs = fs
        self._output_dir = output_dir
        self._auto_refresh = False

        self._init_ui()

        if filepath and os.path.isfile(filepath):
            self._load_file(filepath)
        elif output_dir:
            latest = self._find_latest(output_dir)
            if latest:
                self._load_file(latest)

    def _init_ui(self):
        self.setWindowTitle("波形查看器 — PyQtGraph")
        self.resize(1300, 780)
        self.setMinimumSize(900, 550)
        self.setStyleSheet(DARK_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # 工具栏
        self._init_toolbar(root)

        # 主体：文件列表 + 波形
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(220)
        self.file_list.itemClicked.connect(self._on_file_clicked)
        splitter.addWidget(self.file_list)
        self._refresh_file_list()

        self._wf = WaveformWidget()
        self._wf.data_loaded.connect(self._on_wf_loaded)
        self._wf.status_message.connect(self._on_wf_status)
        splitter.addWidget(self._wf)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪 | 左键双击放游标A  右键双击放游标B  Del清除")
        self.status_bar.addWidget(self.status_label, 1)

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
        btn_clear.clicked.connect(lambda: self._wf._clear_cursors())
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

    # ── 文件操作 ───────────────────────────────────────────

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
        if not self._output_dir: return
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
        if path: self._load_file(path)

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
        if not self._wf.has_data:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出波形图片", self._output_dir or os.getcwd(),
            "PNG 图片 (*.png);;所有文件 (*.*)")
        if path:
            self._wf.export_png(path)
            QMessageBox.information(self, "提示", f"已保存到:\n{path}")

    def _load_file(self, filepath):
        self.file_label.setText(f"加载中: {os.path.basename(filepath)}")
        self._wf.load_file(filepath)

    def _on_wf_loaded(self, path):
        self.file_label.setText(os.path.basename(path))
        self._refresh_file_list()

    def _on_wf_status(self, text):
        self.status_label.setText(text)

    # ── 采样率 ─────────────────────────────────────────────

    def _on_fs_changed(self):
        try:
            self._fs = parse_fs(self.fs_edit.text())
        except ValueError:
            self._fs = DEFAULT_FS
        self.fs_edit.setText(format_fs(self._fs))
        self._wf.set_fs(self._fs)

    # ── 自动刷新 ───────────────────────────────────────────

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
            if latest and os.path.normpath(latest) != os.path.normpath(
                self._wf.loaded_path or ""
            ):
                self._load_file(latest)

    def closeEvent(self, event):
        if hasattr(self, "_auto_refresh_timer"):
            self._auto_refresh_timer.stop()
        super().closeEvent(event)


# ── 入口 ──────────────────────────────────────────────────
_app = None

def show(filepath=None, output_dir=None, fs=DEFAULT_FS):
    global _app
    existing = QApplication.instance()
    if existing is None:
        _app = QApplication(sys.argv)
        _app.setStyleSheet(DARK_QSS)
    viewer = WaveformViewer(filepath=filepath, output_dir=output_dir, fs=fs)
    viewer.show()
    if existing is None:
        _app.exec()
    else:
        viewer.setAttribute(Qt.WA_DeleteOnClose)


if __name__ == "__main__":
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
