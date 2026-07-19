"""配置模型 — QSettings 持久化，替代 gui_config.json"""

from PySide6.QtCore import QObject, QSettings, Signal


DEFAULTS: dict[str, str] = {
    "target_ip":     "",
    "local_ip":      "",
    "data_port":     "9001",
    "cmd_port":      "9002",
    "output_dir":    ".",
    "threshold_mb":  "16",
    "buf_size_mb":   "128",
    "timeout_sec":   "3",
    "cmd_start":     "01",
    "cmd_stop":      "00",
    "coe_file":      "",
    "tx_interval_ms": "1",
    "preamble":      "A5 A5 A5 A5 A5 A5 A5 D5",
    "data_addr":     "01",
    "cmd_addr":      "02",
    "auto_view":     "1",   # "1" = True
}

FLAG_SPEC: list[tuple[str, str, bool]] = [
    # (key, flag, always_include)
    ("target_ip",     "-d",            True),
    ("local_ip",      "--local-ip",    False),
    ("data_port",     "--data-port",   False),
    ("cmd_port",      "--cmd-port",    False),
    ("output_dir",    "-o",            False),
    ("threshold_mb",  "-T",            True),   # 采集阈值
    ("buf_size_mb",   "-b",            False),
    ("timeout_sec",   "-t",            False),
    ("cmd_start",     "--cmd-start",   False),
    ("cmd_stop",      "--cmd-stop",    False),
    ("coe_file",      "--coe-file",    False),   # COE 专用
    ("tx_interval_ms","--tx-interval", False),
    ("preamble",      "--preamble",    False),
    ("data_addr",     "--data-addr",   False),
    ("cmd_addr",      "--cmd-addr",    False),
]


class ConfigModel(QObject):
    """配置持久化模型。

    信号:
        config_loaded()  -- 配置加载完成
    """

    config_loaded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("EthernetCap", "CaptureConfig")
        self._values: dict[str, str] = dict(DEFAULTS)  # 当前值

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default or DEFAULTS.get(key, ""))

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def get_bool(self, key: str) -> bool:
        return self._values.get(key, "0") == "1"

    def set_bool(self, key: str, value: bool) -> None:
        self._values[key] = "1" if value else "0"

    # ── 持久化 ───────────────────────────────────────────────

    def load(self) -> None:
        for key in DEFAULTS:
            val = self._settings.value(key)
            if val is not None:
                self._values[key] = str(val)
        self.config_loaded.emit()

    def save(self) -> None:
        for key, value in self._values.items():
            self._settings.setValue(key, value)
        self._settings.sync()

    # ── CLI 参数构建 ─────────────────────────────────────────

    def get_capture_args(self) -> list[str]:
        return self._build_args(exclude_coe=True)

    def get_coe_args(self) -> list[str]:
        return self._build_args(include_coe_only=True)

    def _build_args(self, exclude_coe: bool = False,
                    include_coe_only: bool = False) -> list[str]:
        coe_keys = {"coe_file", "tx_interval_ms", "preamble", "data_addr", "cmd_addr"}
        args: list[str] = []

        for key, flag, always in FLAG_SPEC:
            if include_coe_only and key not in coe_keys:
                continue
            if exclude_coe and key in coe_keys:
                continue
            val = self._values.get(key, "")
            if always or (val and val != DEFAULTS.get(key, "")):
                args += [flag, val]

        return args
