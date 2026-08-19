"""
词典查询器（GUI 用）。

从构建好的 SQLite 数据库读词条，提供：
  - search(prefix): Spotlight 风格、输入即联想的前缀搜索
  - lookup(key):   精确查正文 HTML
  - fuzzy_search/contains: 可选子串搜索

只读数据库，线程安全（每次查询用独立连接或加锁）。
"""
import os
import re
import sqlite3

MAX_SUGGEST = 30  # 联想列表上限


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
    def search(self, query: str, limit: int = MAX_SUGGEST):
        """前缀搜索，返回 [(key, display)]。query 不能为空。

        Spotlight 交互：用户输入即时联想。这里用大小写不敏感前缀匹配，
        匹配到的直接返回；若前缀无匹配则回退到包含搜索（子串）。
        """
        q = query.strip()
        if not q:
            return []
        ql = q.lower()
        out = []
        with self._lock:
            # 前缀查询（最快，走 B-tree）
            rows = self._conn.execute(
                "SELECT key, key_lower FROM words WHERE key_lower >= ? "
                "AND key_lower < ? ORDER BY key_lower LIMIT ?",
                (ql, ql + "\uffff", limit),
            ).fetchall()
            for r in rows:
                out.append((r["key"], r["key_lower"]))
            # 前缀不足 limit 时，补充子串匹配（更宽松）
            if len(out) < limit:
                found_keys = {k for k, _ in out}
                sub = self._conn.execute(
                    "SELECT key FROM words WHERE key_lower LIKE ? AND key NOT IN (SELECT '') "
                    "ORDER BY length(key) LIMIT ?",
                    (f"%{ql}%", limit - len(out)),
                ).fetchall()
                for r in sub:
                    if r["key"] not in found_keys:
                        out.append((r["key"], r["key"].lower()))
                        found_keys.add(r["key"])
                    if len(out) >= limit:
                        break
        # 结果按 key 排序（区分：前缀优先已在上一步，这里整体按 key 排序即可）
        return out[:limit]

    def lookup(self, key: str):
        """精确查词条正文 HTML。key 大小写不敏感。返回 str 或 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT html FROM words WHERE key_lower = ?", (key.strip().lower(),)
            ).fetchone()
        return row["html"] if row else None

    def key_exists(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM words WHERE key_lower = ?", (key.strip().lower(),)
            ).fetchone()
        return row is not None


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
        t0 = __import__("time").time()
        res = s.search(q, 10)
        t1 = __import__("time").time()
        for k, _ in res:
            print("  ", k)
        print(f"  ({len(res)} 结果, {t1-t0*1000*1000:.0f} µs)")
        if res:
            k = res[0][0]
            html = s.lookup(k)
            print(f"  lookup({k!r}) len={len(html) if html else 0}")