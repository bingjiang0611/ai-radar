"""给「已翻译并搬运到 B站」的 YouTube 视频条目设置 B站链接(存进 items.video_url)。

用法:
    python3 src/set_bili.py <item_hash 或 /item/<hash>.html 或原 YouTube URL> <bilibili_url>

设置时会从 B站 API 取该视频的 cid 一并存入(player 加载更可靠)。之后
`python3 src/run.py --render-only`,该视频详情页「中文」tab 会出现可站内播放的 B站 lite
门面(点封面才挂 player.bilibili.com,不跳转)。清空翻译:bilibili_url 传空串 ""。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import _conn, init_db  # noqa: E402


def _fetch_cid(bv):
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", "Mozilla/5.0", "--max-time", "20",
             f"https://api.bilibili.com/x/web-interface/view?bvid={bv}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=25,
        )
        return str((json.loads(r.stdout).get("data") or {}).get("cid") or "")
    except Exception:  # noqa: BLE001
        return ""


def main():
    if len(sys.argv) < 3:
        print("用法: set_bili.py <item_hash 或 URL> <bilibili_url>", file=sys.stderr)
        return 2
    key, bili = sys.argv[1], sys.argv[2]
    c = _conn()
    init_db(c)
    m = re.search(r"[0-9a-f]{16}", key)  # 16 位 hash(可能裹在 /item/<hash>.html 里)
    row = (c.execute("SELECT hash, title FROM items WHERE hash=?", (m.group(0),)).fetchone() if m
           else c.execute("SELECT hash, title FROM items WHERE url=?", (key,)).fetchone())
    if not row:
        print(f"找不到条目: {key}", file=sys.stderr)
        c.close()
        return 2
    stored = bili
    bv = re.search(r"BV[0-9A-Za-z]+", bili)
    if bv and "cid=" not in bili:
        cid = _fetch_cid(bv.group(0))
        if cid:
            stored = bili + ("&" if "?" in bili else "?") + "cid=" + cid
    c.execute("UPDATE items SET video_url=? WHERE hash=?", (stored, row["hash"]))
    c.commit()
    c.close()
    print(f"已设 B站翻译:{row['title'][:50]} → {stored or '(清空)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
