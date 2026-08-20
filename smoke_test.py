# -*- coding: utf-8 -*-
"""GUI 冒烟测试（offscreen 模式，无真实显示）。"""
import os
import sys

# 强制 UTF-8 输出，避免 Windows cp1252 打印中文报错
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent

from dictionary.searcher import Searcher
from ui.search_window import SearchWindow

results = []


def step(msg):
    results.append(msg)
    print(msg)


def main():
    dbp = os.environ.get("DB", os.path.join(_HERE, "oxford_test.db"))
    app = QApplication([])
    searcher = Searcher(dbp)
    step(f"加载词典: {searcher.count} 词条")
    win = SearchWindow(searcher)
    win.show_window()
    step("窗口显示 OK")

    # 模拟搜索
    win._title.setText("app")
    win._do_search()
    n = win._list.count()
    step(f"搜索 'app' → {n} 条联想")
    first = win._list.item(0).data(Qt.UserRole) if n else None
    step(f"首条: {first!r}")

    # 打开详情：验证详情窗口被创建并显示、内容非空
    win._open_word("apple")
    app.processEvents()
    from ui.detail_window import DetailWindow
    dlist = [w for w in app.topLevelWidgets() if isinstance(w, DetailWindow)]
    shown = [w for w in dlist if w.isVisible()]
    step(f"详情窗口: 创建={len(dlist)} 可见={len(shown)}")
    if shown:
        doc = shown[0]._browser.document()
        txt = doc.toPlainText()
        step(f"详情内容字符数: {len(txt)}  (含词典正文)" if txt.strip() else "警告: 详情内容为空")

    # 透明度测试
    win.setWindowOpacity(1.0)
    win._is_active_opacity = False
    from ui.search_window import OPACITY_FOCUS_LOST
    win.setWindowOpacity(OPACITY_FOCUS_LOST)
    step(f"失焦透明度 → {win.windowOpacity()}")
    win.enterEvent(None)
    step(f"鼠标移入恢复 → {win.windowOpacity()}")

    # 搜索无匹配
    win._title.setText("zzzzqqqq")
    win._do_search()
    step(f"搜索无匹配: list可见={win._list.isVisible()}, 条数={win._list.count()}")

    # 键盘事件 (Esc 隐藏)
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(ev)
    step(f"Esc 后隐藏: {not win.isVisible()}")

    # 拖动模拟
    win.show()
    win._dragging = True
    win._drag_offset = QPoint(10, 10)
    win.move(100, 100)
    e = QMouseEvent(QEvent.Type.MouseMove, QPointF(200,150), Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.mouseMoveEvent(e)
    step(f"拖动后位置: {win.x()},{win.y()} (目标约 190,140)")

    summary = "\n".join(results)
    with open(os.path.join(_HERE, "smoke_result.txt"), "w") as f:
        f.write(summary)
    print("\n=== SMOKE TEST PASSED (无异常) ===")
    app.quit()


if __name__ == "__main__":
    main()