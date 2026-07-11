"""SQLite storage for curated ai-radar items."""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "radar.db"

_STRIP_PREFIX = ("utm_",)
_STRIP_EXACT = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
    "ref",
    "ref_src",
    "ref_url",
    "reflink",
    "igshid",
    "_hsenc",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  hash           TEXT UNIQUE NOT NULL,
  source_id      TEXT NOT NULL,
  source_label   TEXT NOT NULL,
  category       TEXT NOT NULL,
  title          TEXT NOT NULL,
  title_zh       TEXT DEFAULT '',
  summary        TEXT DEFAULT '',
  summary_zh     TEXT DEFAULT '',
  url            TEXT NOT NULL,
  published_at   TEXT DEFAULT '',
  fetched_at     TEXT NOT NULL,
  status         TEXT DEFAULT 'new',
  content_html   TEXT DEFAULT '',
  translation_md TEXT DEFAULT '',
  video_url      TEXT DEFAULT '',
  summary_md     TEXT DEFAULT '',
  tweet_meta     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);
"""

_MIGRATION_COLUMNS = {
    "title_zh": "TEXT DEFAULT ''",
    "summary_zh": "TEXT DEFAULT ''",
    "status": "TEXT DEFAULT 'new'",
    "content_html": "TEXT DEFAULT ''",
    "translation_md": "TEXT DEFAULT ''",
    "video_url": "TEXT DEFAULT ''",
    "summary_md": "TEXT DEFAULT ''",
    "tweet_meta": "TEXT DEFAULT ''",
}


def normalize_url(url):
    parts = urlsplit((url or "").strip())
    kept_query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query)
        if k.lower() not in _STRIP_EXACT and not any(k.lower().startswith(p) for p in _STRIP_PREFIX)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(kept_query), ""))


def url_hash(url):
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db(conn=None):
    c = conn or _conn()
    c.executescript(SCHEMA)
    for col, ddl in _MIGRATION_COLUMNS.items():
        try:
            c.execute(f"ALTER TABLE items ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    c.commit()
    if conn is None:
        c.close()


def insert_items(rows, source, conn=None):
    """Insert minimal curated rows. Existing URLs are ignored."""
    c = conn or _conn()
    init_db(c)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for r in rows:
        cur = c.execute(
            """INSERT OR IGNORE INTO items
               (hash, source_id, source_label, category, title, summary, content_html, url, published_at, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                url_hash(r["url"]),
                source["id"],
                source["source_label"],
                source["category"],
                r["title"],
                r.get("summary", ""),
                r.get("content_html", ""),
                r["url"],
                r.get("published_at", ""),
                now,
            ),
        )
        inserted += cur.rowcount
    c.commit()
    if conn is None:
        c.close()
    return inserted


def _parse_dt(s):
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
    """Delete stale non-curated rows left from the old aggregator era."""
    c = conn or _conn()
    init_db(c)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    purge = []
    for r in c.execute("SELECT hash, published_at, fetched_at, translation_md, summary_md, video_url FROM items"):
        curated = (
            (r["translation_md"] or "").strip()
            or (r["summary_md"] or "").strip()
            or "bilibili" in (r["video_url"] or "")
        )
        if curated:
            continue
        dt = _parse_dt(r["published_at"]) or _parse_dt(r["fetched_at"])
        if dt and dt < cutoff:
            purge.append(r["hash"])
    for h in purge:
        c.execute("DELETE FROM items WHERE hash=?", (h,))
    c.commit()
    if conn is None:
        c.close()
    return len(purge)


def all_items(conn=None):
    c = conn or _conn()
    init_db(c)
    rows = [dict(r) for r in c.execute("SELECT * FROM items").fetchall()]
    if conn is None:
        c.close()
    floor = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: ((_parse_dt(r["published_at"]) or _parse_dt(r["fetched_at"]) or floor), r["id"]), reverse=True)
    return rows
