"""纯 Python 渲染静态站 → dist/index.html。

无模板引擎、无构建链。所有来自外站的字符串渲染前过 html.escape；href 只允许 http(s)。
布局：顶部分类 tab + 搜索；左侧来源栏（按当前分类动态算来源 + 计数，点击二级筛选，
窄屏收成顶部横向胶囊条）；右侧全量 feed，按天分段，每条带分类色块 + 来源徽章 + 链回原文。
分类/来源/搜索三重过滤都是 client-side（规模小到不需要单独的 search.json）。
"""

import html
from datetime import datetime
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / "dist"

# 媒介分类 → chip 配色（Tailwind 类）
_CAT_COLORS = {
    "论文": "bg-violet-100 text-violet-700",
    "研究": "bg-blue-100 text-blue-700",
    "产品": "bg-emerald-100 text-emerald-700",
    "视频": "bg-rose-100 text-rose-700",
    "播客": "bg-amber-100 text-amber-700",
    "Newsletter": "bg-sky-100 text-sky-700",
    "推文": "bg-cyan-100 text-cyan-700",
}
_CAT_DEFAULT = "bg-zinc-100 text-zinc-600"

# client-side 三重过滤（分类 tab + 来源栏 + 搜索）。
# 来源列表按当前分类动态重算计数，单一真源 = 渲染出来的 .item DOM。
# 来源按钮用 createElement + textContent 构建（不用 innerHTML，避免来源名注入）。
_SCRIPT = """
<script>
  const items = [...document.querySelectorAll('.item')];
  const searchEl = document.getElementById('search');
  const sourcesEl = document.getElementById('sources');
  let activeCat = '', activeSource = '';

  const inCat = el => !activeCat || el.dataset.category === activeCat;

  function makeSourceBtn(label, count, src) {
    const b = document.createElement('button');
    b.className = 'src-btn flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-sm md:w-full md:justify-between md:rounded-md md:py-1.5';
    b.dataset.src = src;
    const name = document.createElement('span');
    name.className = 'truncate';
    name.textContent = label;
    const cnt = document.createElement('span');
    cnt.className = 'text-xs text-zinc-400';
    cnt.textContent = count;
    b.append(name, cnt);
    if (src === activeSource) b.classList.add('bg-zinc-100', 'font-medium', 'text-zinc-900');
    else b.classList.add('text-zinc-500');
    b.addEventListener('click', () => { activeSource = src; buildSources(); apply(); });
    return b;
  }

  function buildSources() {
    const counts = new Map();
    items.forEach(el => { if (inCat(el)) counts.set(el.dataset.source, (counts.get(el.dataset.source) || 0) + 1); });
    const total = [...counts.values()].reduce((a, b) => a + b, 0);
    const entries = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    sourcesEl.replaceChildren();
    sourcesEl.appendChild(makeSourceBtn('全部', total, ''));
    entries.forEach(([src, c]) => sourcesEl.appendChild(makeSourceBtn(src, c, src)));
  }

  function apply() {
    const q = searchEl.value.trim().toLowerCase();
    items.forEach(el => {
      const ok = inCat(el)
        && (!activeSource || el.dataset.source === activeSource)
        && (!q || el.dataset.text.includes(q));
      el.style.display = ok ? '' : 'none';
    });
    document.querySelectorAll('.day-section').forEach(sec => {
      const any = [...sec.querySelectorAll('.item')].some(el => el.style.display !== 'none');
      sec.style.display = any ? '' : 'none';
    });
  }

  document.querySelectorAll('.cat-btn').forEach(btn => btn.addEventListener('click', () => {
    activeCat = btn.dataset.cat;
    activeSource = '';  // 切分类时重置来源筛选
    document.querySelectorAll('.cat-btn').forEach(b => {
      const on = (b === btn);
      b.classList.toggle('bg-zinc-800', on);
      b.classList.toggle('text-white', on);
    });
    buildSources();
    apply();
  }));
  searchEl.addEventListener('input', apply);
  buildSources();
  apply();
</script>
"""


def _e(s):
    return html.escape(s or "")


def _safe_url(url):
    u = (url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else "#"


def _day(item):
    return (item.get("fetched_at") or "")[:10] or "未知日期"


def _card(item):
    title = item.get("title_zh") or item.get("title") or ""
    summary = item.get("summary_zh") or item.get("summary") or ""
    cat = item.get("category") or ""
    chip = _CAT_COLORS.get(cat, _CAT_DEFAULT)
    src = item.get("source_label", "")
    when = item.get("published_at") or _day(item)
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
        <a href="{_e(_safe_url(item.get('url','')))}" target="_blank" rel="noopener"
           class="mt-1 block text-base font-medium text-zinc-800 hover:text-blue-600">
          {_e(title)} <span class="text-zinc-300">↗</span>
        </a>
        {summary_html}
      </article>"""


def _category_tabs(categories):
    btns = ['<button class="cat-btn rounded-full px-3 py-1 text-sm bg-zinc-800 text-white" data-cat="">全部</button>']
    for c in categories:
        btns.append(f'<button class="cat-btn rounded-full px-3 py-1 text-sm text-zinc-600" data-cat="{_e(c)}">{_e(c)}</button>')
    return "\n          ".join(btns)


def render_site(items, out_dir=None):
    out = Path(out_dir) if out_dir else DIST
    out.mkdir(parents=True, exist_ok=True)

    categories = sorted({i.get("category", "") for i in items if i.get("category")})

    # 按天分段（items 已是最新在前）
    sections, cur_day, buf = [], None, []
    for it in items:
        d = _day(it)
        if d != cur_day:
            if buf:
                sections.append((cur_day, buf))
            cur_day, buf = d, []
        buf.append(_card(it))
    if buf:
        sections.append((cur_day, buf))

    body = []
    for day, cards in sections:
        body.append(
            f'      <section class="day-section">\n'
            f'        <h2 class="py-2 text-sm font-semibold text-zinc-400">{_e(day)}</h2>\n'
            + "\n".join(cards)
            + "\n      </section>"
        )
    body_html = "\n".join(body) if body else '<p class="py-16 text-center text-zinc-400">暂无内容，跑一次 <code>python3 src/run.py</code> 抓取。</p>'

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Radar</title>
  <script src="https://cdn.tailwindcss.com"></script>
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
{_SCRIPT}
</body>
</html>
"""
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    return index
