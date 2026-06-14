"""纯 Python 渲染静态站。

产物：
- dist/index.html        首页 = 来源卡片总览（按分类分区 + 搜索；点卡片 → feed.html?source=）
- dist/feed.html         单来源内容列表（读 ?source 只展示该来源；条目点进详情/外跳）
- dist/item/<hash>.html  条目详情页（站内展示正文，"打开原文"才外跳；原文/中文翻译 tabs）
- dist/img/<hash>.<ext>  下载进站的图片（由 content.localize_images 写入，此处不动）

外站正文已在入库前用 nh3 清洗 + 图片进站，这里直接渲染；标题/来源等短文本仍过 html.escape。
"""

import html
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# 从 youtube 链接抠 11 位 video id（watch?v= / youtu.be / embed / shorts）
_YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})")

DIST = Path(__file__).resolve().parent.parent / "dist"

_CAT_COLORS = {
    "论文": "bg-violet-100 text-violet-700",
    "研究": "bg-blue-100 text-blue-700",
    "产品": "bg-emerald-100 text-emerald-700",
    "视频": "bg-rose-100 text-rose-700",
    "播客": "bg-amber-100 text-amber-700",
    "Newsletter": "bg-sky-100 text-sky-700",
    "资讯": "bg-orange-100 text-orange-700",
    "推文": "bg-cyan-100 text-cyan-700",
}
_CAT_DEFAULT = "bg-zinc-100 text-zinc-600"
_CAT_ICON = {"论文": "📄", "研究": "🔬", "产品": "🚀", "视频": "▶️", "播客": "🎙️", "Newsletter": "✉️", "资讯": "📰", "推文": "🐦"}
_CAT_ORDER = ["研究", "产品", "Newsletter", "资讯", "论文", "播客", "视频", "推文"]

_ICONS = {}  # source_label -> /icons/<domain>.png（render_site 注入）


def _favicon(label, cls="h-7 w-7 rounded-md"):
    """来源头像：有 favicon 用图，否则首字母占位块。cls 控制尺寸/圆角。"""
    icon = _ICONS.get(label, "")
    if icon:
        return f'<img src="{_e(icon)}" class="{cls} shrink-0 bg-white object-contain" alt="" loading="lazy">'
    ch = label.strip()[:1] if label.strip() else "•"
    return f'<span class="{cls} flex shrink-0 items-center justify-center bg-zinc-200 text-xs font-medium text-zinc-600">{_e(ch)}</span>'

# 详情页正文样式（Tailwind CDN 不含 typography 插件，手写关键排版）
_CONTENT_STYLE = """
<style>
  .doc img{max-width:100%;height:auto;border-radius:.5rem;margin:1rem 0}
  .doc p{margin:.85rem 0;line-height:1.75}
  .doc h1,.doc h2,.doc h3,.doc h4{font-weight:600;margin:1.5rem 0 .5rem;line-height:1.3}
  .doc a{color:#2563eb;text-decoration:underline}
  .doc ul,.doc ol{margin:.85rem 0;padding-left:1.5rem;list-style:revert}
  .doc li{margin:.3rem 0}
  .doc blockquote{border-left:3px solid #e4e4e7;padding-left:1rem;color:#71717a;margin:1rem 0}
  .doc pre{background:#f4f4f5;padding:1rem;border-radius:.5rem;overflow-x:auto;font-size:.85em;margin:1rem 0}
  .doc code{background:#f4f4f5;padding:.1rem .3rem;border-radius:.25rem;font-size:.9em}
  .doc pre code{background:none;padding:0}
  .doc figure{margin:1rem 0}
</style>
"""

# 首页：搜索过滤来源卡片
_HOME_SCRIPT = """
<script>
  const cards = [...document.querySelectorAll('.src-card')];
  const searchEl = document.getElementById('search');
  if (searchEl) searchEl.addEventListener('input', () => {
    const q = searchEl.value.trim().toLowerCase();
    cards.forEach(c => { c.style.display = (!q || c.dataset.text.includes(q)) ? '' : 'none'; });
    document.querySelectorAll('.cat-section').forEach(sec => {
      const any = [...sec.querySelectorAll('.src-card')].some(c => c.style.display !== 'none');
      sec.style.display = any ? '' : 'none';
    });
  });
</script>
"""

# 单来源 feed：按 ?source 只显示该来源 + 站内搜索
_FEED_SCRIPT = """
<script>
  const items = [...document.querySelectorAll('.item')];
  const searchEl = document.getElementById('search');
  const src = new URLSearchParams(location.search).get('source') || '';
  const nameEl = document.getElementById('feed-src');
  if (nameEl) nameEl.textContent = src || '时间流';
  function apply() {
    const q = ((searchEl && searchEl.value) || '').trim().toLowerCase();
    items.forEach(el => {
      // 时间流(无 source):排除「推文」分类,避免 X 列表的高频推文淹没主流;推文只在其来源卡片里看
      const inFeed = src ? el.dataset.source === src : el.dataset.category !== '推文';
      const ok = inFeed && (!q || el.dataset.text.includes(q));
      el.style.display = ok ? '' : 'none';
    });
    document.querySelectorAll('.day-section').forEach(sec => {
      const any = [...sec.querySelectorAll('.item')].some(el => el.style.display !== 'none');
      sec.style.display = any ? '' : 'none';
    });
  }
  if (searchEl) searchEl.addEventListener('input', apply);
  apply();
</script>
"""

# 详情页 tab 切换 + 复制链接 + YouTube 门面
_DETAIL_SCRIPT = """
<script>
  document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(x => x.classList.toggle('bg-white', x === b));
    document.querySelectorAll('.tab-btn').forEach(x => x.classList.toggle('shadow-sm', x === b));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== b.dataset.panel));
  }));
  const copyBtn = document.getElementById('copy-link');
  if (copyBtn) copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(copyBtn.dataset.url).then(() => {
      copyBtn.textContent = '已复制'; setTimeout(() => { copyBtn.textContent = '复制链接'; }, 1500);
    });
  });
  document.querySelectorAll('.yt-facade').forEach(f => f.addEventListener('click', () => {
    const id = f.dataset.id;
    if (!/^[\\w-]{11}$/.test(id)) return;
    const ifr = document.createElement('iframe');
    ifr.className = 'h-full w-full rounded-lg';
    ifr.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
    ifr.allowFullscreen = true;
    ifr.src = 'https://www.youtube.com/embed/' + id + '?autoplay=1';
    f.replaceWith(ifr);
  }));
</script>
"""


def _e(s):
    return html.escape(s or "")


def _safe_url(url):
    u = (url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else "#"


def _day(item):
    return (item.get("fetched_at") or "")[:10] or "未知日期"


def _feed_href(label):
    return "/feed.html?source=" + quote(label)


def _youtube_embed(url):
    """youtube 链接 → 缩略图门面（lite-youtube）：先显示封面+播放钮，点击才加载播放器。
    iframe 由 _DETAIL_SCRIPT 用 createElement 生成；video id 限 [A-Za-z0-9_-]{11}，无注入。"""
    m = _YT_RE.search(url or "")
    if not m:
        return ""
    vid = m.group(1)
    return (
        '<div class="aspect-video my-5">'
        f'<div class="yt-facade group relative h-full w-full cursor-pointer overflow-hidden rounded-lg bg-zinc-900" data-id="{vid}">'
        f'<img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy" class="h-full w-full object-cover opacity-90 transition group-hover:opacity-100">'
        '<span class="absolute inset-0 flex items-center justify-center">'
        '<span class="flex h-14 w-20 items-center justify-center rounded-2xl bg-black/70 text-white transition group-hover:bg-red-600">'
        '<svg width="30" height="30" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
        "</span></span></div></div>"
    )


def _head(title):
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <script src="https://cdn.tailwindcss.com"></script>"""


# ---------- 首页：来源卡片总览 ----------

def _render_home(items, descriptions, out):
    # 聚合每个来源：条数 + 最近更新（items 已按 fetched_at DESC，首见即最新）+ 分类
    stats = {}
    for it in items:
        lbl = it.get("source_label", "")
        if not lbl:
            continue
        s = stats.get(lbl)
        if s is None:
            stats[lbl] = {"count": 1, "latest": (it.get("fetched_at") or "")[:10], "category": it.get("category", "")}
        else:
            s["count"] += 1

    by_cat = {}
    for lbl, s in stats.items():
        by_cat.setdefault(s["category"], []).append((lbl, s))
    ordered = [c for c in _CAT_ORDER if c in by_cat] + [c for c in by_cat if c not in _CAT_ORDER]

    def card(lbl, s):
        cat = s["category"]
        chip = _CAT_COLORS.get(cat, _CAT_DEFAULT)
        icon = _CAT_ICON.get(cat, "")
        desc = descriptions.get(lbl, "")
        blob = _e(f"{lbl} {desc}".lower())
        desc_html = f'<p class="mt-1.5 text-sm leading-relaxed text-zinc-500">{_e(desc)}</p>' if desc else ""
        return f'''        <a href="{_e(_feed_href(lbl))}" class="src-card flex flex-col rounded-xl border border-zinc-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm" data-text="{blob}">
          <div class="flex items-center gap-2 text-xs">
            <span class="rounded px-1.5 py-0.5 font-medium {chip}">{icon} {_e(cat)}</span>
            <span class="ml-auto text-zinc-400">{s["count"]} 条</span>
          </div>
          <div class="mt-2 flex items-center gap-2">{_favicon(lbl)}<h3 class="font-semibold text-zinc-800">{_e(lbl)}</h3></div>
          {desc_html}
          <p class="mt-auto pt-2 text-xs text-zinc-400">最近更新 {_e(s["latest"])}</p>
        </a>'''

    sections = []
    for cat in ordered:
        srcs = sorted(by_cat[cat], key=lambda kv: (kv[1]["latest"], kv[1]["count"]), reverse=True)
        cards = "\n".join(card(lbl, s) for lbl, s in srcs)
        sections.append(
            f'''      <section class="cat-section mb-8">
        <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-500">{_CAT_ICON.get(cat, "")} {_e(cat)}<span class="text-xs font-normal text-zinc-300">{len(srcs)}</span></h2>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
{cards}
        </div>
      </section>'''
        )
    body = "\n".join(sections) if sections else '<p class="py-16 text-center text-zinc-400">暂无来源。</p>'
    total = sum(s["count"] for s in stats.values())

    page = f"""{_head("AI Radar")}
</head>
<body class="bg-zinc-50 text-zinc-800 antialiased">
  <header class="sticky top-0 z-10 border-b border-zinc-200 bg-white/90 backdrop-blur">
    <div class="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2.5">
      <h1 class="text-lg font-bold tracking-tight">AI&nbsp;Radar</h1>
      <a href="/feed.html" class="text-sm font-medium text-zinc-500 hover:text-blue-600">时间流</a>
      <span class="hidden text-sm text-zinc-400 sm:inline">{len(stats)} 个来源 · {total} 条</span>
      <input id="search" type="search" placeholder="搜索来源…"
             class="ml-auto w-44 rounded-full border border-zinc-200 px-3 py-1 text-sm outline-none focus:border-blue-400">
    </div>
  </header>
  <main class="mx-auto max-w-5xl px-4 py-6">
{body}
  </main>
{_HOME_SCRIPT}
</body>
</html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


# ---------- 单来源内容列表 feed.html ----------

def _card(item, mode="detail"):
    title = item.get("title_zh") or item.get("title") or ""
    summary = item.get("summary_zh") or item.get("summary") or ""
    cat = item.get("category") or ""
    chip = _CAT_COLORS.get(cat, _CAT_DEFAULT)
    src = item.get("source_label", "")
    when = item.get("published_at") or _day(item)
    if mode == "link":
        href = _safe_url(item.get("url", ""))
        link_attrs = ' target="_blank" rel="noopener"'
        arrow = ' <span class="text-zinc-300">↗</span>'
    else:
        href = f"/item/{_e(item.get('hash',''))}.html"
        link_attrs = ""
        arrow = ""
    search_blob = _e(f"{title} {summary} {src}".lower())
    summary_html = (
        f'<p class="mt-1.5 text-sm leading-relaxed text-zinc-500">{_e(summary)}</p>'
        if summary else ""
    )
    return f"""      <article class="item flex gap-3 border-b border-zinc-100 py-3.5" data-category="{_e(cat)}" data-source="{_e(src)}" data-text="{search_blob}">
        {_favicon(src, "h-10 w-10 rounded-full")}
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-x-1.5 text-sm">
            <span class="font-semibold text-zinc-800">{_e(src)}</span>
            <span class="rounded px-1.5 py-0.5 text-xs font-medium {chip}">{_e(cat)}</span>
            <span class="text-zinc-400">· {_e(when)}</span>
          </div>
          <a href="{href}"{link_attrs} class="mt-0.5 block font-medium leading-snug text-zinc-800 hover:text-blue-600">{_e(title)}{arrow}</a>
          {summary_html}
        </div>
      </article>"""


def _render_feed(items, interactions, out):
    sections, cur_day, buf = [], None, []
    for it in items:
        d = _day(it)
        if d != cur_day:
            if buf:
                sections.append((cur_day, buf))
            cur_day, buf = d, []
        buf.append(_card(it, interactions.get(it.get("source_id"), "detail")))
    if buf:
        sections.append((cur_day, buf))

    body = []
    for day, cards in sections:
        body.append(
            f'      <section class="day-section">\n'
            f'        <h2 class="py-2 text-sm font-semibold text-zinc-400">{_e(day)}</h2>\n'
            + "\n".join(cards) + "\n      </section>"
        )
    body_html = "\n".join(body) if body else '<p class="py-16 text-center text-zinc-400">暂无内容。</p>'

    page = f"""{_head("AI Radar")}
</head>
<body class="bg-zinc-50 text-zinc-800 antialiased">
  <header class="sticky top-0 z-10 border-b border-zinc-200 bg-white/90 backdrop-blur">
    <div class="mx-auto flex max-w-2xl items-center gap-3 px-4 py-2.5">
      <a href="/" class="shrink-0 text-sm font-bold tracking-tight hover:text-blue-600">← AI&nbsp;Radar</a>
      <span id="feed-src" class="truncate font-medium text-zinc-700"></span>
      <input id="search" type="search" placeholder="搜索…"
             class="ml-auto w-32 shrink-0 rounded-full border border-zinc-200 px-3 py-1 text-sm outline-none focus:border-blue-400">
    </div>
  </header>
  <main class="mx-auto max-w-2xl px-4">
{body_html}
  </main>
{_FEED_SCRIPT}
</body>
</html>
"""
    (out / "feed.html").write_text(page, encoding="utf-8")


# ---------- 详情页 ----------

def _tabs(item):
    content = item.get("content_html") or ""
    yuanwen = content or '<p class="text-zinc-400">本条无正文，点上方「打开原文」查看。</p>'
    zh = item.get("translation_md") or ""
    zh_panel = (f'<div class="doc">{_e(zh)}</div>' if zh
                else '<p class="text-zinc-400">未翻译。挑中该条后会补中文全文。</p>')
    tab = lambda pid, label, active: (  # noqa: E731
        f'<button class="tab-btn rounded-md px-4 py-1.5 text-sm font-medium '
        f'{"bg-white shadow-sm" if active else "text-zinc-500"}" data-panel="{pid}">{label}</button>'
    )
    return f"""      <div class="mt-5 inline-flex gap-1 rounded-lg bg-zinc-100 p-1">
        {tab("p-yuanwen", "原文", True)}
        {tab("p-zh", "中文翻译", False)}
      </div>
      <div id="p-yuanwen" class="tab-panel doc mt-5">{yuanwen}</div>
      <div id="p-zh" class="tab-panel mt-5 hidden">{zh_panel}</div>"""


def _render_detail(item, out, descriptions):
    title_zh = item.get("title_zh") or ""
    title = item.get("title") or ""
    head_title = title_zh or title
    subtitle = (f'<p class="mt-1 text-lg text-zinc-400">{_e(title)}</p>'
                if title_zh and title and title_zh != title else "")
    cat = item.get("category") or ""
    chip = _CAT_COLORS.get(cat, _CAT_DEFAULT)
    src = item.get("source_label", "")
    url = _safe_url(item.get("url", ""))
    when = item.get("published_at") or _day(item)
    embed = _youtube_embed(item.get("url", ""))
    desc = descriptions.get(src, "")
    desc_html = f'<p class="mt-1 text-xs text-zinc-400">{_e(desc)}</p>' if desc else ""

    page = f"""{_head(head_title)}
{_CONTENT_STYLE}
</head>
<body class="bg-zinc-50 text-zinc-800 antialiased">
  <header class="border-b border-zinc-200 bg-white">
    <div class="mx-auto max-w-2xl px-4 py-2.5">
      <a href="{_e(_feed_href(src))}" class="text-sm font-bold tracking-tight hover:text-blue-600">← {_e(src) or 'AI Radar'}</a>
    </div>
  </header>
  <main class="mx-auto max-w-2xl px-4 py-6">
    <div class="flex items-center gap-2 text-xs">
      <span class="rounded px-1.5 py-0.5 font-medium {chip}">{_e(cat)}</span>
      {_favicon(src, "h-4 w-4 rounded")}
      <span class="font-mono text-zinc-400">{_e(src)}</span>
      <span class="text-zinc-300">·</span>
      <span class="text-zinc-400">{_e(when)}</span>
    </div>
    {desc_html}
    <h1 class="mt-2 text-2xl font-bold leading-snug">{_e(head_title)}</h1>
    {subtitle}
    <div class="mt-4 flex flex-wrap gap-2">
      <a href="{url}" target="_blank" rel="noopener"
         class="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium hover:border-blue-400 hover:text-blue-600">↗ 打开原文</a>
      <button id="copy-link" data-url="{_e(item.get('url',''))}"
              class="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium hover:border-blue-400 hover:text-blue-600">复制链接</button>
    </div>
    {embed}
{_tabs(item)}
  </main>
{_DETAIL_SCRIPT}
</body>
</html>
"""
    (out / "item" / f"{item.get('hash','')}.html").write_text(page, encoding="utf-8")


def render_site(items, interactions=None, descriptions=None, icons=None, out_dir=None):
    """interactions: {source_id: 'detail'|'link'}；descriptions/icons: {source_label: 说明/头像路径}。
    首页=来源卡片；feed.html=单来源列表；link 模式的源条目直跳原链、不生成详情页。"""
    global _ICONS
    interactions = interactions or {}
    descriptions = descriptions or {}
    _ICONS = icons or {}
    out = Path(out_dir) if out_dir else DIST
    shutil.rmtree(out / "item", ignore_errors=True)
    (out / "item").mkdir(parents=True, exist_ok=True)
    (out / "sources.html").unlink(missing_ok=True)  # 旧来源页已并入首页
    _render_home(items, descriptions, out)
    _render_feed(items, interactions, out)
    for it in items:
        if it.get("hash") and interactions.get(it.get("source_id"), "detail") != "link":
            _render_detail(it, out, descriptions)
    return out / "index.html"
