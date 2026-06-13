"""通用 parser：rss / json_api。

加新源绝大多数情况只在 sources.json 加一行挂到 rss。
抓取（网络）与解析（纯函数）分离：parse_*_text 不碰网络，便于单测。
"""

import json
import re
import xml.etree.ElementTree as ET

from fetch import fetch


def _clean(text, limit=280):
    """去 HTML 标签、压空白、截断。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _strip_ns(root):
    """就地去掉所有标签的命名空间前缀，让 RSS 和 Atom(YouTube) 能用同一套 localname 查找。"""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


# ---------- RSS / Atom ----------

def parse_rss_text(xml, limit=10):
    """解析 RSS 2.0 (<item>) 或 Atom (<entry>，YouTube 用)。纯函数。"""
    try:
        root = _strip_ns(ET.fromstring(xml))
    except ET.ParseError:
        return []

    nodes = root.findall(".//item") or root.findall(".//entry")
    out = []
    for node in nodes[:limit]:
        title = (node.findtext("title") or "").strip()

        # RSS: <link>text</link>；Atom: <link href="..."/>
        url = ""
        link_el = node.find("link")
        if link_el is not None:
            url = (link_el.text or link_el.get("href") or "").strip()
        if not url:
            url = (node.findtext("id") or "").strip()  # Atom id 兜底

        summary = (
            node.findtext("description")
            or node.findtext("summary")
            or node.findtext("content")
            or ""
        )
        published = (
            node.findtext("pubDate")
            or node.findtext("published")
            or node.findtext("updated")
            or ""
        ).strip()

        if title and url:
            out.append({
                "title": title,
                "url": url,
                "summary": _clean(summary),
                "published_at": published,
            })
    return out


def parse_rss(source):
    xml = fetch(source["url"])
    return parse_rss_text(xml, source.get("limit", 10)) if xml else []


# ---------- 通用 JSON API ----------

def _dotted(obj, path):
    """按点路径取值，如 'paper.title'。任一层缺失返回 None。"""
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def _fmt(template, item):
    """替换模板里的 {点路径} 占位，如 'https://hf.co/papers/{paper.id}'。"""
    def repl(m):
        v = _dotted(item, m.group(1))
        return str(v) if v is not None else ""
    return re.sub(r"\{([^}]+)\}", repl, template)


def parse_json_text(raw, cfg, limit=15):
    """解析 JSON API。cfg: {items_path, title, url|url_template, summary_template}。纯函数。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items_path = cfg.get("items_path", "")
    arr = _dotted(data, items_path) if items_path else data
    if not isinstance(arr, list):
        return []

    out = []
    for it in arr[:limit]:
        title = _dotted(it, cfg.get("title", "title"))
        if cfg.get("url"):
            url = _dotted(it, cfg["url"])
        elif cfg.get("url_template"):
            url = _fmt(cfg["url_template"], it)
        else:
            url = None
        summary = _fmt(cfg["summary_template"], it) if cfg.get("summary_template") else ""

        title = str(title).strip() if title else ""
        url = str(url).strip() if url else ""
        if title and url:
            out.append({
                "title": title,
                "url": url,
                "summary": _clean(summary),
                "published_at": "",
            })
    return out


def parse_json_api(source):
    raw = fetch(source["url"])
    return parse_json_text(raw, source.get("json", {}), source.get("limit", 15)) if raw else []


# ---------- 小宇宙播客（Next.js 页面，集数据嵌在 __NEXT_DATA__ JSON 里，无公开 RSS） ----------

def parse_xiaoyuzhou_text(html_text, limit=15):
    """从小宇宙播客页 HTML 抽 __NEXT_DATA__ → podcast.episodes。纯函数。"""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    podcast = (data.get("props", {}).get("pageProps", {}) or {}).get("podcast", {}) or {}
    out = []
    for ep in (podcast.get("episodes") or [])[:limit]:
        eid = ep.get("eid")
        title = (ep.get("title") or "").strip()
        if not eid or not title:
            continue
        out.append({
            "title": title,
            "url": f"https://www.xiaoyuzhoufm.com/episode/{eid}",
            "summary": _clean(ep.get("description") or ep.get("shownotes") or ""),
            "published_at": (ep.get("pubDate") or "")[:10],  # ISO → 日期
        })
    return out


def parse_xiaoyuzhou(source):
    html_text = fetch(source["url"])
    return parse_xiaoyuzhou_text(html_text, source.get("limit", 15)) if html_text else []


PARSERS = {
    "rss": parse_rss,
    "json_api": parse_json_api,
    "xiaoyuzhou": parse_xiaoyuzhou,
}
