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

修复说明 (v0.1.1+):
    启动引导(选词典/构建)必须在 Qt 主事件循环运行后触发。
    此前在 app.exec() 之前直接调用 QMessageBox/QFileDialog 的模态
    exec()，在 PyInstaller 打包环境窗口不显示，导致看似"双击没反应"。
    现改为进入主循环后由 QTimer.singleShot(0, ...) 触发引导。
"""
import os
import sys
import traceback

# 确保能 import 项目内模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from dictionary.searcher import Searcher
from ui.search_window import SearchWindow


# ----------------------------------------------------------------------------
# 日志（便于 release 排障）
# ----------------------------------------------------------------------------
def _log_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "WordLookup.log")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "WordLookup.log")


def write_log(msg: str):
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 词典定位与构建
# ----------------------------------------------------------------------------
def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def candidate_db_paths(argv) -> list:
    here = _app_root()
    cands = [os.path.abspath(p) for p in argv[1:] if p.lower().endswith(".db")]
    cands += [os.path.join(here, "oxford.db"), os.path.join(here, "dict", "oxford.db")]
    return cands


def find_existing_db(argv) -> str | None:
    for c in candidate_db_paths(argv):
        if os.path.exists(c):
            return os.path.abspath(c)
    return None


def _ask_mdx_path():
    """弹窗让用户选择 .mdx 词典文件。返回路径或 None。

    注意：用*实例化*的 QFileDialog（非静态方法）+ Qt 自绘对话框，
    避免 Windows 原生对话框在 PyInstaller 打包环境下瞬间消失的问题。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    last_dir = os.path.expanduser("~/Desktop")
    dlg = QFileDialog(None, "选择 MDX 词典", last_dir)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    dlg.setNameFilter("MDX 词典 (*.mdx);;所有文件 (*)")
    # 强制用 Qt 自绘对话框（不吃 Windows 原生对话框打包后瞬闪的坑）
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

    # 确保对话框置顶并聚焦
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    QApplication.processEvents()

    state = dlg.exec()  # 阻塞直到用户选定/取消
    if state and dlg.selectedFiles():
        return dlg.selectedFiles()[0]
    return None


def build_from_mdx(mdx_path: str) -> str:
    """把 .mdx 构建成 oxford.db，返回 db 路径。带简单进度提示。"""
    from PySide6.QtWidgets import QMessageBox, QProgressDialog

    db_path = os.path.join(_app_root(), "oxford.db")
    prog = QProgressDialog(
        "正在构建词典索引（首次使用需少量时间，词条越多越久）…",
        "取消", 0, 100, None,
    )
    prog.setWindowTitle("构建词典")
    prog.setWindowModality(0)
    prog.setMinimumDuration(0)
    prog.setValue(5)
    prog.show()
    QApplication.processEvents()

    try:
        from dictionary.indexer import build_from_mdx as _build
        _build(mdx_path, db_path, verbose=False)
    except Exception:
        write_log("build_from_mdx FAILED:\n" + traceback.format_exc())
        raise
    finally:
        prog.close()
    write_log(f"[bootstrap] dictionary built: {db_path}")
    return db_path


# ----------------------------------------------------------------------------
# 引导流程（仅在主事件循环内被调用）
# ----------------------------------------------------------------------------
def bootstrap(app, argv) -> int:
    """进入主循环后的初始化。返回进程退出码；0 表示正常, 1 表示致命错误。"""
    from PySide6.QtWidgets import QMessageBox

    write_log("[bootstrap] start")

    # 1. 词典数据库
    try:
        db_path = find_existing_db(argv)
        if not db_path:
            box = QMessageBox()
            box.setWindowTitle("Word Lookup")
            box.setText(
                "欢迎使用 Word Lookup！\n"
                "还没有词典数据库。是否现在选择你的 .mdx 词典文件来构建索引？"
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if box.exec() != QMessageBox.StandardButton.Yes:
                write_log("[bootstrap] user declined dictionary")
                return 0
            mdx_path = _ask_mdx_path()
            if not mdx_path:
                write_log("[bootstrap] no mdx chosen")
                return 0
            db_path = build_from_mdx(mdx_path)
        write_log(f"[bootstrap] db={os.path.basename(db_path)}")
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:  # noqa: BLE001
        write_log("[bootstrap] dictionary setup FAILED:\n" + traceback.format_exc())
        err = QMessageBox()
        err.setIcon(QMessageBox.Icon.Critical)
        err.setWindowTitle("词典初始化失败")
        err.setText(f"{e}\n\n详细见程序目录 WordLookup.log")
        err.exec()
        return 1

    # 2. 加载词典
    try:
        searcher = Searcher(db_path)
        write_log(f"[bootstrap] searcher loaded, entries={searcher.count}")
    except Exception as e:  # noqa: BLE001
        write_log("[bootstrap] searcher FAILED:\n" + traceback.format_exc())
        err = QMessageBox()
        err.setIcon(QMessageBox.Icon.Critical)
        err.setWindowTitle("词典加载失败")
        err.setText(str(e))
        err.exec()
        return 1

    # 3. 主窗口 + 热键
    window = SearchWindow(searcher)
    bridge = AppBridge(window)

    gh = None
    if sys.platform == "win32":
        try:
            from hotkey.win_hotkey import GlobalHotkey
            gh = GlobalHotkey(["CTRL", "SHIFT"], "M")
            gh.on_press = bridge.toggleRequested.emit
            gh.start()
            write_log("[bootstrap] hotkey registered")
        except Exception as e:  # noqa: BLE001
            write_log("[bootstrap] hotkey register FAILED: " + str(e))

    if "--show" in sys.argv or (sys.platform != "win32" and not gh):
        try:
            window.show_window()
            write_log("[bootstrap] window shown")
        except Exception as e:  # noqa: BLE001
            write_log("[bootstrap] window show FAILED:\n" + traceback.format_exc())
            return 1

    app._gh = gh  # 保存引用防 GC
    write_log("[bootstrap] ready")


class AppBridge(QObject):
    """把跨线程的热键回调安全地投递到 Qt 主线程。"""

    toggleRequested = Signal()

    def __init__(self, window: SearchWindow):
        super().__init__()
        self._window = window
        self.toggleRequested.connect(self._toggle)

    def _toggle(self):
        self._window.toggle()


# ----------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Word Lookup")
    write_log("[startup] QApplication ready")

    # 进入主事件循环后触发引导（确保 Qt 对话框在事件循环内正常显示）
    QTimer.singleShot(0, lambda: bootstrap(app, sys.argv))

    try:
        rc = app.exec()
    finally:
        gh = getattr(app, "_gh", None)
        if gh:
            try:
                gh.close()
            except Exception:
                pass
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        write_log("FATAL top-level:\n" + traceback.format_exc())
        raise