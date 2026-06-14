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
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                                          # noqa: E402
from store import insert_items, url_hash, hash_exists   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_TCO = re.compile(r"https?://t\.co/\S+")  # 推文末尾的媒体/引用短链——展示时去掉(噪音)


def _clean_text(text):
    # Twitter API 文本是 HTML 转义的(&gt;/&amp;/&#8217;)→ 先 unescape 再去 t.co,否则页面显示字面实体
    return _TCO.sub("", html.unescape(text or "").replace("\n", " ")).strip()


def is_reply(t):
    """回复帖:正文以 @ 开头(twitter-cli 无 isReply 字段,用此启发式)。列表里的回复不收。"""
    return (t.get("text", "") or "").lstrip().startswith("@")

SINCE_HOURS = 24   # 只收最近 24 小时的推文(可被源里 window_hours 覆盖)
FETCH_N = 200      # twitter-cli 单次抓取上限 ~200;最活跃列表 24h 超 200 条仍会截断(告警提示)

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


def fetch_list(list_id, n):
    r = subprocess.run(
        ["twitter", "list", list_id, "-n", str(n), "--json"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=300,
    )
    obj = first_json(r.stdout)
    if isinstance(obj, dict):
        return obj.get("data") or obj.get("tweets") or []
    return obj if isinstance(obj, list) else []


def to_item(t):
    a = t.get("author") or {}
    handle = a.get("screenName", "") if isinstance(a, dict) else ""
    tid = str(t.get("id", ""))
    text = _clean_text(t.get("text", ""))  # 去 t.co 链接 + 折行
    if not handle or not tid:
        return None
    if t.get("isRetweet"):
        rb = t.get("retweetedBy")
        rb = rb if isinstance(rb, str) else (rb.get("screenName", "") if isinstance(rb, dict) else "")
        prefix = f"@{rb} 🔁 @{handle}" if rb else f"@{handle}"
    else:
        prefix = f"@{handle}"
    # 原推带图 → 下载进站(content.process:nh3 + 图片本地化),卡片里展示
    photos = [m.get("url", "") for m in (t.get("media") or [])
              if isinstance(m, dict) and m.get("type") == "photo" and m.get("url")]
    imgs = "".join(f'<img src="{u}">' for u in photos[:4])
    return {
        "title": (f"{prefix}：{text}" if text else prefix)[:500],  # 推文全文,时间流标题行不 clamp 完整展示
        "url": f"https://x.com/{handle}/status/{tid}",
        "summary": "",
        "published_at": t.get("createdAtISO") or t.get("createdAt") or "",
        "content_html": content.process(imgs) if imgs else "",
    }


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
    recent = [t for t in recent if not is_reply(t)]    # 去掉回复帖
    ai = [t for t in recent if is_ai(t.get("text", "") or "")]
    items, seen = [], set()
    for t in ai:
        it = to_item(t)
        if not it or it["url"] in seen or hash_exists(url_hash(it["url"])):
            continue
        seen.add(it["url"])
        items.append(it)  # content_html 由 to_item 设(带图则为本地化 <img>,否则空)
    n = insert_items(items, src)
    # 最旧一条仍落在窗口内 → FETCH_N 把时间窗截断了,可能漏掉更早但仍在 24h 内的推
    capped = bool(raw) and in_window(raw[-1])
    print(f"{src['source_label']}: 列表 {list_id} 抓 {len(raw)} 条,{hours}h 内 {len(recent)},"
          f"AI 命中 {len(ai)},新增 {n}"
          + (f"  ⚠️ 最旧一条仍在 {hours}h 内,-n {FETCH_N} 可能截断时间窗有遗漏(调大 FETCH_N)" if capped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
