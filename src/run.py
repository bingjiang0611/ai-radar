"""ai-radar 入口：抓全部启用源 → 去重写库 → 渲染 dist/。

用法:
    python3 src/run.py              抓 + 渲染
    python3 src/run.py --no-render  只抓不渲染
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parsers import PARSERS      # noqa: E402
from store import init_db, insert_items, all_items  # noqa: E402
from render import render_site   # noqa: E402

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
        try:
            rows = parser(s)
        except Exception as e:  # noqa: BLE001 — 单源失败不中断整轮
            print(f"  ✗ {s['source_label']}: {e}", file=sys.stderr)
            continue
        n = insert_items(rows, s)
        total_new += n
        print(f"  • {s['source_label']}: 抓到 {len(rows)} 条, 新增 {n}")
    return total_new


def main():
    print("🔍 抓取中…")
    new = fetch_all()
    print(f"✨ 本次新增 {new} 条")
    if "--no-render" not in sys.argv:
        out = render_site(all_items())
        print(f"🖼  已渲染 → {out}")


if __name__ == "__main__":
    main()
