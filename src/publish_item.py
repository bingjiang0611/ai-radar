"""发布用户精选内容：建/找条目 → 挂译文/总结/B站链接 → 渲染 → 可选部署。

用法:
    .venv/bin/python src/publish_item.py --url URL --title "标题" --kind article --translation /tmp/zh.md
    .venv/bin/python src/publish_item.py --url URL --title "标题" --kind video --summary /tmp/sum.md
    .venv/bin/python src/publish_item.py --url URL --title "标题" --kind video --bili https://www.bilibili.com/video/BV...
    .venv/bin/python src/publish_item.py ... --deploy
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content  # noqa: E402
import run  # noqa: E402
from store import _conn, init_db, insert_items, url_hash  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KIND_TO_CATEGORY = {
    "article": "文章",
    "video": "视频",
    "podcast": "播客",
}


def _read_md(path):
    if not path:
        return ""
    md = Path(path).read_text(encoding="utf-8")
    md = re.sub(r"\A---\n.*?\n---\n", "", md, count=1, flags=re.S).strip()
    if "![[" in md:
        raise ValueError("Markdown 里还有 Obsidian ![[...]] 图片嵌入；先转成 ![](/img/...) 或删掉再发布")
    return md


def _title_from_md(md):
    for line in (md or "").splitlines():
        m = re.match(r"\s*#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def _row_for_url(c, url):
    return c.execute("SELECT * FROM items WHERE hash=?", (url_hash(url),)).fetchone()


def _stored_bili_url(bili):
    if not bili:
        return ""
    bv = re.search(r"BV[0-9A-Za-z]+", bili)
    if not bv or "cid=" in bili:
        return bili
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", "Mozilla/5.0", "--max-time", "20",
             f"https://api.bilibili.com/x/web-interface/view?bvid={bv.group(0)}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=25,
        )
        cid = str((json.loads(r.stdout).get("data") or {}).get("cid") or "")
    except Exception:  # noqa: BLE001
        cid = ""
    return bili + (("&" if "?" in bili else "?") + "cid=" + cid if cid else "")


def publish(args, conn=None):
    translation_md = _read_md(args.translation)
    summary_md = _read_md(args.summary)
    content_md = _read_md(args.content)
    bili = _stored_bili_url(args.bili or "")
    if not (translation_md or summary_md or bili):
        raise ValueError("至少提供一个内容载荷：--translation、--summary 或 --bili")

    c = conn or _conn()
    init_db(c)
    try:
        row = _row_for_url(c, args.url)
        category = KIND_TO_CATEGORY[args.kind]
        title = args.title or args.title_zh or _title_from_md(translation_md) or _title_from_md(summary_md)
        if row is None:
            if not title:
                raise ValueError("新条目需要 --title；或在 markdown 第一行提供 # 标题")
            source = {"id": args.source_id, "source_label": args.source_label, "category": category}
            item = {
                "title": title,
                "url": args.url,
                "summary": args.summary_text or "",
                "content_html": content.process(content.md_to_html(content_md)) if content_md else "",
            }
            insert_items([item], source, c)
            row = _row_for_url(c, args.url)
            if row is None:
                raise RuntimeError("条目写入失败")

        updates = {
            "source_id": args.source_id,
            "source_label": args.source_label,
            "category": category,
        }
        if title:
            updates["title"] = title
        if args.title_zh:
            updates["title_zh"] = args.title_zh
        if args.summary_text:
            updates["summary_zh" if args.summary_zh else "summary"] = args.summary_text
        if translation_md:
            updates["translation_md"] = translation_md
            updates["status"] = "translated"
        if summary_md:
            updates["summary_md"] = summary_md
        if bili:
            updates["video_url"] = bili
        if content_md:
            updates["content_html"] = content.process(content.md_to_html(content_md))

        sets = ", ".join(f"{k}=?" for k in updates)
        c.execute(f"UPDATE items SET {sets} WHERE hash=?", [*updates.values(), row["hash"]])
        c.commit()
        final = c.execute("SELECT hash,title FROM items WHERE hash=?", (row["hash"],)).fetchone()
        print(f"已发布精选内容: {final['title'][:80]} ({final['hash']})")
        return final["hash"]
    finally:
        if conn is None:
            c.close()


def validate_dist(item_hash):
    idx = ROOT / "dist" / "index.html"
    detail = ROOT / "dist" / "item" / f"{item_hash}.html"
    if not idx.exists() or idx.stat().st_size == 0:
        raise RuntimeError("dist/index.html 为空或不存在")
    text = idx.read_text(encoding="utf-8", errors="replace")
    bad = re.search(r"Traceback|ModuleNotFoundError|SyntaxError|Unhandled|error:", text, re.I)
    if bad:
        raise RuntimeError(f"dist/index.html 含明显错误文本: {bad.group(0)}")
    if f"/item/{item_hash}.html" not in text and item_hash not in text:
        raise RuntimeError("首页没有出现本次发布条目")
    if not detail.exists() or detail.stat().st_size == 0:
        raise RuntimeError(f"详情页未生成: dist/item/{item_hash}.html")


def deploy():
    subprocess.run(
        ["npx", "--yes", "wrangler", "pages", "deploy", "./dist",
         "--project-name", "ai-radar", "--branch", "main"],
        cwd=ROOT,
        check=True,
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="发布用户精选内容到 ai-radar。")
    p.add_argument("--url", required=True, help="原文、YouTube、播客或视频 URL")
    p.add_argument("--title", default="", help="原标题或显示标题；新条目必填，除非 markdown 有 # 标题")
    p.add_argument("--title-zh", default="", help="中文标题；提供后页面优先显示它")
    p.add_argument("--kind", choices=sorted(KIND_TO_CATEGORY), required=True, help="内容类型")
    p.add_argument("--translation", help="文章全文中文翻译 markdown")
    p.add_argument("--summary", help="视频/播客/文章中文总结 markdown")
    p.add_argument("--bili", default="", help="B站译制视频 URL")
    p.add_argument("--content", help="可选：原文/简介 markdown，渲染到原文 tab")
    p.add_argument("--summary-text", default="", help="可选：卡片摘要")
    p.add_argument("--summary-zh", action="store_true", help="把 --summary-text 写入中文摘要字段")
    p.add_argument("--source-id", default="user-curated")
    p.add_argument("--source-label", default="用户精选")
    p.add_argument("--no-render", action="store_true", help="只写库，不渲染")
    p.add_argument("--deploy", action="store_true", help="渲染校验后部署到 Cloudflare Pages")
    args = p.parse_args(argv)
    if args.deploy and args.no_render:
        p.error("--deploy 需要渲染，不能和 --no-render 一起用")
    return args


def main(argv=None):
    try:
        args = parse_args(argv)
        item_hash = publish(args)
        if not args.no_render:
            run.render_current()
            validate_dist(item_hash)
        if args.deploy:
            deploy()
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"发布失败: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
