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
    assert isinstance(first_sum, str), "FAIL: 结果条目缺少释义预览数据(summary)"

    # 键盘导航: 在输入框按下 ↓/↑ 应切换联想选中项（直接给列表喂2个候选，
    # 避免 mini db 前缀结果只有1条的局限）
    win._list.clear()
    from PySide6.QtWidgets import QListWidgetItem
    win._list.addItem(QListWidgetItem("alpha")); win._list.addItem(QListWidgetItem("beta"))
    win._list.show()
    win._list.setCurrentRow(0)
    nav = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win._title, nav)
    row_after_down = win._list.currentRow()
    nav_up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win._title, nav_up)
    row_after_up = win._list.currentRow()
    step(f"键盘导航: Down后row={row_after_down} Up后row={row_after_up} (应 1 和 0)")
    if not (row_after_down == 1 and row_after_up == 0):
        raise RuntimeError("FAIL: ↑/↓ 未切换联想选中项")

    # 打开详情：应切换进"详情视图"，详情正文渲染进内嵌视图（不再弹独立窗口）
    win._title.setText("app")
    win._do_search()
    win._show_detail("apple")
    app.processEvents()
    step(f"视图模式: {win._mode} (应 detail)")
    assert win._mode == "detail", "FAIL: 未进入详情视图模式"
    step(f"详情视图可见: {win._detail_view.isVisible()}, 列表隐藏: {not win._list.isVisible()}")
    assert win._detail_view.isVisible(), "FAIL: 内嵌详情视图未显示"
    doc = win._detail_view.document()
    txt = doc.toPlainText()
    step(f"详情内容字符数: {len(txt)}" if txt.strip() else "警告: 详情内容为空")
    step(f"窗口高度(详情): {win.height()} (应={__import__('ui.search_window', fromlist=['H_DETAIL']).H_DETAIL})")
    # 高度动画回归：把手动推进 _resize_tick 直到目标，验证确实到达 H_DETAIL
    import ui.search_window as _sw
    for _ in range(60):
        win._resize_tick()
        if win._resize_to == win.height() and not win._resize_timer.isActive():
            break
    assert win.height() == _sw.H_DETAIL, f"FAIL: 详情高度动画未到达 H_DETAIL (got {win.height()})"
    step(f"高度动画达到详情高度: {win.height()} PASS")

    # Esc 返回列表视图
    ev_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(ev_esc)
    step(f"详情按 Esc → 返回列表: mode={win._mode}, 详情隐藏={not win._detail_view.isVisible()}, 列表可见={win._list.isVisible()}")
    assert win._mode == "list" and not win._detail_view.isVisible(), "FAIL: Esc 未返回列表视图"

    # 详情渲染器: 用词典原文喂给 dict_render, 验证生成 h1+释义卡片
    raw = searcher.lookup("apple")[1]
    from ui.dict_render import convert_dict_html
    assert raw, "lookup('apple') 无正文"
    styled = convert_dict_html(raw)
    n_sense = styled.count("class='sense'")
    step(f"dict_render: h1={'<h1>' in styled} 释义卡片={n_sense}")
    step("dict_render: 生成可读排版 OK" if "<h1>" in styled else "警告: 渲染无词头")

    # 例句英文/中文拆分: 真实牛津结构中 EN(x)与中文(xT><chn>)应分到两行
    from ui.dict_render import _extract_examples
    ex_in = ("<ul class='examples'><li><span class='x'>general <span class='gloss'>(= typical)</span> trend</span>"
             "<xT><chn>总趋势</chn></xT></li></ul>")
    ex_pairs = _extract_examples(ex_in)
    assert ex_pairs and len(ex_pairs[0]) == 2, "FAIL: 例句未拆成(英文,中文)"
    _en, _cn = ex_pairs[0]
    step(f"dict_render 例句拆分: 英文={_en[:18]!r} | 中文={_cn!r} (期望分开两行)")

    # 例句中文: OALD10 例句翻译可能用 xT/aT/oT 三种容器, 都必须能提中文
    ex_oT = _extract_examples("<ul class='examples'><li><span class='x'>IQs show a normal distribution.</span>"
                              "<oT><chn><other>人口智商呈正态分布。</other></chn></oT></li></ul>")
    assert ex_oT and ex_oT[0][1], "FAIL: oT 容器例句的中文未提取到(人口智商这种 oT 例句漏翻译)"
    step(f"dict_render 例句中文 oT: {ex_oT[0][1]!r} ✓")

    # 例句健壮性: 没有 <ul class="examples"> 的词条(如 General American)必须返回空,
    # 绝不允许把整个词条正文(词性/音标/释义/Culture大段)硬凑成一条超长"例句"。
    no_ex_html = ("<h1 class='headword'>general american</h1>Noun /ˌdʒenrəl əˈmerɪkən/[uncountable] "
                  "Culture General American English General American English (GAE) is a term "
                  "that describes the standard English used in most of the US, and it can "
                  "be very long indeed but it is NOT an example sentence in any way. " * 3)
    ex_no = _extract_examples(no_ex_html)
    assert len(ex_no) == 0, f"FAIL: 无 examples 块的词条不应产生例句, 却得到 {len(ex_no)} 条(会把整词条当例句)"
    step("dict_render 例句健壮性: 无 examples 块的词条返回空 ✓ (不再冒一大坨)")

    # 惯用语/idm 词条(如 "fuck me")没有 <h1 class=headword>, 只有 <span class=idm>,
    # 也必须被渲染成有词头+有样式的条目, 不能因缺 h1 掉进 _fallback 而"详情没样式"。
    idm_html = ("<div id='entryContent' class='oald'><span class='idm-g'>"
                "<span class='idm'>fuck me</span>"
                "<span class='def'>used to express surprise</span><defT><chn>（表示惊奇）</chn></defT>"
                "<ul class='examples'><li><span class='x'>Fuck me! Look at that.</span>"
                "<aT><chn><ai>操！看那个。</ai></chn></aT></li></ul></span></div>")
    styled_idm = convert_dict_html(idm_html)
    assert "<style>" in styled_idm, "FAIL: idm 惯用语词条未渲染出样式(掉进无样式 fallback)"
    assert "class='word'" in styled_idm, "FAIL: idm 惯用语词条缺少词头大标题"
    step("dict_render 惯用语(idm)词条带样式 ✓ (不再详情无样式)")

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

    # 子义项小标题 <h2 class="shcut">(<shcutT><chn>中文</chn></shcutT>) 是词条内的
    # 小节标签(如 run 的 manage 管理 / provide 提供), 不是一条独立释义; 其中文若被当作
    # 定义中文, 会污染到上一条释义的中文行(渲染成 "管理；经营管理" 这类杂字)。必须整块跳过。
    shcut_html = ("<div id='x'><span class='def'>to be in charge</span><defT><chn>管理；经营</chn></defT>"
                  "<h2 class='shcut'>manage<shcutT><chn>管理</chn></shcutT></h2>"
                  "<span class='def'>to provide</span><defT><chn>提供</chn></defT></div>")
    sout = convert_dict_html(shcut_html)
    from PySide6.QtGui import QTextDocument
    _doc = QTextDocument(); _doc.setHtml(sout); _txt = _doc.toPlainText()
    assert "管理；经营 提供" not in _txt.replace("\n", " "), \
        f"FAIL: shcut 小标题污染了释义中文行 → {_txt!r}"
    assert "管理；经营\n提供" in _txt or "提供" in _txt.split("管理；经营")[1], \
        f"FAIL: shcut 修复后中文释义缺失 → {_txt!r}"
    step("dict_render 子义项(shcut)小标题不污染释义中文 ✓")

    # 渲染健壮性回归: <style> 必须位于 <head> 内, 否则 QTextDocument 会把 style 的
    # CSS 声明(div.word{...} 等)当作正文文本渲染 → 用户看到"例句区域出现很多 div 字样"。
    # 同时验证渲染结果经 QTextDocument 解析后纯文本不含裸 '<' (无未转义标签文本泄漏)。
    styled_html = convert_dict_html(raw)
    if "<style>" in styled_html:
        head_part = styled_html[:styled_html.find("</head>")] if "</head>" in styled_html else ""
        tail = styled_html.find("<body>")
        body_part = styled_html[tail:] if tail >= 0 else styled_html
        assert "<style>" in head_part, "FAIL: <style> 未位于 <head> 内(会在正文显示 CSS 文本)"
        assert "<style>" not in body_part, "FAIL: <style> 残留于 <body> 内"
    _doc = win._detail_view.document()
    _doc.setHtml(styled_html)
    _plain = _doc.toPlainText()
    assert "<" not in _plain, f"FAIL: 渲染后正文含未转义 '<' (标签文本泄漏): ...{_plain[:80]!r}"
    step(f"dict_render 渲染健壮性: style 位置合规 ✓, 正文无标签泄漏 ✓")

    # 透明度测试（v0.7.0：改为 160ms 渐变，而非跳变）
    # 1) 失焦/移出 → 起动渐变，应能看到透明度下降（并非被卡死在 1.0）
    win.setWindowOpacity(1.0)
    win._is_active_opacity = True
    win._refresh_opacity(force_using=False)     # 无焦点 + 鼠标在外 → 目标 0.10
    step(f"失焦后起动渐变: 目标={win._fade_target}, 当前={win.windowOpacity()}")
    # 播放几帧，模拟 160ms 渐变推进
    for _ in range(int(160 / 16) + 2):
        win._fade_tick()
    step(f"失焦渐变结束 → {win.windowOpacity()}")
    assert win.windowOpacity() < 0.5, "FAIL: 失焦后未变透明(bug 复现)"
    # 2) 鼠标移入/复用 → 渐变恢复不透明
    win._is_active_opacity = False
    win.enterEvent(None)
    assert win._fade_target == 1.0, "FAIL: 移入未触发恢复不透明"
    # 渐变每帧推进 10% of 剩余，越接近越慢；播足够多帧直到到达 1.0
    for _ in range(40):
        win._fade_tick()
        if win.windowOpacity() > 0.99:
            break
    step(f"鼠标移入渐变结束 → {win.windowOpacity()}")
    assert win.windowOpacity() > 0.9, "FAIL: 复用后未恢复不透明"
    step("透明度渐变 PASS")

    # 搜索无匹配
    win._title.setText("zzzzqqqq")
    win._do_search()
    step(f"搜索无匹配: list可见={win._list.isVisible()}, 条数={win._list.count()}")

    # 键盘事件 (Esc 隐藏)
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(ev)
    step(f"Esc 后隐藏: {not win.isVisible()}")

    # 拖动模拟
    win.show()
    win._dragging = True
    win._drag_offset = QPoint(10, 10)
    win.move(100, 100)
    e = QMouseEvent(QEvent.Type.MouseMove, QPointF(200, 150), Qt.MouseButton.NoButton,
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