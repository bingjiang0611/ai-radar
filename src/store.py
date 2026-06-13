"""SQLite 单层去重存储——唯一真源。

去重：hash = md5(归一化URL)，列上 UNIQUE，写入用 INSERT OR IGNORE。
所有函数可传入 conn（便于单测用 :memory:）；不传则用默认 data/radar.db。
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fetch import normalize_url

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "radar.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  hash          TEXT UNIQUE NOT NULL,
  source_id     TEXT NOT NULL,
  source_label  TEXT NOT NULL,
  category      TEXT NOT NULL,
  title         TEXT NOT NULL,
  title_zh      TEXT DEFAULT '',
  summary       TEXT DEFAULT '',
  summary_zh    TEXT DEFAULT '',
  url           TEXT NOT NULL,
  published_at  TEXT DEFAULT '',
  fetched_at    TEXT NOT NULL,
  status        TEXT DEFAULT 'new',
  translation_md TEXT DEFAULT '',
  video_url     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_fetched  ON items(fetched_at);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db(conn=None):
    c = conn or _conn()
    c.executescript(SCHEMA)
    c.commit()
    if conn is None:
        c.close()


def url_hash(url):
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def insert_items(rows, source, conn=None):
    """把 parser 输出写库；hash 撞了自动跳过。返回去重后实际新增条数。"""
    c = conn or _conn()
    init_db(c)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for r in rows:
        cur = c.execute(
            """INSERT OR IGNORE INTO items
               (hash, source_id, source_label, category, title, summary, url, published_at, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (url_hash(r["url"]), source["id"], source["source_label"], source["category"],
             r["title"], r.get("summary", ""), r["url"], r.get("published_at", ""), now),
        )
        if cur.rowcount > 0:
            inserted += 1
    c.commit()
    if conn is None:
        c.close()
    return inserted


def all_items(conn=None):
    """全部条目，最新在前。"""
    c = conn or _conn()
    init_db(c)
    rows = c.execute("SELECT * FROM items ORDER BY fetched_at DESC, id DESC").fetchall()
    out = [dict(r) for r in rows]
    if conn is None:
        c.close()
    return out
