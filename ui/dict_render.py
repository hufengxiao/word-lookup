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
        # idm = 惯用语/短语词目(如 "fuck me"), 也视作词头, 避免这类词典条目
        # 因没有 <h1 class=headword> 而被踢进 _fallback → 详情失去样式。
        if tag == "h1" or self._cls_has(attrs, "headword") or self._cls_has(attrs, "idm"):
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
        # 子义项小标题 <h2 class="shcut">（如 manage 管理 / provide 提供 / liquid 液体）
        # 整棵子树(含内层 <shcutT><chn>中文</chn>)都不是一条独立释义, 必须整块跳过,
        # 否则其中文 <chn> 会被当成“定义中文”并污染到上一条/下一条释义的中文行。
        if tag == "h2" and "shcut" in self._class(attrs).split():
            self._shcut_skip = getattr(self, "_shcut_skip", 0) + 1
            return
        sem = self._sem_of(tag, attrs)
        self._tag_stack.append((tag.lower(), sem))

    def handle_startendtag(self, tag, attrs):
        if tag in ("link", "img", "script", "br"):
            return
        sem = self._sem_of(tag, attrs)
        if sem:
            self._tag_stack.append((tag.lower(), sem))

    def handle_endtag(self, tag):
        if tag == "h2" and getattr(self, "_shcut_skip", 0):
            self._shcut_skip -= 1
            return
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
        if self._skip or self._ex_depth or getattr(self, "_shcut_skip", 0) or not self._tag_stack:
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

    parts = [_HEADER, "<html><head><meta charset='utf-8'>\n", _STYLE, "\n</head><body>"]

    # ---------- 宿主大标题 ----------
    parts.append(f"<div class='word'>{_esc(head_disp)}</div>")

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

        # 该词块的所有释义：def + chn 放进同一个 <div>（用 <br> 换行而非分块），
        # 避免 QTextDocument 把相邻块之间插入大段空白的毛病，让英文/中文贴得更紧。
        if e["defs"]:
            for i, (d, c) in enumerate(e["defs"], 1):
                if not d and not c:
                    continue
                parts.append("<div class='sense'>")
                parts.append(f"<span class='sensenum'>{i}.</span>")
                if d:
                    parts.append(f"<span class='def'>{_esc(d)}</span>")
                if d and c:
                    parts.append("<br>")
                if c:
                    parts.append(f"<span class='chn'>{_esc(c)}</span>")
                parts.append("</div>")

    # 例句（英文一行 + 中文一行，缩进收窄；不用 <ol> 避免 QText 有序列表内置缩进）
    extra = _extract_examples(html)
    if extra:
        parts.append("<div class='seclabel'>EXAMPLE</div><div class='exlist'>")
        for en, cn in extra[:10]:
            if en and cn:
                parts.append(f"<div class='ex'><span class='exx'>{_esc(en)}</span><br>"
                             f"<span class='excn'>{_esc(cn)}</span></div>")
            elif en:
                parts.append(f"<div class='ex'><span class='exx'>{_esc(en)}</span></div>")
            elif cn:
                parts.append(f"<div class='ex'><span class='excn'>{_esc(cn)}</span></div>")
        parts.append("</div>")

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
    """从真实牛津 HTML 提取例句，返回 [(英文, 中文), ...] 配对。

    只认 <ul ... class*examples*...> 块内的 <li>。若整篇文档根本没有标准 examples
    样例块，就返回空列表（不少词条并没有例句，绝不能把整个词条正文当作“例句”，
    否则像 General American 这种会把词性/音标/释义/Culture 大段硬凑成一条超长
    “例句”，渲染成 EXAMPLE 下一大坨连续文字，非常难读）。
    """
    import html as _h
    import re

    out = []
    # 只认 class 值含 "examples" 的 <ul>；没有则 return []（不再退回整个 html 当 body）。
    m = re.search(
        r"<ul\b[^>]*\bclass\s*=\s*[\"'][^\"']*examples[^\"']*[\"'][^>]*>(.*?)</ul>",
        html, re.I | re.S)
    if not m:
        return []
    body = m.group(1)

    def _text(s: str) -> str:
        s = re.sub(r"<[^>]+>", " ", s)
        return _h.unescape(re.sub(r"\s+", " ", s)).strip()

    for li in re.findall(r"<li[^>]*>(.*?)</li>", body, re.I | re.S):
        en = ""
        # 英文：<span class="x"> 或 <span class="unx"> 的内容（优先保内层，去掉嵌套换标签）
        for cls in ("unx", "x"):
            mm = re.search(r'<span\s+class=[\'"]' + cls + r'[\'"]>(.*?)</span>', li, re.I | re.S)
            if mm:
                en = _text_preserve_gloss(mm.group(1))
                break
        if not en:
            # 退化为整个 li
            en = _text_preserve_gloss(li)
        # 中文：<xT><chn>..</chn></xT> / <aT><chn>..</chn></aT> / <oT><chn>..</chn></oT>
        # (OALD10 例句翻译可能用 xT / aT / oT 三种容器, 都认)
        cn = ""
        for m in re.finditer(r'<(xT|aT|oT)>.*?<chn>(.*?)</chn>.*?</\1>', li, re.I | re.S):
            cn = _text_cn(m.group(2))
            if cn:
                break
        if en or cn:
            out.append((en, cn))
    return out


def _text_preserve_gloss(s: str):
    """去标签但保留 gloss/collocation 作为内联引注（换成引号内嵌）。"""
    import html as _h
    import re
    s = re.sub(r'<span\s+class=["\'][^"\']*\bgloss\b[^"\']*["\'][^>]*>(.*?)</span>',
               lambda m: " (" + _h.unescape(re.sub(r"<[^>]+>", "", m.group(1))) + ")",
               s, flags=re.I | re.S)
    return _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s))).strip()


def _text_cn(s: str) -> str:
    import html as _h
    import re
    s = re.sub(r"<[^>]+>", "", s)
    return _h.unescape(re.sub(r"\s+", " ", s)).strip()


def _strip_tags_except(s: str, keep: set):
    """去所有标签，但保留 keep 内标签的内容（如 gloss/cl 内联）。"""
    import html as _h
    import re
    def _repl(m):
        tag = m.group(0).lower()
        if any(k in tag for k in keep):
            return m.group(0)
        return " "
    return _h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", _repl, s))).strip()


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
    # 兜底也套上统一深色样式(而非纯 <!DOCTYPE>+原文), 否则未知结构词条在 QTextDocument
    # 里会用默认浅色/无排版, 视觉上"完全没样式"。此处即使 class 未全对齐, 至少深色底+基础文字可读。
    return _HEADER + "<html><head>" + _STYLE + "</head><body>" + h + "</body></html>"

_HEADER = "<!DOCTYPE html>"

# 与搜索窗口一致的统一色板（苹果设计语言，克制层级，蓝色仅作唯一强调）
_CLR_TEXT         = "#F2F2F7"   # 主文本
_CLR_TEXT_SOFT    = "#E8E8EC"   # 英文例句正文
_CLR_SECONDARY    = "#9AA0A6"   # 次级/音标/中文例句
_CLR_TERTIARY     = "#6E6E73"   # 弱化标签（小标题）
_CLR_ACCENT       = "#0A84FF"   # 唯一强调（词性/序号/链接）
_CLR_CARD         = "#1E1E24"   # 卡片底
_CLR_HAIR         = "#2A2A33"   # 发线/例句竖线
_CLR_CJK_DEF      = "#D8D8E0"   # 中文释义（比英文稍暗，中性、不染色相）

_STYLE = (
    f"""<style>
body{{font-family:'Segoe UI','Microsoft YaHei',sans-serif;font-size:15px;
color:{_CLR_TEXT};line-height:1.62;background:{_CLR_CARD};padding:2px 0px 40px;}}
div.word{{font-size:32px;font-weight:700;letter-spacing:-0.5px;color:#FFFFFF;
text-align:left;margin:0 0 6px;}}
div.posline{{margin:0 0 12px;text-align:left;}}
span.posband{{color:{_CLR_ACCENT};font-style:italic;font-weight:600;font-size:16px;margin-right:14px;}}
span.phon{{color:{_CLR_SECONDARY};font-size:15px;}}
span.sep{{color:{_CLR_HAIR};margin:0 8px;}}
div.possep{{border-top:1px solid {_CLR_HAIR};margin:18px 0 6px;padding-top:14px;}}
div.sense{{margin:0 0 15px;padding-left:2px;}}
span.sensenum{{color:{_CLR_ACCENT};font-weight:700;margin-right:8px;font-size:16px;}}
span.def{{color:#FFFFFF;display:inline;font-size:16px;}}
span.chn{{color:{_CLR_CJK_DEF};font-weight:550;font-size:15.5px;display:inline;}}
div.seclabel{{font-size:11px;color:{_CLR_TERTIARY};font-weight:700;letter-spacing:1.6px;
text-transform:uppercase;margin:22px 0 10px;}}
div.exlist{{margin:0;padding-left:2px;}}
div.ex{{margin:7px 0;padding-left:10px;border-left:2px solid {_CLR_HAIR};color:{_CLR_TEXT_SOFT};}}
span.exx{{color:{_CLR_TEXT_SOFT};font-size:14px;line-height:1.5;}}
span.excn{{color:{_CLR_SECONDARY};font-size:13px;line-height:1.45;}}
table{{border-collapse:collapse;}} td,th{{padding:3px 10px;font-size:15px;}}
img{{max-width:100%;background:transparent;border:0;}}
a{{color:{_CLR_ACCENT};text-decoration:none;}}
</style>"""
)



# 兼容旧调用
def clean_and_render(html: str) -> str:
    return convert_dict_html(html)