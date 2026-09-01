"""词典词条基础释义摘要提取。

用途：给查询联想列表项生成一行"词性缩写 + 中文释义"概览，例如：
    general → "adj. 普遍的 · n. 将军"
    run     → "v. 跑 / n. 跑动"
"""
from html.parser import HTMLParser

_POS_ABBR = {
    "noun": "n", "verb": "v", "adjective": "adj", "adverb": "adv",
    "exclamation": "int", "preposition": "prep", "conjunction": "conj",
    "pronoun": "pron", "determiner": "det", "numeral": "num",
    "modalverb": "v.aux", "abbreviation": "abbr", "prefix": "pref",
    "suffix": "suf", "prepositionoradverb": "prep/adv",
    "combiningform": "comb", "phrase": "phr",
}
_ALIAS = {n: v for v, n in {
    "n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb",
    "prep": "preposition", "conj": "conjunction", "pron": "pronoun",
    "det": "determiner", "num": "numeral", "int": "exclamation",
}.items()}
_MAX_PER_POS = 1   # 每词性取最新一条释义（保持简介、避免例句/衍生词污染）
_MAX_GROUPS = 3
_MAX_CHARS = 115


def _norm_pos(raw):
    s = "".join(ch for ch in raw.lower() if ch.isalpha())
    if not s:
        return ""
    if s in _POS_ABBR:
        return s
    if s in _ALIAS:
        return _ALIAS[s]
    for canon in _POS_ABBR:
        if s.startswith(canon):
            return canon
    return ""


def _short_chn(raw):
    t = " ".join(raw.split())
    for sep in "；;":
        head, _, _ = t.partition(sep)
        if head.strip():
            t = head
            break
    return t.strip()


class _Ext(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pos = ""
        self.groups = {}            # pos -> [gloss,...]
        self.order = []
        self._pos_pending = False
        self._deft = 0             # 在当前 <defT> 内(可收中文)
        self._neg = 0              # 主题/例句等屏蔽容器深度
        self._stack = []           # tag 栈(用于闭合时回退)
        self._skip = 0
        self._ex = 0
        self._opened = []          # (tag, kind) kind∈{"pos","deft","neg",""}

    @staticmethod
    def _cls(attrs):
        c = set()
        for k, v in attrs:
            if k == "class":
                c.update(v.split())
        return c

    def handle_starttag(self, tag, attrs):
        if self._skip:
            if tag in ("script", "style", "audio"):
                self._skip += 1
            return
        if tag in ("script", "style", "audio"):
            self._skip = 1
            return
        cls = self._cls(attrs)
        kind = ""
        if "pos" in cls:
            kind = "pos"
            self._pos_pending = True
        elif tag == "deft":
            kind = "deft"
            self._deft += 1
        elif (tag == "h2" and "shcut" in cls) or (tag == "span" and "x" in cls) \
                or tag in ("uncap", "pv", "v", "ir", "id", "xx") or tag == "ul" and "examples" in cls:
            kind = "neg"
            self._neg += 1
        self._opened.append((tag.lower(), kind))

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if self._skip:
            if tag in ("script", "style", "audio"):
                self._skip -= 1
            return
        for i in range(len(self._opened) - 1, -1, -1):
            t, kind = self._opened[i]
            if t == tag.lower():
                if kind == "deft":
                    self._deft = max(0, self._deft - 1)
                elif kind == "neg":
                    self._neg = max(0, self._neg - 1)
                del self._opened[i]
                break

    def handle_data(self, data):
        if self._skip or not self._opened:
            return
        if self._pos_pending:
            self._pos_pending = False
            np_ = _norm_pos(data)
            if np_:
                self.pos = np_
            return
        if self._deft and self._neg == 0 and self.pos:
            txt = _short_chn(data)
            if txt:
                g = self.groups.setdefault(self.pos, [])
                if len(g) < _MAX_PER_POS and txt not in g:
                    g.append(txt)


def extract_summary(html: str, max_chars: int = _MAX_CHARS) -> str:
    p = _Ext()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return ""
    groups = list(p.groups.items())   # 保持词典自身词性排列(最常用词性在前)
    parts = []
    for pos, gloss in groups[:_MAX_GROUPS]:
        if not gloss:
            continue
        parts.append(f"{_POS_ABBR.get(pos, pos)}. {'；'.join(gloss)}")
    summ = " · ".join(parts)
    if not summ:
        return ""
    if len(summ) > max_chars:
        summ = summ[: max_chars - 3].rstrip() + "…"
    return summ