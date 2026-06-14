"""把 browser-use 抓到的条目写入库——由 ai-radar-scrape skill 调用。

用法:
    echo '[{"title":"...","url":"https://...","summary":"..."}]' | python3 src/ingest.py <source_id>

source_id 必须是 config/sources.json 里 parser=browser 的源。category/source_label/description
都从该源配置取；去重 + 内容处理（清洗+图片进站）复用主流水线逻辑。只插新条目。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                                          # noqa: E402
from store import insert_items, url_hash, hash_exists   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_sources():
    return json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 src/ingest.py <source_id>  （条目 JSON 从 stdin 传入）", file=sys.stderr)
        return 2
    sid = sys.argv[1]
    src = next((s for s in load_sources() if s["id"] == sid), None)
    if src is None:
        print(f"未知 source_id: {sid}", file=sys.stderr)
        return 2

    # 条目 JSON：优先从第 2 个参数指定的文件读，否则从 stdin（后台执行时 stdin 管道可能阻塞，推荐传文件）
    try:
        if len(sys.argv) >= 3:
            rows = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        else:
            rows = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"条目不是合法 JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(rows, list):
        print("条目应为数组", file=sys.stderr)
        return 2

    new = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("url") or not r.get("title"):
            continue
        if hash_exists(url_hash(r["url"])):
            continue
        r["content_html"] = content.process(r.get("content", "") or "")
        new.append(r)
    n = insert_items(new, src)
    print(f"{src['source_label']}: 收到 {len(rows)} 条, 新增 {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
