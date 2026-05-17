"""
以太网上位机 GUI 启动器
Python 3 + tkinter，通过 subprocess 启动 ethernet-cap.exe
"""

import subprocess
import signal
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

EXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "build", "ethernet-cap.exe")

FLAG_SPEC = [
    ("target_ip",  "-d",          True),   # (key, flag, always_include)
    ("local_ip",   "--local-ip",  False),
    ("data_port",  "--data-port", False),
    ("cmd_port",   "--cmd-port",  False),
    ("output_dir", "-o",          False),
    ("file_size",  "-s",          False),
    ("buf_size",   "-b",          False),
    ("timeout",    "-t",          False),
    ("total_size", "-T",          False),
]

DEFAULTS = {spec[0]: "" for spec in FLAG_SPEC}
DEFAULTS.update({
    "data_port": "9001", "cmd_port": "9002", "output_dir": ".",
    "file_size": "10", "buf_size": "32", "timeout": "5", "total_size": "0",
})

PROMPT_SENTINEL = "__GUI_PROMPT__"
LOG_LINE_LIMIT = 10000


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("以太网上位机 - AD 采集控制")
        self.root.resizable(True, True)
        self.root.minsize(700, 500)

        self.process = None
        self._gen = 0          # 世代计数器，防止过期 after() 回调
        self._log_buf = []
        self._flush_id = None

        self._build_ui()
        self._check_exe()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=300)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left.pack_propagate(False)

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._add_section(left, "必需参数")
        self.entries = {}
        self._add_row(left, "下位机 IP:", "target_ip", True)

        self._add_section(left, "可选参数")
        self._add_row(left, "本机 IP:",      "local_ip",   False)
        self._add_row(left, "数据端口:",      "data_port",  False)
        self._add_row(left, "命令端口:",      "cmd_port",   False)
        self._add_row(left, "输出目录:",      "output_dir", False, browse=True)
        self._add_row(left, "文件大小 (MB):", "file_size",  False)
        self._add_row(left, "缓冲大小 (MB):", "buf_size",   False)
        self._add_row(left, "超时 (秒):",     "timeout",    False)
        self._add_row(left, "总量上限 (MB):", "total_size", False, note="0=无限制")

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        self.btn_start = ttk.Button(btn_frame, text="开始采集", command=self.start)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_stop = ttk.Button(btn_frame, text="停止", command=self.stop,
                                   state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        self._add_section(right, "实时输出")
        log_frame = ttk.Frame(right)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED,
                                font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white")
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                                  command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _add_section(self, parent, title):
        ttk.Label(parent, text=title, font=("", 10, "bold")).pack(
            anchor=tk.W, pady=(10, 4))

    def _add_row(self, parent, label, key, required, browse=False, note=None):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)

        lbl = ttk.Label(frame, text=label, width=18, anchor=tk.W)
        lbl.pack(side=tk.LEFT)

        entry = ttk.Entry(frame, width=20)
        entry.insert(0, DEFAULTS.get(key, ""))
        entry.pack(side=tk.LEFT, padx=(0, 4))
        self.entries[key] = entry

        if browse:
            ttk.Button(frame, text="...", width=3,
                       command=lambda e=entry: self._browse_dir(e)
                       ).pack(side=tk.LEFT)

        if note:
            ttk.Label(frame, text=note, foreground="gray").pack(
                side=tk.LEFT, padx=(4, 0))

        if required:
            lbl.config(foreground="red")

    def _browse_dir(self, entry):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    # ------------------------------------------------------------------
    # 日志（缓冲 + 行数限制）
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
        # 限制行数
        end = self.log_text.index("end-1c")
        line_count = int(end.split(".")[0]) if end != "0" else 0
        if line_count > LOG_LINE_LIMIT:
            self.log_text.delete("1.0", f"{line_count - LOG_LINE_LIMIT}.0")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log_buf.clear()

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
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start(self):
        target_ip = self.entries["target_ip"].get().strip()
        if not target_ip:
            messagebox.showwarning("参数错误", "下位机 IP 不能为空")
            return

        # 取消所有待处理的 after() 回调，并递增世代
        self._gen += 1
        gen = self._gen
        if self._flush_id is not None:
            self.root.after_cancel(self._flush_id)
            self._flush_id = None

        cmd = self._build_cmd()
        self._clear_log()
        self._log(f"[CMD] {' '.join(cmd)}\n")
        self._log("=" * 56 + "\n")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
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

    # ------------------------------------------------------------------
    # UI 状态
    # ------------------------------------------------------------------
    def _set_running(self, running):
        state_fields = tk.DISABLED if running else tk.NORMAL
        for e in self.entries.values():
            e.config(state=state_fields)
        self.btn_start.config(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)

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
