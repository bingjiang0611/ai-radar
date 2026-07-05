"""抓 X(Twitter)列表 → AI 关键词过滤 → 写库。

复用本地已认证的 `twitter` CLI(twitter-cli,headless cookie;由用户在 x-operator 里装好/登录)。
**为什么必须在会话里跑**:twitter-cli 绑本地登录态,塞不进无人值守 cron(同 browser 源)。
ai-radar 不调 x-operator 的脚本,只调 `twitter` 这个二进制(同 gh/yt-dlp 级别)。

用法:
    python3 src/fetch_x.py <source_id>   # source 须 parser=browser、fetch=twitter-cli、url=x.com/i/lists/<id>

列表里常混非 AI 推文 → 用 AI 关键词过滤,只留命中的(和资讯源去噪一致)。
"""

import html
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import which

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                                             # noqa: E402
from store import insert_items, url_hash, _conn, init_db    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_TCO = re.compile(r"https?://t\.co/\S+")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _tweet_text(t):
    """推文正文清洗。Twitter 把所有链接缩成 t.co。**绝不删 t.co**——media / quotedTweet 都无法可靠区分
    "作者分享的链接"(如下载地址)与"自动追加的引用/媒体短链"(实测 @oran_ge 既有 media 又有 quotedTweet,
    但末尾 t.co 是下载链;一刀切删/按 media 删/按 quote 删都会误删)。代价是引用推偶尔残留一个 t.co(可接受),
    但绝不丢链接。策略:① unescape(API 文本是 HTML 转义的)+ 折行;② t.co 用 `urls`(展开地址,按出现顺序)
    替换,无展开则保留 t.co(点击仍跳原链)。"""
    text = html.unescape(t.get("text", "") or "").replace("\n", " ")
    expanded = [u for u in (t.get("urls") or []) if isinstance(u, str) and u]
    idx = [0]

    def repl(m):
        if idx[0] < len(expanded):
            u = expanded[idx[0]]; idx[0] += 1; return u
        return m.group(0)  # 没有展开地址 → 保留 t.co(点击仍跳原链)

    return re.sub(r"\s+", " ", _TCO.sub(repl, text)).strip()


def is_reply(t):
    """回复帖:正文以 @ 开头(twitter-cli 无 isReply 字段,用此启发式)。列表里的回复不收。"""
    return (t.get("text", "") or "").lstrip().startswith("@")

SINCE_HOURS = 24   # 只收最近 24 小时的推文(可被源里 window_hours 覆盖)
FETCH_N = _env_int("AI_RADAR_FETCH_N", 200)  # 最活跃列表 24h 超 200 条时可临时调大
SKIP_QUOTE_DETAIL = os.environ.get("AI_RADAR_SKIP_QUOTE_DETAIL", "").lower() in {"1", "true", "yes"}
SKIP_IMAGES = os.environ.get("AI_RADAR_SKIP_IMAGES", "").lower() in {"1", "true", "yes"}
QUOTE_TIMEOUT = _env_int("AI_RADAR_QUOTE_TIMEOUT", 30)
QUOTE_BUDGET = _env_float("AI_RADAR_QUOTE_BUDGET", 60)
IMAGE_TIMEOUT = _env_int("AI_RADAR_X_IMAGE_TIMEOUT", 8)
IMAGE_MAX_TIME = _env_int("AI_RADAR_X_IMAGE_MAX_TIME", 6)
IMAGE_BUDGET = _env_float("AI_RADAR_X_IMAGE_BUDGET", 90)
_QUOTE_DEADLINE = None
_IMAGE_DEADLINE = None
_IMG_CACHE = {}
_IMG_STATS = {"attempt": 0, "ok": 0, "fail": 0, "budget_skip": 0, "cache": 0}
_QUOTE_STATS = {"attempt": 0, "ok": 0, "budget_skip": 0}

# 英文按词边界(避免 "ai" 命中 "said"),中文按子串。
_AI_EN = re.compile(
    r"\b(ai|agi|llm|llms|gpt|rag|mcp|ml|claude|anthropic|openai|chatgpt|gemini|llama|"
    r"mistral|deepseek|qwen|kimi|grok|copilot|cursor|windsurf|agent|agentic|transformer|"
    r"diffusion|prompt|fine-?tune|inference|neural|model|models|benchmark|reasoning)\b",
    re.I,
)
_AI_ZH = ("大模型", "智能体", "人工智能", "模型", "深度学习", "提示词")


def is_ai(text):
    return bool(_AI_EN.search(text)) or any(k in text for k in _AI_ZH)


# 抽奖/转发求评等运营噪音——常含 AI 词(抽 N 个人送书、Grok 抽转发名单)蒙混过 is_ai,单独滤掉。
# twitter-cli 不暴露回复/会话元数据,无法判自串回复,故用抽奖语义信号兜这类。
_NOISE = re.compile(
    r"抽奖|中奖|开奖|获奖|抽中|giveaway|红包|赠书|送书"
    r"|转发.{0,4}名单|(转发|评论|引用|点赞).{0,4}抽|补.{0,3}评论|抽\s*\d{1,4}\s*(个|名|人|位)",
    re.I,
)


def is_noise(text):
    """抽奖/转发求互动类运营噪音(非 AI 实质内容)→ 不收。"""
    return bool(_NOISE.search(text or ""))


def first_json(text):
    i = 0
    while i < len(text) and text[i] not in "[{":
        i += 1
    if i >= len(text):
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[i:])
        return obj
    except json.JSONDecodeError:
        return None


def twitter_cmd():
    """定位 twitter-cli。Codex shell 的 PATH 可能没有 ~/.local/bin。"""
    return os.environ.get("TWITTER_CLI") or which("twitter") or str(Path.home() / ".local/bin/twitter")


def fetch_list(list_id, n):
    r = subprocess.run(
        [twitter_cmd(), "list", list_id, "-n", str(n), "--json"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=300,
    )
    obj = first_json(r.stdout)
    if isinstance(obj, dict):
        return obj.get("data") or obj.get("tweets") or []
    return obj if isinstance(obj, list) else []


def _budget_left(deadline):
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def _image_deadline():
    global _IMAGE_DEADLINE
    if IMAGE_BUDGET <= 0:
        return None
    if _IMAGE_DEADLINE is None:
        _IMAGE_DEADLINE = time.monotonic() + IMAGE_BUDGET
    return _IMAGE_DEADLINE


def _quote_deadline():
    global _QUOTE_DEADLINE
    if QUOTE_BUDGET <= 0:
        return None
    if _QUOTE_DEADLINE is None:
        _QUOTE_DEADLINE = time.monotonic() + QUOTE_BUDGET
    return _QUOTE_DEADLINE


def _download_tweet_image(url):
    """X 媒体小图下载：运行内缓存 + 总预算，避免重复头像把整轮抓取拖死。"""
    if not url or SKIP_IMAGES:
        return ""
    if url in _IMG_CACHE:
        _IMG_STATS["cache"] += 1
        return _IMG_CACHE[url]
    left = _budget_left(_image_deadline())
    if left is not None and left < 2:
        _IMG_STATS["budget_skip"] += 1
        return ""
    timeout = IMAGE_TIMEOUT if left is None else min(IMAGE_TIMEOUT, max(2, int(left)))
    max_time = min(IMAGE_MAX_TIME, max(1, timeout - 1))
    _IMG_STATS["attempt"] += 1
    local = content._download_image(url, max_time=max_time, timeout=timeout) or ""
    _IMG_CACHE[url] = local
    _IMG_STATS["ok" if local else "fail"] += 1
    return local


def _quote_timeout_left():
    left = _budget_left(_quote_deadline())
    if left is not None and left < 2:
        _QUOTE_STATS["budget_skip"] += 1
        return 0
    return QUOTE_TIMEOUT if left is None else min(QUOTE_TIMEOUT, max(2, int(left)))


def _fetch_quote_detail(qid):
    """二次抓被引用推:父推的 quotedTweet 只给 {id,text(截断),author},**不给配图**。
    用被引推自己的 id 再抓一次,取全文 + 配图(下载进站)+ 引用作者头像。
    被引推已删/受保护/抓取失败 → 返回 None,调用方退回纯文本引用(不崩、不清空已有引用)。"""
    if not qid or SKIP_QUOTE_DETAIL:
        return None
    timeout = _quote_timeout_left()
    if not timeout:
        return None
    try:
        _QUOTE_STATS["attempt"] += 1
        r = subprocess.run(
            [twitter_cmd(), "tweet", str(qid), "--json"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        if r.returncode != 0:
            return None
        obj = first_json(r.stdout)
        data = obj.get("data") if isinstance(obj, dict) else None
        t = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not isinstance(t, dict):
            return None
        a = t.get("author") or {}
        photos = [m.get("url", "") for m in (t.get("media") or [])
                  if isinstance(m, dict) and m.get("type") == "photo" and m.get("url")]
        _QUOTE_STATS["ok"] += 1
        return {
            "_checked": True,
            "text": re.sub(r"\s+", " ", html.unescape(t.get("text", "") or "")).strip(),
            "image": _download_tweet_image(photos[0]) if photos else "",
            "avatar": _download_tweet_image(a.get("profileImageUrl")) if a.get("profileImageUrl") else "",
        }
    except subprocess.TimeoutExpired:
        return None
    except Exception:  # noqa: BLE001 — 二次抓失败不致命,退回纯文本引用
        return None


def tweet_url(t):
    a = t.get("author") or {}
    handle = a.get("screenName", "") if isinstance(a, dict) else ""
    tid = str(t.get("id", ""))
    return f"https://x.com/{handle}/status/{tid}" if handle and tid else ""


def to_item(t):
    a = t.get("author") or {}
    handle = a.get("screenName", "") if isinstance(a, dict) else ""
    tid = str(t.get("id", ""))
    text = _tweet_text(t)  # 清洗:删末尾媒体/引用 t.co,展开/保留其余链接(不丢作者分享的链)
    if not handle or not tid:
        return None
    rb = ""
    if t.get("isRetweet"):
        rbv = t.get("retweetedBy")
        rb = rbv if isinstance(rbv, str) else (rbv.get("screenName", "") if isinstance(rbv, dict) else "")
        prefix = f"@{rb} 🔁 @{handle}" if rb else f"@{handle}"
    else:
        prefix = f"@{handle}"
    # 原推带图 → 下载进站(content.process:nh3 + 图片本地化),卡片里展示
    photos = [m.get("url", "") for m in (t.get("media") or [])
              if isinstance(m, dict) and m.get("type") == "photo" and m.get("url")]
    local_photos = [_download_tweet_image(u) for u in photos[:4]]
    imgs = "".join(f'<img src="{u}">' for u in local_photos if u)
    # tweet_meta:作者头像(进站)+ 名称/认证 + 转发者 + 被引用推(quotedTweet),供卡片还原推特视觉
    av = _download_tweet_image(a.get("profileImageUrl")) if isinstance(a, dict) and a.get("profileImageUrl") else ""
    q = t.get("quotedTweet")
    quote = None
    if isinstance(q, dict) and (q.get("text") or (q.get("author") or {}).get("screenName")):
        qa = q.get("author") or {}
        detail = _fetch_quote_detail(q.get("id"))  # 二次抓:全文 + 配图 + 引用作者头像(父推不给)
        qtext = (detail or {}).get("text") or html.unescape(q.get("text", "") or "")  # 优先全文,退回父推截断文本
        quote = {"name": (qa.get("name") or "").strip(), "handle": qa.get("screenName", ""),
                 "text": re.sub(r"\s+", " ", _TCO.sub("", qtext)).strip()[:500],
                 "text_zh": "",  # 非中文引用的中译:Claude 会话回填(同 title_zh,见 ai-radar-scrape skill)
                 "image": (detail or {}).get("image", ""), "avatar": (detail or {}).get("avatar", ""),
                 "detail_checked": bool((detail or {}).get("_checked"))}
    meta = {"name": (a.get("name") or "").strip() if isinstance(a, dict) else "", "handle": handle,
            "avatar": av or "", "verified": bool(isinstance(a, dict) and a.get("verified")),
            "rt": rb, "quote": quote}
    return {
        "title": (f"{prefix}：{text}" if text else prefix)[:500],  # 推文全文,时间流标题行不 clamp 完整展示
        "url": f"https://x.com/{handle}/status/{tid}",
        "summary": "",
        "published_at": t.get("createdAtISO") or t.get("createdAt") or "",
        "content_html": content.process(imgs) if imgs else "",
        "tweet_meta": json.dumps(meta, ensure_ascii=False),
    }


def _json_obj(text):
    try:
        obj = json.loads(text or "{}")
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _media_backfill_needed(row, t):
    """已入库推文若缺头像/配图/quote 详情，允许本轮用列表 payload 增量补齐。"""
    tm = _json_obj(row["tweet_meta"])
    a = t.get("author") or {}
    photos = [m for m in (t.get("media") or []) if isinstance(m, dict) and m.get("type") == "photo" and m.get("url")]
    if isinstance(a, dict) and a.get("profileImageUrl") and not tm.get("avatar"):
        return True
    if photos and "<img" not in (row["content_html"] or ""):
        return True
    q = t.get("quotedTweet")
    if not isinstance(q, dict):
        return False
    old_q = tm.get("quote") or {}
    qa = q.get("author") or {}
    if not old_q:
        return True
    if isinstance(qa, dict) and qa.get("profileImageUrl") and not old_q.get("avatar"):
        return True
    if not SKIP_QUOTE_DETAIL and not old_q.get("detail_checked"):
        return True
    return False


def _merge_existing_media(row, item):
    """只补媒体字段，保留已有标题、中译和已有可用媒体。返回 (content_html, tweet_meta, changed)。"""
    old_meta = _json_obj(row["tweet_meta"])
    new_meta = _json_obj(item.get("tweet_meta", ""))
    if old_meta.get("avatar") and not new_meta.get("avatar"):
        new_meta["avatar"] = old_meta["avatar"]
    old_q = old_meta.get("quote") or {}
    new_q = new_meta.get("quote") or {}
    if old_q and new_q:
        for k in ("text", "image", "avatar", "text_zh"):
            if old_q.get(k) and not new_q.get(k):
                new_q[k] = old_q[k]
        if old_q.get("text_zh"):
            new_q["text_zh"] = old_q["text_zh"]
        if old_q.get("detail_checked"):
            new_q["detail_checked"] = old_q["detail_checked"] or new_q.get("detail_checked")
        new_meta["quote"] = new_q
    elif old_q and not new_q:
        new_meta["quote"] = old_q
    content_html = item.get("content_html") or row["content_html"] or ""
    tweet_meta = json.dumps(new_meta, ensure_ascii=False)
    changed = content_html != (row["content_html"] or "") or tweet_meta != (row["tweet_meta"] or "")
    return content_html, tweet_meta, changed


def _update_existing_media(c, hash_val, item):
    row = c.execute("SELECT hash, content_html, tweet_meta FROM items WHERE hash=?", (hash_val,)).fetchone()
    if not row:
        return False
    content_html, tweet_meta, changed = _merge_existing_media(row, item)
    if changed:
        c.execute("UPDATE items SET content_html=?, tweet_meta=? WHERE hash=?", (content_html, tweet_meta, hash_val))
    return changed


def _media_suffix(backfilled):
    parts = []
    if _IMG_STATS["attempt"] or _IMG_STATS["budget_skip"]:
        parts.append(
            f"图片 {_IMG_STATS['ok']}/{_IMG_STATS['attempt']}"
            + (f",缓存 {_IMG_STATS['cache']}" if _IMG_STATS["cache"] else "")
            + (f",预算跳过 {_IMG_STATS['budget_skip']}" if _IMG_STATS["budget_skip"] else "")
        )
    if _QUOTE_STATS["attempt"] or _QUOTE_STATS["budget_skip"]:
        parts.append(
            f"quote详情 {_QUOTE_STATS['ok']}/{_QUOTE_STATS['attempt']}"
            + (f",预算跳过 {_QUOTE_STATS['budget_skip']}" if _QUOTE_STATS["budget_skip"] else "")
        )
    if backfilled:
        parts.append(f"媒体回填 {backfilled}")
    return ("；" + "；".join(parts)) if parts else ""


def main():
    if len(sys.argv) < 2:
        print("用法: python3 src/fetch_x.py <source_id>", file=sys.stderr)
        return 2
    sid = sys.argv[1]
    srcs = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]
    src = next((s for s in srcs if s["id"] == sid), None)
    if src is None:
        print(f"未知 source_id: {sid}", file=sys.stderr)
        return 2
    m = re.search(r"/lists/(\d+)", src["url"])
    if not m:
        print(f"源 url 不是 X 列表(应含 /lists/<id>):{src['url']}", file=sys.stderr)
        return 2
    list_id = m.group(1)
    hours = src.get("window_hours", SINCE_HOURS)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    def in_window(t):
        ts = t.get("createdAtISO") or t.get("createdAt") or ""
        try:
            return datetime.fromisoformat(ts) >= cutoff
        except ValueError:
            return False  # 解析不出时间 → 不能确认在窗内,排除

    raw = fetch_list(list_id, FETCH_N)
    recent = [t for t in raw if in_window(t)]          # 先卡 24h 时间窗
    recent = [t for t in recent if not is_reply(t)]    # 去掉回复帖(正文以 @ 开头)
    recent = [t for t in recent if not is_noise(t.get("text", "") or "")]  # 去掉抽奖/转发求互动噪音
    ai = [t for t in recent if is_ai(t.get("text", "") or "")]
    items, seen, backfilled = [], set(), 0
    c = _conn()
    init_db(c)
    try:
        for t in ai:
            url = tweet_url(t)
            if not url or url in seen:
                continue
            seen.add(url)
            h = url_hash(url)
            row = c.execute("SELECT hash, content_html, tweet_meta FROM items WHERE hash=?", (h,)).fetchone()
            if row:
                if _media_backfill_needed(row, t):
                    it = to_item(t)
                    if it and _update_existing_media(c, h, it):
                        backfilled += 1
                continue
            it = to_item(t)
            if not it:
                continue
            items.append(it)  # content_html 由 to_item 设(带图则为本地化 <img>,否则空)
        n = insert_items(items, src, c)
        c.commit()
    finally:
        c.close()
    # 最旧一条仍落在窗口内 → FETCH_N 把时间窗截断了,可能漏掉更早但仍在 24h 内的推
    capped = bool(raw) and in_window(raw[-1])
    print(f"{src['source_label']}: 列表 {list_id} 抓 {len(raw)} 条,{hours}h 内 {len(recent)},"
          f"AI 命中 {len(ai)},新增 {n}"
          + _media_suffix(backfilled)
          + (f"  ⚠️ 最旧一条仍在 {hours}h 内,-n {FETCH_N} 可能截断时间窗有遗漏(调大 FETCH_N)" if capped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
