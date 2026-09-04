"""
词典 HTML → 可读排版转换器。

牛津高阶词典正文用大量自定义标签/class(headword/pos/phon/def/defT/chn/examples/...)，
且依赖外部 oald10.css。QTextBrowser 无法加载外部 CSS、也不认自定义标签，直接
setHtml 会失去层次、难以阅读。

本模块用 HTMLParser 把正文解析成结构化片段(基于栈跟踪语义上下文)，再重组成
QTextDocument 友好的、纯块级/内联样式的 HTML：
  - 词头大标题
  - 音标(灰) + 词性(斜体)
  - 主释义区：每条释义：英文释义 + 中文翻译(单独高亮行)，例句紧跟所属释义
  - 习语区(Idioms)：每个习语(如 on the run) 显示词组头 + 释义 + 例句
  - 短语动词区(Phrasal Verbs)：词典将这些短语拆成独立词条，正文只给交叉链接，
    故渲染为一个「词组清单」(点按可跳转对应词条)
  - 剔除 img/link/script/事件/音频

词条含三种语义结构：
  ① 主释义区 <ol class="senses_multiple"> 内嵌 <li class="sense">
  ② 习语区 <div class="idioms"> 内嵌 <span class="idm-g">(习语头 <span class="idm">)
  ③ 短语动词链接区 <span class="phrasal_verb_links"> 内嵌 <ul class="pvrefs">
本实现把 ②③ 从主语义流中分离，单独渲染。
"""
import html as _h
import re as _re
from functools import lru_cache
from html.parser import HTMLParser

# P0-2a 性能：详情渲染用的正则全部模块级预编译，避免每次渲染时重新编译。
_RE_TAG = _re.compile(r"<[^>]+>")
_RE_WS = _re.compile(r"\s+")
_RE_SCRIPT = _re.compile(r"<script\b[^>]*>.*?</script>", _re.I | _re.S)
_RE_STYLE = _re.compile(r"<style\b[^>]*>.*?</style>", _re.I | _re.S)
_RE_LINK = _re.compile(r"<link\b[^>]*>", _re.I)
_RE_AUDIO = _re.compile(r"<audio\b[^>]*>.*?</audio>", _re.I | _re.S)
_RE_EVENTS = _re.compile(
    r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", _re.I)
_RE_IMG = _re.compile(r"<img\b[^>]*>", _re.I)
_RE_GLOSS = _re.compile(
    r'<span\s+class=["\'][^"\']*\bgloss\b[^"\']*["\'][^>]*>(.*?)</span>',
    _re.I | _re.S)
_RE_EX_UL = _re.compile(
    r"<ul\b[^>]*\bclass\s*=\s*[\"'][^\"']*examples[^\"']*[\"'][^>]*>(.*?)</ul>",
    _re.I | _re.S)
_RE_LI = _re.compile(r"<li[^>]*>(.*?)</li>", _re.I | _re.S)
_RE_SPAN_EN = _re.compile(
    r"<span\s+class=[\"'](?:unx|x)[\"']>(.*?)</span>", _re.I | _re.S)
_RE_CN_CONTAINER = _re.compile(
    r"<(?:xT|aT|oT)>.*?<chn>(.*?)</chn>.*?</(?:xT|aT|oT)>", _re.I | _re.S)
_RE_PHON = _re.compile(r"/[^/]+/")

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
        self._ex_depth = 0      # 例句 <ul class=...examples> 嵌套深度(其文本不进语义)
        # sense 边界: 进入一个新的 <li class="sense"> 时置 True, 强制切断 def/chn 连续
        self._senses_sep = False
        # ── 例句归属: 每条释义(sense)内嵌的 <ul class=examples> 例句按 sense 顺序 ──
        # 与 defs 渲染一一对齐: 第 k 条 def 对应 sense_examples[k] (k 从 1 递增)。
        self.sense_idx = 0
        self.sense_examples = []  # index=sense_idx-1 -> [(cf,en,cn), ...]
        self._in_exul = 0         # 例句 <ul class=examples> 深度 (语义 on/off)
        self._ex_li = None        # 当前例句 li 缓冲 {"cf","en","cn"}
        self._ex_seg = None       # 当前例句 li 文本阶段: "cf"/"en"/"cn"
        # ── 义项短语头: sense 内 def 之前的 <span class=cf> 短语(如 take something) ──
        self.sense_phrases = []   # [1-based seq] -> 短语文本, 与 defs/sense_idx 对齐
        self._cf_pending = False  # 已见到 cf 但尚未见到紧跟的 def
        self._cf_buf = ""         # 待绑定短语头的文本缓冲
        # 习语/短语动词区深度(>0 整块跳过主语义流, 单独渲染即跳过)
        self._section_depth = 0

    def _class(self, attrs):
        for k, v in attrs:
            if k == "class":
                return v
        return ""

    def _cls_has(self, attrs, *names):
        c = set(self._class(attrs).split())
        return any(n in c for n in names)

    def _sem_of(self, tag, attrs):
        # idm = 惯用语/短语词目(如 "run for it"), 也视作词头, 避免这类词典条目
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
        # ── 习语区 / 短语动词链接区：整块不进主语义流(各自独立渲染) ──
        if getattr(self, "_section_depth", 0):
            if tag in ("div", "aside"):
                self._section_depth += 1
            return
        if self._cls_has(attrs, "idioms") or self._cls_has(attrs, "phrasal_verb_links"):
            self._section_depth = 1
            return
        if tag == "ul" and "examples" in set(self._class(attrs).split()):
            self._ex_depth += 1
            self._in_exul += 1
        if tag == "li" and self._cls_has(attrs, "sense"):
            self._senses_sep = True
            self.sense_idx += 1
        # 例句内部各标签：仅在例句容器内才收集(文本仍不进语义流)
        if self._in_exul:
            if tag == "li":
                # 例句条目(非 sense li, 因 sense li 不会出现在 examples ul 内)
                self._ex_li = {"cf": "", "en": "", "cn": ""}
                self._ex_seg = None
                return
            if self._ex_li is None:
                self._ex_li = {"cf": "", "en": "", "cn": ""}
                self._ex_seg = None
            cls = set(self._class(attrs).split())
            if tag == "span" and "cf" in cls:
                self._ex_seg = "cf"
                self._cf_sent = False  # 例句内 cf 是"用法结构标注"，不作义项短语头
            elif tag == "span" and (cls & {"x", "unx"}):
                self._ex_seg = "en"
            elif tag in ("xt", "at", "ot") or (tag == "span" and "chn" in cls):
                self._ex_seg = "cn"
            return
        # ---- 义项短语头：仅当 def 紧跟在 cf(sense 内、非例句 ul)后 才记录 ----
        cls = set(self._class(attrs).split())
        if tag == "span" and "cf" in cls:
            self._cf_pending = "maybe"   # 待 def 确认
            self._cf_buf = ""
        elif (tag == "span" and (cls & {"def", "defT"})):
            if self._cf_pending and self.sense_idx > 0:
                _ph = " ".join(self._cf_buf.split())
                if _ph:
                    while len(self.sense_phrases) <= self.sense_idx:
                        self.sense_phrases.append(None)
                    self.sense_phrases[self.sense_idx] = _ph
            self._cf_pending = False
        else:
            if tag in ("span", "x", "O10"):
                self._cf_pending = False
        # 子义项小标题 <h2 class="shcut">：整棵子树(含内层 <shcutT><chn>中文</chn>)
        # 都不是一条独立释义，必须整块跳过。
        if tag == "h2" and "shcut" in self._class(attrs):
            self._shcut_skip = getattr(self, "_shcut_skip", 0) + 1
            return
        sem = self._sem_of(tag, attrs)
        if sem:
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
        # 习语/短语区结束：按 div/aside 闭合递减
        if getattr(self, "_section_depth", 0):
            if tag in ("div", "aside"):
                self._section_depth -= 1
            return
        if self._ex_depth and tag == "ul":
            self._ex_depth -= 1
            if self._in_exul:
                self._in_exul -= 1
        t = tag.lower()
        # 例句 li 结束: flush 当前例句到所属 sense
        if t == "li" and self._ex_li is not None:
            self._ex_li = self._flush_ex_li(self._ex_li)
        # 移除语义栈
        for i in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[i][0] == t:
                del self._tag_stack[i:]
                break

    def handle_data(self, data):
        # 例句容器内: 文本按当前例句段收进例句(不污染语义流)
        if self._in_exul and self._ex_li is not None and self._ex_seg:
            self._ex_li[self._ex_seg] += data
            return
        # 义项短语头缓冲: 在 def 前的 <span class=cf> 内收文本(不进语义流)
        if self._cf_pending:
            self._cf_buf += data
            return
        if self._skip or self._ex_depth or getattr(self, "_shcut_skip", 0) or not self._tag_stack:
            return
        sem = None
        for _t, s in reversed(self._tag_stack):
            if s:
                sem = s
                break
        if not sem:
            return
        # 若刚进入新 sense 且上一片段系同 kind, 强制切开(新 sense)
        if self._senses_sep and self.frag and self.frag[-1][0] == sem:
            self.frag.append([sem, []])
        self._senses_sep = False
        if self.frag and self.frag[-1][0] == sem:
            self.frag[-1][1].append(data)
        else:
            self.frag.append([sem, [data]])

    def _flush_ex_li(self, buf):
        """把一条例句缓冲归一化后写入当前 sense 槽, 返回 None(标志已消费)。"""
        cf = " ".join(buf.get("cf", "").split())
        en = " ".join(buf.get("en", "").split())
        cn = " ".join(buf.get("cn", "").split())
        if en or cn or cf:
            while len(self.sense_examples) <= self.sense_idx:
                self.sense_examples.append([])
            self.sense_examples[self.sense_idx].append((cf, en, cn))
        return None

    @staticmethod
    def _join(frag):
        out = []
        for kind, parts in frag:
            txt = " ".join("".join(parts).split())
            if txt:
                out.append((kind, txt))
        return out


@lru_cache(maxsize=64)
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

    # 重组: 每个 <h1>(headword/词性) 开启一个新的词块(词性/同形词).
    entries = []   # 每个: {"pos": set, "phons": [], "defs": [[def, chn], ...]}
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

    head_disp = entries[0].get("head", "") or ""
    # 该无 headword(如纯 <span class="idm"> 的独立首 block)时, 用第一个 idm 词组头作标题
    if not head_disp:
        _idm = _re.search(r"<span\b[^>]*class=[\"']idm[\"'][^>]*>(.*?)</span>",
                          html, _re.I | _re.S)
        if _idm:
            head_disp = _text_no_tags(_idm.group(1))

    # 过滤既无词性也无释义的空词块
    entries = [e for e in entries if e["defs"] or e["pos"]]

    parts = [_HEADER, "<html><head><meta charset='utf-8'>\n", _STYLE, "\n</head><body>"]

    # ---------- 宿主大标题 ----------
    parts.append(f"<div class='word'>{_esc(head_disp)}</div>")

    # 习语、短语动词区：独立于主词流解析并渲染成两个小节
    idioms_html = _render_idioms(html)
    phrasal_html = _render_phrasal(html)

    sense_cnt = 1  # 与 DictHtmlParser.sense_idx 对齐: 第 k 条 def 渲染对应 sense_examples[k]
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
            parts.append(f"<div class='posline possep'>"
                         f"<span class='posband'>{pos_txt or '·'}</span>"
                         + _ph_html(e["phons"]) + "</div>")

        # 该词块的所有释义：def + chn 放进同一个 <div>（用 <br> 换行而非分块），
        # 例句默认紧跟其所属释义(sense)正下方, 不再全部堆到文档末尾。
        if e["defs"]:
            for i, (d, c) in enumerate(e["defs"], 1):
                cur_no = sense_cnt
                sense_cnt += 1  # 与 DictHtmlParser.sense_idx 对齐(每次 def 递增)
                if not d and not c:
                    continue
                parts.append("<div class='sense'>")
                # 义项短语头(如 take something)：释义正上方醒目小斜体
                _ph = p.sense_phrases[cur_no] if cur_no < len(p.sense_phrases) else None
                if _ph:
                    parts.append(f"<div class='phr'><span class='phrtxt'>{_esc(_ph)}</span></div>")
                parts.append(f"<span class='sensenum'>{i}.</span>")
                if d:
                    parts.append(f"<span class='def'>{_esc(d)}</span>")
                if d and c:
                    parts.append("<br>")
                if c:
                    parts.append(f"<span class='chn'>{_esc(c)}</span>")
                parts.append("</div>")
                # 紧跟本释义的例句: 搭配/英文/中文 分三段各占一行
                exs = p.sense_examples[cur_no] if \
                    cur_no < len(p.sense_examples) else []
                for cf, en, cn in exs:
                    if not (en or cn or cf):
                        continue
                    parts.append("<div class='ex'>")
                    if cf:
                        parts.append(f"<span class='excf'>{_esc(cf)}</span>")
                        if en:
                            parts.append("<br>")
                    if en:
                        parts.append(f"<span class='exx'>{_esc(en)}</span>")
                        if cn:
                            parts.append("<br>")
                    if cn:
                        parts.append(f"<span class='excn'>{_esc(cn)}</span>")
                    parts.append("</div>")

    # 习语小节
    if idioms_html:
        parts.append(idioms_html)
    # 短语动词小节
    if phrasal_html:
        parts.append(phrasal_html)

    parts.append("</body></html>")
    return "\n".join(parts)


# ============================ 习语(Idioms)区 ============================
_IDM_GROUP = _re.compile(
    r'<span\b[^>]*\bidm-g\b[^>]*><div.*?<span\b[^>]*'
    r'class=["\']idm["\'][^>]*>(.*?)</span>.*?'
    r'(?:<li\b[^>]*class=["\']sense["\'][^>]*>(.*?))?</li>\s*</ol>.*?</span>',
    _re.I | _re.S)


def _text_no_tags(s: str) -> str:
    return _h.unescape(_RE_WS.sub(" ", _RE_TAG.sub("", s))).strip()


def _idiom_block(html: str) -> list:
    """在 run 类词条抽取 习语(Idioms) 区, 返回 [(词组头, [(def, chn), ...], [(en, cn), ...]), ...]"""
    m = _re.search(r'<div class="idioms".*?</li>\s*</ol>', html, _re.S)
    if not m:
        return []
    zone = m.group(0)
    blocks = []
    for gm in _re.finditer(r'<span\b[^>]*class=["\'][^"\']*idm-g[^"\']*["\'][^>]*>(.*?)</(?:span|div)>', zone, _re.S):
        body = gm.group(1)
        # 词组头: <span class="idm">xxx</span>
        hm = _re.search(r'<span\b[^>]*class=["\']idm["\'][^>]*>(.*?)</span>', body, _re.S)
        head = _text_no_tags(hm.group(1)) if hm else ""
        if not head:
            continue
        # 该词组块内的释义: <li class="sense"> .. <span class="def">..</span> <defT><chn>..</chn></defT>
        defs = []
        for s in _re.finditer(r'<li\b[^>]*class=["\'][^"\']*sense["\'][^>]*>(.*?)</li>', body, _re.S):
            _s = s.group(1)
            dm = _re.search(r'<span\b[^>]*class=["\'][^"\']*def["\'][^>]*>(.*?)</span>', _s, _re.S)
            cd = _re.search(r'<defT>\s*<chn>(.*?)</chn>\s*</defT>', _s, _re.S)
            en = _text_no_tags(dm.group(1)) if dm else ""
            cn = _text_no_tags(cd.group(1)) if cd else ""
            defs.append([en, cn])
        if not defs:
            # 有的习语直接 def//* 无 li.sense 包裹
            dmf = _re.search(r'<span\b[^>]*class=["\'][^"\']*def["\'][^>]*>(.*?)</span>', body, _re.S)
            cnf = _re.search(r'<defT>\s*<chn>(.*?)</chn>\s*</defT>', body, _re.I)
            if dmf:
                defs.append([_text_no_tags(dmf.group(1)),
                             _text_no_tags(cnf.group(1)) if cnf else ""])
        blocks.append({"head": head, "defs": defs})
    return blocks


def _render_idioms(html: str) -> str:
    """渲染习语区 HTML（若无则返回空串）。"""
    blocks = _render_block_impl2(html)
    if not blocks:
        return ""
    out = ["<div class='seclabel'>Idioms</div>"]
    out.append("<div class='exlist'>")
    for b in blocks:
        if not b["defs"]:
            continue
        out.append(f"<div class='phr'><span class='phrtxt'>{_esc(b['head'])}</span></div>")
        d, c = b["defs"][0]
        if d:
            out.append(f"<span class='def'>{_esc(d)}</span>")
        if d and c:
            out.append("<br>")
        if c:
            out.append(f"<span class='chn'>{_esc(c)}</span>")
    out.append("</div>")
    return "\n".join(out)


# ============================ 短语动词(Phrasal Verbs)区 ============================
def _render_phrasal(html: str) -> str:
    """渲染短语动词链接区：词典正文只给交叉链接，渲染成词组清单。"""
    m = _re.search(r'class=["\'][^"\']*phrasal_verb_links["\'][^>]*>(.*?)</aside>',
                   html, _re.I | _re.S)
    if not m:
        m = _re.search(r'class=["\'][^"\']*phrasal_verb_links["\'][^>]*>(.*?)</span>',
                       html, _re.I | _re.S)
    if not m:
        return ""
    zone = m.group(1)
    heads = []
    for x in _re.finditer(r'<span\b[^>]*class=["\'][^"\']*xh["\'][^>]*>(.*?)</span>',
                          zone, _re.I | _re.S):
        t = _text_no_tags(x.group(1))
        if t:
            heads.append(t)
    if not heads:
        return ""
    from urllib.parse import quote as _quote
    out = ["<div class='seclabel'>Phrasal Verbs</div>", "<div class='exlist'>"]
    for h in heads:
        # 交叉链接：每项跳转到该短语自己的完整词条(点击由 search_window 拦截 lookup: 协议)。
        # 用 "lookup:run%20across" 形式(QUrl.path() 可直接取到解码后的词), 避免 "//" 把词当 host。
        href = "lookup:" + _quote(h)
        out.append(
            f"<div class='ex'><a href='{href}' style='color:{_CLR_ACCENT};"
            f"text-decoration:underline;'>{_esc(h)}</a></div>"
        )
    out.append("</div>")
    out.append("<div class='seclabel' style='font-size:10px;color:#6E6E73;"
               "font-weight:500;letter-spacing:0.3px;margin-top:2px;'>"
               "点击任一短语查看其完整词条</div>")
    return "\n".join(out)


# ============================ 兜底与工具 ============================
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
    范块，就返回空列表（不少词条并没有例句，绝不能把整个词条正文当作"例句"）。
    """
    out = []
    m = _RE_EX_UL.search(html)
    if not m:
        return []
    body = m.group(1)

    def _text(s: str) -> str:
        s = _RE_TAG.sub(" ", s)
        return _h.unescape(_RE_WS.sub(" ", s)).strip()

    for li in _RE_LI.findall(body):
        en = ""
        m_en = _RE_SPAN_EN.search(li)
        if m_en:
            en = _text(m_en.group(1))
        if not en:
            en = _text(li)
        cn = ""
        for mcn in _RE_CN_CONTAINER.finditer(li):
            cn = _text_cn(mcn.group(1))
            if cn:
                break
        if en or cn:
            out.append((en, cn))
    return out


def _text_preserve_gloss(s: str):
    """去标签但保留 gloss/collocation 作为内联引注（换成引号内嵌）。"""
    s = _RE_GLOSS.sub(
        lambda m: " (" + _h.unescape(_RE_TAG.sub("", m.group(1))) + ")", s)
    return _h.unescape(_RE_WS.sub(" ", _RE_TAG.sub("", s))).strip()


def _text_cn(s: str) -> str:
    s = _RE_TAG.sub("", s)
    return _h.unescape(_RE_WS.sub(" ", s)).strip()


def _split_phon(phons):
    """拆开连续 /.../.../ 的 IPA, 去重, 返回列表。"""
    out = []
    for ph in phons:
        for m in _RE_PHON.findall(ph):
            if m not in out:
                out.append(m)
    return out


def _esc(s: str) -> str:
    return _h.escape(s)


def _fallback(html: str) -> str:
    """解析失败时退化为去链接/脚本/图后的原样 HTML。"""
    h = _RE_SCRIPT.sub("", html)
    h = _RE_STYLE.sub("", h)
    h = _RE_LINK.sub("", h)
    h = _RE_AUDIO.sub("", h)
    h = _RE_EVENTS.sub("", h)
    h = _RE_IMG.sub("", h)
    return _HEADER + "<html><head>" + _STYLE + "</head><body>" + h + "</body></html>"


# ============================ 导出辅助(供习语解析) ============================
def _render_block_impl2(html: str) -> list:
    """抽取习语块, 返回 [{head, defs:[(en,cn),...]}]。用专用 HTMLParser 逐 idm-g 块解析。"""
    zone = _slice_idioms(html)
    if not zone:
        return []
    chunks = _split_idm_groups(zone)
    blocks = []
    for chunk in chunks:
        hm = _re.search(r'<span\b[^>]*class=["\']idm["\'][^>]*>(.*?)</span>',
                        chunk, _re.I | _re.S)
        head = _text_no_tags(hm.group(1)) if hm else ""
        if not head:
            continue
        defs = _parse_def_idm(chunk)
        if defs:
            blocks.append({"head": head, "defs": defs})
    return blocks


def _split_idm_groups(zone: str) -> list:
    """把习语区正文按 <span class="idm-g">…</span> 切分成独立块, 返回原始子串。
    深度从外层 span 开始计 1, 内部嵌套 span 增减, 归零即外层闭合。"""
    depth = 0
    out, start_pos = [], None
    for tm in _re.finditer(r'<(/?)span\b([^>]*)>', zone, _re.I):
        is_close = tm.group(1) == "/"
        cls = tm.group(2)
        if not is_close and "idm-g" in cls:
            start_pos = tm.start()
            depth = 1
            continue
        if start_pos is None:
            continue
        if not is_close:
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                out.append(zone[start_pos:tm.end()])
                start_pos = None
    return out


def _parse_def_idm(chunk: str) -> list:
    """解析一个 idm-g 块内的英文 def + 中文 chn。"""
    defs = []
    for s in _re.finditer(r'<li\b[^>]*class=["\'][^"\']*sense["\'][^>]*>(.*?)</li>',
                          chunk, _re.S):
        _s = s.group(1)
        d = _re.search(r'class=["\']def["\'][^>]*>(.*?)</span>', _s, _re.I | _re.S)
        c = _re.search(r'<defT>\s*<chn>(.*?)</chn>\s*</defT>', _s, _re.I | _re.S)
        defs.append([_text_no_tags(d.group(1)) if d else "",
                     _text_no_tags(c.group(1)) if c else ""])
    if not defs:
        dmf = _re.search(r'class=["\']def["\'][^>]*>(.*?)</span>', chunk, _re.I | _re.S)
        cnf = _re.search(r'<defT>\s*<chn>(.*?)</chn>\s*</defT>', chunk, _re.I | _re.S)
        if dmf:
            defs.append([_text_no_tags(dmf.group(1)),
                         _text_no_tags(cnf.group(1)) if cnf else ""])
    return defs


def _slice_idioms(html: str) -> str:
    """从 html 中切出习语区(<div class="idioms">…)正文（按 div 深度配对闭合）。"""
    m = _re.search(r'<div\b[^>]*class=["\'][^"\']*idioms["\'][^>]*>', html, _re.I)
    if not m:
        return ""
    start = m.end()
    # div 深度平衡: 起点已在 <div class="idioms"> 内部, 初始 depth=1,
    # 扫描到归零(闭合最外 idioms div)为止。
    depth = 1
    for tm in _re.finditer(r'<(/?)div\b[^>]*>', html[start:], _re.I):
        if tm.group(1) == "/":
            depth -= 1
            if depth <= 0:
                return html[start:start + tm.start()]
        else:
            depth += 1
    return html[start:]


# ============================ 样式与常量 ============================
_HEADER = "<!DOCTYPE html>"

_CLR_TEXT         = "#F2F2F7"
_CLR_TEXT_SOFT    = "#E8E8EC"
_CLR_SECONDARY    = "#9AA0A6"
_CLR_TERTIARY     = "#6E6E73"
_CLR_ACCENT       = "#0A84FF"
_CLR_CARD         = "#1E1E24"
_CLR_HAIR         = "#2A2A33"
_CLR_CJK_DEF      = "#D8D8E0"

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
div.phr{{margin:4px 0 2px;}}
span.phrtxt{{color:{_CLR_ACCENT};font-style:italic;font-weight:700;font-size:15px;}}
span.sensenum{{color:{_CLR_ACCENT};font-weight:700;margin-right:8px;font-size:16px;}}
span.def{{color:#FFFFFF;display:inline;font-size:16px;}}
span.chn{{color:{_CLR_CJK_DEF};font-weight:550;font-size:15.5px;display:inline;}}
div.seclabel{{font-size:11px;color:{_CLR_TERTIARY};font-weight:700;letter-spacing:1.6px;
text-transform:uppercase;margin:22px 0 10px;}}
div.exlist{{margin:0;padding-left:2px;}}
div.ex{{margin:7px 0;padding-left:10px;border-left:2px solid {_CLR_HAIR};color:{_CLR_TEXT_SOFT};}}
span.exx{{color:{_CLR_TEXT_SOFT};font-size:14px;line-height:1.5;}}
span.excf{{color:{_CLR_ACCENT};font-style:italic;font-weight:600;font-size:13.5px;margin-right:6px;}}
span.excn{{color:{_CLR_SECONDARY};font-size:13px;line-height:1.45;}}
table{{border-collapse:collapse;}} td,th{{padding:3px 10px;font-size:15px;}}
img{{max-width:100%;background:transparent;border:0;}}
a{{color:{_CLR_ACCENT};text-decoration:none;}}
</style>"""
)


# 兼容旧调用
def clean_and_render(html: str) -> str:
    return convert_dict_html(html)