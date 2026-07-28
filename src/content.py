"""Content cleanup for curated uploads."""

import hashlib
import re
import subprocess
from html import escape as _escape, unescape as _unescape
from pathlib import Path

import nh3

_DIST = Path(__file__).resolve().parent.parent / "dist"
DIST_IMG = _DIST / "img"
_MAX_IMG_BYTES = 8_000_000


def sanitize(html):
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
    head = data[:400].lstrip().lower()
    if head[:4] == b"<svg" or (head[:5] == b"<?xml" and b"<svg" in head):
        return ".svg"
    m = re.search(r"\.(jpe?g|png|gif|webp|svg|avif)(?:$|\?)", url.lower())
    return "." + m.group(1).replace("jpeg", "jpg") if m else ".img"


def _is_image(data):
    if not data:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    head = data[:400].lstrip().lower()
    return head[:4] == b"<svg" or (head[:5] == b"<?xml" and b"<svg" in head)


def _download_image(url, max_time=20, timeout=25):
    url = _unescape(url)
    max_time = max(1, int(max_time))
    timeout = max(max_time + 1, int(timeout))
    try:
        r = subprocess.run(
            [
                "curl",
                "-sL",
                "-A",
                "Mozilla/5.0",
                "--max-time",
                str(max_time),
                "--max-filesize",
                str(_MAX_IMG_BYTES),
                url,
            ],
            capture_output=True,
            timeout=timeout,
        )
    except Exception:
        return None
    data = r.stdout
    if r.returncode != 0 or not data or len(data) > _MAX_IMG_BYTES or not _is_image(data):
        return None
    h = hashlib.sha256(data).hexdigest()[:16]
    name = f"{h}{_guess_ext(url, data)}"
    DIST_IMG.mkdir(parents=True, exist_ok=True)
    path = DIST_IMG / name
    if not path.exists():
        path.write_bytes(data)
    return f"/img/{name}"


def localize_images(html):
    if not html or "<img" not in html:
        return html

    def repl(m):
        prefix, src, suffix = m.group(1), m.group(2), m.group(3)
        if not src.lower().startswith(("http://", "https://")):
            return m.group(0)
        local = _download_image(src)
        return f"{prefix}{local}{suffix}" if local else ""

    return re.sub(r'(<img[^>]*\ssrc=")([^"]+)("[^>]*>)', repl, html, flags=re.I)


def process(html):
    return localize_images(sanitize(html))


_MD_IMG = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)')
_MD_LINK = re.compile(r'\[([^\]]+)\]\((\S+?)(?:\s+"[^"]*")?\)')
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _md_inline(text):
    text = _escape(text)
    text = _MD_IMG.sub(r'<img src="\2" alt="\1">', text)
    text = _MD_LINK.sub(r'<a href="\2">\1</a>', text)
    text = _MD_BOLD.sub(r"<strong>\1</strong>", text)
    text = _MD_CODE.sub(r"<code>\1</code>", text)
    return text


def _table_cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_table_sep(line):
    return bool(_MD_TABLE_SEP.match(line or ""))


def _render_table(rows):
    if len(rows) < 2:
        return ""
    head = _table_cells(rows[0])
    sep = _table_cells(rows[1])
    body = [_table_cells(r) for r in rows[2:]]
    if not head or len(sep) != len(head) or any(len(r) != len(head) for r in body):
        return ""
    th = "".join(f"<th>{_md_inline(c)}</th>" for c in head)
    trs = []
    for row in body:
        tds = "".join(f"<td>{_md_inline(c)}</td>" for c in row)
        trs.append(f"<tr>{tds}</tr>")
    return ('<div class="table-wrap"><table><thead><tr>' + th
            + '</tr></thead><tbody>' + "".join(trs)
            + '</tbody></table></div>')


def md_to_html(md):
    if not md:
        return ""
    out, para, in_list = [], [], None

    def flush():
        if para:
            out.append("<p>" + _md_inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("```"):
            flush()
            close_list()
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + _escape("\n".join(code)) + "</code></pre>")
            continue
        if not line.strip():
            flush()
            close_list()
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            flush()
            close_list()
            rows = [line, lines[i + 1].rstrip()]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i].rstrip())
                i += 1
            table = _render_table(rows)
            if table:
                out.append(table)
            else:
                para.extend(r.strip() for r in rows)
            continue
        h = re.match(r"(#{1,6})\s+(.*)", line)
        if h:
            flush()
            close_list()
            lvl = len(h.group(1))
            out.append(f"<h{lvl}>{_md_inline(h.group(2))}</h{lvl}>")
            i += 1
            continue
        m = re.match(r"\s*[-*+]\s+(.*)", line)
        if m:
            flush()
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append("<li>" + _md_inline(m.group(1)) + "</li>")
            i += 1
            continue
        m = re.match(r"\s*\d+\.\s+(.*)", line)
        if m:
            flush()
            if in_list != "ol":
                close_list()
                out.append("<ol>")
                in_list = "ol"
            out.append("<li>" + _md_inline(m.group(1)) + "</li>")
            i += 1
            continue
        if line.startswith(">"):
            flush()
            close_list()
            out.append("<blockquote>" + _md_inline(line.lstrip("> ")) + "</blockquote>")
            i += 1
            continue
        close_list()
        para.append(line.strip())
        i += 1
    flush()
    close_list()
    return "\n".join(out)


def gc_images(html_blobs):
    if not DIST_IMG.exists():
        return 0
    referenced = set()
    for blob in html_blobs:
        referenced.update(re.findall(r"/img/([^\"'\s)]+)", blob or ""))
    removed = 0
    for f in DIST_IMG.iterdir():
        if f.is_file() and f.name not in referenced:
            f.unlink()
            removed += 1
    return removed
