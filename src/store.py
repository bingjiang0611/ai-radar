"""SQLite 单层去重存储——唯一真源。

去重：hash = md5(归一化URL)，列上 UNIQUE，写入用 INSERT OR IGNORE。
所有函数可传入 conn（便于单测用 :memory:）；不传则用默认 data/radar.db。
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
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
  content_html  TEXT DEFAULT '',
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


def hash_exists(hash_val, conn=None):
    """该 hash 是否已入库（用于只对新条目做昂贵的内容处理/图片下载）。"""
    c = conn or _conn()
    init_db(c)
    row = c.execute("SELECT 1 FROM items WHERE hash = ?", (hash_val,)).fetchone()
    if conn is None:
        c.close()
    return row is not None


def insert_items(rows, source, conn=None):
    """把 parser 输出写库；hash 撞了自动跳过。返回去重后实际新增条数。
    row 可带 content_html（已清洗+图片进站的正文）。"""
    c = conn or _conn()
    init_db(c)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for r in rows:
        cur = c.execute(
            """INSERT OR IGNORE INTO items
               (hash, source_id, source_label, category, title, summary, content_html, url, published_at, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (url_hash(r["url"]), source["id"], source["source_label"], source["category"],
             r["title"], r.get("summary", ""), r.get("content_html", ""),
             r["url"], r.get("published_at", ""), now),
        )
        if cur.rowcount > 0:
            inserted += 1
    c.commit()
    if conn is None:
        c.close()
    return inserted


def _parse_dt(s):
    """解析 published_at / fetched_at：兼容 ISO 与 RFC822(pubDate)。返回带时区 datetime 或 None。"""
    from email.utils import parsedate_to_datetime
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


def purge_old(days=7, conn=None):
    """按内容新鲜度保留近 days 天:发布时间(published_at)已知且超期 → 删;
    发布时间未知(如无日期的博客/论文)→ 退回看抓取时间(fetched_at)超期才删。返回删除数。"""
    c = conn or _conn()
    init_db(c)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    purge = []
    for r in c.execute("SELECT hash, published_at, fetched_at FROM items").fetchall():
        pub = _parse_dt(r["published_at"])
        if pub is not None:
            if pub < cutoff:
                purge.append(r["hash"])
        else:
            fet = _parse_dt(r["fetched_at"])
            if fet is not None and fet < cutoff:
                purge.append(r["hash"])
    for h in purge:
        c.execute("DELETE FROM items WHERE hash=?", (h,))
    c.commit()
    if conn is None:
        c.close()
    return len(purge)


def all_items(conn=None):
    """全部条目，按发布时间(published_at，兼容 RFC822；无则退 fetched_at)倒序——最新发布在前。"""
    c = conn or _conn()
    init_db(c)
    rows = c.execute("SELECT * FROM items").fetchall()
    out = [dict(r) for r in rows]
    if conn is None:
        c.close()
    _min = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda r: ((_parse_dt(r["published_at"]) or _parse_dt(r["fetched_at"]) or _min), r["id"]),
             reverse=True)
    return out
