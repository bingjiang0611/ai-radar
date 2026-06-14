"""内容处理：清洗外站 HTML（nh3）+ 把图片下载进站（防丢）。

顺序：先 nh3.clean 清洗（保留 img / 外链 https src，剥 script/iframe/on*/javascript:），
再把 <img src> 下载到 dist/img/{sha256}.{ext}，src 改成站内根路径 /img/...。
图片按内容 hash 命名 → 天然去重、跨 run 复用（文件已存在则不重下）。
"""

import hashlib
import re
import subprocess
from html import escape as _escape, unescape as _unescape
from pathlib import Path
from urllib.parse import urlsplit

import nh3

_DIST = Path(__file__).resolve().parent.parent / "dist"
DIST_IMG = _DIST / "img"
DIST_ICONS = _DIST / "icons"
_MAX_IMG_BYTES = 8_000_000


def fetch_favicon(url):
    """取来源域名的 favicon 下载进站 dist/icons/<domain>.png（缓存，按域名），返回站内路径 /icons/... 或 ""。
    用 Google s2 favicon 服务（按域名稳定返回 PNG）。已存在则不重下。"""
    dom = urlsplit(url if "//" in (url or "") else "//" + (url or "")).netloc.lower()
    if not dom:
        return ""
    safe = re.sub(r"[^a-z0-9.-]", "_", dom)
    DIST_ICONS.mkdir(parents=True, exist_ok=True)
    path = DIST_ICONS / f"{safe}.png"
    rel = f"/icons/{safe}.png"
    if path.exists():
        return rel
    src = f"https://www.google.com/s2/favicons?domain={dom}&sz=64"
    try:
        r = subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", "15", src],
                           capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        return ""
    data = r.stdout
    if r.returncode == 0 and data and len(data) > 100:
        path.write_bytes(data)
        return rel
    return ""


def sanitize(html):
    """nh3 默认白名单清洗，返回安全 HTML。"""
    return nh3.clean(html or "")


def _guess_ext(url, data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return ".svg"
    m = re.search(r"\.(jpe?g|png|gif|webp|svg|avif)(?:$|\?)", url.lower())
    return "." + m.group(1).replace("jpeg", "jpg") if m else ".img"


def _is_image(data):
    """按魔数判定是否真图片——挡住「URL 后缀是 .jpg 但内容其实是 HTML 错误页/登录页」这类。"""
    if not data:
        return False
    if data[:3] == b"\xff\xd8\xff":               # jpg
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":           # png
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):         # gif
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    head = data[:400].lstrip().lower()             # svg(可能带 <?xml 头)
    return head[:4] == b"<svg" or (head[:5] == b"<?xml" and b"<svg" in head)


def _download_image(url):
    """下载图片 → dist/img/{hash}{ext}；返回站内路径 /img/... 或 None（失败/过大/非图片）。"""
    url = _unescape(url)  # HTML 属性里的 &amp; → & —— 否则带 query 的 URL(如 Next.js _next/image?...&w=)参数传不全
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", "20", url],
            capture_output=True, timeout=25,
        )
    except Exception:  # noqa: BLE001 — 单张图失败不影响整篇
        return None
    data = r.stdout
    if r.returncode != 0 or not data or len(data) > _MAX_IMG_BYTES:
        return None
    if not _is_image(data):  # 拿到的是 HTML 错误页/登录页(非真图)→ 不存,localize_images 会丢掉该 <img>
        return None
    h = hashlib.sha256(data).hexdigest()[:16]
    name = f"{h}{_guess_ext(url, data)}"
    DIST_IMG.mkdir(parents=True, exist_ok=True)
    path = DIST_IMG / name
    if not path.exists():
        path.write_bytes(data)
    return f"/img/{name}"


def localize_images(html):
    """把已清洗 html 里的 http(s) <img src> 下载进站，src 改为 /img/...。"""
    if not html or "<img" not in html:
        return html

    def repl(m):
        prefix, src, suffix = m.group(1), m.group(2), m.group(3)
        if not src.lower().startswith(("http://", "https://")):
            return m.group(0)
        local = _download_image(src)
        return f"{prefix}{local}{suffix}" if local else ""  # 下不到有效图 → 丢掉整个 <img>,不留破图

    return re.sub(r'(<img[^>]*\ssrc=")([^"]+)("[^>]*>)', repl, html, flags=re.I)


def process(html):
    """清洗 + 图片进站，返回可直接渲染的安全 HTML。只对新条目调用（含网络下载）。"""
    return localize_images(sanitize(html))


# ---------- 入口B 正文：Jina 取正文 markdown → HTML（站内详情页用）----------

_MD_IMG = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
_MD_LINK = re.compile(r'\[([^\]]+)\]\((\S+?)(?:\s+"[^"]*")?\)')
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")


def _md_inline(text):
    text = _escape(text)  # 先转义,markdown 标记(*[]()`)不受影响,正则仍可匹配
    text = _MD_IMG.sub(r'<img src="\2" alt="\1">', text)
    text = _MD_LINK.sub(r'<a href="\2">\1</a>', text)
    text = _MD_BOLD.sub(r"<strong>\1</strong>", text)
    text = _MD_CODE.sub(r"<code>\1</code>", text)
    return text


def md_to_html(md):
    """极简 markdown → HTML：覆盖 Jina readability 输出的常见块（标题/段落/列表/图片/链接/
    引用/代码/分隔线）。产物再交给 process() 走 nh3 清洗 + 图片进站，故无需自身完备/绝对安全。"""
    if not md:
        return ""
    idx = md.find("Markdown Content:")  # 剥掉 Jina 头部元信息(Title/URL Source/Published Time)
    if idx != -1:
        md = md[idx + len("Markdown Content:"):]
    out, para, in_list = [], [], [None]

    def flush():
        if para:
            out.append("<p>" + _md_inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        if in_list[0]:
            out.append(f"</{in_list[0]}>")
            in_list[0] = None

    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("```"):
            flush(); close_list(); i += 1; code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            out.append("<pre><code>" + _escape("\n".join(code)) + "</code></pre>")
            continue
        if not line.strip():
            flush(); close_list(); i += 1; continue
        h = re.match(r"(#{1,6})\s+(.*)", line)
        if h:
            flush(); close_list()
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{_md_inline(h.group(2))}</h{lvl}>"); i += 1; continue
        if re.fullmatch(r"(\s*[-*_]){3,}\s*", line):
            flush(); close_list(); out.append("<hr>"); i += 1; continue
        if line.startswith(">"):
            flush(); close_list()
            out.append("<blockquote>" + _md_inline(line.lstrip("> ")) + "</blockquote>"); i += 1; continue
        m = re.match(r"\s*[-*+]\s+(.*)", line)
        if m:
            flush()
            if in_list[0] != "ul":
                close_list(); out.append("<ul>"); in_list[0] = "ul"
            out.append("<li>" + _md_inline(m.group(1)) + "</li>"); i += 1; continue
        m = re.match(r"\s*\d+\.\s+(.*)", line)
        if m:
            flush()
            if in_list[0] != "ol":
                close_list(); out.append("<ol>"); in_list[0] = "ol"
            out.append("<li>" + _md_inline(m.group(1)) + "</li>"); i += 1; continue
        close_list()
        para.append(line.strip())
        i += 1
    flush(); close_list()
    return "\n".join(out)


_STRIP_TAGS = re.compile(r"(?is)<(script|style|nav|header|footer|aside|form|svg|button|figure)\b[^>]*>.*?</\1>")
_ARTICLE = re.compile(r"(?is)<article\b[^>]*>(.*?)</article>")
_BLOCK = re.compile(r"(?is)<(p|h[1-3])\b[^>]*>(.*?)</\1>")
# 服务端直出新闻站正文末尾常见的非正文段落(广告/活动推广/作者 bio/订阅 CTA/UI 残片)——抽正文时整段丢弃
_BOILERPLATE = re.compile(
    r"(?i)(get an inside look at what it takes|you can contact or verify outreach"
    r"|please logout and then login again|techcrunch disrupt|all stage passes"
    r"|is a freelance (contributor|writer|journalist)|fill out (this|the) form"
    r"|sign up (for|to) (our |the )?.{0,30}newsletter|subscribe (for|to) (our |the )?.{0,30}newsletter"
    r"|register now (and|to)|join us at)"
)


def _extract_article(html):
    """站点无关地从服务端直出的 HTML 抽正文:剥非正文容器 → 限定到 <article>(若有)→ 取长 <p> 与小标题,
    丢弃广告/作者 bio/订阅 CTA 等 boilerplate 段,输出纯文本段落(转义,不带外链/图片——避免破图/跟踪链)。
    拿不到足量正文返回 ""。"""
    if not html:
        return ""
    h = _STRIP_TAGS.sub(" ", html)
    m = _ARTICLE.search(h)
    scope = m.group(1) if m else h
    out, total = [], 0
    for tag, inner in _BLOCK.findall(scope):
        text = re.sub(r"\s+", " ", _unescape(re.sub(r"(?is)<[^>]+>", "", inner))).strip()
        if _BOILERPLATE.search(text):  # 广告/活动推广/作者 bio/订阅 CTA/UI 残片 → 丢
            continue
        if tag == "p":
            if len(text) < 60:
                continue
            out.append(f"<p>{_escape(text)}</p>"); total += len(text)
        elif text:
            out.append(f"<{tag}>{_escape(text)}</{tag}>")
    return "\n".join(out) if total >= 200 else ""  # 正文太少(付费墙 stub/纯导航)→ 视为没抓到


def _fetch_direct(url, timeout=30):
    """直连 curl 取服务端直出 HTML → 抽正文。给 Jina 穿不过的服务端渲染新闻站(TechCrunch/Wired/TechRadar)兜底。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
             "--max-time", str(timeout - 3), url],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return ""
    if r.returncode != 0 or not r.stdout or "Just a moment" in r.stdout[:1000]:
        return ""  # Cloudflare 等挡住,直连也拿不到
    return _extract_article(r.stdout)


def fetch_article_html(url, timeout=60):
    """取单篇正文 HTML：Jina 优先（救 SPA/隐私护栏站）→ Jina 失败再直连 curl 抽正文（救 Jina 限流的新闻站）。
    都拿不到/被 Cloudflare 挡 → 返回 ""（详情页回退到摘要 +「打开原文」）。"""
    if not url:
        return ""
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", str(timeout - 5), f"https://r.jina.ai/{url}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        r = None
    md = (r.stdout if r else "") or ""
    bad = (r is None or r.returncode != 0 or len(md) < 80
           or "Just a moment" in md[:500] or md.lstrip()[:9] == '{"data":n')  # Jina 错误包(限流 code 451 等)
    if bad:
        return _fetch_direct(url)  # Jina 不行 → 直连兜底
    return md_to_html(md)


def gc_images(html_blobs):
    """删掉 dist/img 下没被任何现存条目引用的图片（配合 1 个月 retention）。返回删除数。"""
    if not DIST_IMG.exists():
        return 0
    referenced = set()
    for h in html_blobs:
        referenced.update(re.findall(r"/img/([^\"'\s)]+)", h or ""))
    removed = 0
    for f in DIST_IMG.iterdir():
        if f.is_file() and f.name not in referenced:
            f.unlink()
            removed += 1
    return removed
