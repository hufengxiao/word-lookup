# -*- coding: utf-8 -*-
"""
轻量查词工具 - 入口。

用法:
    python main.py [oxford.db]

功能:
    - Ctrl+Shift+M 唤起/隐藏搜索窗 (Windows 全局热键)
    - Spotlight 式搜索，回车进详情
    - 失焦变透明，鼠标移入恢复
"""
import os
import sys

# 确保能 import 项目内模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from dictionary.searcher import Searcher
from ui.search_window import SearchWindow


class AppBridge(QObject):
    """把跨线程的热键回调安全地投递到 Qt 主线程。"""

    toggleRequested = Signal()

    def __init__(self, window: SearchWindow):
        super().__init__()
        self._window = window
        self.toggleRequested.connect(self._toggle)

    def _toggle(self):
        self._window.toggle()


def find_db(argv) -> str:
    """定位词典数据库：命令行参数 > 可执行文件旁 > 项目根目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [p for p in argv[1:] if p.lower().endswith(".db")]
    candidates += [
        os.path.join(here, "oxford.db"),
        os.path.join(here, "dict", "oxford.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return candidates[0]


def main():
    db_path = find_db(sys.argv)
    app = QApplication(sys.argv)
    app.setApplicationName("Oxford Lookup")

    try:
        searcher = Searcher(db_path)
    except FileNotFoundError as e:
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("缺少词典数据库")
        box.setText(str(e))
        box.setDetailedText(
            "请先用 indexer 从 .mdx 构建 oxford.db，并放在程序同级目录：\n"
            "python -m dictionary.indexer <你的.mdx> oxford.db"
        )
        box.exec()
        return 1

    window = SearchWindow(searcher)
    bridge = AppBridge(window)

    gh = None
    if sys.platform == "win32":
        from hotkey.win_hotkey import GlobalHotkey
        gh = GlobalHotkey(["CTRL", "SHIFT"], "M")
        gh.on_press = bridge.toggleRequested.emit  # 跨线程发信号
        gh.start()

    if "--show" in sys.argv or (sys.platform != "win32" and not gh):
        window.show_window()

    try:
        rc = app.exec()
    finally:
        if gh:
            gh.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())