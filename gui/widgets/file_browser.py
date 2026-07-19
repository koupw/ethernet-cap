"""文件浏览器 — QTreeView + QFileSystemModel 过滤 *.bin"""

import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTreeView, QPushButton, QCheckBox, QMenu, QFileSystemModel,
    QFileDialog, QMessageBox, QHeaderView,
)
from PySide6.QtCore import Qt, QDir, QTimer, Signal


class FileBrowser(QWidget):
    """bin 文件浏览器。

    信号:
        file_selected(str)  -- 用户点击/双击文件，参数为完整路径
    """

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: QFileSystemModel | None = None
        self._root_path = os.getcwd()
        self._auto_refresh_timer: QTimer | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()

        btn_open = QPushButton("浏览目录")
        btn_open.clicked.connect(self._browse_dir)
        toolbar.addWidget(btn_open)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        toolbar.addWidget(btn_refresh)

        toolbar.addStretch()

        self._auto_cb = QCheckBox("自动刷新")
        self._auto_cb.toggled.connect(self._toggle_auto_refresh)
        toolbar.addWidget(self._auto_cb)

        layout.addLayout(toolbar)

        # 文件树
        self._tree = QTreeView()
        self._tree.setRootIsDecorated(False)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(1, Qt.DescendingOrder)  # 按修改时间倒序
        self._tree.setSelectionMode(QTreeView.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._tree)

    # ── 公共方法 ────────────────────────────────────────────

    def set_root_path(self, path: str) -> None:
        """设置监控的根目录。"""
        self._root_path = path
        self.refresh()

    def root_path(self) -> str:
        return self._root_path

    def refresh(self) -> None:
        """刷新文件列表。"""
        old = self._model
        self._model = QFileSystemModel()
        self._model.setRootPath(self._root_path)
        self._model.setNameFilters(["*.bin"])
        self._model.setNameFilterDisables(False)
        self._model.setFilter(QDir.Files | QDir.NoDotAndDotDot)

        self._tree.setModel(self._model)
        self._tree.setRootIndex(self._model.index(self._root_path))

        # 释放旧模型（在设置新模型后安全删除）
        if old:
            old.deleteLater()

        # 隐藏不需要的列
        self._tree.setColumnHidden(0, True)  # 不显示完整路径列
        for i in range(1, self._model.columnCount()):
            if i not in (1, 2, 3):
                self._tree.setColumnHidden(i, True)

        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)

    # ── 槽 ──────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录", self._root_path)
        if path:
            self.set_root_path(path)

    def _on_double_clicked(self, index) -> None:
        info = self._model.fileInfo(index)
        if info.isFile() and info.suffix() == "bin":
            self.file_selected.emit(info.absoluteFilePath())

    def _on_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        info = self._model.fileInfo(index)
        if not info.isFile():
            return

        filepath = info.absoluteFilePath()
        menu = QMenu(self)

        act_open = menu.addAction("在波形查看器中打开")
        act_open.triggered.connect(lambda: self.file_selected.emit(filepath))

        menu.addSeparator()

        act_explorer = menu.addAction("在资源管理器中显示")
        act_explorer.triggered.connect(lambda: subprocess.Popen(
            ["explorer", "/select,", filepath]))

        menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _toggle_auto_refresh(self, checked: bool) -> None:
        if checked:
            self._auto_refresh_timer = QTimer(self)
            self._auto_refresh_timer.timeout.connect(self.refresh)
            self._auto_refresh_timer.start(2000)
        else:
            if self._auto_refresh_timer:
                self._auto_refresh_timer.stop()
                self._auto_refresh_timer = None
