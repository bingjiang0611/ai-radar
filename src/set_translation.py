"""给挑中的条目上传中文全文翻译(存进 items.translation_md)。

用法:
    python3 src/set_translation.py <item_hash 或 /item/<hash>.html 或原 URL> <译文.md 文件>

译文是 markdown(段落/小标题/**加粗**/列表/引用)。之后 `python3 src/run.py --render-only`,
该条目详情页「中文翻译」tab 会用 md_to_html 渲染出译文全文(取代诚实空态)。
清空翻译:第二个参数传一个空文件(或内容为空)。

约定(见 CLAUDE.md「翻译」边界):全文翻译只给人工挑选的条目;标题/摘要中译走 translate.py。
译文只译正文,剔除原站页面 chrome(版权/作者 bio/相关文章列表等)。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import _conn, init_db  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("用法: set_translation.py <item_hash 或 URL> <译文.md 文件>", file=sys.stderr)
        return 2
    key, md_path = sys.argv[1], sys.argv[2]
    md = Path(md_path).read_text(encoding="utf-8").strip()
    c = _conn()
    init_db(c)
    m = re.search(r"[0-9a-f]{16}", key)  # 16 位 hash(可能裹在 /item/<hash>.html 里)
    row = (c.execute("SELECT hash, title FROM items WHERE hash=?", (m.group(0),)).fetchone() if m
           else c.execute("SELECT hash, title FROM items WHERE url=?", (key,)).fetchone())
    if not row:
        print(f"找不到条目: {key}", file=sys.stderr)
        c.close()
        return 2
    c.execute("UPDATE items SET translation_md=?, status=? WHERE hash=?",
              (md, "translated" if md else "new", row["hash"]))
    c.commit()
    c.close()
    print(f"已{'上传译文' if md else '清空译文'}({len(md)} 字):{row['title'][:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
