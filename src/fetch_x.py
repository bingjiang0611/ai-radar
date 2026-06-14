"""抓 X(Twitter)列表 → AI 关键词过滤 → 写库。

复用本地已认证的 `twitter` CLI(twitter-cli,headless cookie;由用户在 x-operator 里装好/登录)。
**为什么必须在会话里跑**:twitter-cli 绑本地登录态,塞不进无人值守 cron(同 browser 源)。
ai-radar 不调 x-operator 的脚本,只调 `twitter` 这个二进制(同 gh/yt-dlp 级别)。

用法:
    python3 src/fetch_x.py <source_id>   # source 须 parser=browser、fetch=twitter-cli、url=x.com/i/lists/<id>

列表里常混非 AI 推文 → 用 AI 关键词过滤,只留命中的(和资讯源去噪一致)。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content                                          # noqa: E402
from store import insert_items, url_hash, hash_exists   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

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
        capture_output=True, encoding="utf-8", errors="replace", timeout=180,
    )
    obj = first_json(r.stdout)
    if isinstance(obj, dict):
        return obj.get("data") or obj.get("tweets") or []
    return obj if isinstance(obj, list) else []


def to_item(t):
    a = t.get("author") or {}
    handle = a.get("screenName", "") if isinstance(a, dict) else ""
    tid = str(t.get("id", ""))
    text = (t.get("text", "") or "").replace("\n", " ").strip()
    if not handle or not tid:
        return None
    if t.get("isRetweet"):
        rb = t.get("retweetedBy")
        rb = rb if isinstance(rb, str) else (rb.get("screenName", "") if isinstance(rb, dict) else "")
        prefix = f"@{rb} 🔁 @{handle}" if rb else f"@{handle}"
    else:
        prefix = f"@{handle}"
    return {
        "title": f"{prefix}：{text}"[:200],
        "url": f"https://x.com/{handle}/status/{tid}",
        "summary": "",
        "published_at": t.get("createdAtISO") or t.get("createdAt") or "",
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
    limit = src.get("limit", 20)

    raw = fetch_list(list_id, limit * 3)  # 多抓,过滤后保量
    ai = [t for t in raw if is_ai(t.get("text", "") or "")]
    items, seen = [], set()
    for t in ai:
        it = to_item(t)
        if not it or it["url"] in seen or hash_exists(url_hash(it["url"])):
            continue
        seen.add(it["url"])
        it["content_html"] = ""
        items.append(it)
        if len(items) >= limit:
            break
    n = insert_items(items, src)
    print(f"{src['source_label']}: 列表 {list_id} 抓 {len(raw)} 条,AI 命中 {len(ai)},新增 {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
