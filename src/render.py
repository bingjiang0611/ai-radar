"""纯 Python 渲染静态站（编辑体阅读风 · 深色可切 · 手写 token，无 Tailwind）。

产物（URL 结构不变）：
- dist/index.html        首页 = 报头 + 「最新」头版 + 来源目录（按分类分区 + 搜索）
- dist/feed.html         时间流（无 ?source，排除推文）/ 单来源列表（?source=<label>）
- dist/item/<hash>.html  条目详情：文章态（content_html）/ 视频态（YouTube 门面）
- dist/img/<hash>.<ext>  下载进站的图片（content.localize_images 写入，此处不动）

设计系统照搬高保真蓝本：serif=编辑体内容/标题、sans=产品 chrome、mono=元信息；
8 类色只用于 dot / 类别名 / avatar 渐变，不做满色 pill。主题持久化 localStorage('air-theme')。
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

# 分类 → CSS 类（提供 --cat 色）+ 英文副名 + 排序
_CAT_CLASS = {
    "研究": "c-research", "产品": "c-product", "Newsletter": "c-newsletter", "资讯": "c-news",
    "论文": "c-paper", "播客": "c-podcast", "视频": "c-video", "推文": "c-tweet",
}
_CAT_EN = {
    "研究": "Research", "产品": "Product", "Newsletter": "Newsletter", "资讯": "News",
    "论文": "Papers", "播客": "Podcast", "视频": "Video", "推文": "Tweets",
}
_CAT_ORDER = ["推文", "资讯", "视频", "Newsletter", "产品", "研究", "论文", "播客"]
_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

_ICONS = {}  # source_label -> /icons/<domain>.png（render_site 注入）

# ---------- SVG（内联，不引 icon font）----------
_BRAND_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
              '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
              '<circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>'
              '<path d="M12 12 L19 6.5" stroke-linecap="round"/></svg>')
_SUNMOON_SVG = ('<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
                '<circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22'
                'M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" stroke-linecap="round"/></svg>'
                '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
                '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.3 6.3 0 0 0 10.5 10.5z" stroke-linejoin="round"/></svg>')
_SEARCH_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
               '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4" stroke-linecap="round"/></svg>')
_PLAY_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
_EXTLINK_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                '<path d="M7 17L17 7M9 7h8v8" stroke-linecap="round" stroke-linejoin="round"/></svg>')
_COPY_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
             '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10" stroke-linecap="round"/></svg>')
_TR_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">'
           '<path d="M4 5h7M9 3v2c0 4-2 7-5 9M5 9c0 3 3 5 7 6" stroke-linecap="round" stroke-linejoin="round"/>'
           '<path d="M14 20l4-9 4 9M15.5 17h5" stroke-linecap="round" stroke-linejoin="round"/></svg>')

# ---------- 主题预设（CSS 前内联，防闪白）----------
_THEME_PRESET = ("try{var t=localStorage.getItem('air-theme');"
                 "if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme:dark)').matches))"
                 "document.documentElement.setAttribute('data-theme','dark');"
                 "else document.documentElement.setAttribute('data-theme','light');}catch(e){}")

_FONT_LINKS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
               '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
               '<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;'
               '6..72,600;6..72,700;6..72,400i;6..72,500i&display=swap" rel="stylesheet">')

# ---------- 设计系统（基础，全页共用）----------
_BASE_CSS = """
:root{
  --bg:oklch(98.6% 0.004 255);--surface:oklch(100% 0 0);--surface-2:oklch(97% 0.005 255);
  --inset:oklch(95.5% 0.006 255);--fg:oklch(24% 0.018 262);--fg-2:oklch(43% 0.016 262);
  --muted:oklch(55% 0.013 260);--faint:oklch(66% 0.011 260);--border:oklch(91.5% 0.006 262);
  --border-2:oklch(86% 0.008 262);--accent:oklch(54% 0.16 256);--accent-2:oklch(48% 0.16 256);
  --accent-soft:oklch(95.5% 0.03 256);--accent-line:oklch(82% 0.07 256);
  --shadow:0 1px 2px oklch(24% 0.02 262 / .05),0 8px 24px -12px oklch(24% 0.04 262 / .18);
  --c-research:oklch(56% 0.135 255);--c-product:oklch(57% 0.11 165);--c-newsletter:oklch(56% 0.15 300);
  --c-news:oklch(62% 0.13 66);--c-paper:oklch(56% 0.13 212);--c-podcast:oklch(58% 0.16 352);
  --c-video:oklch(60% 0.17 27);--c-tweet:oklch(62% 0.115 196);
  --serif:'Newsreader','Iowan Old Style','Source Serif 4',Charter,Georgia,'Songti SC',serif;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',system-ui,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono','Menlo',monospace;
  --maxw:1080px;
}
[data-theme="dark"]{
  --bg:oklch(18.5% 0.016 262);--surface:oklch(21.5% 0.017 262);--surface-2:oklch(24% 0.017 262);
  --inset:oklch(26% 0.017 262);--fg:oklch(92% 0.012 255);--fg-2:oklch(78% 0.014 255);
  --muted:oklch(66% 0.014 258);--faint:oklch(54% 0.014 258);--border:oklch(30% 0.014 262);
  --border-2:oklch(36% 0.016 262);--accent:oklch(72% 0.14 256);--accent-2:oklch(78% 0.13 256);
  --accent-soft:oklch(30% 0.05 256);--accent-line:oklch(42% 0.09 256);
  --shadow:0 1px 2px oklch(0% 0 0 / .3),0 14px 34px -16px oklch(0% 0 0 / .6);
  --c-research:oklch(72% 0.13 255);--c-product:oklch(73% 0.11 165);--c-newsletter:oklch(73% 0.13 300);
  --c-news:oklch(76% 0.12 70);--c-paper:oklch(73% 0.12 212);--c-podcast:oklch(74% 0.14 352);
  --c-video:oklch(74% 0.15 28);--c-tweet:oklch(76% 0.1 196);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.55;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;transition:background .25s ease,color .25s ease}
a{color:inherit;text-decoration:none}
img{max-width:100%}
::selection{background:var(--accent-soft);color:var(--accent-2)}
.c-research{--cat:var(--c-research)}.c-product{--cat:var(--c-product)}.c-newsletter{--cat:var(--c-newsletter)}
.c-news{--cat:var(--c-news)}.c-paper{--cat:var(--c-paper)}.c-podcast{--cat:var(--c-podcast)}
.c-video{--cat:var(--c-video)}.c-tweet{--cat:var(--c-tweet)}
.top{position:sticky;top:0;z-index:50;background:color-mix(in oklch,var(--bg) 88%,transparent);
  backdrop-filter:saturate(1.4) blur(12px);-webkit-backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--border)}
.top-in{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;gap:16px;padding:11px 24px}
.brand{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-weight:600;font-size:13px;letter-spacing:.16em;text-transform:uppercase}
.brand svg{width:20px;height:20px;color:var(--accent);flex:none}
.nav{display:flex;gap:4px;margin-left:6px}
.nav a{font-size:13.5px;font-weight:500;color:var(--muted);padding:5px 11px;border-radius:7px;transition:.15s}
.nav a:hover{color:var(--fg);background:var(--surface-2)}
.nav a.on{color:var(--fg);background:var(--inset)}
.stat{margin-left:6px;font-family:var(--mono);font-size:11.5px;color:var(--faint);letter-spacing:.02em}
.top-right{margin-left:auto;display:flex;align-items:center;gap:9px}
.search{position:relative}
.search input{width:190px;background:var(--surface-2);border:1px solid var(--border);color:var(--fg);
  border-radius:999px;padding:7px 12px 7px 32px;font-size:13px;font-family:var(--sans);outline:none;transition:.18s}
.search input:focus{border-color:var(--accent-line);background:var(--surface)}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:var(--faint)}
.icon-btn{width:34px;height:34px;display:grid;place-items:center;border:1px solid var(--border);
  background:var(--surface-2);color:var(--fg-2);border-radius:9px;cursor:pointer;transition:.15s}
.icon-btn:hover{border-color:var(--border-2);color:var(--fg)}
.icon-btn svg{width:16px;height:16px}
[data-theme="light"] .moon{display:none}[data-theme="dark"] .sun{display:none}
.foot{max-width:var(--maxw);margin:0 auto;padding:22px 24px 40px;display:flex;gap:13px;flex-wrap:wrap;align-items:center;
  border-top:1px solid var(--border);font-family:var(--mono);font-size:11px;color:var(--faint)}
.foot .sep{opacity:.5}
.empty{display:none;text-align:center;color:var(--faint);font-size:14px;padding:54px 0}
.lightbox{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;padding:24px;
  cursor:zoom-out;background:oklch(12% 0.02 262 / .9);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
.lightbox img{max-width:92vw;max-height:92vh;border-radius:10px;box-shadow:0 20px 60px -10px oklch(0% 0 0 / .6)}
@media(max-width:560px){.top-in{padding:10px 16px;gap:10px}.brand span{display:none}}
"""

_HOME_CSS = """
.wrap{max-width:var(--maxw);margin:0 auto;padding:30px 24px 56px}
.kicker{display:flex;align-items:center;gap:10px;margin:0 0 16px}
.kicker h2{font-family:var(--mono);font-size:11.5px;font-weight:600;letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.kicker .cnt{font-family:var(--mono);font-size:11px;color:var(--faint)}
.kicker .rule{flex:1;height:1px;background:var(--border)}
.front{display:grid;grid-template-columns:1.5fr 1fr;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--surface);box-shadow:var(--shadow)}
.lead{padding:26px 28px;border-right:1px solid var(--border);display:flex;flex-direction:column;min-height:260px}
.meta{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;color:var(--muted)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--cat,var(--accent));flex:none}
.meta .src{color:var(--fg-2);font-weight:500}
.lead h3{font-family:var(--serif);font-weight:500;font-size:31px;line-height:1.16;letter-spacing:-.01em;margin:14px 0 10px;text-wrap:balance}
.lead:hover h3{color:var(--accent-2)}
.lead-sub{font-family:var(--serif);font-style:italic;font-size:16px;line-height:1.35;color:var(--muted);margin:-2px 0 12px;max-width:52ch}
.lead p{color:var(--fg-2);font-size:14.5px;line-height:1.6;max-width:54ch;
  display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden}
.lead .when{margin-top:16px;font-family:var(--mono);font-size:11px;color:var(--faint)}
.lead{justify-content:center}
.mini-list{display:flex;flex-direction:column}
.mini{padding:15px 24px;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:7px;transition:background .15s}
.mini:last-child{border-bottom:0}
.mini:hover{background:var(--surface-2)}
.mini h4{font-family:var(--serif);font-weight:500;font-size:16.5px;line-height:1.3;letter-spacing:-.005em}
.mini:hover h4{color:var(--accent-2)}
.dir{margin-top:42px}
.cat-section{margin-bottom:34px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.src-card{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:16px 17px;transition:transform .16s ease,border-color .16s,box-shadow .16s}
.src-card:hover{border-color:var(--accent-line);transform:translateY(-2px);box-shadow:var(--shadow)}
.sc-top{display:flex;align-items:center;gap:10px;margin-bottom:11px}
.avatar{width:34px;height:34px;border-radius:9px;flex:none;display:grid;place-items:center;
  font-family:var(--serif);font-weight:600;font-size:16px;color:#fff;
  background:linear-gradient(150deg,var(--cat,var(--accent)),color-mix(in oklch,var(--cat,var(--accent)) 62%,black))}
.avatar-img{width:34px;height:34px;border-radius:9px;flex:none;object-fit:contain;background:#fff;border:1px solid var(--border)}
.sc-name{font-weight:600;font-size:14.5px;line-height:1.25;letter-spacing:-.01em}
.sc-cat{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--cat,var(--muted));display:flex;align-items:center;gap:5px;margin-top:2px}
.sc-cat .dot{width:5px;height:5px}
.src-card p{color:var(--muted);font-size:12.8px;line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sc-foot{margin-top:auto;padding-top:13px;display:flex;align-items:center;justify-content:space-between;gap:8px;font-family:var(--mono);font-size:10.5px;color:var(--faint)}
.sc-foot .n{color:var(--fg-2);background:var(--inset);padding:2px 7px;border-radius:6px}
.sc-foot .b{color:var(--muted);border:1px solid var(--border-2);padding:1px 6px;border-radius:6px;letter-spacing:.04em}
@media(max-width:880px){.grid{grid-template-columns:repeat(2,1fr)}.front{grid-template-columns:1fr}
  .lead{border-right:0;border-bottom:1px solid var(--border);min-height:0}.lead h3{font-size:27px}.stat,.nav{display:none}}
@media(max-width:560px){.wrap{padding:22px 16px 48px}.grid{grid-template-columns:1fr}.search input{width:150px}}
"""

_FEED_CSS = """
.wrap{max-width:var(--maxw);margin:0 auto;padding:26px 24px 56px}
.feed-head{margin-bottom:16px}
.feed-head .back{font-family:var(--mono);font-size:11.5px;letter-spacing:.04em;color:var(--muted)}
.feed-head .back:hover{color:var(--accent-2)}
.feed-head h1{font-family:var(--serif);font-weight:500;font-size:30px;letter-spacing:-.01em;margin:8px 0 3px}
.feed-head .sub{font-family:var(--mono);font-size:11.5px;color:var(--faint)}
.pills{display:flex;gap:7px;flex-wrap:wrap;margin-top:16px}
.pill{font-size:12.5px;font-weight:500;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);
  padding:5px 12px;border-radius:999px;cursor:pointer;transition:.14s;display:flex;align-items:center;gap:6px}
.pill:hover{border-color:var(--border-2);color:var(--fg)}
.pill .dot{width:6px;height:6px;border-radius:50%;background:var(--cat,var(--faint))}
.pill.on{color:var(--surface);background:var(--fg);border-color:var(--fg)}
.pill.on .dot{background:var(--surface)}
.day{margin-top:8px}
.day-label{position:sticky;top:54px;z-index:5;display:flex;align-items:center;gap:10px;padding:14px 0 8px;
  background:linear-gradient(var(--bg) 70%,transparent)}
.day-label .d{font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.1em;color:var(--fg-2)}
.day-label .w{font-family:var(--mono);font-size:11px;color:var(--faint)}
.day-label .rule{flex:1;height:1px;background:var(--border)}
.day-label .n{font-family:var(--mono);font-size:11px;color:var(--faint)}
.item{display:flex;gap:13px;padding:15px 12px;margin:0 -12px;border-radius:10px;transition:background .14s}
.item+.item{border-top:1px solid var(--border)}
.item:hover{background:var(--surface-2)}
.avatar{width:30px;height:30px;border-radius:8px;flex:none;display:grid;place-items:center;margin-top:1px;
  font-family:var(--serif);font-weight:600;font-size:13.5px;color:#fff;
  background:linear-gradient(150deg,var(--cat,var(--accent)),color-mix(in oklch,var(--cat,var(--accent)) 62%,black))}
.avatar-img{width:30px;height:30px;border-radius:8px;flex:none;margin-top:1px;object-fit:contain;background:#fff;border:1px solid var(--border)}
.it-body{min-width:0;flex:1}
.it-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;margin-bottom:3px}
.it-meta .src{font-weight:600;color:var(--fg)}
.tag{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--cat);padding:1.5px 7px;border-radius:5px;background:color-mix(in oklch,var(--cat) 12%,transparent);border:1px solid color-mix(in oklch,var(--cat) 26%,transparent)}
.tag .dot{width:5px;height:5px;border-radius:50%;background:var(--cat)}
.it-meta .time{font-family:var(--mono);font-size:11px;color:var(--faint);margin-left:auto}
.it-title{font-family:var(--serif);font-weight:500;font-size:17.5px;line-height:1.34;letter-spacing:-.005em;color:var(--fg)}
.item:hover .it-title{color:var(--accent-2)}
.it-sum{color:var(--muted);font-size:13.2px;line-height:1.55;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.it-title .ext{font-size:12px;color:var(--faint);margin-left:3px}
.it-orig{color:var(--faint);font-size:13px;line-height:1.55;margin-top:5px;font-style:italic;font-family:var(--serif)}
.it-media{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}
.it-media img{max-height:200px;max-width:100%;border-radius:10px;border:1px solid var(--border);object-fit:cover}
.play{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;margin-right:6px;vertical-align:-2px;color:var(--cat)}
.play svg{width:14px;height:14px}
@media(max-width:560px){.wrap{padding:20px 16px 48px}.nav{display:none}.search input{width:130px}
  .feed-head h1{font-size:25px}.it-meta .time{margin-left:0}.day-label{top:52px}}
"""

_DETAIL_CSS = """
.progress{position:fixed;top:0;left:0;height:2.5px;width:0;background:var(--accent);z-index:60;transition:width .08s linear}
.top-in{max-width:920px;gap:14px}
.back{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:12px;letter-spacing:.04em;color:var(--muted)}
.back:hover{color:var(--accent-2)}
.back .av{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-family:var(--serif);font-weight:600;font-size:11px;color:#fff;
  background:linear-gradient(150deg,var(--cat,var(--accent)),color-mix(in oklch,var(--cat,var(--accent)) 62%,black))}
.back .av-img{width:20px;height:20px;border-radius:6px;object-fit:contain;background:#fff;border:1px solid var(--border)}
.wrap{max-width:var(--maxw);margin:0 auto;padding:34px 24px 80px}
.a-meta{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
.tag{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--cat);padding:2px 8px;border-radius:5px;background:color-mix(in oklch,var(--cat) 12%,transparent);border:1px solid color-mix(in oklch,var(--cat) 26%,transparent)}
.tag .dot{width:5px;height:5px;border-radius:50%;background:var(--cat)}
.a-meta .src{font-weight:600;color:var(--fg-2)}
.a-meta .mono{font-family:var(--mono);font-size:11px;color:var(--faint)}
h1.title{font-family:var(--serif);font-weight:600;font-size:clamp(28px,3.4vw,39px);line-height:1.15;letter-spacing:-.015em;margin:16px 0 8px;text-wrap:balance}
.subtitle{font-family:var(--serif);font-style:italic;font-weight:400;font-size:19px;line-height:1.35;color:var(--muted)}
.actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:22px 0 4px}
.btn{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:500;font-family:var(--sans);
  border:1px solid var(--border);background:var(--surface);color:var(--fg);padding:8px 14px;border-radius:9px;cursor:pointer;transition:.15s}
.btn:hover{border-color:var(--accent-line);color:var(--accent-2)}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.primary:hover{background:var(--accent-2);color:#fff}
.btn svg{width:14px;height:14px}
.read-time{font-family:var(--mono);font-size:11px;color:var(--faint);margin-left:auto}
.tabs{display:inline-flex;gap:3px;background:var(--inset);padding:3px;border-radius:10px;margin:24px 0 6px}
.tab{font-size:13px;font-weight:500;color:var(--muted);padding:6px 16px;border-radius:7px;cursor:pointer;border:0;background:transparent;font-family:var(--sans);transition:.15s}
.tab.on{background:var(--surface);color:var(--fg);box-shadow:var(--shadow)}
.panel{display:none}.panel.on{display:block}
.doc{font-family:var(--serif);font-size:18.5px;line-height:1.78;color:var(--fg);margin-top:14px}
.doc p{margin:1.05em 0}
.doc a{color:var(--accent-2);text-decoration:underline;text-underline-offset:2.5px;text-decoration-thickness:1px;text-decoration-color:var(--accent-line)}
.doc a:hover{text-decoration-color:var(--accent-2)}
.doc h1,.doc h2,.doc h3,.doc h4{font-family:var(--serif);font-weight:600;line-height:1.25;letter-spacing:-.01em;margin:1.7em 0 .5em}
.doc h2{font-size:25px}.doc h3{font-size:21px}.doc h4{font-size:18px}
.doc strong{font-weight:600}.doc em{font-style:italic}
.doc ul,.doc ol{margin:1.05em 0;padding-left:1.4em}
.doc ul{list-style:none}.doc ul li{position:relative;margin:.5em 0;padding-left:.2em}
.doc ul li::before{content:"";position:absolute;left:-.9em;top:.72em;width:5px;height:5px;border-radius:50%;background:var(--accent-line)}
.doc ol{list-style:decimal}.doc ol li{margin:.5em 0;padding-left:.2em}
.doc blockquote{margin:1.4em 0;padding:.2em 0 .2em 1.3em;border-left:3px solid var(--accent-line);font-style:italic;font-size:20px;line-height:1.5;color:var(--fg-2)}
.doc img{display:block;max-width:100%;height:auto;border-radius:12px;margin:1.6em auto}
.doc pre{font-family:var(--mono);font-size:14px;background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:14px 16px;overflow-x:auto;margin:1.3em 0;line-height:1.5}
.doc code{font-family:var(--mono);font-size:.86em;background:var(--inset);padding:.12em .35em;border-radius:5px}
.doc pre code{background:none;padding:0}
.doc figure{margin:1.8em 0}
.doc figcaption{font-family:var(--mono);font-size:11px;color:var(--faint);text-align:center;margin-top:9px}
.doc hr{border:0;text-align:center;margin:2.2em 0}
.doc hr::before{content:"\\002731";color:var(--faint);font-size:14px;letter-spacing:.4em}
.doc .src-note{margin-top:2.4em;padding-top:1.2em;border-top:1px solid var(--border);font-family:var(--sans);font-size:13px;color:var(--muted)}
.tr-empty{display:flex;flex-direction:column;align-items:center;text-align:center;gap:12px;padding:56px 24px;
  background:var(--surface-2);border:1px solid var(--border);border-radius:14px;margin-top:14px}
.tr-empty .ico{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;background:var(--accent-soft);color:var(--accent-2)}
.tr-empty .ico svg{width:24px;height:24px}
.tr-empty h3{font-family:var(--serif);font-weight:500;font-size:21px;color:var(--fg)}
.tr-empty p{font-size:13.5px;color:var(--muted);max-width:42ch;line-height:1.6}
.tr-empty .why{font-family:var(--mono);font-size:11px;color:var(--faint);margin-top:2px}
.facade{position:relative;aspect-ratio:16/9;border-radius:16px;overflow:hidden;cursor:pointer;background:oklch(15% 0.02 262);box-shadow:var(--shadow);border:1px solid var(--border);margin-bottom:4px}
.facade .thumb{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.92;transition:.18s}
.facade:hover .thumb{opacity:1}
.facade .play{position:absolute;inset:0;display:grid;place-items:center}
.facade .play .pbtn{width:84px;height:60px;border-radius:18px;background:oklch(20% 0 0 / .72);display:grid;place-items:center;color:#fff;transition:.18s;backdrop-filter:blur(2px)}
.facade:hover .play .pbtn{background:oklch(58% 0.2 27);transform:scale(1.04)}
.facade .play .pbtn svg{width:34px;height:34px;margin-left:3px}
.facade .ov{position:absolute;left:0;right:0;bottom:0;padding:46px 22px 16px;display:flex;align-items:flex-end;gap:9px;color:#fff;
  background:linear-gradient(transparent,oklch(12% 0.02 262 / .82))}
.facade .ov .dotmark{width:30px;height:30px;border-radius:50%;background:#fff;display:grid;place-items:center;color:#111;font-family:var(--serif);font-weight:600;font-size:14px;flex:none}
.facade .ov .nm{font-size:13.5px;font-weight:600}
.facade .ov .sub2{font-size:11px;color:oklch(85% 0 0 / .8);font-family:var(--mono)}
.facade .hint{position:absolute;top:18px;right:18px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:oklch(92% 0 0 / .8);background:oklch(12% 0 0 / .45);padding:4px 9px;border-radius:999px}
@media(max-width:560px){.top-in{padding:10px 16px}.wrap{padding:24px 18px 64px}
  h1.title{font-size:27px}.subtitle{font-size:17px}.doc{font-size:17.5px}.read-time{display:none}
  .facade{border-radius:12px}.facade .play .pbtn{width:68px;height:48px}}
"""

# ---------- JS ----------
_THEME_JS = ("document.getElementById('theme').addEventListener('click',function(){"
             "var d=document.documentElement,n=d.getAttribute('data-theme')==='dark'?'light':'dark';"
             "d.setAttribute('data-theme',n);try{localStorage.setItem('air-theme',n);}catch(e){}});")

_HOME_JS = """
(function(){var input=document.getElementById('search'),
  cards=[].slice.call(document.querySelectorAll('.src-card')),
  secs=[].slice.call(document.querySelectorAll('.cat-section')),empty=document.getElementById('empty');
  if(!input)return;
  input.addEventListener('input',function(){var q=input.value.trim().toLowerCase(),hit=0;
    cards.forEach(function(c){var ok=!q||(c.dataset.text||'').indexOf(q)>-1;c.style.display=ok?'':'none';if(ok)hit++;});
    secs.forEach(function(s){var any=[].slice.call(s.querySelectorAll('.src-card')).some(function(c){return c.style.display!=='none';});s.style.display=any?'':'none';});
    if(empty)empty.style.display=hit?'none':'block';});})();
"""

_FEED_JS = """
(function(){
  var input=document.getElementById('search'),pills=[].slice.call(document.querySelectorAll('.pill')),
    items=[].slice.call(document.querySelectorAll('.item')),days=[].slice.call(document.querySelectorAll('.day')),
    empty=document.getElementById('empty'),cat='',
    src=new URLSearchParams(location.search).get('source')||'',
    titleEl=document.getElementById('feed-title'),subEl=document.getElementById('feed-sub'),pillBox=document.getElementById('pills');
  if(src){if(titleEl)titleEl.textContent=src;if(subEl)subEl.textContent='单一来源 · 按时间倒序';if(pillBox)pillBox.style.display='none';}
  function apply(){var q=(input&&input.value||'').trim().toLowerCase(),hit=0;
    items.forEach(function(el){
      var inFeed=src?el.dataset.source===src:el.dataset.cat!=='推文';
      var ok=inFeed&&(!cat||el.dataset.cat===cat)&&(!q||(el.dataset.text||'').indexOf(q)>-1);
      el.style.display=ok?'':'none';if(ok)hit++;});
    days.forEach(function(s){var any=[].slice.call(s.querySelectorAll('.item')).some(function(el){return el.style.display!=='none';});s.style.display=any?'':'none';});
    if(empty)empty.style.display=hit?'none':'block';}
  pills.forEach(function(p){p.addEventListener('click',function(){pills.forEach(function(x){x.classList.toggle('on',x===p);});cat=p.dataset.cat||'';apply();});});
  if(input)input.addEventListener('input',apply);
  apply();})();
"""

_DETAIL_JS = """
var tabs=[].slice.call(document.querySelectorAll('.tab')),panels=[].slice.call(document.querySelectorAll('.panel'));
tabs.forEach(function(b){b.addEventListener('click',function(){
  tabs.forEach(function(x){x.classList.toggle('on',x===b);});
  panels.forEach(function(p){p.classList.toggle('on',p.id===b.dataset.panel);});});});
var copy=document.getElementById('copy');
if(copy)copy.addEventListener('click',function(){var s=copy.querySelector('span');
  navigator.clipboard.writeText(copy.dataset.url).then(function(){s.textContent='已复制';setTimeout(function(){s.textContent='复制链接';},1500);});});
var bar=document.getElementById('progress');
if(bar)window.addEventListener('scroll',function(){var h=document.documentElement,max=h.scrollHeight-h.clientHeight;
  bar.style.width=(max>0?(h.scrollTop/max*100):0)+'%';},{passive:true});
var f=document.getElementById('facade');
if(f)f.addEventListener('click',function(){var id=f.dataset.id;if(!/^[\\w-]{11}$/.test(id))return;
  var ifr=document.createElement('iframe');
  ifr.style.cssText='position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:16px';
  ifr.allow='accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture';
  ifr.allowFullscreen=true;ifr.src='https://www.youtube.com/embed/'+id+'?autoplay=1';
  f.replaceWith(ifr);},{once:true});
"""


_LIGHTBOX_JS = """
(function(){
  function open(src){
    var ov=document.createElement('div');ov.className='lightbox';
    var im=document.createElement('img');im.src=src;ov.appendChild(im);
    ov.addEventListener('click',function(){ov.remove();});
    document.body.appendChild(ov);
  }
  [].slice.call(document.querySelectorAll('.it-media img, .doc img')).forEach(function(im){
    im.style.cursor='zoom-in';
    im.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();open(im.currentSrc||im.src);});
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){var l=document.querySelector('.lightbox');if(l)l.remove();}});
})();
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


def _yt_id(url):
    m = _YT_RE.search(url or "")
    return m.group(1) if m else ""


def _cat_class(cat):
    return _CAT_CLASS.get(cat, "c-research")


def _monogram(label):
    s = (label or "").strip()
    if not s:
        return "•"
    if s[0].isdigit():
        return re.match(r"\d+", s).group(0)[:2]
    return s[0]


def _avatar(label, kind="avatar"):
    """kind=avatar(home/feed) / av(detail back)。有 favicon 用图，否则首字母 monogram + 类别色渐变。"""
    icon = _ICONS.get(label, "")
    if icon:
        return f'<img class="{kind}-img" src="{_e(icon)}" alt="" loading="lazy">'
    return f'<span class="{kind}">{_e(_monogram(label))}</span>'


def _fmt_md(s):
    """'2026-06-14...' → '06-14'。非 ISO(如 RFC822 pubDate)返回 ""，由调用方回退 fetched_at。"""
    s = (s or "")[:10]
    return s[5:] if (len(s) == 10 and s[4] == "-" and s[7] == "-") else ""


def _fmt_time(item):
    """published_at 有时间则 'MM-DD · HH:MM'，否则只 'MM-DD'。"""
    p = item.get("published_at") or ""
    d = _fmt_md(p) or _fmt_md(item.get("fetched_at"))
    m = re.search(r"T(\d{2}:\d{2})", p)
    return f"{d} · {m.group(1)}" if m and d else d


def _weekday(date_str):
    try:
        return _WEEKDAY[datetime.strptime((date_str or "")[:10], "%Y-%m-%d").weekday()]
    except ValueError:
        return ""


def _read_time(content_html):
    text = re.sub(r"<[^>]+>", "", content_html or "")
    n = len(text.strip())
    return f"约 {max(1, round(n / 400))} 分钟读" if n >= 60 else ""


def _item_href(item, interactions):
    """详情态 → 站内 /item/<hash>.html；link 态 → 原文外链。返回 (href, is_ext)。"""
    if interactions.get(item.get("source_id"), "detail") == "link" or not item.get("hash"):
        return _safe_url(item.get("url", "")), True
    return f"/item/{_e(item.get('hash', ''))}.html", False


def _head(title, page_css, maxw="1080px"):
    return ('<!doctype html>\n<html lang="zh-CN" data-theme="light">\n<head>\n'
            '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{_e(title)}</title>\n'
            f'<script>{_THEME_PRESET}</script>\n'
            f'{_FONT_LINKS}\n<style>\n{_BASE_CSS}\n:root{{--maxw:{maxw}}}\n{page_css}\n</style>\n</head>')


def _top_header(active, stat="", search_ph="搜索…"):
    def nav(href, label, key):
        cls = ' class="on"' if key == active else ''
        return f'<a href="{href}"{cls}>{label}</a>'
    stat_html = f'<span class="stat">{_e(stat)}</span>' if stat else ""
    return (f'<header class="top"><div class="top-in">'
            f'<a href="/" class="brand">{_BRAND_SVG}<span>AI&nbsp;Radar</span></a>'
            f'<nav class="nav">{nav("/", "总览", "home")}{nav("/feed.html", "时间流", "feed")}</nav>'
            f'{stat_html}'
            f'<div class="top-right"><div class="search">{_SEARCH_SVG}'
            f'<input id="search" type="search" placeholder="{_e(search_ph)}" autocomplete="off"></div>'
            f'<button class="icon-btn" id="theme" aria-label="切换深浅色">{_SUNMOON_SVG}</button>'
            f'</div></div></header>')


# ---------- 首页 ----------

def _render_home(items, descriptions, methods, interactions, out):
    stats = {}
    for it in items:
        lbl = it.get("source_label", "")
        if not lbl:
            continue
        s = stats.get(lbl)
        if s is None:
            stats[lbl] = {"count": 1, "latest": _day(it), "category": it.get("category", ""), "src_id": it.get("source_id", "")}
        else:
            s["count"] += 1

    # 「最新」头版：跨源最新（排除推文，避免高频推淹没头版）。lead 取近期里摘要最长的一条，填满版面不空。
    front_pool = [it for it in items if it.get("category") != "推文"]
    lead = max(front_pool[:15], key=lambda it: len(it.get("summary_zh") or it.get("summary") or "")) if front_pool else None
    minis = [it for it in front_pool if it is not lead][:4]

    def front_meta(it):
        cat = it.get("category", "")
        return (f'<div class="meta"><span class="dot"></span><span class="src">{_e(it.get("source_label",""))}</span>'
                f'<span>·</span><span>{_e(cat)}</span></div>')

    front_html = ""
    if lead:
        href, _ = _item_href(lead, interactions)
        title = lead.get("title_zh") or lead.get("title") or ""
        summ = lead.get("summary_zh") or lead.get("summary") or ""
        rt = _read_time(lead.get("content_html", ""))
        when = _fmt_md(lead.get("published_at")) or _fmt_md(lead.get("fetched_at"))
        when_html = f'{_e(when)}{" · " + rt if rt else ""}'
        summ_html = f'<p>{_e(summ)}</p>' if summ else ""
        title_en = lead.get("title") or ""
        sub_html = (f'<p class="lead-sub">{_e(title_en)}</p>'
                    if lead.get("title_zh") and title_en and lead.get("title_zh") != title_en else "")
        lead_html = (f'<a class="lead {_cat_class(lead.get("category",""))}" href="{href}">'
                     f'{front_meta(lead)}<h3>{_e(title)}</h3>{sub_html}{summ_html}'
                     f'<div class="when">{when_html}</div></a>')
        mini_html = ""
        for it in minis:
            mh, _ = _item_href(it, interactions)
            mt = it.get("title_zh") or it.get("title") or ""
            mini_html += (f'<a class="mini {_cat_class(it.get("category",""))}" href="{mh}">'
                          f'{front_meta(it)}<h4>{_e(mt)}</h4></a>')
        front_html = (f'<section><div class="kicker"><h2>最新 · Latest</h2>'
                      f'<span class="cnt">跨 {len(stats)} 源</span><span class="rule"></span></div>'
                      f'<div class="front">{lead_html}<div class="mini-list">{mini_html}</div></div></section>')

    # 来源目录
    by_cat = {}
    for lbl, s in stats.items():
        by_cat.setdefault(s["category"], []).append((lbl, s))
    ordered = [c for c in _CAT_ORDER if c in by_cat] + [c for c in by_cat if c not in _CAT_ORDER]

    def card(lbl, s):
        cat = s["category"]
        desc = descriptions.get(lbl, "")
        blob = _e(f"{lbl} {desc} {cat}".lower())
        desc_html = f'<p>{_e(desc)}</p>' if desc else ""
        m = methods.get(lbl, "")
        b_html = f'<span class="b" title="入口B:无 RSS,须在 Claude 会话里抓取">入口B</span>' if m else ""
        return (f'<a class="src-card {_cat_class(cat)}" href="{_e(_feed_href(lbl))}" data-text="{blob}">'
                f'<div class="sc-top">{_avatar(lbl)}<div>'
                f'<div class="sc-name">{_e(lbl)}</div>'
                f'<div class="sc-cat"><span class="dot"></span>{_e(cat)}</div></div></div>'
                f'{desc_html}'
                f'<div class="sc-foot"><span>最近更新 {_e(s["latest"][5:] or s["latest"])}</span>'
                f'<span style="display:flex;gap:6px;align-items:center">{b_html}<span class="n">{s["count"]} 条</span></span></div></a>')

    sections = []
    for cat in ordered:
        srcs = sorted(by_cat[cat], key=lambda kv: (kv[1]["latest"], kv[1]["count"]), reverse=True)
        en = _CAT_EN.get(cat, "")
        cards = "\n".join(card(lbl, s) for lbl, s in srcs)
        sections.append(
            f'<section class="cat-section"><div class="kicker"><h2>{_e(cat)}{" · " + en if en else ""}</h2>'
            f'<span class="cnt">{len(srcs)} 来源</span><span class="rule"></span></div>'
            f'<div class="grid">\n{cards}\n</div></section>')
    dir_html = "\n".join(sections) if sections else ""

    total = sum(s["count"] for s in stats.values())
    latest = max((s["latest"] for s in stats.values()), default="")
    stat = f"{len(stats)} 来源 · {total} 条 · {_fmt_md(latest)} 更新"
    build = datetime.now().strftime("%Y-%m-%d %H:%M")

    page = (_head("AI Radar — 来源总览", _HOME_CSS)
            + "\n<body>\n" + _top_header("home", stat=stat, search_ph="搜索来源…")
            + '\n<main class="wrap">\n' + front_html
            + f'\n<div class="dir">\n{dir_html}\n<p class="empty" id="empty">没有匹配的来源。</p>\n</div>\n</main>\n'
            + f'<footer class="foot"><span>AI&nbsp;RADAR</span><span class="sep">·</span>'
            + f'<span>本地聚合 · 无登录分享</span><span class="sep">·</span>'
            + f'<span>{len(stats)} 来源 · {len(by_cat)} 分类 · {total} 条</span><span class="sep">·</span>'
            + f'<span>构建于 {build}</span></footer>\n'
            + f'<script>{_THEME_JS}{_HOME_JS}</script>\n</body>\n</html>\n')
    (out / "index.html").write_text(page, encoding="utf-8")


# ---------- 时间流 / 单来源 ----------

def _card(item, mode="detail"):
    cat = item.get("category") or ""
    src = item.get("source_label", "")
    title = item.get("title_zh") or item.get("title") or ""
    summ = item.get("summary_zh") or item.get("summary") or ""
    if mode == "link":
        href, is_ext = _safe_url(item.get("url", "")), True
    else:
        href, is_ext = f'/item/{_e(item.get("hash",""))}.html', False
    ext_attr = ' target="_blank" rel="noopener"' if is_ext else ""
    if cat == "推文":  # 推文卡片:译文(主)+ 原文(英,弱化)+ 原推配图;链接直跳 X
        trans = item.get("title_zh") or item.get("title") or ""
        orig = item.get("title") or ""
        tw_ext = '<span class="ext">↗</span>' if is_ext else ""
        orig_html = f'<div class="it-orig">{_e(orig)}</div>' if orig and orig != trans else ""
        media = item.get("content_html") or ""
        media_html = f'<div class="it-media">{media}</div>' if media else ""
        return (f'<a class="item {_cat_class(cat)}" href="{href}"{ext_attr} '
                f'data-cat="{_e(cat)}" data-source="{_e(src)}" data-text="{_e(f"{trans} {orig} {src}".lower())}">'
                f'{_avatar(src)}<div class="it-body">'
                f'<div class="it-meta"><span class="src">{_e(src)}</span>'
                f'<span class="tag"><span class="dot"></span>{_e(cat)}</span>'
                f'<span class="time">{_e(_fmt_time(item))}</span></div>'
                f'<div class="it-title">{_e(trans)}{tw_ext}</div>{orig_html}{media_html}</div></a>')
    blob = _e(f"{title} {summ} {src}".lower())
    play = f'<span class="play">{_PLAY_SVG}</span>' if cat == "视频" else ""
    ext = '<span class="ext">↗</span>' if is_ext else ""
    summ_html = f'<div class="it-sum">{_e(summ)}</div>' if summ else ""
    return (f'<a class="item {_cat_class(cat)}" href="{href}"{ext_attr} '
            f'data-cat="{_e(cat)}" data-source="{_e(src)}" data-text="{blob}">'
            f'{_avatar(src)}<div class="it-body">'
            f'<div class="it-meta"><span class="src">{_e(src)}</span>'
            f'<span class="tag"><span class="dot"></span>{_e(cat)}</span>'
            f'<span class="time">{_e(_fmt_time(item))}</span></div>'
            f'<div class="it-title">{play}{_e(title)}{ext}</div>{summ_html}</div></a>')


def _render_feed(items, interactions, out):
    sections, cur, buf = [], None, []
    for it in items:
        d = _day(it)
        if d != cur:
            if buf:
                sections.append((cur, buf))
            cur, buf = d, []
        buf.append(it)
    if buf:
        sections.append((cur, buf))

    body = []
    for day, its in sections:
        rows = "\n".join(_card(it, interactions.get(it.get("source_id"), "detail")) for it in its)
        md = _fmt_md(day).replace("-", " / ")
        body.append(f'<section class="day"><div class="day-label"><span class="d">{_e(md)}</span>'
                    f'<span class="w">{_weekday(day)}</span><span class="rule"></span>'
                    f'<span class="n">{len(its)} 条</span></div>\n{rows}\n</section>')
    body_html = "\n".join(body) if body else ""

    pills = ['<span class="pill on" data-cat="">全部</span>']
    for cat in [c for c in _CAT_ORDER if c != "推文"]:
        pills.append(f'<span class="pill {_cat_class(cat)}" data-cat="{_e(cat)}"><span class="dot"></span>{_e(cat)}</span>')
    pills_html = "".join(pills)

    page = (_head("AI Radar — 时间流", _FEED_CSS, maxw="760px")
            + "\n<body>\n" + _top_header("feed", search_ph="搜索标题…")
            + '\n<main class="wrap"><div class="feed-head"><a href="/" class="back">← 总览</a>'
            + '<h1 id="feed-title">时间流</h1><div class="sub" id="feed-sub">全部来源 · 按时间倒序 · 不含推文</div>'
            + f'<div class="pills" id="pills">{pills_html}</div></div>\n'
            + body_html
            + '\n<p class="empty" id="empty">该分类暂无内容。</p>\n</main>\n'
            + f'<script>{_THEME_JS}{_FEED_JS}{_LIGHTBOX_JS}</script>\n</body>\n</html>\n')
    (out / "feed.html").write_text(page, encoding="utf-8")


# ---------- 详情页 ----------

def _tr_empty(kind="文章"):
    if kind == "视频":
        return ('<div class="tr-empty"><div class="ico">' + _TR_SVG + '</div>'
                '<h3>这条视频还没有中文字幕</h3>'
                '<p>该条目暂未提供中文字幕。本系统只对人工挑选的内容生成翻译。</p>'
                '<p class="why">挑中后 → 取 YouTube 字幕 → 精翻 → 此处切换为双语字幕</p></div>')
    return ('<div class="tr-empty"><div class="ico">' + _TR_SVG + '</div>'
            '<h3>这篇还没有中文全文</h3>'
            '<p>该条目暂未提供中文翻译。标题/摘要已自动中译;本系统只对人工挑选的内容生成全文翻译。</p>'
            '<p class="why">挑中后 → markitdown 取正文 → 精翻 → 此处切换为译文</p></div>')


def _youtube_embed(url, src=""):
    """YouTube 门面：缩略图封面 + 播放钮 + 频道名;点击才由 _DETAIL_JS 挂 iframe（无注入）。无 vid → ""。"""
    vid = _yt_id(url)
    if not vid:
        return ""
    return (f'<div class="facade" id="facade" data-id="{vid}">'
            f'<img class="thumb" src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy">'
            f'<div class="hint">点击播放</div>'
            f'<div class="play"><span class="pbtn">{_PLAY_SVG}</span></div>'
            f'<div class="ov"><span class="dotmark">{_e(_monogram(src))}</span>'
            f'<div><div class="nm">{_e(src)}</div><div class="sub2">YouTube</div></div></div></div>')


def _tabs(item):
    """文章态 tabs：原文（content_html 原样，不改写）/ 中文翻译（诚实空态，translation_md 现恒空）。"""
    content = item.get("content_html") or ""
    yuanwen = content or '<p style="color:var(--muted)">本条无正文,点上方「打开原文」查看。</p>'
    return ('<div class="tabs"><button class="tab on" data-panel="p-orig">原文</button>'
            '<button class="tab" data-panel="p-zh">中文翻译</button></div>'
            f'<section class="panel on doc" id="p-orig">{yuanwen}</section>'
            f'<section class="panel" id="p-zh">{_tr_empty("文章")}</section>')


def _detail_header(src, cat_cls):
    return (f'<header class="top"><div class="top-in">'
            f'<a href="{_e(_feed_href(src))}" class="back {cat_cls}">'
            f'{_avatar(src, "av")}<span>← {_e(src) or "AI Radar"}</span></a>'
            f'<div class="top-right"><button class="icon-btn" id="theme" aria-label="切换深浅色">{_SUNMOON_SVG}</button></div>'
            f'</div></header>')


def _render_detail(item, out, descriptions):
    title_zh = item.get("title_zh") or ""
    title = item.get("title") or ""
    head_title = title_zh or title
    cat = item.get("category") or ""
    cat_cls = _cat_class(cat)
    src = item.get("source_label", "")
    url = _safe_url(item.get("url", ""))
    raw_url = item.get("url", "")
    when = _fmt_time(item)
    vid = _yt_id(raw_url)
    is_video = cat == "视频" or bool(vid)

    meta = (f'<div class="a-meta"><span class="tag"><span class="dot"></span>{_e(cat)}</span>'
            f'<span class="src">{_e(src)}</span><span class="mono">· {_e(when)}</span></div>')

    if is_video:
        # ---- 视频态 ----
        facade = _youtube_embed(raw_url, src)
        subtitle = item.get("summary_zh") or item.get("summary") or (title if title_zh and title != title_zh else "")
        sub_html = f'<p class="subtitle" style="font-style:normal;font-size:14.5px;color:var(--muted)">{_e(subtitle)}</p>' if subtitle else ""
        desc = item.get("summary_zh") or item.get("summary") or ""
        desc_panel = f'<p>{_e(desc)}</p>' if desc else '<p style="color:var(--muted)">本条视频默认只抓标题与链接;点上方封面在站内播放,或「在 YouTube 打开」。</p>'
        body = (f'<main class="wrap {cat_cls}">{facade}'
                f'<div style="margin-top:22px"></div>'
                f'{meta}<h1 class="title">{_e(head_title)}</h1>{sub_html}'
                f'<div class="actions">'
                f'<a class="btn primary" href="{url}" target="_blank" rel="noopener">{_EXTLINK_SVG}在 YouTube 打开</a>'
                f'<button class="btn" id="copy" data-url="{_e(raw_url)}">{_COPY_SVG}<span>复制链接</span></button></div>'
                f'<div class="tabs"><button class="tab on" data-panel="p-desc">简介</button>'
                f'<button class="tab" data-panel="p-zh">中文字幕</button></div>'
                f'<section class="panel on doc" id="p-desc">{desc_panel}</section>'
                f'<section class="panel" id="p-zh">{_tr_empty("视频")}</section></main>')
        progress = ""
    else:
        # ---- 文章态 ----
        subtitle = title if (title_zh and title and title_zh != title) else ""
        sub_html = f'<p class="subtitle">{_e(subtitle)}</p>' if subtitle else ""
        rt = _read_time(item.get("content_html", ""))
        rt_html = f'<span class="read-time">{rt}</span>' if rt else ""
        body = (f'<main class="wrap {cat_cls}">'
                f'{meta}<h1 class="title">{_e(head_title)}</h1>{sub_html}'
                f'<div class="actions">'
                f'<a class="btn primary" href="{url}" target="_blank" rel="noopener">{_EXTLINK_SVG}打开原文</a>'
                f'<button class="btn" id="copy" data-url="{_e(raw_url)}">{_COPY_SVG}<span>复制链接</span></button>{rt_html}</div>'
                f'{_tabs(item)}</main>')
        progress = '<div class="progress" id="progress"></div>'

    page = (_head(head_title + " · AI Radar", _DETAIL_CSS, maxw="680px" if not is_video else "760px")
            + "\n<body>\n" + progress + "\n" + _detail_header(src, cat_cls) + "\n" + body
            + f'\n<script>{_THEME_JS}{_DETAIL_JS}{_LIGHTBOX_JS}</script>\n</body>\n</html>\n')
    (out / "item" / f"{item.get('hash','')}.html").write_text(page, encoding="utf-8")


def render_site(items, interactions=None, descriptions=None, icons=None, out_dir=None, methods=None):
    """interactions: {source_id: 'detail'|'link'}；descriptions/icons/methods: {source_label: ...}。
    首页=报头+最新头版+来源目录；feed.html=时间流/单来源；item/<hash>.html=文章态/视频态。"""
    global _ICONS
    interactions = interactions or {}
    descriptions = descriptions or {}
    _ICONS = icons or {}
    out = Path(out_dir) if out_dir else DIST
    shutil.rmtree(out / "item", ignore_errors=True)
    (out / "item").mkdir(parents=True, exist_ok=True)
    (out / "sources.html").unlink(missing_ok=True)
    _render_home(items, descriptions, methods or {}, interactions, out)
    _render_feed(items, interactions, out)
    for it in items:
        if it.get("hash") and interactions.get(it.get("source_id"), "detail") != "link":
            _render_detail(it, out, descriptions)
    return out / "index.html"
