"""以太网上位机 — 兼容入口（委托 main_window）

保留旧入口兼容，实际启动统一 Qt 主窗口。
"""

import sys
from pathlib import Path

# 确保当前目录在 sys.path 中
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from main_window import main

if __name__ == "__main__":
    main()
