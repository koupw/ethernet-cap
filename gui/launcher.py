"""
以太网上位机 GUI 启动器
Python 3 + tkinter，通过 subprocess 启动 ethernet-cap.exe
深色专业主题 + 参数折叠 + 状态栏 + 日志搜索
"""

import subprocess
import signal
import os
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from dark_theme import apply_dark_theme
from waveform_viewer import WaveformViewer

EXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "build", "ethernet-cap.exe")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "gui_config.json")

FLAG_SPEC = [
    ("target_ip",   "-d",           True),   # (key, flag, always_include)
    ("local_ip",    "--local-ip",   False),
    ("data_port",   "--data-port",  False),
    ("cmd_port",    "--cmd-port",   False),
    ("output_dir",  "-o",           False),
    ("file_size",   "-s",           False),
    ("buf_size",    "-b",           False),
    ("timeout",     "-t",           False),
    ("total_size",  "-T",           False),
    ("cmd_start",   "--cmd-start",  False),
    ("cmd_stop",    "--cmd-stop",   False),
    ("tx_interval", "--tx-interval", False),
    ("preamble",    "--preamble",   False),
    ("data_addr",   "--data-addr",  False),
    ("cmd_addr",    "--cmd-addr",   False),
]

DEFAULTS = {spec[0]: "" for spec in FLAG_SPEC}
DEFAULTS.update({
    "data_port": "9001", "cmd_port": "9002", "output_dir": ".",
    "file_size": "10", "buf_size": "128", "timeout": "5", "total_size": "0",
    "cmd_start": "01",
    "cmd_stop": "00",
    "tx_interval": "1", "preamble": "A5 A5 A5 A5 A5 A5 A5 D5",
    "data_addr": "01", "cmd_addr": "02",
})

# 使用 Spinbox 的字段及范围: (key, from, to, increment)
SPINBOX_FIELDS = {
    "data_port":  (1, 65535, 1),
    "cmd_port":   (1, 65535, 1),
    "file_size":  (1, 1024, 1),
    "buf_size":   (1, 4096, 1),
    "timeout":    (1, 3600, 1),
    "total_size": (0, 1048576, 1),
    "tx_interval":(1, 60000, 1),
}

PROMPT_SENTINEL = "__GUI_PROMPT__"
LOG_LINE_LIMIT = 10000


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.theme = apply_dark_theme(root)
        self.root.title("以太网上位机 - AD 采集控制")
        self.root.resizable(True, True)
        self.root.minsize(860, 700)

        self.process = None
        self._gen = 0
        self._log_buf = []
        self._flush_id = None
        self._auto_scroll = tk.BooleanVar(value=True)
        self._search_query = ""

        self._build_ui()
        self._load_config()
        self._check_exe()
        self._update_status_bar()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- 左侧参数面板（滚动）---
        left_outer = ttk.Frame(main, width=370)
        left_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left_outer.pack_propagate(False)

        # 滚动容器
        canvas = tk.Canvas(left_outer, highlightthickness=0,
                           bg=self.theme["bg"], width=370)
        scrollbar_left = ttk.Scrollbar(left_outer, orient=tk.VERTICAL,
                                       command=canvas.yview)
        self.left_panel = ttk.Frame(canvas)
        self.left_panel.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.left_panel, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_left.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_left.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮绑定（仅本地，不使用 bind_all 以免影响波形查看器）
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Enter>", lambda e: canvas.focus_set())

        # --- 必需参数 ---
        self.entries = {}
        self._add_section(self.left_panel, "必需参数")
        self._add_row(self.left_panel, "下位机 IP:", "target_ip", True)

        # --- 可选参数 ---
        self._add_section(self.left_panel, "可选参数")
        self._add_row(self.left_panel, "本机 IP:",      "local_ip",   False)
        self._add_row(self.left_panel, "数据端口:",      "data_port",  False)
        self._add_row(self.left_panel, "命令端口:",      "cmd_port",   False)
        self._add_row(self.left_panel, "输出目录:",      "output_dir", False, browse=True)
        self._add_row(self.left_panel, "文件大小 (MB):", "file_size",  False)
        self._add_row(self.left_panel, "缓冲大小 (MB):", "buf_size",   False)
        self._add_row(self.left_panel, "超时 (秒):",     "timeout",    False)
        self._add_row(self.left_panel, "总量上限 (MB):", "total_size", False, note="0=无限制")
        self._add_row(self.left_panel, "开始命令 (hex):", "cmd_start", False, note="例: 01 02 03")
        self._add_row(self.left_panel, "停止命令 (hex):", "cmd_stop",  False)

        # --- COE 发送参数（可折叠）---
        self._coe_frame, self._coe_toggle_btn = self._add_collapsible_section(
            self.left_panel, "COE 发送参数", collapsed=True)
        self._add_row(self._coe_frame, "COE 文件:",      "coe_file",    False, browse_file=True)
        self._add_row(self._coe_frame, "发送间隔 (ms):",  "tx_interval", False)
        self._add_row(self._coe_frame, "引导码 (hex):",   "preamble",    False)
        self._add_row(self._coe_frame, "数据地址:",       "data_addr",   False)
        self._add_row(self._coe_frame, "命令地址:",       "cmd_addr",    False)

        # --- 按钮区 ---
        btn_frame = ttk.Frame(self.left_panel)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        row1 = ttk.Frame(btn_frame)
        row1.pack(fill=tk.X, pady=(0, 5))
        self.btn_start = ttk.Button(row1, text="开始采集",
                                    style="Accent.TButton",
                                    command=self.start)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_stop = ttk.Button(row1, text="停止",
                                   style="Danger.TButton",
                                   command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        row2 = ttk.Frame(btn_frame)
        row2.pack(fill=tk.X)
        self.btn_send_data = ttk.Button(row2, text="发送数据",
                                         command=self.send_coe_data)
        self.btn_send_data.pack(side=tk.LEFT)

        row3 = ttk.Frame(btn_frame)
        row3.pack(fill=tk.X, pady=(5, 0))
        self.btn_view_wave = ttk.Button(row3, text="查看波形",
                                        command=self.open_waveform_viewer)
        self.btn_view_wave.pack(side=tk.LEFT, padx=(0, 12))
        self.auto_view_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="采集后自动查看",
                        variable=self.auto_view_var).pack(side=tk.LEFT)

        # --- 右侧：日志区 ---
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 日志区标题
        self._add_section(right, "实时输出")

        # 日志工具条：[清空] [搜索] [滚动跟随]
        log_toolbar2 = ttk.Frame(right)
        log_toolbar2.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(log_toolbar2, text="清空",
                   command=self._clear_log).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(log_toolbar2, text="搜索:").pack(side=tk.LEFT, padx=(2, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        search_entry = ttk.Entry(log_toolbar2, textvariable=self.search_var,
                                 width=20)
        search_entry.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Checkbutton(log_toolbar2, text="滚动跟随",
                        variable=self._auto_scroll).pack(side=tk.LEFT)

        log_frame = ttk.Frame(right)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 10),
                                bg=self.theme["log_bg"],
                                fg=self.theme["log_fg"],
                                insertbackground=self.theme["text"],
                                selectbackground=self.theme["log_select"],
                                selectforeground=self.theme["log_select_fg"],
                                borderwidth=0, relief=tk.FLAT,
                                highlightthickness=0)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                                  command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- 底部状态栏 ---
        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Separator(self.status_bar, orient=tk.HORIZONTAL).pack(fill=tk.X)
        status_inner = ttk.Frame(self.status_bar, padding=(8, 4))
        status_inner.pack(fill=tk.X)
        self.status_led = tk.Label(status_inner, text="●", fg=self.theme["text_green"],
                                   bg=self.theme["bg"], font=("", 11))
        self.status_led.pack(side=tk.LEFT, padx=(0, 6))
        self.status_label = ttk.Label(status_inner, text="就绪",
                                      style="Note.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=(0, 16))
        self.status_ip = ttk.Label(status_inner, text="", style="Note.TLabel")
        self.status_ip.pack(side=tk.LEFT, padx=(0, 16))
        self.status_data = ttk.Label(status_inner, text="", style="Note.TLabel")
        self.status_data.pack(side=tk.LEFT)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _add_section(self, parent, title):
        ttk.Label(parent, text=title, style="Section.TLabel").pack(
            anchor=tk.W, pady=(10, 4))

    def _add_collapsible_section(self, parent, title, collapsed=False):
        """创建可折叠的参数区段。返回 (content_frame, toggle_button)。"""
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(10, 2))

        arrow_char = "▶" if collapsed else "▼"
        btn = ttk.Label(header, text=f" {arrow_char} {title}",
                        style="Section.TLabel", cursor="hand2")
        btn.pack(anchor=tk.W)

        content = ttk.Frame(parent)
        if not collapsed:
            content.pack(fill=tk.X, pady=(0, 4))

        def toggle(event=None):
            nonlocal collapsed
            collapsed = not collapsed
            if collapsed:
                content.pack_forget()
                btn.config(text=f" ▶ {title}")
            else:
                content.pack(fill=tk.X, pady=(0, 4), after=header)
                btn.config(text=f" ▼ {title}")

        btn.bind("<Button-1>", toggle)
        return content, btn

    def _add_row(self, parent, label, key, required, browse=False,
                 browse_file=False, note=None):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        lbl_style = "Required.TLabel" if required else "TLabel"
        lbl = ttk.Label(frame, text=label, width=18, anchor=tk.W,
                        style=lbl_style)
        lbl.pack(side=tk.LEFT)

        # Spinbox 或 Entry
        if key in SPINBOX_FIELDS:
            frm, to, inc = SPINBOX_FIELDS[key]
            entry = ttk.Spinbox(frame, from_=frm, to=to, increment=inc,
                                width=22)
        else:
            entry = ttk.Entry(frame, width=24)

        entry.delete(0, tk.END)
        entry.insert(0, DEFAULTS.get(key, ""))
        entry.pack(side=tk.LEFT, padx=(0, 4))
        self.entries[key] = entry

        if browse:
            ttk.Button(frame, text="...", width=3,
                       command=lambda e=entry: self._browse_dir(e)
                       ).pack(side=tk.LEFT)
        elif browse_file:
            ttk.Button(frame, text="...", width=3,
                       command=lambda e=entry: self._browse_file(e)
                       ).pack(side=tk.LEFT)

        if note:
            ttk.Label(frame, text=note, style="Note.TLabel").pack(
                side=tk.LEFT, padx=(4, 0))

    def _browse_dir(self, entry):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def _browse_file(self, entry):
        path = filedialog.askopenfilename(
            title="选择 COE 文件",
            filetypes=[("COE 文件", "*.coe"), ("所有文件", "*.*")]
        )
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    # ------------------------------------------------------------------
    # 日志（缓冲 + 行数限制 + 搜索高亮）
    # ------------------------------------------------------------------
    def _log(self, text):
        self._log_buf.append(text)
        if self._flush_id is None:
            self._flush_id = self.root.after(100, self._flush_log)

    def _flush_log(self):
        self._flush_id = None
        if not self._log_buf:
            return
        text = "".join(self._log_buf)
        self._log_buf.clear()

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        end = self.log_text.index("end-1c")
        line_count = int(end.split(".")[0]) if end != "0" else 0
        if line_count > LOG_LINE_LIMIT:
            self.log_text.delete("1.0", f"{line_count - LOG_LINE_LIMIT}.0")
        if self._auto_scroll.get():
            self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

        self._apply_search_highlight()
        self._update_status_bar()

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log_buf.clear()

    def _on_search(self, *args):
        self._search_query = self.search_var.get().strip().lower()
        self._apply_search_highlight()

    def _apply_search_highlight(self):
        """清除旧高亮 → 搜索匹配行 → 高亮。"""
        self.log_text.config(state=tk.NORMAL)
        # 清除旧 tag
        self.log_text.tag_remove("search_match", "1.0", "end")
        # 应用搜索高亮
        if self._search_query:
            start = "1.0"
            first = True
            while True:
                pos = self.log_text.search(self._search_query, start,
                                           stopindex="end", nocase=True)
                if not pos:
                    break
                line_end = f"{pos} lineend"
                self.log_text.tag_add("search_match", pos, line_end)
                start = f"{pos} + 1 line"
                if first:
                    self.log_text.see(pos)
                    first = False
        self.log_text.tag_configure("search_match",
                                    background=self.theme["accent"],
                                    foreground="#ffffff")
        self.log_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------
    def _update_status_bar(self):
        if self.process and self.process.poll() is None:
            self.status_led.config(fg=self.theme["text_green"])
            self.status_label.config(text="运行中")
        else:
            self.status_led.config(fg="#808080")
            self.status_label.config(text="就绪")

        ip = self.entries.get("target_ip")
        if ip:
            self.status_ip.config(text=f"IP: {ip.get().strip()}")

        # 从日志中解析最新累计数据量
        log_content = self.log_text.get("1.0", "end-1c")
        import re
        m = re.findall(r"累计:\s*(\d+)\s*MB", log_content)
        if m:
            self.status_data.config(text=f"数据: {m[-1]} MB")
        else:
            self.status_data.config(text="数据: 0 MB")

    # ------------------------------------------------------------------
    # 命令行构建（数据驱动）
    # ------------------------------------------------------------------
    def _build_cmd(self):
        cmd = [EXE_PATH]
        for key, flag, always in FLAG_SPEC:
            val = self.entries[key].get().strip()
            if always or (val and val != DEFAULTS[key]):
                cmd += [flag, val]
        return cmd

    # ------------------------------------------------------------------
    # exe 检查
    # ------------------------------------------------------------------
    def _check_exe(self):
        if not os.path.exists(EXE_PATH):
            self._log(f"[WARN] 未找到 ethernet-cap.exe: {EXE_PATH}\n"
                      f"[WARN] 请先编译项目\n")
            self.btn_start.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------
    def _save_config(self):
        data = {key: self.entries[key].get().strip()
                for key in self.entries}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        for key, val in data.items():
            if key in self.entries and isinstance(val, str):
                self.entries[key].delete(0, tk.END)
                self.entries[key].insert(0, val)

    # ------------------------------------------------------------------
    # 波形查看器
    # ------------------------------------------------------------------
    def open_waveform_viewer(self):
        output_dir = self.entries["output_dir"].get().strip() or "."
        WaveformViewer(parent=self.root, output_dir=output_dir,
                       theme=self.theme)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self):
        target_ip = self.entries["target_ip"].get().strip()
        if not target_ip:
            messagebox.showwarning("参数错误", "下位机 IP 不能为空")
            return

        self._save_config()

        self._gen += 1
        gen = self._gen
        if self._flush_id is not None:
            self.root.after_cancel(self._flush_id)
            self._flush_id = None

        cmd = self._build_cmd()
        self._clear_log()
        self._log(f"[CMD] {' '.join(cmd)}\n")
        self._log("=" * 56 + "\n")

        self._launch_process(cmd, gen)

    def send_coe_data(self):
        target_ip = self.entries["target_ip"].get().strip()
        coe_file = self.entries["coe_file"].get().strip()
        if not target_ip:
            messagebox.showwarning("参数错误", "下位机 IP 不能为空")
            return
        if not coe_file:
            messagebox.showwarning("参数错误", "COE 文件路径不能为空")
            return

        self._save_config()
        self._gen += 1
        gen = self._gen
        if self._flush_id is not None:
            self.root.after_cancel(self._flush_id)
            self._flush_id = None

        cmd = [EXE_PATH, "-d", target_ip, "--coe-file", coe_file]
        lip = self.entries["local_ip"].get().strip()
        if lip:
            cmd += ["--local-ip", lip]
        for key, flag in [("tx_interval", "--tx-interval"),
                          ("preamble", "--preamble"),
                          ("data_addr", "--data-addr"),
                          ("cmd_addr", "--cmd-addr")]:
            val = self.entries[key].get().strip()
            if val and val != DEFAULTS.get(key, ""):
                cmd += [flag, val]

        self._clear_log()
        self._log(f"[CMD] {' '.join(cmd)}\n")
        self._log("=" * 56 + "\n")

        self._launch_process(cmd, gen)

    def _launch_process(self, cmd, gen):
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                              | subprocess.CREATE_NO_WINDOW,
            )
        except OSError as e:
            self._log(f"[ERR] 启动进程失败: {e}\n")
            if e.errno == 2:
                messagebox.showerror("启动失败",
                                     f"未找到 ethernet-cap.exe:\n{EXE_PATH}")
            else:
                messagebox.showerror("启动失败", str(e))
            return

        self._set_running(True)
        self._update_status_bar()
        threading.Thread(target=self._read_stderr, args=(gen,), daemon=True).start()
        threading.Thread(target=self._read_stdout, args=(gen,), daemon=True).start()

    def stop(self):
        if not self.process:
            return
        self._log("\n[GUI] 正在发送停止信号...\n")
        try:
            os.kill(self.process.pid, signal.CTRL_BREAK_EVENT)
        except OSError:
            try:
                self.process.terminate()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 管道读取
    # ------------------------------------------------------------------
    def _read_stderr(self, gen):
        try:
            for line in self.process.stderr:
                if gen != self._gen:
                    break
                self._log(line)
                if PROMPT_SENTINEL in line:
                    self.root.after(500, self._send_enter, gen)
        except (ValueError, OSError):
            pass

        if gen == self._gen:
            self.root.after(0, self._on_process_exit, gen)

    def _read_stdout(self, gen):
        try:
            for _ in self.process.stdout:
                if gen != self._gen:
                    break
        except (ValueError, OSError):
            pass

        if gen == self._gen:
            self.root.after(0, self._on_process_exit, gen)

    def _send_enter(self, gen):
        if gen != self._gen or self.process is None:
            return
        if self.process.poll() is not None:
            return
        try:
            self.process.stdin.write("\n")
            self.process.stdin.flush()
            self._log("[GUI] 已自动发送 Enter 开始采集\n")
        except (OSError, ValueError):
            pass

    def _on_process_exit(self, gen):
        if gen != self._gen or self.process is None:
            return
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

        rc = self.process.returncode
        self._log(f"\n[GUI] 进程已退出，返回码: {rc}\n")
        self.process = None
        self._set_running(False)
        self._update_status_bar()

        if self.auto_view_var.get() and rc == 0:
            self.root.after(300, self.open_waveform_viewer)

    # ------------------------------------------------------------------
    # UI 状态
    # ------------------------------------------------------------------
    def _set_running(self, running):
        state_fields = tk.DISABLED if running else tk.NORMAL
        for e in self.entries.values():
            e.config(state=state_fields)
        self.btn_start.config(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)
        self.btn_send_data.config(state=tk.DISABLED if running else tk.NORMAL)

    def _on_close(self):
        if self.process and self.process.poll() is None:
            self.stop()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()