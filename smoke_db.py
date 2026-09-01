#!/usr/bin/env python3
"""快速生成一个最小词典 SQLite(db)，供 CI 冒烟测试使用（GUI 冒烟 + exe 冒烟共用）。

用法: python smoke_db.py <output.db>
创建 words 表 + 索引 + 3 个极简词条，覆盖"加载词典→搜索→显示详情→渲染"路径。
"""
import sqlite3
import sys

WORDS = [("apple", "apple", "<p>apple</p>"),
         ("hello", "hello", "<p>hello</p>"),
         ("world", "world", "<p>world</p>")]


def make_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE words (id INTEGER PRIMARY KEY, "
                "key TEXT, key_lower TEXT, html TEXT)")
    con.execute("CREATE INDEX idx_words_key_lower ON words(key_lower)")
    con.executemany(
        "INSERT INTO words(key, key_lower, html) VALUES(?,?,?)", WORDS)
    con.commit()
    con.close()
    print(f"smoke db created: {path}")


if __name__ == "__main__":
    make_db(sys.argv[1] if len(sys.argv) > 1 else "smoke_test.db")