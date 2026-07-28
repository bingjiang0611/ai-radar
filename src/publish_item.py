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
DIST_IMG = ROOT / "dist" / "img"
KIND_TO_CATEGORY = {
    "article": "文章",
    "video": "视频",
    "podcast": "播客",
}
_X_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]{1,20}/status(?:es)?/\d+")
_MD_IMG = re.compile(r"!\[[^\]]*]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_IMG_SRC = re.compile(r"""(?i)<img[^>]+src=["']([^"']+)["']""")


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


def _tweet_meta_with_cover(row, cover):
    if not cover:
        return ""
    if not cover.startswith(("/img/", "http://", "https://")):
        raise ValueError("--cover 必须是 /img/... 或 http(s) 图片 URL")
    if cover.startswith("/img/") and not (DIST_IMG / cover.removeprefix("/img/")).exists():
        raise ValueError(f"--cover 指向的站内图片不存在: {cover}")
    try:
        meta = json.loads((row["tweet_meta"] if row else "") or "{}")
    except json.JSONDecodeError:
        meta = {}
    meta["cover"] = cover
    return json.dumps(meta, ensure_ascii=False, sort_keys=True)


def _row_cover(row):
    if not row:
        return ""
    try:
        return (json.loads(row["tweet_meta"] or "{}").get("cover") or "").strip()
    except json.JSONDecodeError:
        return ""


def _local_cover_exists(src):
    src = (src or "").strip()
    return bool(src.startswith("/img/") and (DIST_IMG / src.removeprefix("/img/")).exists())


def _has_embedded_cover(*blobs):
    for blob in blobs:
        for m in _MD_IMG.finditer(blob or ""):
            if _local_cover_exists((m.group(1) or "").strip("<>")):
                return True
        for m in _IMG_SRC.finditer(blob or ""):
            if _local_cover_exists(m.group(1) or ""):
                return True
    return False


def _validate_x_video_cover(args, row, translation_md, summary_md, content_md):
    if args.kind != "video" or not _X_STATUS_RE.match(args.url or ""):
        return
    if args.cover:
        if not args.cover.startswith("/img/"):
            raise ValueError("X 视频封面必须先落到 dist/img/，然后用 --cover /img/... 发布")
        _tweet_meta_with_cover(row, args.cover)
        return
    if _local_cover_exists(_row_cover(row)):
        return
    row_blobs = []
    if row:
        row_blobs = [row["translation_md"] or "", row["summary_md"] or "", row["content_html"] or ""]
    if _has_embedded_cover(translation_md, summary_md, content_md, *row_blobs):
        return
    raise ValueError("X 视频必须提供真实封面：先从 tweet-result 的 video.poster 下载到 dist/img/，再传 --cover /img/...")


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
        _validate_x_video_cover(args, row, translation_md, summary_md, content_md)
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
        if args.cover:
            updates["tweet_meta"] = _tweet_meta_with_cover(row, args.cover)

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
    detail_text = detail.read_text(encoding="utf-8", errors="replace")
    card = re.search(
        rf'<a\b[^>]*href="/item/{re.escape(item_hash)}\.html#[^"]+"[\s\S]*?</a>',
        text,
    )
    if card and "twitter-tweet" in detail_text and "has-img" not in card.group(0):
        raise RuntimeError("X 视频首页卡片缺封面: 渲染成了 poster fallback")


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
    p.add_argument("--cover", default="", help="可选：卡片封面 URL；支持 /img/... 或 http(s)")
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
