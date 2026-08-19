# -*- coding: utf-8 -*-
"""
轻量查词工具 - 入口。

用法:
    python main.py [oxford.db]

功能:
    - Ctrl+Shift+M 唤起/隐藏搜索窗 (Windows 全局热键)
    - Spotlight 式搜索，回车进详情
    - 失焦变透明，鼠标移入恢复
    - 若没有 oxford.db，首启引导选择 .mdx 词典并自动构建索引
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


def candidate_db_paths(argv) -> list:
    """候选数据库路径：命令行参数 > 可执行文件旁 > 项目根目录。"""
    here = _app_root()
    cands = [os.path.abspath(p) for p in argv[1:] if p.lower().endswith(".db")]
    cands += [
        os.path.join(here, "oxford.db"),
        os.path.join(here, "dict", "oxford.db"),
    ]
    return cands


def _app_root() -> str:
    """应用根目录（PyInstaller 打包后为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_existing_db(argv) -> str | None:
    for c in candidate_db_paths(argv):
        if os.path.exists(c):
            return os.path.abspath(c)
    return None


def _ask_mdx_path():
    """弹窗让用户选择 .mdx 词典文件。返回路径或 None。"""
    from PySide6.QtWidgets import QFileDialog

    default_dir = os.path.expanduser("~/Desktop")
    path, _ = QFileDialog.getOpenFileName(
        None, "选择 MDX 词典", default_dir,
        "MDX 词典 (*.mdx);;所有文件 (*)",
    )
    return path or None


def build_from_mdx(mdx_path: str) -> str:
    """把 .mdx 构建成 oxford.db，返回 db 路径。带简单进度提示。"""
    from PySide6.QtWidgets import QProgressDialog

    db_path = os.path.join(_app_root(), "oxford.db")
    prog = QProgressDialog(
        "正在构建词典索引（首次使用需少量时间，词条越多越久）…",
        "取消", 0, 100, None,
    )
    prog.setWindowTitle("构建词典")
    prog.setWindowModality(0)  # 非模态，避免卡
    prog.setMinimumDuration(0)
    prog.setValue(5)
    prog.show()

    from dictionary.indexer import build_from_mdx as _build
    stats = _build(mdx_path, db_path, verbose=False)
    prog.setValue(100)
    prog.close()
    return db_path


def ensure_dictionary(argv) -> str:
    """确保存在词典数据库：找到则返回，找不到则引导用户选 .mdx 构建。"""
    existing = find_existing_db(argv)
    if existing:
        return existing

    from PySide6.QtWidgets import QMessageBox

    # 用户取消/忽略直接退出
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("首次使用")
    box.setText("还没有词典数据库。\n是否现在选择你的 .mdx 词典文件来构建？（后续即可直接使用）")
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if box.exec() != QMessageBox.StandardButton.Yes:
        raise SystemExit(0)

    mdx_path = _ask_mdx_path()
    if not mdx_path:
        raise SystemExit(0)
    try:
        return build_from_mdx(mdx_path)
    except Exception as e:  # noqa: BLE001
        err = QMessageBox()
        err.setIcon(QMessageBox.Icon.Critical)
        err.setWindowTitle("构建失败")
        err.setText(f"无法构建词典库：\n{e}")
        err.exec()
        raise SystemExit(1)


def main():
    try:
        db_path = ensure_dictionary(sys.argv)
    except SystemExit:
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("Word Lookup")

    try:
        searcher = Searcher(db_path)
    except Exception as e:  # noqa: BLE001
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("词典加载失败")
        box.setText(str(e))
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