# -*- coding: utf-8 -*-
"""
词典 HTML → 可读排版转换器。

牛津高阶词典正文用大量自定义标签/class(headword/pos/phon/def/defT/chn/examples/...)
且依赖外部 oald10.css。QTextBrowser 无法加载外部 CSS、也不认自定义标签，直接
setHtml 会失去层次、难以阅读。

本模块用 HTMLParser 把正文解析成结构化片段(基于栈跟踪语义上下文)，再重组成
QTextDocument 友好的、纯块级/内联样式的 HTML：
  - 词头大标题
  - 音标(灰) + 词性(斜体)
  - 每条释义：英文释义 + 中文翻译(单独高亮行)
  - 例句列表
  - 习语/搭配 次级块
  - 剔除 img/link/script/事件/音频
"""
from html.parser import HTMLParser

# 语义上下文 -> 该上下文内的文本归属 kind
_SEM = {
    "headword": "headword",
    "pos": "pos",
    "phon": "phon",
    "def": "def",
    "chn": "chn",
    "defT": "chn",   # <defT><chn>中文</chn></defT>
}


class DictHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frag = []          # [(kind, text)] 按文档顺序
        self._tag_stack = []    # (tag_lower, sem_kind 或 None)
        self._skip = 0
        self._ex_depth = 0      # 例句块 <ul class=...examples> 嵌套深度(其文本不进语义)
        # sense 边界: 进入一个新的 <li class="sense"> 时置 True, 强制切断 def/chn 连续
        self._senses_sep = False

    def _class(self, attrs):
        for k, v in attrs:
            if k == "class":
                return v
        return ""

    def _cls_has(self, attrs, *names):
        c = set(self._class(attrs).split())
        return any(n in c for n in names)

    def _sem_of(self, tag, attrs):
        if tag == "h1" or self._cls_has(attrs, "headword"):
            return "headword"
        if self._cls_has(attrs, "pos"):
            return "pos"
        if self._cls_has(attrs, "phon"):
            return "phon"
        if self._cls_has(attrs, "def"):
            return "def"
        # defT/chn 是自定义中文容器: HTMLParser 传 tag 为小写 "deft"/"chn"
        if self._cls_has(attrs, "chn") or tag in ("deft", "chn"):
            return "chn"
        return None

    def handle_starttag(self, tag, attrs):
        if self._skip:
            if tag in ("script", "style", "audio"):
                self._skip += 1
            return
        if tag in ("script", "style", "audio"):
            self._skip = 1
            return
        if tag == "ul" and "examples" in set(self._class(attrs).split()):
            self._ex_depth += 1
        if tag == "li" and self._cls_has(attrs, "sense"):
            self._senses_sep = True
        sem = self._sem_of(tag, attrs)
        self._tag_stack.append((tag.lower(), sem))

    def handle_startendtag(self, tag, attrs):
        if tag in ("link", "img", "script", "br"):
            return
        sem = self._sem_of(tag, attrs)
        if sem:
            self._tag_stack.append((tag.lower(), sem))

    def handle_endtag(self, tag):
        if self._skip:
            if tag in ("script", "style", "audio"):
                self._skip -= 1
            return
        if self._ex_depth and tag == "ul":
            self._ex_depth -= 1
        tag = tag.lower()
        for i in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[i][0] == tag:
                del self._tag_stack[i:]
                break

    def handle_data(self, data):
        if self._skip or self._ex_depth or not self._tag_stack:
            return
        sem = None
        for _t, s in reversed(self._tag_stack):
            if s:
                sem = s
                break
        if not sem:
            return
        # 若刚进入新 sense 且上一片段是同 kind, 强制切开(新 sense)
        if self._senses_sep and self.frag and self.frag[-1][0] == sem:
            self.frag.append([sem, []])
        self._senses_sep = False
        if self.frag and self.frag[-1][0] == sem:
            self.frag[-1][1].append(data)
        else:
            self.frag.append([sem, [data]])

    @staticmethod
    def _join(frag):
        out = []
        for kind, parts in frag:
            txt = " ".join("".join(parts).split())
            if txt:
                out.append((kind, txt))
        return out


def convert_dict_html(html: str) -> str:
    p = DictHtmlParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001
        pass
    frag = DictHtmlParser._join(p.frag)
    if not frag:
        return _fallback(html)

    # 重组: 每个 <h1>(headword) 开启一个新的词块(词性/同形词).
    # 牛津词典按词性/同形词拆成多个 <div class="entry">, 每个 entry 以 h1 开头.
    entries = []   # 每个: {"pos": set, "phons": [], "senses": [[def, chn],...]}
    cur = None
    for kind, text in frag:
        if kind == "headword":
            cur = {"pos": "", "phons": [], "defs": [], "cur_def": None, "head": text}
            entries.append(cur)
            continue
        if cur is None:
            continue
        if kind == "pos":
            if not cur["pos"]:
                cur["pos"] = text
        elif kind == "phon":
            cur["phons"].append(text)
        elif kind == "def":
            cur["defs"].append([text, ""])
            cur["cur_def"] = cur["defs"][-1]
        elif kind == "chn":
            if cur["cur_def"] is not None and not cur["cur_def"][1] and cur["cur_def"][0]:
                cur["cur_def"][1] = text
            elif cur["defs"]:
                cur["defs"][-1][1] = text

    if not entries:
        return _fallback(html)

    # 若整个词条只有一个词头(单数词条), 归一化
    head_disp = entries[0].get("head", "") or ""

    # 过滤既无词性也无释义的空词块(牛津里偶有空 <div class=entry>)
    entries = [e for e in entries if e["defs"] or e["pos"]]

    parts = [_HEADER, "<html><head><meta charset='utf-8'></head><body>", _STYLE]

    # ---------- 宿主大标题 ----------
    parts.append(f"<h1>{_esc(head_disp)}</h1>")

    for ei, e in enumerate(entries):
        # 第0个词块的词性跟在 h1 后; 之后的词块独立小节
        pos_txt = _esc(e["pos"]) if e["pos"] else ""
        if ei == 0:
            if pos_txt:
                parts.append(
                    f"<div class='posline'><span class='posband'>{pos_txt}</span>"
                    + _ph_html(e["phons"]) + "</div>")
            else:
                parts.append(_ph_html(e["phons"]))
        else:
            # 后续词块: 醒目的小节头(词性+音标), 以分隔视觉
            parts.append(f"<div class='posline possep'>"
                         f"<span class='posband'>{pos_txt or '·'}</span>"
                         + _ph_html(e["phons"]) + "</div>")

        # 该词块的所有释义
        if e["defs"]:
            for i, (d, c) in enumerate(e["defs"], 1):
                if not d and not c:
                    continue
                parts.append("<div class='sense'>")
                parts.append(f"<span class='sensenum'>{i}.</span>")
                if d:
                    parts.append(f"<span class='def'>{_esc(d)}</span>")
                if c:
                    parts.append(f"<div class='chn'>{_esc(c)}</div>")
                parts.append("</div>")

    # 例句
    extra = _extract_examples(html)
    if extra:
        parts.append(f"<h2>例句</h2><div class='exlist'><ol class='ex'>")
        for e in extra[:12]:
            parts.append(f"<li class='ex'>{_esc(e)}</li>")
        parts.append("</ol></div>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _ph_html(phons):
    """音标组 HTML(拆开连续 IPA + 去重 + 用 · 分隔)."""
    uniq = _split_phon(phons)
    if not uniq:
        return ""
    inner = "<span class='sep'>·</span>".join(
        f"<span class='phon'>{_esc(x)}</span>" for x in uniq[:2])
    return f"<div class='phonrow'>{inner}</div>"


def _extract_examples(html: str) -> list:
    """尽力提取例句(例句块 <ul class=examples> 或 <span class=x>). 失败返回[]."""
    import re
    out = []
    # 方式1: <ul class="examples">...</ul>
    m = re.search(r'<ul\s+class="examples"[^>]*>(.*?)</ul>', html, re.I | re.S)
    body = m.group(1) if m else html
    # 提取 li 文本
    for li in re.findall(r"<li[^>]*>(.*?)</li>", body, re.I | re.S):
        txt = re.sub(r"<[^>]+>", " ", li)
        import html as _h
        txt = _h.unescape(re.sub(r"\s+", " ", txt)).strip()
        if txt:
            out.append(txt)
    return out


def _split_phon(phons):
    """拆开连续 /.../.../ 的 IPA, 去重, 返回列表。"""
    import re
    out = []
    for ph in phons:
        for m in re.findall(r"/[^/]+/", ph):
            if m not in out:
                out.append(m)
    return out


def _esc(s: str) -> str:
    import html as _h
    return _h.escape(s)


def _fallback(html: str) -> str:
    """解析失败时退化为去链接/脚本/图后的原样 HTML。"""
    import re
    h = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    h = re.sub(r"<style\b[^>]*>.*?</style>", "", h, flags=re.I | re.S)
    h = re.sub(r"<link\b[^>]*>", "", h, flags=re.I)
    h = re.sub(r"<audio\b[^>]*>.*?</audio>", "", h, flags=re.I | re.S)
    h = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h, flags=re.I)
    h = re.sub(r"<img\b[^>]*>", "", h, flags=re.I)
    return _HEADER + h

_HEADER = "<!DOCTYPE html>"
_STYLE = (
    "<style>"
    "body{font-family:'Segoe UI','PingFang SC','Helvetica Neue',sans-serif;"
    "font-size:15.5px;color:#1D1D1F;line-height:1.7;"
    "background:#F4F5F7;padding:26px 34px 40px;}"
    "h1{font-size:40px;font-weight:700;letter-spacing:-0.3px;color:#111114;"
    "margin:2px 0 8px;}"
    "div.meta{color:#6E6E73;font-size:15px;margin:0 0 6px;}"
    "span.pos{color:#0A84FF;font-style:italic;font-weight:550;margin-right:10px;font-size:16px;}"
    "span.phon{color:#8E8E93;font-size:15px;}"
    "span.sep{color:#C7C7CC;margin:0 8px;}"
    "div.posline{margin:6px 0 2px;}"
    "span.posband{color:#0A84FF;font-style:italic;font-weight:550;font-size:16px;}"
    "div.gap{height:10px;}"
    "div.possep{border-top:1px solid #E7E9ED;margin-top:16px;padding-top:14px;}"
    "div.sense{margin:0 0 4px;padding-left:2px;}"
    "span.sensenum{color:#0A84FF;font-weight:650;margin-right:8px;font-size:15.5px;}"
    "span.def{color:#1D1D1F;}"
    "div.chn{color:#14806B;font-weight:610;margin-top:1px;margin-bottom:10px;"
    "padding-left:22px;font-size:15.5px;}"
    "h2{font-size:11.5px;color:#8E8E93;font-weight:700;letter-spacing:1.6px;"
    "text-transform:uppercase;margin:26px 0 8px;}"
    "div.exlist{color:#3A3A3E;margin:0;}"
    "ol.ex{margin:0;padding:0 0 0 4px;list-style:none;}"
    "ol.ex li.ex{margin:5px 0;color:#3A3A3E;list-style:none;}"
    "ol.ex li.ex:before{content:'\\2022  ';color:#0A84FF;margin-right:4px;}"
    "table{border-collapse:collapse;} td,th{padding:3px 10px;font-size:15px;}"
    "ol,ul{margin:4px 0 8px;} li{margin:3px 0;}"
    "img{max-width:100%;background:transparent;border:0;}"
    "a{color:#0A84FF;}"
    "</style>"
)


# 兼容旧调用
def clean_and_render(html: str) -> str:
    return convert_dict_html(html)