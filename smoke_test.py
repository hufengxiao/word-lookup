# -*- coding: utf-8 -*-
"""GUI 冒烟测试（offscreen 模式，无真实显示）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

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
    win._edit.setText("app")
    win._do_search()
    n = win._list.count()
    step(f"搜索 'app' → {n} 条联想")
    first = win._list.item(0).data(0x0100) if n else None  # Qt.UserRole
    step(f"首条: {first!r}")

    # 打开详情
    win._open_word("apple")
    nwin = app.topLevelWidgets()
    step(f"详情窗口数: {len(nwin)}")

    # 透明度测试
    win.setWindowOpacity(1.0)
    win._is_active_opacity = False
    from ui.search_window import OPACITY_FOCUS_LOST
    win.setWindowOpacity(OPACITY_FOCUS_LOST)
    step(f"失焦透明度 → {win.windowOpacity()}")
    win.enterEvent(None)
    step(f"鼠标移入恢复 → {win.windowOpacity()}")

    # 搜索无匹配
    win._edit.setText("zzzzqqqq")
    win._do_search()
    step(f"搜索无匹配: list可见={win._list.isVisible()}, 条数={win._list.count()}")

    # 键盘事件 (Esc 隐藏)
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import Qt
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(ev)
    step(f"Esc 后隐藏: {not win.isVisible()}")

    # 拖动模拟
    from PySide6.QtGui import QMouseEvent, QPointF
    from PySide6.QtCore import QPoint, QEvent
    win.show()
    win._dragging = True
    win._drag_offset = QPoint(10, 10)
    win.move(100, 100)
    e = QMouseEvent(QEvent.Type.MouseMove, QPointF(200,150), Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.mouseMoveEvent(e)
    step(f"拖动后位置: {win.x()},{win.y()} (目标约 290,240)")

    summary = "\n".join(results)
    with open("/root/oxford-lookup/smoke_result.txt", "w") as f:
        f.write(summary)
    print("\n=== SMOKE TEST PASSED (无异常) ===")
    app.quit()


if __name__ == "__main__":
    main()