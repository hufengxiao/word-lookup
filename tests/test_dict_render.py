"""dict_render 单元测试 —— headless 可跑，无需真实 GUI 窗口。

覆盖离线渲染器的语义稳定性：例句配对、oT 中文容器、无例句块不硬凑、
<style> 位置、idm 惯用语样式、shcut 小标题防污染。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.dict_render import _extract_examples, convert_dict_html  # noqa: E402


def _plain(html: str) -> str:
    """用 QTextDocument 把渲染结果转纯文本（离屏，最接近用户所见）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText()


def test_normal_example_pair():
    """普通 <xT><chn> 例句：英文 + 中文正确配对。"""
    ul = ("<ul class='examples'><li><span class='x'>Peel the apples.</span>"
          "<xT><chn>把苹果削皮。</chn></xT></li></ul>")
    assert _extract_examples(ul) == [("Peel the apples.", "把苹果削皮。")]


def test_ot_cn_container():
    """normal distribution 的 <oT><chn> 容器中文不能被漏，否则例句没翻译。"""
    li = ("<ul class='examples'><li><span class='x'>IQs follow a normal"
          " distribution.</span><oT><chn><other>人口智商呈正态分布。</other></chn></oT></li></ul>")
    ex = _extract_examples(li)
    assert len(ex) == 1
    assert ex[0][1] == "人口智商呈正态分布。"


def test_no_examples_block_returns_empty():
    """没有 <ul class=examples> 的词条绝不能把整词条当一条例句。"""
    no_ex = ("<ul><li><h1 class='headword'>General American</h1>"
             "<span class='pos'>noun</span><span class='def'>the US English</span>"
             "<defT><chn>通美式英语</chn></defT>"
             "<div class='culture'>long culture prose that must NOT be an example.</div></li></ul>")
    assert _extract_examples(no_ex) == []


def test_style_inside_head_no_leak():
    """style 必须位于 head 内；正文不得把 CSS 声明当文本显示。"""
    raw = ("<div id='x'><h1 class='headword'>apple</h1>"
           "<span class='def'>a fruit</span><defT><chn>苹果</chn></defT></div>")
    out = convert_dict_html(raw)
    head = out[: out.find("</head>")] if "</head>" in out else out
    body = out[out.find("<body>"):] if "<body>" in out else out
    assert "<style>" in head
    assert "<style>" not in body
    # QTextDocument 纯文本不应出现 CSS 规则文本
    assert "div.word" not in _plain(out)


def test_idm_phrase_gets_styled():
    """惯用语 <span class=idm>(无 h1.headword)不能掉进无样式 fallback。"""
    raw = ("<div class='o'><span class='idm'>fuck me</span>"
           "<span class='def'>expression of surprise</span><defT><chn>（表示惊奇）</chn></defT></div>")
    out = convert_dict_html(raw)
    assert "<style>" in out
    assert "class='word'" in out


def test_shcut_does_not_pollute_cn():
    """h2.shcut 小标题的中文(如 manage 管理)不得污染上一条释义中文。"""
    raw = ("<div class='x'><span class='def'>to be in charge</span><defT><chn>经营</chn></defT>"
           "<h2 class='shcut'>manage<shcutT><chn>管理</chn></shcutT></h2>"
           "<span class='def'>to provide</span><defT><chn>提供</chn></defT></div>")
    txt = _plain(convert_dict_html(raw))
    # 中文 "经营" 与 "提供" 应分属两条释义，不出现 "经营管理 提供" 拼接
    assert "经营管" not in txt.replace(" ", "").replace("\n", "")
    assert "提供" in txt


def _render_text(raw):
    return _plain(convert_dict_html(raw)).replace("\n", " ")


def test_examples_follow_their_sense():
    """例句必须紧跟其所属释义(而不是整体堆到文档末尾 EXAMPLE 区)。

    两条 sense: 每条带独立例句。断言: 例句1 出现在释义1之后、释义2之前;
    全文不出现集中式的 'EXAMPLE' 区。
    """
    raw = (
        "<div class='entry'><h1 class='headword'>abandon</h1>"
        "<span class='pos'>verb</span>"
        "<li class='sense'><span class='def'>to leave somebody</span>"
        "<defT><chn>抛弃</chn></defT>"
        "<ul class='examples'><li><span class='x'>They left the baby.</span>"
        "<xT><chn>他们遗弃了婴儿。</chn></xT></li></ul></li>"
        "<li class='sense'><span class='def'>to stop doing something</span>"
        "<defT><chn>中止</chn></defT>"
        "<ul class='examples'><li><span class='x'>They abandoned the talks.</span>"
        "<xT><chn>他们中止了会谈。</chn></xT></li></ul></li>"
    )
    txt = _render_text(raw)
    i_def1 = txt.find("to leave somebody")
    i_ex1 = txt.find("They left the baby.")
    i_def2 = txt.find("to stop doing something")
    i_ex2 = txt.find("They abandoned the talks.")
    assert 0 < i_def1 < i_ex1 < i_def2 < i_ex2, f"例句错位, 文本:{txt}"
    assert "EXAMPLE" not in txt, "不应再出现集中式 EXAMPLE 区"


def test_example_collocation_prefix_shows():
    """例句前的搭配短语(<span class=cf>)保留为可读前缀, 不丢失。"""
    raw = ("<div class='x'><li class='sense'><span class='def'>to leave</span>"
           "<defT><chn>离开</chn></defT>"
           "<ul class='examples'><li><span class='cf'>abandon somebody</span> "
           "<span class='x'>He left his post.</span><xT><chn>他离职了。</chn></xT></li></ul></li></div>")
    txt = _render_text(raw)
    assert "abandon somebody" in txt


def test_sense_phrase_head_shows_before_def():
    """义项短语头(<span class="cf"> 在 sense 内 def 之前, 仿 Oxford 短语动词专条):
    take something 是"义项短语头", 应显示在释义正上方(而非被丢弃)。"""
    raw = ("<div class='entry'><h1 class='headword'>take</h1><span class='pos'>verb</span>"
           "<li class='sense'><span class='cf'>take something</span>"
           "<span class='def'>to use a form of transport</span><defT><chn>乘坐</chn></defT>"
           "<ul class='examples'><li><span class='x'>We took the train.</span>"
           "<xT><chn>我们坐了火车。</chn></xT></li></ul></li></div>")
    out = convert_dict_html(raw)
    # 短语头必须出现在释义文本之前的那一行
    i_ph = out.find("take something")
    i_def = out.find("to use a form of transport")
    assert 0 < i_ph < i_def, "义项短语头应显示在释义之前"
    assert "phr" in out, "应使用短语头样式块"
    assert "phrtxt" in out