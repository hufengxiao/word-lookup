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

from unittest import mock

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from dictionary.searcher import Searcher
from ui.search_window import H_EXPANDED, SearchWindow

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
    step("dict_render 渲染健壮性: style 位置合规 ✓, 正文无标签泄漏 ✓")

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

    # 回归：隐藏/显示前必须清理输入法组合(composition)状态。
    # Windows 输入「Ctrl+A 全选后直接打中文」会在 IME 预编辑(组合)态；若隐藏时
    # 未 commit()+reset(), 重新显示找回焦点会带残留组合 → 中文只显示半截。
    # 这两个调用必须真的发生在 hide_window()/show_window() 路径上。
    _im = QGuiApplication.inputMethod()
    calls = {"commit": 0, "reset": 0}
    def _c():
        calls["commit"] += 1
        return None
    def _r():
        calls["reset"] += 1
        return None
    with mock.patch.object(_im, "commit", side_effect=_c), \
         mock.patch.object(_im, "reset", side_effect=_r):
        calls["commit"] = calls["reset"] = 0
        win.hide_window()
        win.show_window()
    step(f"hide/show 触发 inputMethod.commit={calls['commit']} reset={calls['reset']} (均应>=1)")
    assert calls["commit"] >= 2 and calls["reset"] >= 2, \
        "FAIL: hide/show 未清理输入法组合状态(中文显示半截的根因), 需 commit()+reset()"

    # 搜索无匹配
    win._title.setText("zzzzqqqq")
    win._do_search()
    step(f"搜索无匹配: list可见={win._list.isVisible()}, 条数={win._list.count()}")

    # 回归：无匹配(如中文)、空态项按 Enter 不应切进详情视图(问题1)
    # 根因修复：_on_return/_current_key 对 UserRole 为空的占位项返回 None，不 _show_detail
    win._mode = "list"
    win._detail_view.hide()
    win._title.setText("金额")
    win._do_search()
    win._on_return()   # 模拟用户按 Enter
    step(f"中文无匹配按Enter: mode={win._mode} (应 list), 详情可见={win._detail_view.isVisible()} (应 False)")
    assert win._mode == "list", "FAIL(问题1): 查不到的中文按Enter仍切进详情视图"
    assert not win._detail_view.isVisible(), "FAIL(问题1): 中文无匹配却进了详情"

    # 回归：空态项("没有找到 xxx")行高不应塌成一个字符高(问题2)
    # 根因修复的关键 = view(_list) 本身必须 setFont(setFamilies) 含中文字体。
    # 空态行高由 QListView 用 view.font() 的 QFontMetrics 计算（不经 delegate 的
    # sizeHint）；若 view.font 只是 Segoe UI，Windows 对中文回退 metrics 极低 →
    # 空态行塌成一个字符。上一版只给 styleSheet 加中文 font-family 无效（styleSheet
    # 的 font-family 不改变 widget.font()），必须 setFont(setFamilies)。
    import ui.search_window as _sw2
    step(f"view/输入框字体中文字体回退: _list={win._list.font().families()} _title={win._title.font().families()}")
    assert _sw2.FONT_FAMILY_CJK in win._list.font().families(), \
        "FAIL(问题2): _list view.font 未 setFamilies 含中文字体, 空态行 Windows 必塌"
    # 真实空态行高：用一条中文空态项度量 QListView 实际给的高度(非 delegate 兜底)
    try:
        row_h = win._list.sizeHintForRow(0)
    except Exception:
        row_h = 0
    step(f"空态项行高 sizeHintForRow: {row_h}px (期望 >= 30, 不应塌成仅选手符高度)")
    assert row_h >= 20, f"FAIL(问题2): 结果行高塌陷成 {row_h}px(只剩一个字符)"

    # 回归(问题2 根因·垂直裁剪)：中文只显示"字中间一条" = 控件/行高不足以容纳中文
    # 实心方块字形，被以控件水平中线为中心上下各裁一段。必须显式给足 input 高度 +
    # 列表 item 行高(都比 Latin metrics 高, 且显式 sizeHint 绕开 view 的矮默认计算)。
    _mh = win._title.minimumHeight()
    step(f"输入框 minimumHeight={_mh}px (应≥40, 给足中文字形) | _row_h={win._row_h}px")
    assert _mh >= 40, f"FAIL: 输入框默认高度不足({_mh}px), 中文会被上下裁成中间一条"
    # 列表任意一行 item 的显式 sizeHint 应 == _row_h(不等于 view 按自身 metrics 算出的矮默认)
    if win._list.count():
        it0 = win._list.item(0)
        if it0 is not None:
            hint = it0.sizeHint().height()
            step(f"列表首项显式 sizeHint 高={hint}px (应≈_row_h={win._row_h})")
            assert hint == win._row_h, "FAIL: 列表项未设显式中文字高(空态/候选会被压矮)"

    # 回归(布局垂直不重叠)：输入框 minimumHeight 加大后, 若窗口高度不足以容纳
    # 「输入行 + 列表」, 中文会溢出下界与列表文字重叠、列表可视高度被挤矮。
    # 断言: 展开态下 列表 top ≥ 输入框 bottom(不重叠)。
    win._animate_height(H_EXPANDED)
    win._resize_ticks = 999
    win._resize_tick()
    win.layout().activate()
    _list_top = win._list.geometry().top()
    _title_bottom = win._title.geometry().bottom()
    step(f"布局: 列表top({_list_top}) vs 输入框bottom({_title_bottom}) 是否重叠: {_list_top < _title_bottom}")
    assert _list_top >= _title_bottom, "FAIL: 列表与输入框垂直重叠(中文会被压到列表上)"

    # 回归(根治性)：窗口被误收起的「IME 组合触发的 collapse」不应让 show 停在收起态。
    # 真实 bug:「Ctrl+A 全选→输入中文」时 composition 把 text() 瞬时空 → _do_search
    # 误调 _collapse() → _expanded=False 且窗口 76px; show_window 又因 _expanded 收缩。
    # 修复: show_window 在 text 非空时强制 _expand()(以有无内容为准)。断言: 即使
    # _expanded 已被误置 False 且窗口被收到 76, 只要输入框有内容, 显示后应回到展开态。
    win._title.setText("金额搜索")
    win._do_search()
    win._expanded = False          # 模拟 IME 组合期间被 _collapse 误置
    win.setFixedSize(win.width(), 76)
    win.layout().activate()
    _before_h = win.height()
    win.show_window()              # 应触发 _expand() 展开
    win._resize_ticks = 999
    win._resize_tick()
    _after_h = win.height()
    step(f"折叠三角: 误折叠后H={_before_h} → show_window后H={_after_h} (应≥420展开)")
    assert _after_h >= 420, f"FAIL(问题3): 窗口有内容却停在收起态 {_after_h}px(中文/放大镜/列表被挤矮)"

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