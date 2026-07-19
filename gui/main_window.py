"""以太网上位机 — 统一 Qt 主窗口"""

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel,
    QStatusBar, QSplitter, QMenuBar, QMenu, QMessageBox, QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QAction, QIcon

# ---------------------------------------------------------------------------
# 项目内导入
# ---------------------------------------------------------------------------
from engine.process_manager import ProcessManager
from widgets.log_panel import LogPanel
from widgets.capture_panel import CapturePanel
from widgets.waveform_widget import WaveformWidget
from widgets.file_browser import FileBrowser
from models.config import ConfigModel

# ---------------------------------------------------------------------------
# 深色 QSS
# ---------------------------------------------------------------------------
DARK_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e6e6e6;
}
QMenuBar {
    background-color: #252526;
    color: #e6e6e6;
    border-bottom: 1px solid #3f3f46;
}
QMenuBar::item:selected {
    background-color: #3f3f46;
}
QMenu {
    background-color: #252526;
    color: #e6e6e6;
    border: 1px solid #3f3f46;
}
QMenu::item:selected {
    background-color: #094771;
}
QListWidget {
    background-color: #252526;
    color: #e6e6e6;
    border: none;
    outline: none;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: #094771;
}
QListWidget::item:hover:!selected {
    background-color: #2a2d2e;
}
QSplitter::handle {
    background-color: #3f3f46;
    width: 1px;
}
QStatusBar {
    background-color: #252526;
    color: #e6e6e6;
    border-top: 1px solid #3f3f46;
}
QPushButton {
    background-color: #2d2d30;
    color: #e6e6e6;
    border: 1px solid #3f3f46;
    padding: 6px 14px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #3e3e42;
}
QPushButton:pressed {
    background-color: #007acc;
}
QPushButton:disabled {
    color: #717171;
}
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #252526;
    color: #e6e6e6;
    border: 1px solid #3f3f46;
    padding: 3px 6px;
    border-radius: 2px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #007acc;
}
QCheckBox {
    color: #e6e6e6;
}
QGroupBox {
    color: #e6e6e6;
    border: 1px solid #3f3f46;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLabel {
    color: #e6e6e6;
}
"""

# ── 侧边栏条目 ────────────────────────────────────────────────
NAV_ITEMS = [
    ("📊  采集控制", 0),
    ("📈  波形显示", 1),
    ("📁  文件管理", 2),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("以太网上位机")
        self.setMinimumSize(1000, 650)
        self.resize(1400, 850)

        # 状态栏变量
        self._status_led = QLabel("●")
        self._status_label = QLabel("就绪")
        self._status_ip = QLabel("")
        self._status_data = QLabel("")

        # 引擎
        self._pm = ProcessManager(self)
        self._pm.log_received.connect(self._on_log)
        self._pm.process_finished.connect(self._on_process_done)

        # 配置
        self._cfg = ConfigModel(self)

        self._init_ui()
        self._apply_dark_theme()
        self._restore_geometry()

    # ── UI 构建 ────────────────────────────────────────────────

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 侧边栏
        sidebar = QWidget()
        sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(6, 8, 6, 8)
        sidebar_layout.setSpacing(2)

        self._nav_list = QListWidget()
        self._nav_list.setIconSize(QSize(18, 18))
        for text, idx in NAV_ITEMS:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, idx)
            self._nav_list.addItem(item)
        self._nav_list.setCurrentRow(0)
        self._nav_list.currentRowChanged.connect(self._on_nav_changed)
        sidebar_layout.addWidget(self._nav_list)
        sidebar_layout.addStretch()

        # 页面容器
        self._pages = QStackedWidget()

        # 页 0：采集控制（可拖拽分隔）
        page_capture = QWidget()
        capture_layout = QVBoxLayout(page_capture)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        capture_layout.setSpacing(0)

        splitter = QSplitter(Qt.Vertical)
        self._capture_splitter = splitter

        self._capture_panel = CapturePanel(self._pm, self._cfg)
        self._capture_panel.capture_started.connect(self._on_capture_started)
        self._capture_panel.capture_finished.connect(self._on_capture_finished)
        self._capture_panel.view_waveform.connect(self._on_view_waveform)
        self._capture_panel.setMinimumHeight(260)
        splitter.addWidget(self._capture_panel)

        self._log_panel = LogPanel()
        self._log_panel.setMinimumHeight(120)
        splitter.addWidget(self._log_panel)

        splitter.setSizes([310, 370])
        splitter.setCollapsible(0, False)
        capture_layout.addWidget(splitter)

        self._pages.addWidget(page_capture)

        # 页 1：波形显示
        self._waveform = WaveformWidget()
        self._waveform.status_message.connect(self._on_wf_status)
        self._pages.addWidget(self._waveform)

        # 页 2：文件管理
        self._file_browser = FileBrowser()
        self._file_browser.file_selected.connect(self.load_waveform_file)
        self._pages.addWidget(self._file_browser)

        # 分割线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color: #3f3f46; max-width: 1px;")

        # 组装
        root_layout.addWidget(sidebar)
        root_layout.addWidget(sep)
        root_layout.addWidget(self._pages, 1)

        # 状态栏
        self._build_status_bar()

        # 菜单栏
        self._build_menu_bar()

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setStyleSheet("QStatusBar::item { border: none; }")

        self._status_led.setStyleSheet("color: #717171; font-size: 12px; padding: 0 4px;")
        bar.addWidget(self._status_led)

        self._status_label.setStyleSheet("padding-right: 16px;")
        bar.addWidget(self._status_label)

        self._status_ip.setStyleSheet("padding: 0 4px;")
        bar.addWidget(self._status_ip)

        bar.addPermanentWidget(self._status_data)
        self.setStatusBar(bar)

    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件(&F)")
        act_exit = QAction("退出(&X)", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 视图
        view_menu = menubar.addMenu("视图(&V)")
        act_cap = QAction("采集控制", self)
        act_cap.triggered.connect(lambda: self._nav_list.setCurrentRow(0))
        view_menu.addAction(act_cap)
        act_wf = QAction("波形显示", self)
        act_wf.triggered.connect(lambda: self._nav_list.setCurrentRow(1))
        view_menu.addAction(act_wf)
        act_fl = QAction("文件管理", self)
        act_fl.triggered.connect(lambda: self._nav_list.setCurrentRow(2))
        view_menu.addAction(act_fl)

        # 帮助
        help_menu = menubar.addMenu("帮助(&H)")
        act_about = QAction("关于(&A)", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    # ── 暗色主题 ──────────────────────────────────────────────

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet(DARK_QSS)

    # ── 窗口状态 ──────────────────────────────────────────────

    def _restore_geometry(self) -> None:
        settings = QSettings("EthernetCap", "MainWindow")
        geo = settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        splitter_state = settings.value("splitter")
        if splitter_state:
            self._capture_splitter.restoreState(splitter_state)

    def closeEvent(self, event) -> None:
        self._pm.stop()
        settings = QSettings("EthernetCap", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("splitter", self._capture_splitter.saveState())
        super().closeEvent(event)

    # ── 槽 ────────────────────────────────────────────────────

    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self._pages.count():
            self._pages.setCurrentIndex(row)

    def _on_log(self, text: str) -> None:
        self._log_panel.append(text)

    def _on_process_done(self, exit_code: int) -> None:
        self._update_status(False)

    def _update_status(self, running: bool) -> None:
        if running:
            self._status_led.setStyleSheet("color: #89d185; font-size: 12px; padding: 0 4px;")
            self._status_label.setText("运行中")
        else:
            self._status_led.setStyleSheet("color: #717171; font-size: 12px; padding: 0 4px;")
            self._status_label.setText("就绪")

    def _on_capture_started(self, output_dir: str) -> None:
        self._update_status(True)
        ip = self._cfg.get("target_ip", "")
        self._status_ip.setText(ip)
        self._file_browser.set_root_path(output_dir)

    def _on_capture_finished(self, exit_code: int) -> None:
        self._update_status(False)
        self._status_ip.setText("")

    def _on_wf_status(self, text: str) -> None:
        self._status_data.setText(text)

    def _on_view_waveform(self, output_dir: str) -> None:
        """采集完成后查看波形：先切换页面，再延迟加载文件。"""
        self._nav_list.setCurrentRow(1)
        # 延迟 300ms 等待 C 进程排空写盘完成
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, lambda: self._try_load_latest(output_dir))

    def _try_load_latest(self, output_dir: str) -> None:
        latest = self._find_latest_bin(output_dir)
        if latest:
            self._waveform.load_file(latest)

    def load_waveform_file(self, filepath: str) -> None:
        """从文件浏览器加载 .bin 文件到内嵌波形组件。"""
        self._waveform.load_file(filepath)
        self._nav_list.setCurrentRow(1)

    @staticmethod
    def _find_latest_bin(directory: str) -> str | None:
        try:
            files = [f for f in os.listdir(directory) if f.endswith(".bin")]
            if not files:
                return None
            files.sort(key=lambda f: os.path.getmtime(
                os.path.join(directory, f)), reverse=True)
            return os.path.join(directory, files[0])
        except OSError:
            return None

    def _show_about(self) -> None:
        QMessageBox.about(self, "关于",
                          "以太网上位机 v2.0\n\n"
                          "UDP 采集 AD 数据 + COE 发送 + 波形查看")


# ── 入口 ──────────────────────────────────────────────────────
def main():
    import traceback
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("ethernet-cap")
        app.setOrganizationName("EthernetCap")
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        # 打包后无终端，错误写入文件方便诊断
        err_path = os.path.join(os.path.dirname(sys.executable)
                                if getattr(sys, 'frozen', False)
                                else os.getcwd(),
                                "ethernet-cap-error.log")
        with open(err_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise


if __name__ == "__main__":
    main()
