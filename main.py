"""
轻量查词工具 - 入口。

用法:
    python main.py [oxford.db]   # 启动查词工具
    python main.py --version     # 打印版本号

功能:
    - Ctrl+Shift+M 唤起/隐藏搜索窗 (Windows 全局热键)
    - Spotlight 式搜索，回车进详情
    - 失焦变透明，鼠标移入恢复
    - 若没有 oxford.db，首启引导选择 .mdx 词典并自动构建索引

修订:
  v0.1.1+ 启动引导移入 Qt 主事件循环后 (QTimer.singleShot)，避免打包后弹窗不显示。
  v0.1.6+ 词典索引构建放入独立子进程 (multiprocessing)，避免占用 GUI 主线程
          导致进度窗口白屏/未响应/被系统杀掉。
"""
import multiprocessing as _mp
import os
import sys
import traceback

# 源码运行/未打包时的回落版本号（发布 exe 的版本号由打包内 version.txt 指定，
# 由 CI 从 git tag 注入，见 build.yml —— 单一来源彻底根治版本错位）。
__version__ = "0.7.12DEV"


def get_version() -> str:
    """返回应用版本号。

    单一来源 <-> 打包内嵌 version.txt (CI 从 git 发布 tag 写入, 随 exe --add-data 打包)。
    读取优先级:
      1) 打包内嵌文件 (frozen): sys._MEIPASS/version.txt
      2) 源码旁边的 version.txt
      3) 代码内 __version__ 回落
    这样任一发布的 exe 报告版本永远等于该次发布的 git tag。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, "version.txt"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "version.txt"))
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as fh:
                v = fh.read().strip()
            if v:
                return v
        except OSError:
            continue
    return __version__

# 确保能 import 项目内模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PySide6.QtCore import QObject, Qt, QTimer, Signal
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


def _build_worker_proc(mdx_path: str, db_path: str, result_q):
    """(子进程入口) 在独立进程里构建词典索引。"""
    try:
        import os as _os
        # 确保子进程能找到 dictionary 包（源码运行时项目根；打包后 _HERE 为临时目录
        # 但词典模块打入 PYZ 由 PyInstaller 提供）
        _root = _os.path.dirname(_os.path.abspath(__file__))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from dictionary.indexer import build_from_mdx as _indexer_build

        _indexer_build(mdx_path, db_path, verbose=False)
        result_q.put(("done", db_path))
    except Exception as e:  # noqa: BLE001
        try:
            result_q.put(("error", f"{type(e).__name__}: {e}"))
        except Exception:
            pass


def _backfill_worker_proc(db_path: str, result_q):
    """(子进程入口) 就地补 summary 列(利用已存储 html，无需 mdx)。"""
    try:
        import os as _os
        _root = _os.path.dirname(_os.path.abspath(__file__))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from dictionary.indexer import backfill_summary

        changed, filled = backfill_summary(db_path)
        result_q.put(("done", (changed, filled)))
    except Exception as e:  # noqa: BLE001
        try:
            result_q.put(("error", f"{type(e).__name__}: {e}"))
        except Exception:
            pass


def maybe_backfill_summary(db_path: str):
    """若 db 缺 summary 列(旧版构建的老数据库)，就地补列并回填。

    关键设计：**纯同步、在主线程、一次连接**。在任何只读连接(Searcher)打开之前
    就把列补好，避免子进程写入与主线程读取之间的 "database is locked" 竞态。

    利用已存储的 html，无需 mdx。处理期间用 processEvents 保持窗口响应。
    """
    from dictionary.indexer import has_summary_col

    if has_summary_col(db_path):
        return  # 已是新版，无需处理

    write_log("[browse] 词典库缺 summary 列 → 就地补全释义预览…")
    from PySide6.QtWidgets import (
        QApplication as _QApp,
    )
    from PySide6.QtWidgets import (
        QProgressDialog,
    )

    prog = QProgressDialog(
        "正在为词典库补全释义预览（首次升级，仅需一次，请稍候…）",
        None, 0, 0, None,
    )
    prog.setWindowTitle("升级词典")
    prog.setWindowModality(Qt.WindowModality.NonModal)
    prog.setMinimumDuration(0)
    prog.setAutoClose(False)
    prog.setAutoReset(False)
    prog.show()
    _QApp.processEvents()

    try:
        # 纯同步、单连接补全；每个批次后 pump 事件避免窗口假死
        _run_backfill(db_path, hook=lambda t, c: _QApp.processEvents())
        write_log("[bootstrap] summary backfill done")
    except Exception as e:  # noqa: BLE001
        write_log("[backfill] FAILED: " + traceback.format_exc())
        from PySide6.QtWidgets import QMessageBox
        err = QMessageBox()
        err.setIcon(QMessageBox.Icon.Critical)
        err.setWindowTitle("升级失败")
        err.setText(f"无法补全释义预览：\n{e}")
        err.exec()
    finally:
        prog.close()


def _run_backfill(db_path, hook=None):
    """在调用线程内对 db 就地补全 summary 列，全程单连接，最后 conn 关闭。"""
    import sqlite3

    from dictionary.summary import extract_summary

    if not db_path or not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("ALTER TABLE words ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 列可能已存在
    rows = conn.execute("SELECT id, html FROM words")
    batch = []
    done = 0
    while True:
        chunk = rows.fetchmany(2000)
        if not chunk:
            break
        for rid, html in chunk:
            s = extract_summary(html or "")
            batch.append((s, rid))
        conn.executemany("UPDATE words SET summary=? WHERE id=?", batch)
        done += len(batch)
        batch = []
        if hook:
            hook(done, None)
    if batch:
        conn.executemany("UPDATE words SET summary=? WHERE id=?", batch)
        if hook:
            hook(done + len(batch), None)
    conn.commit()
    conn.close()

def build_from_mdx(mdx_path: str) -> str:
    """在子进程中把 .mdx 构建成 oxford.db。

    关键：构建在 multiprocessing 子进程里执行，GUI 主线程保持响应，
    进度窗口不会白屏/未响应。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox, QProgressDialog

    db_path = os.path.join(_app_root(), "oxford.db")

    # 启动子进程构建
    ctx = _mp.get_context("spawn" if sys.platform == "win32" else "fork")
    result_q = ctx.Queue()
    proc = ctx.Process(target=_build_worker_proc, args=(mdx_path, db_path, result_q), daemon=True)
    proc.start()
    write_log("[build] worker started (subprocess)")

    prog = QProgressDialog(
        "正在构建词典索引…\n大词典可能需要 1-5 分钟，请耐心等待。",
        "取消", 0, 0, None,   # range(0,0) = 不确定进度(转圈)
    )
    prog.setWindowTitle("构建词典")
    prog.setWindowModality(Qt.WindowModality.NonModal)
    prog.setMinimumDuration(0)
    prog.setAutoClose(False)
    prog.setAutoReset(False)
    prog.show()
    QApplication.processEvents()

    outcome = {"db": None, "err": None}

    def poll():
        if not result_q.empty():
            tag, val = result_q.get_nowait()
            if tag == "done":
                outcome["db"] = val
            else:
                outcome["err"] = val
            running[0] = False
            timer.stop()
            prog.close()
        elif not proc.is_alive() and running[0]:
            # 进程异常退出且没发结果
            running[0] = False
            timer.stop()
            prog.close()
            outcome["err"] = "构建进程异常退出"

    running = [True]
    timer = QTimer()
    timer.setInterval(300)
    timer.timeout.connect(poll)
    timer.start()

    # 阻塞等待用户取消或构建完成（循环内 processEvents 保持 UI 响应）
    while running[0] and prog.wasCanceled() is False:
        QApplication.processEvents()
        QApplication.processEvents()
        import time as _t
        _t.sleep(0.05)

    if running[0]:
        # 用户取消：终止子进程
        timer.stop()
        prog.close()
        try:
            proc.terminate()
        except Exception:
            pass
        write_log("[build] cancelled by user")
        raise SystemExit(0)

    if outcome["err"]:
        write_log("[build] FAILED: " + outcome["err"])
        err = QMessageBox()
        err.setIcon(QMessageBox.Icon.Critical)
        err.setWindowTitle("构建失败")
        err.setText(f"无法构建词典库：\n{outcome['err']}\n\n详细见程序目录 WordLookup.log")
        err.exec()
        raise RuntimeError(outcome["err"])

    write_log(f"[bootstrap] dictionary built: {outcome['db']}")
    return outcome["db"]


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
        # 老库(无 summary 列)就地升级出释义预览
        try:
            maybe_backfill_summary(db_path)
        except SystemExit:
            return 0
        except Exception as e:  # noqa: BLE001
            write_log(f"[bootstrap] summary backfill skipped: {e}")
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

    # 关键：bootstrap 是普通函数，返回后局部变量会被 Python 垃圾回收。
    # 必须把 window/bridge/searcher/gh 存到 app 上持有引用，否则信号源
    # (bridge) / 窗口会被回收 → 热键回调报 "Signal source has been deleted"、
    # 详情窗口消失等诡异现象。统一挂到 app._app_refs 容器。
    app._app_refs = {
        "searcher": searcher,
        "window": window,
        "bridge": bridge,
        "gh": None,
    }

    gh = None
    if sys.platform == "win32":
        try:
            from hotkey.win_hotkey import GlobalHotkey
            # 独立线程 + GetMessageW 监听 WM_HOTKEY，回调经信号跨线程投递到主线程
            gh = GlobalHotkey(["CTRL", "SHIFT"], "M", bridge.toggleRequested.emit, log=write_log)
            gh.start(wait=True)   # 阻塞到注册结果确定
            write_log("[bootstrap] hotkey registered")
        except Exception as e:  # noqa: BLE001
            write_log("[bootstrap] hotkey register FAILED: " + str(e))
            gh = None
    app._app_refs["gh"] = gh

    # 托盘图标：后台驻留时的可见入口（右键菜单打开/退出）
    _setup_tray(app, window, gh)

    # 无论是否 --show，启动后都显示一次搜索框——用户打开即见界面，
    # 不需要猜热键；Ctrl+Shift+M 用于随时唤起/隐藏。
    try:
        window.show_window()
        write_log("[bootstrap] window shown")
    except Exception:  # noqa: BLE001
        write_log("[bootstrap] window show FAILED:\n" + traceback.format_exc())
        return 1

    app._gh = gh  # 保存引用防 GC
    write_log("[bootstrap] ready")


def _setup_tray(app, window: SearchWindow, gh):
    """创建系统托盘图标，作为后台驻留的可见入口。"""

    def open_window():
        window.show_window()

    try:
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        app.setQuitOnLastWindowClosed(False)  # 关闭搜索框不退出进程

        tray = QSystemTrayIcon(app)
        # 用打包进来的图标
        icon_path = None
        if getattr(sys, "frozen", False):
            cand = os.path.join(os.path.dirname(sys.executable), "WordLookup.ico")
            if os.path.exists(cand):
                icon_path = cand
        if not icon_path:
            cand = os.path.join(_HERE, "assets", "WordLookup.ico")
            if os.path.exists(cand):
                icon_path = cand
        if icon_path:
            from PySide6.QtGui import QIcon
            tray.setIcon(QIcon(icon_path))

        menu = QMenu()
        act_open = menu.addAction("打开查词 (Ctrl+Shift+M)")
        act_open.triggered.connect(open_window)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(app.quit)

        tray.setContextMenu(menu)
        tray.setToolTip("Word Lookup — 按 Ctrl+Shift+M 唤起查词")
        tray.activated.connect(
            lambda reason: open_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.setVisible(True)
        app._tray = tray  # 防 GC
        write_log("[bootstrap] tray icon shown")
    except Exception as e:  # noqa: BLE001
        write_log("[bootstrap] tray setup FAILED: " + str(e))


class AppBridge(QObject):
    """把跨线程的热键回调安全地投递到 Qt 主线程。"""

    toggleRequested = Signal()

    def __init__(self, window: SearchWindow):
        super().__init__()
        self._window = window
        self.toggleRequested.connect(self._toggle)

    def _toggle(self):
        write_log("[hotkey] Ctrl+Shift+M pressed -> toggle")
        self._window.toggle()


# ----------------------------------------------------------------------------
def _print_version_to_parent_console() -> bool:
    """尽量在启动本 exe 的父终端(PowerShell/Windows Terminal/cmd)打印一行。

    PyInstaller --windowed 的 exe 默认不绑定控制台，sys.stdout 为 None，直接
    print 无处可去。这里用 Win32 AttachConsole(ATTACH_PARENT_PROCESS) 把自己
    接到父进程的终端，再把标准输出指向该终端的 CONOUT$ 句柄即可即时打印。

    注意: 绝不用 AllocConsole() 兜底 —— 那会凭空弹出一个一闪而过的黑框
    (用户已碰到)。附加失败就返回 False, 由调用方改用 Qt 模态弹窗。

    返回 True 表示已成功在父终端打印。
    """
    try:
        import ctypes
    except Exception:
        return False
    kd = ctypes.windll.kernel32
    if not kd.GetConsoleWindow():                 # 自身无控制台(PyInstaller windowed)
        kd.FreeConsole()                          # 排除残留绑定
        if not kd.AttachConsole(-1):             # ATTACH_PARENT_PROCESS
            return False                         # 没有可附加的父终端
    try:
        stdout_fd = kd.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if not stdout_fd or stdout_fd == -1:
            return False
        import io
        sys.stdout = io.TextIOWrapper(
            io.FileIO(stdout_fd, "w"), encoding="utf-8", newline="")
    except Exception:
        return False
    try:
        print(f"Word Lookup {get_version()}")
        sys.stdout.flush()
    except Exception:
        return False
    return True


def main():
    # ---- CLI 便捷参数：--version / -v ----
    if any(a in ("--version", "-v") for a in sys.argv[1:]):
        ok = False
        if sys.stdout is not None:               # 有控制台语境(源码 run/调试)
            print(f"Word Lookup {get_version()}")
            ok = True
        elif _print_version_to_parent_console():  # windowed 但在终端里启动
            ok = True
        if ok:
            return 0
        # 兜底：无法在终端打印(如双击启动) → Qt 模态框 (会阻塞直到用户点掉)
        # 局部只 import QMessageBox，绝不重复 import QApplication(避免遮蔽全局)。
        from PySide6.QtWidgets import QMessageBox
        app = QApplication(sys.argv)
        QMessageBox.information(
            None, "Word Lookup",
            f"Word Lookup\n版本 {get_version()}\n更新见 GitHub hufengxiao/word-lookup",
        )
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("Word Lookup")
    write_log("[startup] QApplication ready")

    # ---- 单实例保护：避免重复双击导致热键/db 冲突 ----
    try:
        from PySide6.QtCore import QLockFile
        lock_path = os.path.join(_app_root(), "wordlookup.lock")
        lock = QLockFile(lock_path)
        # 关键：给过期的锁留一个可回收时间。若设 0，崩溃/强杀残留的野锁永远不会
        # 被认作过期，导致"之前强制关了之后再也打不开"。设为 10s：
        #   - 若真有其他实例在运行 → 它会持续刷新锁，这里拿不到锁(仍会被拒绝)
        #   - 若是已崩溃进程留下的锁 → 超过 10s 自动判为陈旧并被回收
        lock.setStaleLockTime(10000)
        if lock.tryLock(100):
            app._lockfile = lock
        else:
            write_log("[startup] 已有 Word Lookup 在运行，本次启动退出")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        write_log("[startup] lock setup FAILED: " + str(e))

    # 进入主事件循环后触发引导（确保 Qt 对话框在事件循环内正常显示）
    QTimer.singleShot(0, lambda: bootstrap(app, sys.argv))

    try:
        rc = app.exec()
    finally:
        gh = getattr(app, "_gh", None)
        if gh:
            try:
                gh.stop()
            except Exception:
                pass
    return rc


if __name__ == "__main__":
    # PyInstaller + Windows multiprocessing 必需：子进程会重新进入 exe
    _mp.freeze_support()
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        write_log("FATAL top-level:\n" + traceback.format_exc())
        raise