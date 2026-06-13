"""纯 Python 渲染静态站。

产物：
- dist/index.html        全量 feed（分类 tab + 左侧来源栏 + 搜索；卡片点击进站内详情页）
- dist/item/<hash>.html  条目详情页（站内展示正文，"打开原文"才外跳；原文/中文翻译/乔木重写 tabs）
- dist/img/<hash>.<ext>  下载进站的图片（由 content.localize_images 写入，此处不动）

外站正文已在入库前用 nh3 清洗 + 图片进站，这里直接渲染；标题/来源等短文本仍过 html.escape。
"""

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

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

# 首页 client-side 三重过滤（分类 tab + 来源栏 + 搜索）
_INDEX_SCRIPT = """
<script>
  const items = [...document.querySelectorAll('.item')];
  const searchEl = document.getElementById('search');
  const sourcesEl = document.getElementById('sources');
  let activeCat = '', activeSource = '';
  const inCat = el => !activeCat || el.dataset.category === activeCat;
  // 来源类型标识（按媒介分类）
  const CAT_ICON = {'论文':'📄','研究':'🔬','产品':'🚀','视频':'▶️','播客':'🎙️','Newsletter':'✉️','资讯':'📰','推文':'🐦'};

  function makeSourceBtn(label, count, src, icon) {
    const b = document.createElement('button');
    b.className = 'src-btn flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-sm md:w-full md:justify-between md:rounded-md md:py-1.5';
    b.dataset.src = src;
    if (src && window.SOURCE_DESC && window.SOURCE_DESC[src]) b.title = window.SOURCE_DESC[src];
    const left = document.createElement('span'); left.className = 'flex min-w-0 items-center gap-1.5';
    if (icon) { const ic = document.createElement('span'); ic.className = 'shrink-0'; ic.textContent = icon; left.appendChild(ic); }
    const name = document.createElement('span'); name.className = 'truncate'; name.textContent = label; left.appendChild(name);
    const cnt = document.createElement('span'); cnt.className = 'shrink-0 text-xs text-zinc-400'; cnt.textContent = count;
    b.append(left, cnt);
    b.classList.add(src === activeSource ? 'bg-zinc-100' : 'text-zinc-500');
    if (src === activeSource) b.classList.add('font-medium', 'text-zinc-900');
    b.addEventListener('click', () => { activeSource = src; buildSources(); apply(); });
    return b;
  }
  function buildSources() {
    const counts = new Map(), cats = new Map();
    items.forEach(el => {
      if (!inCat(el)) return;
      const s = el.dataset.source;
      counts.set(s, (counts.get(s) || 0) + 1);
      cats.set(s, el.dataset.category);
    });
    const total = [...counts.values()].reduce((a, b) => a + b, 0);
    const entries = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    sourcesEl.replaceChildren();
    sourcesEl.appendChild(makeSourceBtn('全部', total, '', ''));
    entries.forEach(([src, c]) => sourcesEl.appendChild(makeSourceBtn(src, c, src, CAT_ICON[cats.get(src)] || '•')));
  }
  function apply() {
    const q = searchEl.value.trim().toLowerCase();
    items.forEach(el => {
      const ok = inCat(el) && (!activeSource || el.dataset.source === activeSource) && (!q || el.dataset.text.includes(q));
      el.style.display = ok ? '' : 'none';
    });
    document.querySelectorAll('.day-section').forEach(sec => {
      const any = [...sec.querySelectorAll('.item')].some(el => el.style.display !== 'none');
      sec.style.display = any ? '' : 'none';
    });
  }
  document.querySelectorAll('.cat-btn').forEach(btn => btn.addEventListener('click', () => {
    activeCat = btn.dataset.cat; activeSource = '';
    document.querySelectorAll('.cat-btn').forEach(b => { const on = (b === btn); b.classList.toggle('bg-zinc-800', on); b.classList.toggle('text-white', on); });
    buildSources(); apply();
  }));
  searchEl.addEventListener('input', apply);
  buildSources(); apply();
</script>
"""

# 详情页 tab 切换 + 复制链接
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
  // 点击封面门面 → 加载 YouTube 播放器（用户手势触发）
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


def _youtube_embed(url):
    """youtube 链接 → 缩略图门面（lite-youtube）：先显示封面+播放钮，点击才加载播放器。
    避免一进页面就内嵌 iframe（YouTube 反爬「确认非 bot」在无用户手势时更易触发），也更省资源。
    iframe 在点击时由 _DETAIL_SCRIPT 用 createElement 生成（不过 nh3）；video id 限 [A-Za-z0-9_-]{11}，无注入。"""
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


# ---------- 首页卡片 ----------

def _card(item, mode="detail"):
    title = item.get("title_zh") or item.get("title") or ""
    summary = item.get("summary_zh") or item.get("summary") or ""
    cat = item.get("category") or ""
    chip = _CAT_COLORS.get(cat, _CAT_DEFAULT)
    src = item.get("source_label", "")
    when = item.get("published_at") or _day(item)
    # open=link：标题直跳原链；open=detail：进站内详情页
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
    return f"""      <article class="item border-b border-zinc-100 py-4" data-category="{_e(cat)}" data-source="{_e(src)}" data-text="{search_blob}">
        <div class="flex items-center gap-2 text-xs">
          <span class="rounded px-1.5 py-0.5 font-medium {chip}">{_e(cat)}</span>
          <span class="font-mono text-zinc-400">{_e(src)}</span>
          <span class="text-zinc-300">·</span>
          <span class="text-zinc-400">{_e(when)}</span>
        </div>
        <a href="{href}"{link_attrs} class="mt-1 block text-base font-medium text-zinc-800 hover:text-blue-600">{_e(title)}{arrow}</a>
        {summary_html}
      </article>"""


def _category_tabs(categories):
    btns = ['<button class="cat-btn rounded-full px-3 py-1 text-sm bg-zinc-800 text-white" data-cat="">全部</button>']
    for c in categories:
        btns.append(f'<button class="cat-btn rounded-full px-3 py-1 text-sm text-zinc-600" data-cat="{_e(c)}">{_e(c)}</button>')
    return "\n          ".join(btns)


def _render_index(items, out, interactions, descriptions):
    desc_json = json.dumps(descriptions, ensure_ascii=False)
    categories = sorted({i.get("category", "") for i in items if i.get("category")})
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
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    page = f"""{_head("AI Radar")}
</head>
<body class="bg-zinc-50 text-zinc-800 antialiased">
  <header class="sticky top-0 z-10 border-b border-zinc-200 bg-white/90 backdrop-blur">
    <div class="mx-auto max-w-5xl px-4 py-2.5">
      <div class="flex items-center gap-3">
        <h1 class="text-lg font-bold tracking-tight">AI&nbsp;Radar</h1>
        <input id="search" type="search" placeholder="搜索…"
               class="ml-auto w-40 rounded-full border border-zinc-200 px-3 py-1 text-sm outline-none focus:border-blue-400">
      </div>
      <div id="cats" class="mt-2 flex flex-wrap gap-1.5">
          {_category_tabs(categories)}
      </div>
    </div>
  </header>
  <div class="mx-auto max-w-5xl gap-8 px-4 md:flex">
    <aside class="md:sticky md:top-[112px] md:h-[calc(100vh-120px)] md:w-52 md:shrink-0 md:self-start md:overflow-y-auto">
      <p class="hidden pt-4 text-xs font-semibold text-zinc-400 md:block">来源</p>
      <div id="sources" class="flex gap-1.5 overflow-x-auto py-3 md:flex-col md:gap-0.5 md:py-2"></div>
    </aside>
    <main class="min-w-0 max-w-2xl flex-1">
{body_html}
      <p class="py-8 text-center text-xs text-zinc-300">共 {len(items)} 条 · 生成于 {generated}</p>
    </main>
  </div>
  <script>window.SOURCE_DESC = {desc_json};</script>
{_INDEX_SCRIPT}
</body>
</html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


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
    url = _safe_url(item.get("url", ""))
    when = item.get("published_at") or _day(item)
    embed = _youtube_embed(item.get("url", ""))  # 视频→站内可播
    desc = descriptions.get(item.get("source_label", ""), "")
    desc_html = f'<p class="mt-1 text-xs text-zinc-400">{_e(desc)}</p>' if desc else ""

    page = f"""{_head(head_title)}
{_CONTENT_STYLE}
</head>
<body class="bg-zinc-50 text-zinc-800 antialiased">
  <header class="border-b border-zinc-200 bg-white">
    <div class="mx-auto max-w-2xl px-4 py-2.5">
      <a href="/" class="text-sm font-bold tracking-tight hover:text-blue-600">← AI&nbsp;Radar</a>
    </div>
  </header>
  <main class="mx-auto max-w-2xl px-4 py-6">
    <div class="flex items-center gap-2 text-xs">
      <span class="rounded px-1.5 py-0.5 font-medium {chip}">{_e(cat)}</span>
      <span class="font-mono text-zinc-400">{_e(item.get('source_label',''))}</span>
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


def render_site(items, interactions=None, descriptions=None, out_dir=None):
    """interactions: {source_id: 'detail'|'link'}；descriptions: {source_label: 说明}。
    link 模式的源卡片直跳原链、不生成详情页。"""
    interactions = interactions or {}
    descriptions = descriptions or {}
    out = Path(out_dir) if out_dir else DIST
    # 清掉旧详情页，避免改成 link 模式 / 被 retention 删掉的条目残留页面
    shutil.rmtree(out / "item", ignore_errors=True)
    (out / "item").mkdir(parents=True, exist_ok=True)
    _render_index(items, out, interactions, descriptions)
    for it in items:
        if it.get("hash") and interactions.get(it.get("source_id"), "detail") != "link":
            _render_detail(it, out, descriptions)
    return out / "index.html"
