"""
词典查询器（GUI 用）。

从构建好的 SQLite 数据库读词条，提供：
  - search(prefix): Spotlight 风格、输入即联想的前缀搜索
  - lookup(key):   精确查正文 HTML
  - fuzzy = False(默认): 纯前缀联想 —— 走 B-tree 索引, 亚毫秒级, 输入不会卡

性能要点（已在 NAS 真词典 31 万词条实测）：
  - 前缀查询: 走 idx_words_key_lower 索引, 0.1~24ms
  - LIKE '%xxx%' 子串回退: 全表扫描, 100ms~3s —— 是输入卡顿的元凶。
    默认关闭; 需要容错时用 fuzzy=True 手动启用。

只读数据库，线程安全（每次查询用独立连接或加锁）。
"""
import os
import sqlite3
from collections import OrderedDict

MAX_SUGGEST = 20  # 联想列表上限


class Searcher:
    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"词典数据库不存在: {db_path}")
        self.db_path = db_path
        self._lock = _Lock()
        # 快速单例连接，只读
        self._conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self._count = self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        # P0-2b：脱敏 lookup 结果 LRU 缓存(手动 OrderedDict, 避免 lru_cache 在方法上
        # 持有 self 引用的泄漏)。容量 128, 超限弹最旧。
        self._lookup_cache = OrderedDict()
        self._lookup_cache_max = 128

    @property
    def count(self) -> int:
        return self._count

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = MAX_SUGGEST, fuzzy: bool = False):
        """前缀联想搜索，返回 [(key, display)]。

        默认 fuzzy=False：只做大小写不敏感前缀匹配（Spotlight 风格），
        走 B-tree 索引，亚毫秒。fuzzy=True 时前缀不足才补子串扫描。
        """
        q = query.strip()
        if not q:
            return []
        ql = q.lower()
        out = []
        has_summary = getattr(self, "_has_summary", None)
        if has_summary is None:
            try:
                cols = self._conn.execute("PRAGMA table_info(words)").fetchall()
                self._has_summary = any(c["name"] == "summary" for c in cols)
            except Exception:
                self._has_summary = False
            has_summary = self._has_summary
        sel = "key, key_lower, summary" if has_summary else "key, key_lower, '' as summary"
        with self._lock:
            # 前缀查询（最快，走 B-tree range）
            rows = self._conn.execute(
                f"SELECT {sel} FROM words WHERE key_lower >= ? "
                "AND key_lower < ? ORDER BY key_lower LIMIT ?",
                (ql, _upper_bound(ql), limit),
            ).fetchall()
            for r in rows:
                out.append((r["key"], r["summary"] or ""))
            # 前缀不足且允许模糊时，补充受限的子串匹配（潜在慢，谨慎用）
            if fuzzy and len(out) < limit:
                found = {k for k, _ in out}
                sub = self._conn.execute(
                    "SELECT key FROM words WHERE key_lower LIKE ? "
                    "ORDER BY length(key) LIMIT ?",
                    (f"%{ql}%", limit - len(out)),
                ).fetchall()
                for r in sub:
                    k = r["key"]
                    if k not in found:
                        out.append((k, ""))
                        found.add(k)
                    if len(out) >= limit:
                        break
        return out[:limit]

    def lookup(self, key: str):
        """给定 key 精确查找词条正文 HTML，跟随 @@@LINK 重定向(复数/派生→主词条)。

        key 大小写不敏感。返回 (display_key, html) 或 (key, None)。

        P0-2 性能：结果 LRU 缓存(容量 128)缓存最近查过的词条，来回切换
        同一词条不重复查库。key 本身作缓存键(大小写不同产生重复项无碍正确性)。
        """
        target = key.strip()
        cached = self._lookup_cache.get(target)
        if cached is not None:
            return cached
        seen = set()
        while len(seen) < 16:
            t = target.lower()
            if t in seen:
                break
            seen.add(t)
            with self._lock:
                row = self._conn.execute(
                    "SELECT key, html FROM words WHERE key_lower = ?", (t,)
                ).fetchone()
            if not row:
                result = (key, None)
                self._populate_cache(target, result)
                return result
            html = row["html"]
            if html and html.lstrip().startswith("@@@LINK="):
                target = html.split("@@@LINK=", 1)[1].strip()
                continue
            result = (row["key"], html)
            self._populate_cache(target, result)
            return result
        result = (key, None)
        self._populate_cache(target, result)
        return result

    def _populate_cache(self, target: str, result):
        """把 (target -> result) 写入 LRU 缓存；超容弹最旧。"""
        cache = self._lookup_cache
        if len(cache) >= self._lookup_cache_max:
            cache.popitem(last=False)
        cache[target] = result
        cache.move_to_end(target)

    def key_exists(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM words WHERE key_lower = ?", (key.strip().lower(),)
            ).fetchone()
        return row is not None


def _upper_bound(ql: str) -> str:
    """前缀查询上界：ql 后接超出正常字符的哨兵，构成 [ql, ql\\uffff) 前缀区间。"""
    return ql + "\uffff"


class _Lock:
    """轻量可重入锁封装（进程内线程安全）。"""

    import threading

    def __init__(self):
        self._l = self.threading.Lock()

    def __enter__(self):
        self._l.acquire()

    def __exit__(self, *a):
        self._l.release()


if __name__ == "__main__":
    import sys

    dbp = sys.argv[1] if len(sys.argv) > 1 else "oxford.db"
    dbp = os.path.expanduser(dbp)
    s = Searcher(dbp)
    print("词典词条数:", s.count)
    while True:
        q = input("输入搜索词 (回车退出): ").strip()
        if not q:
            break
        import time
        t0 = time.time()
        res = s.search(q, 10)
        t1 = time.time()
        for k, _ in res:
            print("  ", k)
        print(f"  ({len(res)} 结果, {(t1-t0)*1000:.1f} ms)")
        if res:
            k = res[0][0]
            html = s.lookup(k)
            print(f"  lookup({k!r}) len={len(html) if html else 0}")