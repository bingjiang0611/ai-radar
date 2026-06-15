"""给推文里被引用推(quote)的非中文正文回填中译(存进 items.tweet_meta 的 quote.text_zh)。

为什么:@dotey 这类中文 KOL 引用英文原推,卡片里主推是中文、但引用框是英文原文。引用正文 ~300 字
属"摘要级",按 ai-radar 既定边界(标题+摘要中译走 Claude 会话)由会话回填,渲染时在英文下显示一行中译。

用法:
    python3 src/set_quote_zh.py --pending          # 列出需翻译的引用(引用为非中文 + text_zh 仍空)→ JSON
    python3 src/set_quote_zh.py <item_hash 或 URL> <中文译文>   # 写单条
    python3 src/set_quote_zh.py --file <json>      # 批量,json 为 {hash: 中文译文}

之后 `python3 src/run.py --render-only`,推文卡引用框英文下会多一行中译。清空:中文译文传空串。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import _conn, init_db  # noqa: E402

_CJK = re.compile(r"[一-鿿]")


def _is_zh(text):
    """中文字符占比够高 → 视为已是中文,无需翻译。"""
    t = (text or "").strip()
    return bool(t) and len(_CJK.findall(t)) >= max(4, len(t) * 0.15)


def _pending(c):
    """列出所有引用为非中文、且 text_zh 仍空的推文 → [{hash, text}]。"""
    out = []
    for r in c.execute("SELECT hash, tweet_meta FROM items WHERE category='推文' AND tweet_meta!=''").fetchall():
        try:
            tm = json.loads(r["tweet_meta"])
        except ValueError:
            continue
        q = tm.get("quote") or {}
        txt = (q.get("text") or "").strip()
        if txt and not _is_zh(txt) and not (q.get("text_zh") or "").strip():
            out.append({"hash": r["hash"], "text": txt})
    return out


def _set_one(c, key, zh):
    """把 zh 写进该条目 quote.text_zh(保留 quote 其余字段)。返回 (ok, msg)。"""
    m = re.search(r"[0-9a-f]{16}", key)
    row = (c.execute("SELECT hash, tweet_meta FROM items WHERE hash=?", (m.group(0),)).fetchone() if m
           else c.execute("SELECT hash, tweet_meta FROM items WHERE url=?", (key,)).fetchone())
    if not row:
        return False, f"找不到条目: {key}"
    try:
        tm = json.loads(row["tweet_meta"] or "{}")
    except ValueError:
        tm = {}
    if not tm.get("quote"):
        return False, f"该条目无引用推: {key}"
    tm["quote"]["text_zh"] = (zh or "").strip()
    c.execute("UPDATE items SET tweet_meta=? WHERE hash=?", (json.dumps(tm, ensure_ascii=False), row["hash"]))
    return True, f"已{'写入' if zh else '清空'}引用中译({len((zh or '').strip())} 字):{row['hash']}"


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    c = _conn()
    init_db(c)
    try:
        if sys.argv[1] == "--pending":
            print(json.dumps(_pending(c), ensure_ascii=False, indent=2))
            return 0
        if sys.argv[1] == "--file":
            mapping = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
            n = 0
            for h, zh in mapping.items():
                ok, msg = _set_one(c, h, zh)
                if ok:
                    n += 1
                else:
                    print("⚠️ " + msg, file=sys.stderr)
            c.commit()
            print(f"批量写入 {n}/{len(mapping)} 条引用中译")
            return 0
        if len(sys.argv) < 3:
            print("用法: set_quote_zh.py <hash 或 URL> <中文译文>", file=sys.stderr)
            return 2
        ok, msg = _set_one(c, sys.argv[1], sys.argv[2])
        c.commit()
        print(("" if ok else "⚠️ ") + msg, file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 2
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
