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
    first_sum = win._list.item(0).data(Qt.UserRole + 1) if n else ""
    step(f"首条释义预览: {first_sum!r}")
    assert isinstance(first_sum, str), "FAIL: 结果缺少释义预览数据(summary)"

    # 键盘导航: 在输入框按下 ↓/↑ 应切换联想选中项（直接给列表喂2个候选，
    # 避免 mini db 前缀结果只有1条的局限）
    win._list.clear()
    from PySide6.QtWidgets import QListWidgetItem
    win._list.addItem(QListWidgetItem("alpha")); win._list.addItem(QListWidgetItem("beta"))
    win._list.show()
    win._list.setCurrentRow(0)
    nav = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win._title, nav)
    row_after_down = win._list.currentRow()
    nav_up = QKeyEvent(QEvent.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win._title, nav_up)
    row_after_up = win._list.currentRow()
    step(f"键盘导航: Down后row={row_after_down} Up后row={row_after_up} (应 1 和 0)")
    if not (row_after_down == 1 and row_after_up == 0):
        raise RuntimeError("FAIL: ↑/↓ 未切换联想选中项")

    # 打开详情：验证详情窗口被创建并显示、内容非空
    before = [w.__class__.__name__ for w in app.topLevelWidgets()]
    win._open_word("apple")
    app.processEvents()
    after = [w.__class__.__name__ for w in app.topLevelWidgets()]
    step(f"详情前 top: {before}")
    step(f"详情后 top: {after}")
    from ui.detail_window import DetailWindow
    dlist = [w for w in app.topLevelWidgets() if isinstance(w, DetailWindow)]
    detail_refs = getattr(win, "_details", [])
    step(f"详情窗口: top-level={len(dlist)} 持有引用={len(detail_refs)}")
    shown = [w for w in dlist+detail_refs if w.isVisible()]
    step(f"详情可见: {len(shown)}")
    if shown:
        doc = shown[0]._browser.document()
        txt = doc.toPlainText()
        step(f"详情内容字符数: {len(txt)}" if txt.strip() else "警告: 详情内容为空")
    else:
        raise RuntimeError("FAIL: 详情窗口未显示 (top-level 或引用列表均为空)")

    # 详情渲染器: 用词典原文喂给 dict_render, 验证生成 h1+释义卡片
    raw = searcher.lookup("apple")[1]
    from ui.dict_render import convert_dict_html
    assert raw, "lookup('apple') 无正文"
    styled = convert_dict_html(raw)
    n_sense = styled.count("class='sense'")
    step(f"dict_render: h1={'<h1>' in styled} 释义卡片={n_sense}")
    step("dict_render: 生成可读排版 OK" if "<h1>" in styled else "警告: 渲染无词头")

    # 多词性健壮性: 喂一个含多词性(section)的真实结构, 应生成多个词性小节且不崩
    multi = ("<div id='entryContent'><div class='entry'><h1 class='headword'>run</h1>"
             "<span class='pos'>verb</span><ol class='sense_single'>"
             "<li class='sense'><span class='def'>to move fast</span><defT><chn>跑</chn></defT></li>"
             "</ol></div><div class='entry'><h1 class='headword'>run</h1>"
             "<span class='pos'>noun</span><ol class='sense_single'>"
             "<li class='sense'><span class='def'>an act of running</span><defT><chn>跑步</chn></defT></li>"
             "</ol></div></div>")
    mout = convert_dict_html(multi)
    n_pos = mout.count("class='posband'")
    m_sense = mout.count("class='sense'")
    step(f"dict_render 多词性: 词性小节={n_pos} (期望>=2) 释义卡片={m_sense}")
    if n_pos < 2:
        raise RuntimeError("FAIL: 多词性词条渲染未生成多个词性小节")

    # 重定向跟随: lookup(stepsons) 应命中主词条(或至少不崩溃) — mini db 无重定向则跳过
    try:
        disp, _h = searcher.lookup("stepsons")
        step(f"重定向跟随 lookup(stepsons) → {disp!r}")
    except Exception as e:
        raise RuntimeError(f"FAIL: lookup 重定向异常 {e}")

    # 透明度测试
    win.setWindowOpacity(1.0)
    win._is_active_opacity = False
    from ui.search_window import OPACITY_FOCUS_LOST
    win.setWindowOpacity(OPACITY_FOCUS_LOST)
    step(f"失焦透明度 → {win.windowOpacity()}")
    win.enterEvent(None)
    step(f"鼠标移入恢复 → {win.windowOpacity()}")
    # 回归：修复"移入后一直不透明"的 bug —— 失焦/移出后应能再次变透明。
    win.setWindowOpacity(1.0)
    win._is_active_opacity = True
    win._refresh_opacity(force_using=False)     # 无焦点 + 鼠标在外 → 判透明
    step(f"移出+失焦后透明度 → {win.windowOpacity()}")
    assert win.windowOpacity() < 0.5, "FAIL: 失焦/移出后未变透明(bug 复现)"
    win._refresh_opacity(force_using=True)      # 再悬停 → 恢复不透明
    step(f"再次使用后透明度 → {win.windowOpacity()}")
    assert win.windowOpacity() > 0.9, "FAIL: 复用后未恢复不透明"
    step("透明度回归 PASS")

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
    with open(os.path.join(_HERE, "smoke_result.txt"), "w", encoding="utf-8") as f:
        f.write(summary)
    print("\n=== SMOKE TEST PASSED (无异常) ===")
    app.quit()


if __name__ == "__main__":
    main()