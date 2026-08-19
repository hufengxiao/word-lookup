"""
词典索引构建器。

一次性把 .mdx 解析并写入 SQLite 数据库，供 GUI 快速查询。
GUI 端不再需要 LZO 库 / 大 mdx 文件，只需读取生成的 .db。

数据库 schema:
    words(
        id        INTEGER PRIMARY KEY,
        key       TEXT NOT NULL,          -- 原始词条名
        key_lower TEXT NOT NULL,          -- 小写（用于排序/不区分大小写前缀查询）
        html      TEXT NOT NULL,          -- 词条正文 HTML
        freq      INTEGER DEFAULT 0
    );
    CREATE INDEX idx_words_key_lower ON words(key_lower);
    -- 可选 FTS5 用于子串/模糊搜索
"""
import os
import sqlite3
import time

from .mdx_parser import MDX


class IndexBuilder:
    def __init__(self, mdx_path: str, db_path: str):
        self.mdx_path = mdx_path
        self.db_path = db_path
        self.mdx = None

    def build(self, verbose=True):
        t0 = time.time()
        self.mdx = MDX(self.mdx_path)
        t1 = time.time()
        if verbose:
            print(f"解析索引块 {t1 - t0:.2f}s，共 {len(self.mdx)} 词条")

        # 删除旧的
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=OFF")
        cur.execute("PRAGMA synchronous=OFF")
        cur.execute("PRAGMA cache_size=-200000")
        cur.execute(
            """CREATE TABLE words(
                id INTEGER PRIMARY KEY,
                key TEXT NOT NULL,
                key_lower TEXT NOT NULL,
                html TEXT NOT NULL
            )"""
        )
        cur.execute("CREATE INDEX idx_words_key_lower ON words(key_lower)")

        # 逐块写正文
        batch = []
        n = 0
        batch_size = 2000
        t_write = time.time()
        for key_text, html in self.mdx._iter_record_blocks():
            try:
                key_s = key_text.decode("utf-8", "replace")
            except Exception:
                key_s = key_text
            batch.append((key_s, key_s.lower(), html.decode("utf-8", "replace")))
            n += 1
            if len(batch) >= batch_size:
                cur.executemany(
                    "INSERT INTO words(key,key_lower,html) VALUES(?,?,?)", batch
                )
                batch = []
                if verbose and n % 50000 < batch_size:
                    print(f"  已写入 {n} 条，累计 {time.time()-t_write:.1f}s")
        if batch:
            cur.executemany(
                "INSERT INTO words(key,key_lower,html) VALUES(?,?,?)", batch
            )
        conn.commit()

        # 统计
        cur.execute("SELECT COUNT(*), SUM(LENGTH(html)), SUM(LENGTH(key)) FROM words")
        cnt, html_len, key_len = cur.fetchone()
        cur.execute("PRAGMA page_count")
        pages = cur.fetchone()[0]
        cur.execute("PRAGMA page_size")
        page_size = cur.fetchone()[0]
        conn.commit()
        conn.close()
        t2 = time.time()
        if verbose:
            print(f"构建完成 {t2-t0:.1f}s")
            print(f"词条 {cnt}，正文总长 {html_len/1024/1024:.1f} MB，")
            print(f"数据库大小约 {pages*page_size/1024/1024:.1f} MB")
        return {
            "count": cnt,
            "html_bytes": html_len,
            "db_mb": pages * page_size / 1024 / 1024,
            "seconds": t2 - t0,
        }


def build_from_mdx(mdx_path: str, db_path: str, verbose=True):
    """便捷函数：从 mdx 构建 sqlite。返回统计 dict。"""
    return IndexBuilder(mdx_path, db_path).build(verbose=verbose)


if __name__ == "__main__":
    import sys

    mdx_p = sys.argv[1] if len(sys.argv) > 1 else "~/Projects/牛津高阶第10版英汉双解V132.mdx"
    db_p = sys.argv[2] if len(sys.argv) > 2 else "oxford.db"
    mdx_p = os.path.expanduser(mdx_p)
    build_from_mdx(mdx_p, db_p)