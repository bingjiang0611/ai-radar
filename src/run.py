"""ai-radar 入口：抓全部启用源 → 去重写库 → 渲染 dist/。

用法:
    python3 src/run.py              抓 + 渲染
    python3 src/run.py --no-render  只抓不渲染
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                  # noqa: E402
from fetch import resolve_url    # noqa: E402
from parsers import PARSERS      # noqa: E402
from store import init_db, insert_items, all_items, url_hash, hash_exists, purge_old  # noqa: E402
from render import render_site   # noqa: E402

RETENTION_DAYS = 30  # 只保留近一个月内容

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.json"


def load_sources():
    return json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]


def fetch_all():
    init_db()
    total_new = 0
    for s in [s for s in load_sources() if s.get("enabled")]:
        parser = PARSERS.get(s["parser"])
        if parser is None:
            print(f"  ✗ {s['source_label']}: 未知 parser '{s['parser']}'", file=sys.stderr)
            continue
        resolved = dict(s, url=resolve_url(s["url"]))  # 填 {week}/{date} 占位
        try:
            rows = parser(resolved)
        except Exception as e:  # noqa: BLE001 — 单源失败不中断整轮
            print(f"  ✗ {s['source_label']}: {e}", file=sys.stderr)
            continue
        # 只对新条目做昂贵的内容处理（清洗 + 图片下载进站）
        new_rows = []
        for r in rows:
            if hash_exists(url_hash(r["url"])):
                continue
            r["content_html"] = content.process(r.get("content", "") or "")
            new_rows.append(r)
        n = insert_items(new_rows, s)
        total_new += n
        print(f"  • {s['source_label']}: 抓到 {len(rows)} 条, 新增 {n}")
    return total_new


def main():
    print("🔍 抓取中…")
    new = fetch_all()
    print(f"✨ 本次新增 {new} 条")

    purged = purge_old(RETENTION_DAYS)
    items = all_items()
    removed_imgs = content.gc_images([i["content_html"] for i in items])
    if purged or removed_imgs:
        print(f"🧹 retention：清掉 {purged} 条过期条目、{removed_imgs} 张无引用图片")

    if "--no-render" not in sys.argv:
        out = render_site(items)
        print(f"🖼  已渲染 → {out}（{len(items)} 条）")


if __name__ == "__main__":
    main()
