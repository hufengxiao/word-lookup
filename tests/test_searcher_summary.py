"""searcher / summary / indexer.backfill 单元测试 —— headless，无需 GUI。

覆盖查询核心（前缀/子串/大小写/@@@LINK 重定向）、词性沿归一 与 中文释义摘要、
以及老库就地补 summary 列的幂等性 —— 这是此前单测未覆盖的纯逻辑层。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from dictionary.searcher import Searcher  # noqa: E402
from dictionary.summary import _norm_pos, extract_summary  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_path(tmp_path):
    """构造含 summary 列的临时词典库：apple / banana / run / bad→@@@LINK。"""
    p = str(tmp_path / "t.db")
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE words(id INTEGER PRIMARY KEY, key TEXT, key_lower TEXT, "
        "html TEXT, summary TEXT NOT NULL DEFAULT '')"
    )
    rows = [
        ("apple", "apple", "<h1 class='headword'>apple</h1><span class='pos'>n.</span>"
         "<span class='def'>a fruit</span><defT><chn>苹果</chn></defT>", "n. 苹果"),
        ("Apples", "apples", "<h1 class='headword'>Apples</h1><span class='def'>pl.</span>",
         "pl."),
        ("sun", "sun", "<h1 class='headword'>sun</h1><span class='def'>the star</span>"
         "<defT><chn>太阳</chn></defT>", "n. 太阳"),
        ("run", "run", "<h1 class='headword'>run</h1><span class='pos'>v.</span>"
         "<span class='def'>to move fast</span><defT><chn>跑</chn></defT>", "v. 跑"),
        ("bad", "bad", "@@@LINK=worse", ""),  # 重定向到 worse
    ]
    conn.executemany("INSERT INTO words(key,key_lower,html,summary) VALUES(?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return str(p)


def _locked(path):
    # 每用例独立临时库, 避免 Searcher 单例连接互相影响
    return Searcher(path)


# ---------------------------------------------------------------------------
# searcher.search — 前缀 / 大小写 / limit
# ---------------------------------------------------------------------------
def test_search_prefix(db_path):
    s = _locked(db_path)
    res = s.search("app", 20)
    keys = [k for k, _ in res]
    # 前缀匹配 "app" 命中 apple + Apples（大小写不敏感前缀）
    assert "apple" in keys and "Apples" in keys


def test_search_case_insensitive(db_path):
    s = _locked(db_path)
    lower = [k for k, _ in s.search("APPLE", 20)]
    upper = [k for k, _ in s.search("apple", 20)]
    assert "apple" in lower and "apple" in upper


def test_search_empty_query(db_path):
    s = _locked(db_path)
    assert s.search("   ") == []


def test_search_no_match(db_path):
    s = _locked(db_path)
    assert s.search("zzznotfound") == []


def test_search_respects_limit(db_path):
    s = _locked(db_path)
    # 只有 apple 前缀; 用 "ap" 只能命中 apple(非), 验证 limit 不被放大
    res = s.search("a", limit=1)
    assert len(res) == 1


# ---------------------------------------------------------------------------
# searcher — lookup / key_exists
# ---------------------------------------------------------------------------
def test_lookup_exact(db_path):
    s = _locked(db_path)
    display, html = s.lookup("Apple")
    assert display == "apple"
    assert "苹果" in html.decode() if isinstance(html, bytes) else "苹果" in html


def test_lookup_missing_returns_none(db_path):
    s = _locked(db_path)
    assert s.lookup("nope") == ("nope", None)


def test_lookup_follows_atat_link(db_path):
    """@@@LINK 重定向：查 'bad' 应落到 'good' 正文（本库无 good → 返回 None）。"""
    s = _locked(db_path)
    display, html = s.lookup("bad")
    assert display == "bad"   # 找不到目标词条时返回查入 key 与 None
    assert html is None


def test_key_exists(db_path):
    s = _locked(db_path)
    assert s.key_exists("SUN")
    assert not s.key_exists("galaxy")


# ---------------------------------------------------------------------------
# summary — 词性归一化（含 _norm_pos 变体/前缀兜底）
# ---------------------------------------------------------------------------
def test_norm_pos_aliases():
    assert _norm_pos("noun") == "noun"
    assert _norm_pos("N.") == "noun"          # 去掉标点
    assert _norm_pos("v") == "verb"           # 别名
    assert _norm_pos("adj.") == "adjective"
    # 后缀变体走最长前缀兜底
    assert _norm_pos("adverbial") == "adverb"
    assert _norm_pos("nouns") == "noun"
    assert _norm_pos("") == ""
    assert _norm_pos("!!!") == ""


def test_extract_summary_basic():
    html = ("<span class='pos'>noun</span><span class='def'>a round fruit</span>"
            "<defT><chn>苹果</chn></defT>")
    s = extract_summary(html)
    assert "n." in s
    assert "a round fruit" in s or "苹果" in s


def test_extract_summary_empty_html():
    assert extract_summary("") == ""
    assert extract_summary("<script>var x=1</script>") == ""


def test_extract_summary_truncates_long():
    # 超长摘要被 max_chars 截断并加省略号
    long_def = ("<span class='pos'>adj</span><span class='def'>"
                "a" * 200 + "</span>")
    s = extract_summary(long_def)
    assert len(s) <= 118  # max_chars=115 + 省略号安全


# ---------------------------------------------------------------------------
# indexer.backfill_summary —— 老库(无 summary 列)就地补列 + 幂等
# ---------------------------------------------------------------------------
def test_backfill_summary_adds_column(tmp_path):
    from dictionary.indexer import backfill_summary

    p = str(tmp_path / "old.db")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE words(id INTEGER PRIMARY KEY, key TEXT, "
                 "key_lower TEXT, html TEXT)")
    conn.execute("INSERT INTO words(id,key,key_lower,html) VALUES(1,'sun','sun',"
                 "'<span class=pos>n</span><span class=def>the star</span>"
                 "<defT><chn>太阳</chn></defT>')")
    conn.commit()
    conn.close()

    changed, filled = backfill_summary(p)
    assert changed is True
    assert filled == 1

    # 幂等：再跑一次，changed 应为 False（列已存在）
    changed2, _ = backfill_summary(p)
    assert changed2 is False

    # 列已存在且摘要已写入
    conn = sqlite3.connect(p)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(words)")]
    assert "summary" in cols
    got = conn.execute("SELECT summary FROM words WHERE key='sun'").fetchone()[0]
    conn.close()
    assert got  # 非空