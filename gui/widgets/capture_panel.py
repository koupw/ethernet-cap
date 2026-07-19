"""采集参数面板 — 采集/COE 并排布局 + 控制按钮"""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QPushButton,
    QCheckBox, QGroupBox, QFileDialog, QMessageBox, QLabel,
)
from PySide6.QtCore import Signal

from engine.process_manager import ProcessManager
from models.config import ConfigModel, DEFAULTS


class CapturePanel(QWidget):
    """采集参数面板。

    信号:
        capture_started(str)
        capture_finished(int)
        view_waveform(str)
    """

    capture_started = Signal(str)
    capture_finished = Signal(int)
    view_waveform = Signal(str)

    def __init__(self, pm: ProcessManager, config: ConfigModel, parent=None):
        super().__init__(parent)
        self._pm = pm
        self._cfg = config

        self._pm.status_changed.connect(self._on_status_changed)
        self._pm.process_finished.connect(self._on_process_done)

        self._widgets: dict[str, QWidget] = {}
        self._build_ui()
        self._load_config()

    # ── 控件工厂 ──────────────────────────────────────────────

    @staticmethod
    def _entry(default: str = "") -> QLineEdit:
        return QLineEdit(default)

    @staticmethod
    def _spinbox(min_v: int, max_v: int, default: str) -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(min_v, max_v)
        sb.setValue(int(default))
        return sb

    def _add_row(self, form: QFormLayout, label: str, key: str,
                  widget: QWidget, note: str = "",
                  required: bool = False) -> None:
        self._widgets[key] = widget
        if required:
            lbl = QLabel(f'<span style="color:#f48771;font-weight:bold;">* {label}</span>')
        else:
            lbl = QLabel(label)
        if note:
            row = QHBoxLayout()
            row.addWidget(widget)
            nl = QLabel(note)
            nl.setStyleSheet("color: #717171;")
            row.addWidget(nl)
            form.addRow(lbl, row)
        else:
            form.addRow(lbl, widget)

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # ── 参数组：左右并排 ──────────────────────────────────
        groups_row = QHBoxLayout()
        groups_row.setSpacing(8)

        # 左：采集参数
        cap_group = QGroupBox("采集参数")
        cap_form = QFormLayout(cap_group)
        cap_form.setSpacing(5)
        cap_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._add_row(cap_form, "下位机 IP:", "target_ip",
                       self._entry(DEFAULTS["target_ip"]), required=True)
        self._add_row(cap_form, "本机 IP:", "local_ip",
                       self._entry(), "留空=INADDR_ANY")
        self._add_row(cap_form, "数据端口:", "data_port",
                       self._spinbox(1, 65535, DEFAULTS["data_port"]))
        self._add_row(cap_form, "命令端口:", "cmd_port",
                       self._spinbox(1, 65535, DEFAULTS["cmd_port"]))

        out_row = QHBoxLayout()
        self._widgets["output_dir"] = self._entry(DEFAULTS["output_dir"])
        out_row.addWidget(self._widgets["output_dir"])
        btn = QPushButton("…")
        btn.setFixedWidth(28)
        btn.clicked.connect(self._browse_output_dir)
        out_row.addWidget(btn)
        cap_form.addRow("输出目录:", out_row)

        self._add_row(cap_form, "采集阈值 (MB):", "threshold_mb",
                       self._spinbox(0, 1024, DEFAULTS["threshold_mb"]), "0=不限制")
        self._add_row(cap_form, "缓冲大小 (MB):", "buf_size_mb",
                       self._spinbox(1, 4096, DEFAULTS["buf_size_mb"]))
        self._add_row(cap_form, "超时 (秒):", "timeout_sec",
                       self._spinbox(1, 3600, DEFAULTS["timeout_sec"]), "无数据自动停")
        self._add_row(cap_form, "开始命令:", "cmd_start",
                       self._entry(DEFAULTS["cmd_start"]))
        self._add_row(cap_form, "停止命令:", "cmd_stop",
                       self._entry(DEFAULTS["cmd_stop"]))

        groups_row.addWidget(cap_group, 1)

        # 右：COE 参数
        coe_group = QGroupBox("COE 发送参数")
        coe_form = QFormLayout(coe_group)
        coe_form.setSpacing(5)

        coe_row = QHBoxLayout()
        self._widgets["coe_file"] = self._entry()
        coe_row.addWidget(self._widgets["coe_file"])
        btn = QPushButton("…")
        btn.setFixedWidth(28)
        btn.clicked.connect(self._browse_coe_file)
        coe_row.addWidget(btn)
        coe_form.addRow("COE 文件:", coe_row)

        self._add_row(coe_form, "发送间隔:", "tx_interval_ms",
                       self._spinbox(1, 60000, DEFAULTS["tx_interval_ms"]), "ms")
        self._add_row(coe_form, "引导码:", "preamble",
                       self._entry(DEFAULTS["preamble"]))
        self._add_row(coe_form, "数据地址:", "data_addr",
                       self._entry(DEFAULTS["data_addr"]))
        self._add_row(coe_form, "命令地址:", "cmd_addr",
                       self._entry(DEFAULTS["cmd_addr"]))

        groups_row.addWidget(coe_group, 1)
        layout.addLayout(groups_row)

        # ── 按钮行 ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._btn_start = QPushButton("开始采集")
        self._btn_start.setFixedHeight(34)
        self._btn_start.setStyleSheet("""
            QPushButton {
                background-color: #007acc; color: #fff; font-weight: bold;
                border: none; padding: 6px 18px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #1f6feb; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self._btn_start.clicked.connect(self._start_capture)
        btn_row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("停止")
        self._btn_stop.setFixedHeight(34)
        self._btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #a1260d; color: #fff; font-weight: bold;
                border: none; padding: 6px 18px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #c4391a; }
            QPushButton:disabled { background-color: #333; color: #666; }
        """)
        self._btn_stop.clicked.connect(self._stop_capture)
        self._btn_stop.setEnabled(False)
        btn_row.addWidget(self._btn_stop)

        self._btn_coe = QPushButton("发送COE数据")
        self._btn_coe.setFixedHeight(34)
        self._btn_coe.clicked.connect(self._send_coe)
        btn_row.addWidget(self._btn_coe)

        self._btn_view = QPushButton("查看波形")
        self._btn_view.setFixedHeight(34)
        self._btn_view.clicked.connect(self._open_waveform)
        btn_row.addWidget(self._btn_view)

        btn_row.addStretch()

        self._auto_view_cb = QCheckBox("停止后自动显示波形")
        self._auto_view_cb.setChecked(self._cfg.get_bool("auto_view"))
        btn_row.addWidget(self._auto_view_cb)

        layout.addLayout(btn_row)

    # ── 配置读写 ──────────────────────────────────────────────

    def _load_config(self) -> None:
        self._cfg.load()
        for key, w in self._widgets.items():
            val = self._cfg.get(key, "")
            if isinstance(w, QLineEdit):
                w.setText(val)
            elif isinstance(w, QSpinBox):
                w.setValue(int(val) if val else 0)

    def _save_config(self) -> None:
        for key, w in self._widgets.items():
            if isinstance(w, QLineEdit):
                self._cfg.set(key, w.text().strip())
            elif isinstance(w, QSpinBox):
                self._cfg.set(key, str(w.value()))
        self._cfg.set_bool("auto_view", self._auto_view_cb.isChecked())
        self._cfg.save()

    # ── 控件读取 ──────────────────────────────────────────────

    def _get(self, key: str, fallback: str = "") -> str:
        w = self._widgets.get(key)
        if isinstance(w, QLineEdit):
            return w.text().strip()
        if isinstance(w, QSpinBox):
            return str(w.value())
        return fallback

    # ── 控制 ──────────────────────────────────────────────────

    def _start_capture(self) -> None:
        if not self._get("target_ip"):
            QMessageBox.warning(self, "参数错误", "请输入下位机 IP 地址")
            return
        self._save_config()
        if not self._pm.start_capture(self._cfg.get_capture_args()):
            QMessageBox.warning(self, "启动失败", "无法启动 C 引擎，请检查 ethernet-cap.exe")

    def _stop_capture(self) -> None:
        self._pm.stop()

    def _send_coe(self) -> None:
        if not self._get("target_ip"):
            QMessageBox.warning(self, "参数错误", "请输入下位机 IP 地址")
            return
        if not self._get("coe_file"):
            QMessageBox.warning(self, "参数错误", "请选择 COE 文件")
            return
        self._save_config()
        if not self._pm.start_tx_mode(self._get("coe_file"),
                                       self._cfg.get_coe_args()):
            QMessageBox.warning(self, "启动失败", "无法启动 C 引擎，请检查 ethernet-cap.exe")

    def _open_waveform(self) -> None:
        self.view_waveform.emit(self._get("output_dir", "."))

    # ── 文件浏览 ──────────────────────────────────────────────

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self._widgets["output_dir"].setText(path)

    def _browse_coe_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 COE 文件", "", "COE 文件 (*.coe);;所有文件 (*)")
        if path:
            self._widgets["coe_file"].setText(path)

    # ── 状态 ──────────────────────────────────────────────────

    def _on_status_changed(self, running: bool) -> None:
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_coe.setEnabled(not running)
        if running:
            self.capture_started.emit(self._get("output_dir", "."))

    def _on_process_done(self, exit_code: int) -> None:
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_coe.setEnabled(True)
        self.capture_finished.emit(exit_code)
        if exit_code == 0 and self._auto_view_cb.isChecked():
            self._open_waveform()
