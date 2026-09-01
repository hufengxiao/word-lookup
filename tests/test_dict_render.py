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