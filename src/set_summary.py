"""给挑中的条目(主要是视频)上传中文内容总结(存进 items.summary_md)。

用法:
    python3 src/set_summary.py <item_hash 或 /item/<hash>.html 或原 URL> <总结.md 文件>

总结是 markdown(看完视频/读完原文提炼的要点,段落/小标题/**加粗**/列表)。之后
`python3 src/run.py --render-only`,视频详情页会出现「总结」tab(有总结则默认打开),
用 md_to_html 渲染。清空总结:第二个参数传一个空文件。

与 set_translation.py(全文翻译,存 translation_md)互补:总结是提炼,翻译是逐句对照。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import _conn, init_db  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("用法: set_summary.py <item_hash 或 URL> <总结.md 文件>", file=sys.stderr)
        return 2
    key, md_path = sys.argv[1], sys.argv[2]
    md = Path(md_path).read_text(encoding="utf-8")
    md = re.sub(r"\A---\n.*?\n---\n", "", md, count=1, flags=re.S).strip()  # 剥 Obsidian/YAML frontmatter
    if "![[" in md:  # Obsidian 本地图嵌入 md_to_html 渲染不了 → 提示先转成 ![](/img/..) 或删
        print("⚠️  含 Obsidian ![[..]] 本地图嵌入,渲染不出。请先把图拷进 dist/img 改成 ![](/img/..) 或删除,再上传。", file=sys.stderr)
    c = _conn()
    init_db(c)
    m = re.search(r"[0-9a-f]{16}", key)  # 16 位 hash(可能裹在 /item/<hash>.html 里)
    row = (c.execute("SELECT hash, title FROM items WHERE hash=?", (m.group(0),)).fetchone() if m
           else c.execute("SELECT hash, title FROM items WHERE url=?", (key,)).fetchone())
    if not row:
        print(f"找不到条目: {key}", file=sys.stderr)
        c.close()
        return 2
    c.execute("UPDATE items SET summary_md=? WHERE hash=?", (md, row["hash"]))
    c.commit()
    c.close()
    print(f"已{'上传总结' if md else '清空总结'}({len(md)} 字):{row['title'][:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
