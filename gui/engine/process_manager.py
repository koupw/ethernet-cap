"""C 引擎进程管理器 — QProcess 封装"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QProcess


# PyInstaller 打包后 C 引擎在 bundle 根目录
if getattr(sys, 'frozen', False):
    EXE_PATH = os.path.join(sys._MEIPASS, "ethernet-cap-engine.exe")
else:
    EXE_PATH = str(Path(__file__).resolve().parent.parent.parent / "ethernet-cap-engine.exe")

PROMPT_SENTINEL = "__GUI_PROMPT__"
LOG_LINE_LIMIT = 10000


class ProcessManager(QObject):
    """封装 C 引擎生命周期。

    信号:
        log_received(str)  -- stderr 输出
        process_finished(int)  -- 进程退出码
        status_changed(bool)  -- True=运行中, False=已停止
    """

    log_received = Signal(str)
    process_finished = Signal(int)
    status_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._exe_path = EXE_PATH

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.NotRunning

    # ── 公共接口 ─────────────────────────────────────────────

    def start(self, args: list[str]) -> bool:
        """启动 C 引擎。

        Args:
            args: 命令行参数列表（不含 exe 路径），如 ["-d", "192.168.1.10", ...]

        Returns:
            True 若启动成功
        """
        if self.is_running:
            self.stop()

        self._process = QProcess(self)

        # 合并 stdout/stderr 到 stderr 通道（C 引擎的日志全走 stderr）
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_ready_read)
        self._process.finished.connect(self._on_finished)

        self._process.start(self._exe_path, args)
        started = self._process.waitForStarted(3000)
        if started:
            self.status_changed.emit(True)
        else:
            self.log_received.emit("[ERR] 无法启动 C 引擎进程")
        return started

    def start_capture(self, args: list[str]) -> bool:
        """启动采集模式。"""
        return self.start(args)

    def start_tx_mode(self, coe_file: str, args: list[str]) -> bool:
        """启动 COE 发送模式。"""
        full_args = ["--coe-file", coe_file] + args
        return self.start(full_args)

    def stop(self) -> None:
        """停止 C 引擎。

        先向 stdin 写入换行触发 C 端正常退出，
        超时后用 terminate/kill 强制终止。
        """
        if not self._process or not self.is_running:
            return

        # 向 C 进程 stdin 写入换行使其优雅退出
        self._process.write(b"\n")
        self._process.waitForBytesWritten(500)

        finished = self._process.waitForFinished(3000)
        if not finished:
            self._process.terminate()
            if not self._process.waitForFinished(2000):
                self._process.kill()
                self._process.waitForFinished(500)

    # ── 内部槽 ────────────────────────────────────────────────

    def _on_ready_read(self) -> None:
        data = self._process.readAllStandardOutput().data()
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return

        for line in text.splitlines():
            self.log_received.emit(line)
            if PROMPT_SENTINEL in line:
                self._send_enter()

    def _send_enter(self) -> None:
        if self._process and self.is_running:
            self._process.write(b"\n")

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self.status_changed.emit(False)
        self.process_finished.emit(exit_code)
