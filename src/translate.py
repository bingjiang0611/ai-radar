"""标题/摘要中译——Claude 会话内翻译，无 API、无 key。

用法:
    python3 src/translate.py export [--limit N] [--out file]   # 导出未译条目 JSON
    python3 src/translate.py import <file>                     # 按 hash 写回 title_zh/summary_zh

「未译」= title_zh 为空且标题不含中文（已是中文的源如播客自动跳过）。
译文规范:技术词/专有名词保留英文(Transformer/LLM/RAG/Agent/MCP/Claude/GPT/OpenAI 等),
标题简洁不书面化。import 的文件为 [{"hash","title_zh","summary_zh"}]。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import _conn, init_db  # noqa: E402

_CJK = re.compile(r"[一-鿿]")


def export(limit=None):
    c = _conn()
    init_db(c)
    rows = c.execute(
        "SELECT hash, title, summary FROM items WHERE COALESCE(title_zh,'')='' ORDER BY fetched_at DESC, id DESC"
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        title = r["title"] or ""
        if _CJK.search(title):  # 已是中文，跳过
            continue
        out.append({"hash": r["hash"], "title": title, "summary": (r["summary"] or "")[:200]})
        if limit and len(out) >= limit:
            break
    return out


def import_(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    c = _conn()
    init_db(c)
    n = 0
    for d in data:
        h = d.get("hash")
        if not h:
            continue
        cur = c.execute(
            "UPDATE items SET title_zh=?, summary_zh=? WHERE hash=?",
            (d.get("title_zh", "") or "", d.get("summary_zh", "") or "", h),
        )
        n += cur.rowcount
    c.commit()
    c.close()
    return n


def main():
    args = sys.argv[1:]
    if args and args[0] == "export":
        limit = None
        if "--limit" in args:
            limit = int(args[args.index("--limit") + 1])
        rows = export(limit)
        text = json.dumps(rows, ensure_ascii=False, indent=2)
        if "--out" in args:
            Path(args[args.index("--out") + 1]).write_text(text, encoding="utf-8")
            print(f"导出 {len(rows)} 条待译 → {args[args.index('--out') + 1]}", file=sys.stderr)
        else:
            print(text)
        return 0
    if len(args) >= 2 and args[0] == "import":
        n = import_(args[1])
        print(f"写回译文 {n} 条")
        return 0
    print("用法: translate.py export [--limit N] [--out file] | import <file>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
