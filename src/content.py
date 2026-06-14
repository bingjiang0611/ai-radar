"""内容处理：清洗外站 HTML（nh3）+ 把图片下载进站（防丢）。

顺序：先 nh3.clean 清洗（保留 img / 外链 https src，剥 script/iframe/on*/javascript:），
再把 <img src> 下载到 dist/img/{sha256}.{ext}，src 改成站内根路径 /img/...。
图片按内容 hash 命名 → 天然去重、跨 run 复用（文件已存在则不重下）。
"""

import hashlib
import re
import subprocess
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


def _download_image(url):
    """下载图片 → dist/img/{hash}{ext}；返回站内路径 /img/... 或 None（失败/过大）。"""
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
        return f"{prefix}{local}{suffix}" if local else m.group(0)

    return re.sub(r'(<img[^>]*\ssrc=")([^"]+)("[^>]*>)', repl, html, flags=re.I)


def process(html):
    """清洗 + 图片进站，返回可直接渲染的安全 HTML。只对新条目调用（含网络下载）。"""
    return localize_images(sanitize(html))


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
