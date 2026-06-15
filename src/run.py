"""ai-radar 入口：抓全部启用源 → 去重写库 → 渲染 dist/。

用法:
    python3 src/run.py              抓 + 渲染
    python3 src/run.py --no-render  只抓不渲染
"""

import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                  # noqa: E402
from fetch import resolve_url, is_paywalled    # noqa: E402
from parsers import PARSERS      # noqa: E402
from store import init_db, insert_items, all_items, all_hashes, url_hash, purge_old, _parse_dt  # noqa: E402
from render import render_site   # noqa: E402

RETENTION_DAYS = 7   # 只保留近 7 天内容（控站点/图片体积）
_SHORT_CONTENT = 400  # feed 正文纯文本短于此 → 视为只给摘要,用 Jina 抓全文补全(非视频/非 link 源)
_MAX_WORKERS = 8     # 受控并发抓源/补正文（curl 子进程 I/O 密集，线程足够）；SQLite 写仍只在主线程

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "config" / "sources.json"


def load_sources():
    return json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]


def _fetch_source(s):
    """抓+解析单源（纯网络，无 SQLite）。未知 parser / 请求失败 → 抛异常，由上层汇总为 ✗。"""
    parser = PARSERS.get(s["parser"])
    if parser is None:
        raise RuntimeError(f"未知 parser '{s['parser']}'")
    return parser(dict(s, url=resolve_url(s["url"])))  # 填 {week}/{date} 占位


def _process_content(s, r):
    """单条新条目的内容处理（清洗 + 图片进站 + 短摘要 Jina/直连补全文）。纯网络+CPU、无 SQLite，可在线程内跑。
    就地写 r["content_html"]；任何异常都退回处理 feed 正文，不让单条拖垮整轮。"""
    feed_c = r.get("content", "") or ""
    try:
        if s.get("open", "detail") == "link":
            r["content_html"] = ""  # 播客等直跳原链,不要正文
        elif s["category"] != "视频" and len(re.sub(r"<[^>]+>", "", feed_c)) < _SHORT_CONTENT:
            full = content.fetch_article_html(r["url"])  # feed 只给摘要 → Jina/直连抓全文补全
            r["content_html"] = content.process(full) if full else content.process(feed_c)
        else:
            r["content_html"] = content.process(feed_c)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  正文处理失败 {r.get('url','')[:50]}: {e}", file=sys.stderr)
        r["content_html"] = content.process(feed_c)
    return r


def fetch_all():
    init_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)  # 发布超 7 天的不收
    sources = [s for s in load_sources() if s.get("enabled") and s["parser"] != "browser"]
    existing = all_hashes()  # 主线程一次性预读,线程内只判存

    # Phase 1：并发抓+解析（只网络）。失败/0 条分开汇总——请求失败 ✗，抓到内容但 0 条仍算正常。
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        submitted = [(s, ex.submit(_fetch_source, s)) for s in sources]
    fetched, failed = [], {}
    for s, fut in submitted:
        try:
            fetched.append((s, fut.result()))
        except Exception as e:  # noqa: BLE001 — 单源失败不中断整轮
            failed[s["source_label"]] = str(e)

    # 主线程筛新条目（判存 + 近 7 天 + 同轮去重）
    pending = []
    for s, rows in fetched:
        for r in rows:
            if is_paywalled(r["url"]):
                continue  # 硬付费墙域名:正文拿不到,只会是 stub → 不收
            h = url_hash(r["url"])
            if h in existing:
                continue
            pub = _parse_dt(r.get("published_at"))
            if pub and pub < cutoff:
                continue
            existing.add(h)  # 防同轮内两源给同一 URL 重复处理
            pending.append((s, r))

    # Phase 2：并发处理新条目正文（Jina/直连 + 图片下载，纯网络，无 SQLite）
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        list(ex.map(lambda sr: _process_content(*sr), pending))

    # Phase 3：串行写库（主线程）+ 按源报告
    by_src = defaultdict(list)
    for s, r in pending:
        by_src[s["id"]].append(r)
    total_new = 0
    for s, rows in fetched:
        n = insert_items(by_src.get(s["id"], []), s)
        total_new += n
        print(f"  • {s['source_label']}: 抓到 {len(rows)} 条, 新增 {n}")
    for label, err in failed.items():
        print(f"  ✗ {label}: {err}", file=sys.stderr)
    if failed:
        print(f"  ⚠️  {len(failed)}/{len(sources)} 源请求失败（上方 ✗）；其余正常")
    return total_new


def main():
    # --render-only：跳过抓取，只做 retention + 渲染（ai-radar-scrape skill 抓完后调用）
    if "--render-only" not in sys.argv:
        print("🔍 抓取中…")
        print(f"✨ 本次新增 {fetch_all()} 条")

    purged = purge_old(RETENTION_DAYS)
    items = all_items()
    removed_imgs = content.gc_images([i["content_html"] for i in items])
    if purged or removed_imgs:
        print(f"🧹 retention：清掉 {purged} 条过期条目、{removed_imgs} 张无引用图片")

    if "--no-render" not in sys.argv:
        srcs = load_sources()
        interactions = {s["id"]: s.get("open", "detail") for s in srcs}
        descriptions = {s["source_label"]: s.get("description", "") for s in srcs}
        icons = {s["source_label"]: content.fetch_favicon(s["url"]) for s in srcs if s.get("enabled")}
        # 入口 B（parser=browser，须 Claude 会话抓取）标抓取方式;入口 A（Python 自动抓）留空不标
        methods = {s["source_label"]: ("" if s["parser"] != "browser"
                                       else {"jina": "Jina", "twitter-cli": "twitter-cli"}.get(s.get("fetch"), "browser-use"))
                   for s in srcs}
        out = render_site(items, interactions, descriptions, icons, methods=methods)
        print(f"🖼  已渲染 → {out}（{len(items)} 条，头像 {sum(1 for v in icons.values() if v)} 个）")


if __name__ == "__main__":
    main()
