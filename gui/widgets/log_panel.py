"""日志面板 — 深色主题 QPlainTextEdit + 搜索高亮"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QLineEdit, QPushButton, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QFont, QTextCharFormat, QColor, QPalette,
    QSyntaxHighlighter,
)

LOG_LINE_LIMIT = 10000

# ── 深色日志样式 ─────────────────────────────────────────────
LOG_BG = QColor("#1e1e1e")
LOG_FG = QColor("#e6e6e6")
LOG_SEARCH_BG = QColor("#264f78")
LOG_SEARCH_FG = QColor("#ffffff")


class _SearchHighlighter(QSyntaxHighlighter):
    """关键词高亮器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyword = ""
        self._fmt = QTextCharFormat()
        self._fmt.setBackground(LOG_SEARCH_BG)
        self._fmt.setForeground(LOG_SEARCH_FG)

    def set_keyword(self, keyword: str) -> None:
        self._keyword = keyword.lower()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not self._keyword:
            return
        needle = self._keyword
        text_lower = text.lower()
        start = 0
        while True:
            idx = text_lower.find(needle, start)
            if idx < 0:
                break
            self.setFormat(idx, len(needle), self._fmt)
            start = idx + 1


class LogPanel(QWidget):
    """深色日志面板。

    方法:
        append(text)  -- 追加一行
        clear()       -- 清空
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_scroll = True
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()

        self._btn_clear = QPushButton("清空")
        self._btn_clear.clicked.connect(self.clear)
        toolbar.addWidget(self._btn_clear)

        toolbar.addStretch()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索…")
        self._search_edit.setMaximumWidth(200)
        self._search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self._search_edit)

        self._auto_cb = QCheckBox("滚动跟随")
        self._auto_cb.setChecked(True)
        self._auto_cb.toggled.connect(self._on_auto_toggled)
        toolbar.addWidget(self._auto_cb)

        layout.addLayout(toolbar)

        # 文本区
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._text.setMaximumBlockCount(LOG_LINE_LIMIT)

        pal = self._text.palette()
        pal.setColor(QPalette.Base, LOG_BG)
        pal.setColor(QPalette.Text, LOG_FG)
        self._text.setPalette(pal)

        layout.addWidget(self._text)

        # 搜索高亮
        self._highlighter = _SearchHighlighter(self._text.document())

    # ── 公共方法 ──────────────────────────────────────────────

    def append(self, text: str) -> None:
        self._text.appendPlainText(text)
        if self._auto_scroll:
            self._text.verticalScrollBar().setValue(
                self._text.verticalScrollBar().maximum())

    def clear(self) -> None:
        self._text.clear()

    # ── 槽 ────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self._highlighter.set_keyword(text)

    def _on_auto_toggled(self, checked: bool) -> None:
        self._auto_scroll = checked
