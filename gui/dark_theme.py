"""
深色专业主题 — 统一应用于上位机和波形查看器
基于 clam 主题（唯一在 Windows 上完全支持自定义颜色的 ttk 主题）
"""

from tkinter import ttk

# ===========================================================================
# 色板（VS Code Dark+ 风格）
# ===========================================================================
DARK_BG       = "#1e1e1e"   # 主背景
DARK_PANEL    = "#252526"   # 面板/输入框背景
DARK_BORDER   = "#3f3f46"   # 边框
DARK_ACTIVE   = "#3f3f46"   # 激活态背景
ACCENT        = "#007acc"   # 强调色（蓝）
ACCENT_HOVER  = "#1f6feb"   # 强调色悬停
TEXT          = "#e6e6e6"   # 正文文字
TEXT_DIM      = "#717171"   # 次要/禁用文字
TEXT_RED      = "#f48771"   # 红色（必填、错误）
TEXT_GREEN    = "#89d185"   # 绿色（状态就绪）
TEXT_GRAY     = "#808080"   # 备注灰色
SELECT_BG     = "#264f78"   # 选中背景
GRID_COLOR    = "#333333"   # matplotlib 网格
CURSOR_COLOR  = "#ffd700"   # 游标颜色（金色）


def apply_dark_theme(root):
    """将深色主题应用到根窗口及其下所有 ttk 控件。

    应在创建任何 ttk 控件之前调用。
    """
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=DARK_BG)

    # --- Frame ---
    style.configure("TFrame", background=DARK_BG)

    # --- Label ---
    style.configure("TLabel", background=DARK_BG, foreground=TEXT)
    # 区段标题
    style.configure("Section.TLabel",
                    background=DARK_BG, foreground=TEXT,
                    font=("", 10, "bold"))
    # 备注
    style.configure("Note.TLabel",
                    background=DARK_BG, foreground=TEXT_GRAY)
    # 必填
    style.configure("Required.TLabel",
                    background=DARK_BG, foreground=TEXT_RED,
                    font=("", 10, "bold"))

    # --- Button ---
    style.configure("TButton",
                    background=DARK_PANEL, foreground=TEXT,
                    bordercolor=DARK_BORDER, lightcolor=DARK_BORDER,
                    darkcolor=DARK_BG, focuscolor=DARK_BORDER,
                    relief="flat", borderwidth=1, padding=(8, 4))
    style.map("TButton",
             background=[("active", DARK_ACTIVE),
                         ("pressed", ACCENT),
                         ("disabled", DARK_BG)],
             foreground=[("disabled", TEXT_DIM)],
             bordercolor=[("focus", ACCENT)])

    # 强调按钮（开始采集等主操作）
    style.configure("Accent.TButton",
                    background=ACCENT, foreground="#ffffff",
                    bordercolor=ACCENT, lightcolor=ACCENT,
                    darkcolor=ACCENT, relief="flat",
                    borderwidth=1, padding=(8, 4))
    style.map("Accent.TButton",
             background=[("active", ACCENT_HOVER),
                         ("pressed", ACCENT_HOVER),
                         ("disabled", DARK_BG)],
             foreground=[("disabled", TEXT_DIM)])

    # 危险按钮（停止）
    style.configure("Danger.TButton",
                    background="#a1260d", foreground="#ffffff",
                    bordercolor="#a1260d", relief="flat",
                    borderwidth=1, padding=(8, 4))
    style.map("Danger.TButton",
             background=[("active", "#c4391a"),
                         ("pressed", "#c4391a"),
                         ("disabled", DARK_BG)],
             foreground=[("disabled", TEXT_DIM)])

    # --- Entry ---
    style.configure("TEntry",
                    fieldbackground=DARK_PANEL, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=DARK_BORDER,
                    lightcolor=DARK_BORDER, darkcolor=DARK_BG,
                    relief="flat", borderwidth=1, padding=3)
    style.map("TEntry",
             fieldbackground=[("readonly", DARK_BG)],
             bordercolor=[("focus", ACCENT)])

    # --- Spinbox ---
    style.configure("TSpinbox",
                    fieldbackground=DARK_PANEL, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=DARK_BORDER,
                    lightcolor=DARK_BORDER, darkcolor=DARK_BG,
                    relief="flat", borderwidth=1, padding=3,
                    arrowcolor=TEXT)
    style.map("TSpinbox",
             fieldbackground=[("readonly", DARK_BG)],
             bordercolor=[("focus", ACCENT)])

    # --- Checkbutton ---
    style.configure("TCheckbutton",
                    background=DARK_BG, foreground=TEXT,
                    indicatorbackground=DARK_PANEL,
                    indicatorforeground=ACCENT,
                    bordercolor=DARK_BORDER, relief="flat")
    style.map("TCheckbutton",
             background=[("active", DARK_BG)],
             indicatorbackground=[("selected", ACCENT)],
             foreground=[("disabled", TEXT_DIM)])

    # --- Scrollbar ---
    style.configure("TScrollbar",
                    background=DARK_PANEL, troughcolor=DARK_BG,
                    arrowcolor=TEXT, bordercolor=DARK_BORDER,
                    relief="flat", borderwidth=0)
    style.map("TScrollbar",
             background=[("active", DARK_ACTIVE)])

    # --- Treeview（文件列表）---
    style.configure("Treeview",
                    background=DARK_PANEL, fieldbackground=DARK_PANEL,
                    foreground=TEXT, bordercolor=DARK_BORDER,
                    rowheight=24)
    style.map("Treeview",
             background=[("selected", SELECT_BG)],
             foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading",
                    background=DARK_ACTIVE, foreground=TEXT,
                    relief="flat", borderwidth=0)
    style.map("Treeview.Heading",
             background=[("active", DARK_BORDER)])

    # --- Separator ---
    style.configure("TSeparator",
                    background=DARK_BORDER)

    # --- LabelFrame ---
    style.configure("TLabelframe",
                    background=DARK_BG, foreground=TEXT,
                    bordercolor=DARK_BORDER, relief="flat",
                    borderwidth=1)
    style.configure("TLabelframe.Label",
                    background=DARK_BG, foreground=TEXT,
                    font=("", 9, "bold"))

    # --- 日志 Text 控件颜色（供调用方使用）---
    LOG_TEXT_BG       = DARK_BG
    LOG_TEXT_FG       = TEXT
    LOG_SELECT_BG     = SELECT_BG
    LOG_SELECT_FG     = "#ffffff"

    return {
        "bg":          DARK_BG,
        "panel":        DARK_PANEL,
        "border":       DARK_BORDER,
        "accent":       ACCENT,
        "accent_hover": ACCENT_HOVER,
        "text":         TEXT,
        "text_dim":     TEXT_DIM,
        "text_red":     TEXT_RED,
        "text_green":   TEXT_GREEN,
        "text_gray":    TEXT_GRAY,
        "select_bg":    SELECT_BG,
        "grid_color":   GRID_COLOR,
        "cursor_color": CURSOR_COLOR,
        "log_bg":       LOG_TEXT_BG,
        "log_fg":       LOG_TEXT_FG,
        "log_select":   LOG_SELECT_BG,
        "log_select_fg": LOG_SELECT_FG,
    }