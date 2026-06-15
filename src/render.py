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
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from store import _parse_dt  # 统一时间解析(兼容 ISO 与 RFC822 pubDate)
from content import md_to_html  # 译文 translation_md(markdown)→ HTML

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
_VERIFIED_SVG = ('<svg class="tw-vf" viewBox="0 0 22 22" aria-label="认证">'
                 '<path fill="currentColor" d="M11 1l2.6 2 3.3-.2 1 3.1 2.6 2-1.2 3 1.2 3-2.6 2-1 3.1-3.3-.2L11 21l-2.6-2-3.3.2-1-3.1L1.5 14l1.2-3-1.2-3 2.6-2 1-3.1L8.4 3z"/>'
                 '<path fill="#fff" d="M9.7 13.5l-2.3-2.3 1.1-1.1 1.2 1.2 3.6-3.6 1.1 1.1z"/></svg>')
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
                 "else document.documentElement.setAttribute('data-theme','light');"
                 "var fs=localStorage.getItem('air-fontsize');if(fs)document.documentElement.style.setProperty('--doc-size',fs);"
                 "var dw=localStorage.getItem('air-width');if(dw)document.documentElement.style.setProperty('--doc-maxw',dw);"
                 "var cv=localStorage.getItem('air-canvas');if(cv==='sepia')document.documentElement.setAttribute('data-canvas','sepia');"
                 "}catch(e){}")

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
  --maxw:1080px;--doc-size:18.5px;--doc-maxw:680px;
}
/* sepia 阅读底(详情页用,localStorage 持久化) */
[data-canvas="sepia"]{
  --bg:oklch(96.5% 0.014 80);--surface:oklch(98% 0.012 80);--surface-2:oklch(94.5% 0.016 80);
  --inset:oklch(93% 0.018 80);--fg:oklch(30% 0.025 60);--fg-2:oklch(46% 0.022 60);
  --muted:oklch(54% 0.018 70);--faint:oklch(64% 0.014 70);--border:oklch(89% 0.014 80);
  --border-2:oklch(83% 0.018 80);
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
@media(max-width:560px){.top-in{padding:9px 13px;gap:9px}.brand span{display:none}
  .stat{display:none}.nav{margin-left:2px;gap:2px}.nav a{font-size:13px;padding:5px 8px}
  .top-right{flex:1;min-width:0;margin-left:6px;justify-content:flex-end}
  .search{flex:1;min-width:56px;max-width:240px}.search input{width:100%}}
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
/* ===== v2 增益:Today on Radar 雷达条 + Editor's Cut 副位 + 来源卡片预览行 ===== */
.radar{display:grid;grid-template-columns:auto 1fr auto;gap:24px;align-items:center;padding:18px 22px;background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);margin-bottom:30px}
.radar-l{display:flex;flex-direction:column;gap:2px;border-right:1px solid var(--border);padding-right:24px}
.radar-l .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.radar-l .v{font-family:var(--serif);font-size:30px;font-weight:500;letter-spacing:-.01em;line-height:1}
.radar-l .v sup{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--accent-2);margin-left:6px;vertical-align:14px}
.radar-l .s{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:5px}
.radar-bars{display:grid;grid-template-columns:repeat(8,1fr);gap:14px;height:62px;align-items:end}
.radar .bar{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px;cursor:pointer;height:100%;text-decoration:none}
.radar .bar:hover .bar-fill{filter:brightness(1.1);opacity:1}
.bar-fill{width:100%;background:var(--cat,var(--accent));border-radius:3px 3px 0 0;min-height:3px;transition:.16s;opacity:.85}
.bar-label{font-family:var(--mono);font-size:9.5px;letter-spacing:.05em;color:var(--muted);white-space:nowrap}
.bar-n{font-family:var(--mono);font-size:10px;font-weight:600;color:var(--fg)}
.radar-r{display:flex;flex-direction:column;align-items:flex-end;gap:4px;font-family:var(--mono);font-size:10.5px;color:var(--faint);letter-spacing:.04em}
.radar-r .pulse{display:flex;align-items:center;gap:6px;color:var(--accent-2);font-weight:600;letter-spacing:.05em}
.radar-r .pulse::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent);animation:pulse 1.8s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:1;transform:scale(1.2)}}
.front-row{display:grid;grid-template-columns:2fr 1fr;gap:18px}
.cut{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px 22px;display:flex;flex-direction:column;box-shadow:var(--shadow);position:relative;overflow:hidden;text-decoration:none}
.cut::before{content:"";position:absolute;left:22px;right:22px;top:0;height:2px;background:linear-gradient(90deg,var(--accent),var(--accent-2),transparent)}
.cut .ek{font-family:var(--mono);font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--accent-2);font-weight:600;display:flex;align-items:center;gap:7px;margin-bottom:14px}
.cut .ek svg{width:11px;height:11px}
.cut .meta{margin-bottom:8px}
.cut h3{font-family:var(--serif);font-weight:600;font-size:21px;line-height:1.24;letter-spacing:-.01em;margin-bottom:8px}
.cut:hover h3{color:var(--accent-2)}
.cut .ed-note{font-family:var(--serif);font-style:italic;font-size:14px;line-height:1.6;color:var(--muted);border-top:1px solid var(--border);padding-top:12px;margin-top:auto}
.cut .ed-note::before{content:"「";color:var(--accent-line);font-size:20px;margin-right:2px;vertical-align:-3px}
.cut .ed-note::after{content:"」";color:var(--accent-line);font-size:20px;margin-left:2px;vertical-align:-3px}
.cut .ed-foot{display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:10px}
.cut .ed-foot .who{color:var(--fg-2)}
.cut .ed-auto{font-family:var(--mono);font-size:10px;color:var(--faint);letter-spacing:.04em}
/* 来源卡片预览行(latest_title) */
.sc-peek{margin-top:10px;padding-top:10px;border-top:1px dashed var(--border);font-family:var(--serif);font-size:13px;line-height:1.4;color:var(--fg-2);display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.sc-peek::before{content:"›";color:var(--cat,var(--accent-line));font-family:var(--mono);font-weight:700;margin-right:6px;font-size:14px}
.src-card:hover .sc-peek{color:var(--fg);-webkit-line-clamp:2}
.sc-foot .fresh{color:var(--accent-2);font-weight:600;letter-spacing:.04em}
.kicker .more{font-family:var(--mono);font-size:11px;color:var(--accent-2);letter-spacing:.04em;text-decoration:none}
@media(max-width:880px){.grid{grid-template-columns:repeat(2,1fr)}.front{grid-template-columns:1fr}
  .lead{border-right:0;border-bottom:1px solid var(--border);min-height:0}.lead h3{font-size:27px}
  .front-row{grid-template-columns:1fr}
  .radar{grid-template-columns:1fr;gap:14px}
  .radar-l{border-right:0;border-bottom:1px solid var(--border);padding-right:0;padding-bottom:14px;flex-direction:row;align-items:baseline;gap:16px}
  .radar-r{flex-direction:row;flex-wrap:wrap;align-items:center;gap:12px}}
@media(max-width:560px){.wrap{padding:22px 16px 48px}.grid{grid-template-columns:1fr}
  .radar-bars{gap:8px}.bar-label{font-size:8.5px}
  .radar{padding:14px 16px}}
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
.day{margin-top:34px}
.day:first-of-type{margin-top:8px}
.day-label{position:sticky;top:50px;z-index:5;display:flex;align-items:center;gap:11px;padding:10px 0;margin-bottom:8px;
  background:var(--bg);border-bottom:1px solid var(--border-2)}
.day-label::before{content:"";width:4px;height:20px;border-radius:2px;background:var(--accent-2)}
.day-label .d{font-family:var(--mono);font-size:17px;font-weight:700;letter-spacing:.04em;color:var(--fg)}
.day-label .w{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--muted)}
.day-label .rule{flex:1}
.day-label .n{font-family:var(--mono);font-size:11px;color:var(--faint);background:var(--inset);padding:2px 8px;border-radius:999px}
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
.tw .avatar-img{border-radius:50%;background:var(--surface-2);object-fit:cover}
.it-meta .tw-name{font-weight:600;color:var(--fg);display:inline-flex;align-items:center;gap:3px}
.tw-vf{width:14.5px;height:14.5px;color:var(--accent-2);flex:none}
.it-meta .tw-handle{color:var(--faint);font-weight:400}
.it-meta .tw-rt{color:var(--faint);font-size:11.5px}
.tw-quote{margin-top:10px;border:1px solid var(--border);border-radius:13px;padding:9px 12px;background:var(--surface-2)}
.tw-quote .tw-q-head{font-size:13px;font-weight:600;color:var(--fg-2);margin-bottom:2px}
.tw-quote .tw-q-head .tw-handle{font-weight:400;color:var(--faint)}
.tw-quote .tw-q-text{font-size:13.5px;line-height:1.5;color:var(--fg-2);white-space:pre-wrap}
.play{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;margin-right:6px;vertical-align:-2px;color:var(--cat)}
.play svg{width:14px;height:14px}
/* ===== v2 增益:左侧迷你日期游标 + day-label 分类点位 + 已精读徽章 ===== */
.shell{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:140px 1fr;gap:36px;padding:26px 24px 56px}
.shell>.wrap{min-width:0;max-width:none;padding:0}
.rail{position:sticky;top:68px;align-self:start;max-height:calc(100vh - 96px);overflow-y:auto;padding:2px 0;font-family:var(--mono)}
.rail-k{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:14px}
.rail-day{display:grid;grid-template-columns:1fr auto;align-items:center;gap:10px;padding:6px 0;color:var(--muted);font-size:11px;letter-spacing:.04em;cursor:pointer;transition:.14s;position:relative;text-decoration:none}
.rail-day .d{font-weight:600;color:var(--fg-2);font-size:11.5px}
.rail-day .w{font-size:10px;color:var(--faint);margin-left:6px}
.rail-day .vol{width:46px;height:5px;background:var(--inset);border-radius:3px;overflow:hidden;flex:none}
.rail-day .vol span{display:block;height:100%;background:var(--accent-line);border-radius:3px;transition:.14s}
.rail-day:hover{color:var(--fg)}
.rail-day:hover .vol span{background:var(--accent-2)}
.rail-day.on .d{color:var(--accent-2)}
.rail-day.on .vol span{background:var(--accent)}
.rail-day::before{content:"";position:absolute;left:-12px;top:50%;transform:translateY(-50%);width:3px;height:14px;border-radius:2px;background:transparent;transition:.14s}
.rail-day:hover::before,.rail-day.on::before{background:var(--accent)}
.day-label{flex-direction:column;align-items:stretch;gap:6px}
.day-label-row{display:flex;align-items:center;gap:11px}
.day-label-row::before{content:"";width:4px;height:20px;border-radius:2px;background:var(--accent-2)}
.day-label::before{content:none}
.day-cats{display:flex;gap:14px;flex-wrap:wrap;padding-left:14px;font-family:var(--mono);font-size:10.5px}
.day-cats .dc{display:flex;align-items:center;gap:5px;color:var(--muted)}
.day-cats .dc .dot{width:5px;height:5px;border-radius:50%;background:var(--cat,var(--faint))}
.day-cats .dc .n{color:var(--fg-2);font-weight:600;letter-spacing:.04em}
.day-cats .dc.zero{opacity:.32}
.it-meta .read{font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:.06em;color:var(--accent-2);background:var(--accent-soft);padding:1px 6px;border-radius:5px;text-transform:uppercase}
@media(max-width:880px){
  .shell{grid-template-columns:1fr;gap:18px;padding:20px 24px 56px}
  .rail{display:none}}
@media(max-width:560px){.wrap{padding:20px 16px 48px}
  .feed-head h1{font-size:25px}.it-meta .time{margin-left:0}.day-label{top:52px}
  .shell{padding:18px 16px 48px}
  .day-cats{padding-left:0;gap:10px}}
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
.doc{font-family:var(--serif);font-size:var(--doc-size);line-height:1.78;color:var(--fg);margin-top:14px}
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
/* ===== v2 增益:阅读偏好控制条 + 右浮 outline + 视频章节时间戳 ===== */
/* 顶栏右侧 reader 工具条 */
.reader{display:inline-flex;align-items:center;gap:0;background:var(--surface-2);border:1px solid var(--border);border-radius:9px;height:34px;overflow:hidden;font-family:var(--mono);font-size:11.5px;margin-right:4px}
.reader button{height:100%;padding:0 10px;background:transparent;border:0;color:var(--fg-2);font-family:var(--mono);font-size:11.5px;cursor:pointer;letter-spacing:.02em;transition:.14s;display:flex;align-items:center;gap:4px}
.reader button:hover{background:var(--inset);color:var(--fg)}
.reader button+button{border-left:1px solid var(--border)}
.reader .opt[data-on="1"]{background:var(--accent-soft);color:var(--accent-2);font-weight:600}
/* 文章态:.wrap 外面包 .shell-doc 双列(正文 + outline) */
.shell-doc{max-width:920px;margin:0 auto;display:grid;grid-template-columns:var(--doc-maxw) 200px;gap:60px;padding:0 24px;align-items:start;justify-content:center}
.shell-doc>.wrap{max-width:none;margin:0;padding:34px 0 80px;min-width:0}
.outline{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 96px);overflow-y:auto;padding:38px 0 6px 18px;border-left:1px solid var(--border);font-family:var(--sans);font-size:12.5px}
.outline-k{font-family:var(--mono);font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}
.outline ol{list-style:none;padding:0;margin:0}
.outline li{margin:8px 0;line-height:1.45;position:relative}
.outline li.h3{padding-left:14px;font-size:12px}
.outline a{display:block;color:var(--muted);transition:.14s;padding-right:6px;text-decoration:none}
.outline a:hover{color:var(--fg)}
.outline li.on>a{color:var(--accent-2);font-weight:600}
.outline li.on::before{content:"";position:absolute;left:-19px;top:6px;width:3px;height:14px;border-radius:2px;background:var(--accent)}
.doc h1,.doc h2,.doc h3,.doc h4{scroll-margin-top:80px}
/* 视频态:facade 角标(时长/发布日期/HD) + 总结 tab 章节时间戳跳转条 */
.facade .dur{position:absolute;right:14px;bottom:14px;font-family:var(--mono);font-size:11.5px;font-weight:700;letter-spacing:.04em;background:oklch(12% 0 0 / .82);color:#fff;padding:3px 8px;border-radius:6px;backdrop-filter:blur(2px)}
.facade .pub{position:absolute;top:18px;right:18px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:oklch(92% 0 0 / .85);background:oklch(12% 0 0 / .55);padding:4px 9px;border-radius:999px;backdrop-filter:blur(2px)}
.chapters{display:flex;gap:8px;overflow-x:auto;padding:14px 0 6px;margin-bottom:8px;border-bottom:1px solid var(--border);scrollbar-width:thin}
.chapters::-webkit-scrollbar{height:4px}
.chapters::-webkit-scrollbar-thumb{background:var(--border-2);border-radius:2px}
.chap{flex:none;display:flex;flex-direction:column;gap:3px;padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--surface);cursor:pointer;transition:.14s;min-width:140px;text-decoration:none}
.chap:hover{border-color:var(--accent-line);background:var(--surface-2)}
.chap .ts{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--accent-2)}
.chap .ttl{font-family:var(--serif);font-size:14px;font-weight:500;line-height:1.3;letter-spacing:-.005em;color:var(--fg)}
.chap.on{border-color:var(--accent);background:var(--accent-soft)}
.chap.on .ttl{color:var(--accent-2)}
.doc h2 .ts{font-family:var(--mono);font-size:.7em;font-weight:600;color:var(--accent-2);background:var(--accent-soft);padding:2px 8px;border-radius:5px;letter-spacing:.04em;margin-right:9px;vertical-align:3px}
@media(max-width:1080px){.shell-doc{grid-template-columns:1fr;gap:0}.outline{display:none}}
@media(max-width:560px){.top-in{padding:10px 16px}.wrap{padding:24px 18px 64px}
  h1.title{font-size:27px}.subtitle{font-size:17px}.read-time{display:none}
  .facade{border-radius:12px}.facade .play .pbtn{width:68px;height:48px}
  .reader{display:none}
  .shell-doc{padding:0 18px}.shell-doc>.wrap{padding:24px 0 64px}}
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
  function go(){var v=input.value.trim();if(v)location.href='/feed.html?q='+encodeURIComponent(v);}  // 回车 → 搜全部内容
  input.addEventListener('keydown',function(e){if(e.key==='Enter')go();});
  input.addEventListener('input',function(){var q=input.value.trim().toLowerCase(),hit=0;
    cards.forEach(function(c){var ok=!q||(c.dataset.text||'').indexOf(q)>-1;c.style.display=ok?'':'none';if(ok)hit++;});
    secs.forEach(function(s){var any=[].slice.call(s.querySelectorAll('.src-card')).some(function(c){return c.style.display!=='none';});s.style.display=any?'':'none';});
    if(empty){empty.style.display=hit?'none':'block';
      if(!hit&&input.value.trim())empty.textContent='没有匹配的来源 — 按回车搜「'+input.value.trim()+'」的全部内容 →';}});})();
"""

_FEED_JS = """
(function(){
  var input=document.getElementById('search'),pills=[].slice.call(document.querySelectorAll('.pill')),
    items=[].slice.call(document.querySelectorAll('.item')),days=[].slice.call(document.querySelectorAll('.day')),
    empty=document.getElementById('empty'),cat='',
    src=new URLSearchParams(location.search).get('source')||'',
    qp=new URLSearchParams(location.search).get('q')||'',
    titleEl=document.getElementById('feed-title'),subEl=document.getElementById('feed-sub'),pillBox=document.getElementById('pills');
  if(src){if(titleEl)titleEl.textContent=src;if(subEl)subEl.textContent='单一来源 · 按时间倒序';if(pillBox)pillBox.style.display='none';}
  if(qp&&input){input.value=qp;if(titleEl)titleEl.textContent='搜索';if(subEl)subEl.textContent='搜全部内容(含推文)· 关键词「'+qp+'」';if(pillBox)pillBox.style.display='none';}
  function apply(){var q=(input&&input.value||'').trim().toLowerCase(),searching=!!q,hit=0;
    items.forEach(function(el){
      var inFeed=src?el.dataset.source===src:(searching?true:el.dataset.cat!=='推文');
      var ok=inFeed&&(!cat||el.dataset.cat===cat)&&(!q||(el.dataset.text||'').indexOf(q)>-1);
      el.style.display=ok?'':'none';if(ok)hit++;});
    days.forEach(function(s){var any=[].slice.call(s.querySelectorAll('.item')).some(function(el){return el.style.display!=='none';});s.style.display=any?'':'none';});
    if(empty)empty.style.display=hit?'none':'block';}
  pills.forEach(function(p){p.addEventListener('click',function(){pills.forEach(function(x){x.classList.toggle('on',x===p);});cat=p.dataset.cat||'';apply();});});
  if(input)input.addEventListener('input',apply);
  apply();})();
/* ===== v2:rail 左侧日期游标滚动联动 ===== */
(function(){var rail=document.getElementById('rail');if(!rail)return;
  var links=[].slice.call(rail.querySelectorAll('.rail-day'));
  var sections=links.map(function(l){return document.getElementById('d-'+l.dataset.day);}).filter(Boolean);
  function setActive(id){links.forEach(function(l){l.classList.toggle('on',l.dataset.day===id);});}
  window.addEventListener('scroll',function(){var top=window.scrollY+120,cur='';
    sections.forEach(function(s){if(s.offsetTop<=top)cur=s.id.slice(2);});if(cur)setActive(cur);},{passive:true});})();
"""

_DETAIL_JS = """
var tabs=[].slice.call(document.querySelectorAll('.tab')),panels=[].slice.call(document.querySelectorAll('.panel'));
tabs.forEach(function(b){b.addEventListener('click',function(){
  tabs.forEach(function(x){x.classList.toggle('on',x===b);});
  panels.forEach(function(p){p.classList.toggle('on',p.id===b.dataset.panel);});});});
(function(){var hp=(location.hash||'').slice(1);if(!hp)return;  // #zh/#sum/#en/#orig → 打开对应 tab(精读页深链用)
  var b=tabs.filter(function(x){return x.dataset.panel==='p-'+hp;})[0];if(b)b.click();})();
(function(){if(new URLSearchParams(location.search).get('from')!=='reads')return;  // 从精读进来 → 返回回精读列表
  var bk=document.getElementById('back');if(!bk)return;
  bk.href='/reads.html';var s=bk.querySelector('span');if(s)s.textContent='← 精读';
  var av=bk.querySelector('.av');if(av)av.style.display='none';})();
var copy=document.getElementById('copy');
if(copy)copy.addEventListener('click',function(){var s=copy.querySelector('span');
  navigator.clipboard.writeText(copy.dataset.url).then(function(){s.textContent='已复制';setTimeout(function(){s.textContent='复制链接';},1500);});});
var bar=document.getElementById('progress');
if(bar)window.addEventListener('scroll',function(){var h=document.documentElement,max=h.scrollHeight-h.clientHeight;
  bar.style.width=(max>0?(h.scrollTop/max*100):0)+'%';},{passive:true});
[].slice.call(document.querySelectorAll('.facade')).forEach(function(f){
  f.addEventListener('click',function(){
    var yt=f.dataset.yt,bv=f.dataset.bv,url='';
    if(yt&&/^[\\w-]{11}$/.test(yt))url='https://www.youtube.com/embed/'+yt+'?autoplay=1';
    else if(bv&&/^BV[0-9A-Za-z]+$/.test(bv))url='https://player.bilibili.com/player.html?isOutside=true&bvid='+bv+(f.dataset.cid?'&cid='+f.dataset.cid:'')+'&p=1&autoplay=1&danmaku=0';
    else return;
    var ifr=document.createElement('iframe');
    ifr.style.cssText='width:100%;aspect-ratio:16/9;border:0;border-radius:16px;display:block';
    ifr.allow='accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture';
    ifr.allowFullscreen=true;ifr.src=url;
    f.replaceWith(ifr);
  },{once:true});
});
/* ===== v2:Reader 控制(A-/A+/宽窄/sepia) + outline 联动 + chapters 联动 ===== */
(function(){var root=document.documentElement;
  var fd=document.getElementById('font-down'),fu=document.getElementById('font-up'),wt=document.getElementById('width-toggle'),sp=document.getElementById('sepia');
  if(!(fd||fu||wt||sp))return;
  var sizes=[16,17.5,18.5,20,22],cur=2;
  var saved=localStorage.getItem('air-fontsize');
  if(saved){var idx=sizes.indexOf(parseFloat(saved));if(idx>-1)cur=idx;}
  function applySize(){var v=sizes[cur]+'px';root.style.setProperty('--doc-size',v);try{localStorage.setItem('air-fontsize',v);}catch(e){}}
  if(fd)fd.addEventListener('click',function(){if(cur>0){cur--;applySize();}});
  if(fu)fu.addEventListener('click',function(){if(cur<sizes.length-1){cur++;applySize();}});
  if(wt){var sw=localStorage.getItem('air-width');if(sw==='820px'){wt.dataset.on='1';root.style.setProperty('--doc-maxw','820px');}
    wt.addEventListener('click',function(){var on=wt.dataset.on==='1';
      if(on){wt.dataset.on='0';root.style.setProperty('--doc-maxw','680px');try{localStorage.setItem('air-width','680px');}catch(e){}}
      else{wt.dataset.on='1';root.style.setProperty('--doc-maxw','820px');try{localStorage.setItem('air-width','820px');}catch(e){}}});}
  if(sp){if(localStorage.getItem('air-canvas')==='sepia')sp.dataset.on='1';
    sp.addEventListener('click',function(){var on=sp.dataset.on==='1';
      if(on){sp.dataset.on='0';root.removeAttribute('data-canvas');try{localStorage.removeItem('air-canvas');}catch(e){}}
      else{sp.dataset.on='1';root.setAttribute('data-canvas','sepia');try{localStorage.setItem('air-canvas','sepia');}catch(e){}}});}})();
(function(){var outline=document.getElementById('outline');if(!outline)return;
  var anchors=[].slice.call(outline.querySelectorAll('a'));
  var heads=anchors.map(function(a){return document.getElementById(a.getAttribute('href').slice(1));}).filter(Boolean);
  function setActive(id){anchors.forEach(function(a){a.parentElement.classList.toggle('on',a.getAttribute('href')==='#'+id);});}
  window.addEventListener('scroll',function(){var top=window.scrollY+120,cur='';
    heads.forEach(function(h){if(h.offsetTop<=top)cur=h.id;});if(cur)setActive(cur);},{passive:true});})();
(function(){var chaps=[].slice.call(document.querySelectorAll('.chap'));if(!chaps.length)return;
  chaps.forEach(function(c){c.addEventListener('click',function(e){
    e.preventDefault();var id=c.dataset.anchor;var h=document.getElementById(id);if(!h)return;
    chaps.forEach(function(x){x.classList.toggle('on',x===c);});
    window.scrollTo({top:h.offsetTop-80,behavior:'smooth'});});});
  var heads=chaps.map(function(c){return document.getElementById(c.dataset.anchor);}).filter(Boolean);
  window.addEventListener('scroll',function(){var top=window.scrollY+150,cur='';
    heads.forEach(function(h){if(h.offsetTop<=top)cur=h.id;});
    if(cur)chaps.forEach(function(c){c.classList.toggle('on',c.dataset.anchor===cur);});},{passive:true});})();
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


_IMG_TAG = re.compile(r"(?i)<img[^>]*>")
_IMG_LOCAL = re.compile(r'src="/img/([^"]+)"')
_img_have_cache = [None]


def _img_have():
    """dist/img 现存文件名集合(每次渲染进程缓存一次)。"""
    if _img_have_cache[0] is None:
        from content import DIST_IMG
        _img_have_cache[0] = {p.name for p in DIST_IMG.iterdir()} if DIST_IMG.exists() else set()
    return _img_have_cache[0]


def _lazy_imgs(html_str):
    """给正文/推文配图的 <img> 补 loading="lazy"(隐藏/未滚到视口不下载);
    并**丢弃 /img 文件已不在站的 <img>**——避免破图图标(图若丢失则优雅地不显示,而非裂图)。"""
    if not html_str:
        return html_str
    have = _img_have()

    def repl(m):
        tag = m.group(0)
        loc = _IMG_LOCAL.search(tag)
        if loc and loc.group(1) not in have:
            return ""  # 站内图文件缺失 → 不渲染该 <img>(无破图)
        return tag if "loading=" in tag else tag.replace("<img", '<img loading="lazy"', 1)

    return _IMG_TAG.sub(repl, html_str)


def _e(s):
    return html.escape(s or "")


def _safe_url(url):
    u = (url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else "#"


_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


def _effective_dt(item):
    """条目的有效时间:优先发布时间(published_at,兼容 RFC822),无则退抓取时间。用于排序/分组/显示三处一致。"""
    return _parse_dt(item.get("published_at")) or _parse_dt(item.get("fetched_at")) or _MIN_DT


def _day(item):
    dt = _effective_dt(item)
    return dt.strftime("%Y-%m-%d") if dt != _MIN_DT else "未知日期"


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
    """有效时间 → 'MM-DD'，带具体时刻则 'MM-DD · HH:MM'(兼容 ISO 与 RFC822)。"""
    dt = _effective_dt(item)
    if dt == _MIN_DT:
        return ""
    s = dt.strftime("%m-%d")
    return f"{s} · {dt.strftime('%H:%M')}" if (dt.hour or dt.minute) else s


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
            f'<nav class="nav">{nav("/", "总览", "home")}{nav("/feed.html", "时间流", "feed")}'
            f'{nav("/reads.html", "精读", "reads")}</nav>'
            f'{stat_html}'
            f'<div class="top-right"><div class="search">{_SEARCH_SVG}'
            f'<input id="search" type="search" placeholder="{_e(search_ph)}" autocomplete="off"></div>'
            f'<button class="icon-btn" id="theme" aria-label="切换深浅色">{_SUNMOON_SVG}</button>'
            f'</div></div></header>')


# ---------- 首页 ----------

def _render_home(items, descriptions, methods, interactions, out):
    now = datetime.now(timezone.utc)  # v2:统一时间锚,供 today 雷达 / fresh 卡片 / 7 日均使用
    # v2:stats 顺序按时间倒序遍历(items 已倒序),第一次见某源即为其最新条目→记 latest_title / latest_dt(用于来源卡 sc-peek 与 fresh 徽章)
    stats = {}
    for it in items:
        lbl = it.get("source_label", "")
        if not lbl:
            continue
        s = stats.get(lbl)
        if s is None:
            stats[lbl] = {
                "count": 1,
                "latest": _day(it),
                "latest_dt": _effective_dt(it),
                "latest_title": it.get("title_zh") or it.get("title") or "",
                "category": it.get("category", ""),
                "src_id": it.get("source_id", ""),
            }
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

    # === v2 增益:Today on Radar 雷达条 ===
    today = now.strftime("%Y-%m-%d")
    today_items = [it for it in items if _day(it) == today]
    cat_today = {c: 0 for c in _CAT_ORDER}
    for it in today_items:
        c = it.get("category", "")
        if c in cat_today:
            cat_today[c] += 1
    today_total = sum(cat_today.values())
    # 7 日均(不含今天)用于同比
    last7 = {it.get("hash"): _effective_dt(it) for it in items}
    week_total = sum(
        1 for it in items
        if (_effective_dt(it) and _MIN_DT < _effective_dt(it) < now
            and (now - _effective_dt(it)).days < 8 and _day(it) != today)
    )
    week_avg = week_total / 7 if week_total else 0
    diff_pct = int(round((today_total - week_avg) / week_avg * 100)) if week_avg else 0
    diff_html = (f'<span>↑ {diff_pct}% vs 7 日均</span>' if diff_pct > 0
                 else f'<span>↓ {abs(diff_pct)}% vs 7 日均</span>' if diff_pct < 0
                 else '<span>= 7 日均</span>')
    max_cat = max(cat_today.values()) if cat_today.values() else 1
    last4h = sum(1 for it in today_items
                 if _effective_dt(it) != _MIN_DT and (now - _effective_dt(it)).total_seconds() < 4 * 3600)
    pulse_html = f'<span class="pulse">LIVE · 最近 4 小时 +{last4h}</span>' if last4h else '<span class="pulse">LIVE · 待更新</span>'
    bars_html = ""
    for cat in _CAT_ORDER:
        n = cat_today.get(cat, 0)
        h = max(3, int(n / max_cat * 100)) if max_cat else 3
        bars_html += (f'<a class="bar {_cat_class(cat)}" href="{_e(_feed_href("") if False else "/feed.html")}" title="{_e(cat)} {n} 条">'
                      f'<span class="bar-n">{n}</span><span class="bar-fill" style="height:{h}%"></span>'
                      f'<span class="bar-label">{_e(cat)}</span></a>')
    wd = _WEEKDAY[now.weekday()] if 0 <= now.weekday() < 7 else ""
    radar_html = (f'<section class="radar" aria-label="今日上新雷达">'
                  f'<div class="radar-l"><div class="k">Today on Radar</div>'
                  f'<div class="v">{today_total}</div>'
                  f'<div class="s">{today} · {wd}</div></div>'
                  f'<div class="radar-bars">{bars_html}</div>'
                  f'<div class="radar-r">{pulse_html}{diff_html}<span>构建 {now.strftime("%m-%d %H:%M")}</span></div>'
                  f'</section>') if today_total else ""

    # === v2 增益:Editor's Cut 副位(自动挑读)——从人工挑过的条目里挑近期最贴合的一条,不假装编辑批注 ===
    pick_pool = [it for it in items
                 if it is not lead and _has_zh_deep(it) and it.get("category") != "推文"]
    pick = pick_pool[0] if pick_pool else None
    cut_html = ""
    if pick:
        ph, _ = _item_href(pick, interactions)
        pt = pick.get("title_zh") or pick.get("title") or ""
        ps_raw = (pick.get("summary_zh") or pick.get("summary") or "").strip()
        ps = (ps_raw[:78] + "…") if len(ps_raw) > 78 else ps_raw
        pcat = pick.get("category", "")
        pwhen = _fmt_md(_day(pick))
        prt = _read_time(pick.get("content_html", ""))
        kind = "已翻译全文" if (pick.get("translation_md") or "").strip() else ("已总结" if (pick.get("summary_md") or "").strip() else "已搬运 B 站")
        cut_html = (f'<a class="cut {_cat_class(pcat)}" href="{ph}?from=reads">'
                    f'<div class="ek"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                    f'<path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.4 2.4-7.4L2 9.4h7.6L12 2z" stroke-linejoin="round"/></svg>'
                    f"Editor's Cut · 精读挑读</div>"
                    f'<div class="meta"><span class="dot"></span><span class="src">{_e(pick.get("source_label",""))}</span>'
                    f'<span>·</span><span>{_e(pcat)}</span></div>'
                    f'<h3>{_e(pt)}</h3>'
                    f'{f"<p class=\"ed-note\">{_e(ps)}</p>" if ps else ""}'
                    f'<div class="ed-foot"><span class="ed-auto">自动挑选 · {_e(kind)}</span>'
                    f'<span>{_e(pwhen)}{" · " + prt if prt else ""}</span></div></a>')

    front_html = ""
    if lead:
        href, _ = _item_href(lead, interactions)
        title = lead.get("title_zh") or lead.get("title") or ""
        summ = lead.get("summary_zh") or lead.get("summary") or ""
        rt = _read_time(lead.get("content_html", ""))
        when = _fmt_md(_day(lead))
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
        kicker = (f'<div class="kicker"><h2>最新 · Latest</h2>'
                  f'<span class="cnt">跨 {len(stats)} 源</span><span class="rule"></span>'
                  f'<a href="/feed.html" class="more">看全部 →</a></div>')
        # 有 cut 时用 .front-row 双列;没有就退回原单列
        if cut_html:
            front_html = (f'<section>{kicker}<div class="front-row">'
                          f'<div class="front">{lead_html}<div class="mini-list">{mini_html}</div></div>'
                          f'{cut_html}</div></section>')
        else:
            front_html = (f'<section>{kicker}'
                          f'<div class="front">{lead_html}<div class="mini-list">{mini_html}</div></div></section>')

    # 来源目录
    by_cat = {}
    for lbl, s in stats.items():
        by_cat.setdefault(s["category"], []).append((lbl, s))
    ordered = [c for c in _CAT_ORDER if c in by_cat] + [c for c in by_cat if c not in _CAT_ORDER]

    def _fresh(dt):
        """≤24h 用 accent 'Nh 前' 加深为 fresh;否则 mono 灰 'MM-DD'。"""
        if dt and dt != _MIN_DT:
            delta = (now - dt).total_seconds()
            if 0 <= delta < 24 * 3600:
                h = max(1, int(delta // 3600))
                return f'<span class="fresh">{h}h 前</span>'
        s = (dt.strftime("%Y-%m-%d") if dt and dt != _MIN_DT else "")
        return f'<span>{_e(s[5:] or s)}</span>'

    def card(lbl, s):
        cat = s["category"]
        desc = descriptions.get(lbl, "")
        peek = s.get("latest_title") or ""
        blob = _e(f"{lbl} {desc} {cat} {peek}".lower())
        desc_html = f'<p class="sc-desc">{_e(desc)}</p>' if desc else ""
        peek_html = f'<div class="sc-peek">{_e(peek)}</div>' if peek else ""
        m = methods.get(lbl, "")
        b_html = f'<span class="b" title="入口B:无 RSS,须在 Claude 会话里抓取">入口B</span>' if m else ""
        return (f'<a class="src-card {_cat_class(cat)}" href="{_e(_feed_href(lbl))}" data-text="{blob}">'
                f'<div class="sc-top">{_avatar(lbl)}<div>'
                f'<div class="sc-name">{_e(lbl)}</div>'
                f'<div class="sc-cat"><span class="dot"></span>{_e(cat)}</div></div></div>'
                f'{desc_html}{peek_html}'
                f'<div class="sc-foot">{_fresh(s.get("latest_dt"))}'
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
            + "\n<body>\n" + _top_header("home", stat=stat, search_ph="搜来源 · 回车搜内容")
            + '\n<main class="wrap">\n' + radar_html + "\n" + front_html
            + f'\n<div class="dir">\n{dir_html}\n<p class="empty" id="empty">没有匹配的来源。</p>\n</div>\n</main>\n'
            + f'<footer class="foot"><span>AI&nbsp;RADAR</span><span class="sep">·</span>'
            + f'<span>本地聚合 · 无登录分享</span><span class="sep">·</span>'
            + f'<span>{len(stats)} 来源 · {len(by_cat)} 分类 · {total} 条</span><span class="sep">·</span>'
            + f'<span>构建于 {build}</span></footer>\n'
            + f'<script>{_THEME_JS}{_HOME_JS}</script>\n</body>\n</html>\n')
    (out / "index.html").write_text(page, encoding="utf-8")


# ---------- 时间流 / 单来源 ----------

_TW_PFX = re.compile(r"^@\S+(?:\s*🔁\s*@\S+)?：")  # 推文正文前缀 "@handle：" / "@A 🔁 @B：",卡片里移到 meta 行后剥掉

def _card(item, mode="detail", anchor=""):
    cat = item.get("category") or ""
    src = item.get("source_label", "")
    title = item.get("title_zh") or item.get("title") or ""
    summ = item.get("summary_zh") or item.get("summary") or ""
    if mode == "link":
        href, is_ext = _safe_url(item.get("url", "")), True
    else:
        href, is_ext = f'/item/{_e(item.get("hash",""))}.html{anchor}', False  # anchor 如 #zh:直接开中文翻译 tab
    ext_attr = ' target="_blank" rel="noopener"' if is_ext else ""
    if cat == "推文":  # 推文卡片:真头像 + 作者名@handle(认证)+ 译文(主)+ 原文(弱化)+ 配图 + 被引用推卡;直跳 X
        try:
            tm = json.loads(item.get("tweet_meta") or "{}")
        except (ValueError, TypeError):
            tm = {}
        trans = item.get("title_zh") or item.get("title") or ""
        orig = item.get("title") or ""
        trans_t = _TW_PFX.sub("", trans).strip()   # 去正文前缀 "@handle："(作者已移到 meta 行)
        orig_t = _TW_PFX.sub("", orig).strip()
        handle, name = tm.get("handle", ""), (tm.get("name") or "").strip()
        name = name or (f"@{handle}" if handle else src)
        avatar = (f'<img class="avatar-img tw-av" src="{_e(tm["avatar"])}" alt="" loading="lazy">'
                  if tm.get("avatar") else _avatar(name or src))
        vf = _VERIFIED_SVG if tm.get("verified") else ""
        handle_html = f'<span class="tw-handle">@{_e(handle)}</span>' if handle else ""
        rt_html = f'<span class="tw-rt">🔁 @{_e(tm.get("rt"))}</span>' if tm.get("rt") else ""
        tw_ext = '<span class="ext">↗</span>' if is_ext else ""
        orig_html = f'<div class="it-orig">{_e(orig_t)}</div>' if orig_t and orig_t != trans_t else ""
        media = _lazy_imgs(item.get("content_html") or "")
        media_html = f'<div class="it-media">{media}</div>' if media else ""
        q = tm.get("quote") or {}
        quote_html = ""
        if q.get("text") or q.get("handle"):
            qn = (q.get("name") or "").strip() or (f"@{q.get('handle','')}")
            qh = f' <span class="tw-handle">@{_e(q.get("handle"))}</span>' if q.get("handle") else ""
            quote_html = (f'<div class="tw-quote"><div class="tw-q-head">{_e(qn)}{qh}</div>'
                          f'<div class="tw-q-text">{_e(q.get("text", ""))}</div></div>')
        return (f'<a class="item {_cat_class(cat)} tw" href="{href}"{ext_attr} '
                f'data-cat="{_e(cat)}" data-source="{_e(src)}" data-text="{_e(f"{trans} {orig} {src}".lower())}">'
                f'{avatar}<div class="it-body">'
                f'<div class="it-meta"><span class="tw-name">{_e(name)}{vf}</span>{handle_html}{rt_html}'
                f'<span class="tag"><span class="dot"></span>{_e(cat)}</span>'
                f'<span class="time">{_e(_fmt_time(item))}</span></div>'
                f'<div class="it-title">{_e(trans_t)}{tw_ext}</div>{orig_html}{media_html}{quote_html}</div></a>')
    # 搜索域:中英都进(title_zh 中译 + title 英文原 + 两版摘要),这样英文关键词也能搜到
    blob = _e(f"{item.get('title','')} {item.get('title_zh','')} {item.get('summary','')} {item.get('summary_zh','')} {src}".lower())
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

    # v2:逐天的分类点位计数(8 类全部展示,0 的半透明) + 当日总量(用于 rail vol 条相对最大值)
    max_day_n = max((len(its) for _, its in sections), default=1) or 1
    day_info = []  # [(day, its, cat_counts, vol_pct)]
    for day, its in sections:
        cc = {c: 0 for c in _CAT_ORDER}
        for it in its:
            c = it.get("category", "")
            if c in cc:
                cc[c] += 1
        vol = int(len(its) / max_day_n * 100) if max_day_n else 0
        day_info.append((day, its, cc, vol))

    def _day_cats_html(cc):
        parts = []
        for cat in _CAT_ORDER:
            n = cc.get(cat, 0)
            cls = f"dc {_cat_class(cat)}" + (" zero" if n == 0 else "")
            parts.append(f'<span class="{cls}"><span class="dot"></span>{_e(cat)} <span class="n">{n}</span></span>')
        return "".join(parts)

    body = []
    for day, its, cc, vol in day_info:
        rows = "\n".join(_card(it, interactions.get(it.get("source_id"), "detail")) for it in its)
        md = _fmt_md(day).replace("-", " / ")
        body.append(f'<section class="day" id="d-{_e(day)}">'
                    f'<div class="day-label">'
                    f'<div class="day-label-row"><span class="d">{_e(md)}</span>'
                    f'<span class="w">{_weekday(day)}</span><span class="rule"></span>'
                    f'<span class="n">{len(its)} 条</span></div>'
                    f'<div class="day-cats">{_day_cats_html(cc)}</div>'
                    f'</div>\n{rows}\n</section>')
    body_html = "\n".join(body) if body else ""

    # v2:左侧迷你日期游标(最多 14 天)
    rail_items = []
    for day, its, _cc, vol in day_info[:14]:
        md = _fmt_md(day).replace("-", " / ")
        rail_items.append(
            f'<a href="#d-{_e(day)}" class="rail-day" data-day="{_e(day)}">'
            f'<span><span class="d">{_e(md)}</span><span class="w">{_weekday(day)}</span></span>'
            f'<span class="vol"><span style="width:{max(6, vol)}%"></span></span></a>')
    if rail_items:
        # 首项默认 on
        rail_items[0] = rail_items[0].replace('class="rail-day"', 'class="rail-day on"', 1)
    rail_html = '<aside class="rail" id="rail"><div class="rail-k">Timeline</div>' + "".join(rail_items) + '</aside>' if rail_items else ""

    pills = ['<span class="pill on" data-cat="">全部</span>']
    for cat in [c for c in _CAT_ORDER if c != "推文"]:
        pills.append(f'<span class="pill {_cat_class(cat)}" data-cat="{_e(cat)}"><span class="dot"></span>{_e(cat)}</span>')
    pills_html = "".join(pills)

    page = (_head("AI Radar — 时间流", _FEED_CSS, maxw="760px")
            + "\n<body>\n" + _top_header("feed", search_ph="搜索内容(中英)…")
            + '\n<div class="shell">' + rail_html
            + '<main class="wrap"><div class="feed-head"><a href="/" class="back">← 总览</a>'
            + '<h1 id="feed-title">时间流</h1><div class="sub" id="feed-sub">全部来源 · 按时间倒序 · 不含推文</div>'
            + f'<div class="pills" id="pills">{pills_html}</div></div>\n'
            + body_html
            + '\n<p class="empty" id="empty">该分类暂无内容。</p>\n</main>\n</div>\n'
            + f'<script>{_THEME_JS}{_FEED_JS}{_LIGHTBOX_JS}</script>\n</body>\n</html>\n')
    (out / "feed.html").write_text(page, encoding="utf-8")


def _has_zh_deep(item):
    """有人工中文深读内容:全文翻译(translation_md)/ 视频总结(summary_md)/ B站译制版(video_url 含 bilibili)。"""
    return bool((item.get("translation_md") or "").strip()
                or (item.get("summary_md") or "").strip()
                or "bilibili" in (item.get("video_url") or ""))


def _render_reads(items, interactions, out):
    """「精读」=所有带全文翻译 / 视频总结的条目(文章 + 视频),按天分组、按时间倒序。
    卡片深链到中文内容:有总结的视频→详情默认开「总结」;有译文的文章→ #zh 直接开「中文翻译」。"""
    reads = [it for it in items if _has_zh_deep(it)]
    sections, cur, buf = [], None, []
    for it in reads:
        d = _day(it)
        if d != cur:
            if buf:
                sections.append((cur, buf))
            cur, buf = d, []
        buf.append(it)
    if buf:
        sections.append((cur, buf))

    def anchor(it):
        # ?from=reads 让详情页把返回链接改成「← 精读」;hash 直接打开对应 tab
        if (it.get("summary_md") or "").strip():
            return "?from=reads"          # 视频总结:详情页「总结」tab 已默认打开
        return "?from=reads#zh"           # 文章译文:直接开「中文翻译」tab

    body = []
    for day, its in sections:
        rows = "\n".join(_card(it, interactions.get(it.get("source_id"), "detail"), anchor(it)) for it in its)
        md = _fmt_md(day).replace("-", " / ")
        body.append(f'<section class="day"><div class="day-label">'
                    f'<div class="day-label-row"><span class="d">{_e(md)}</span>'
                    f'<span class="w">{_weekday(day)}</span><span class="rule"></span>'
                    f'<span class="n">{len(its)} 条</span></div>'
                    f'</div>\n{rows}\n</section>')
    body_html = "\n".join(body) if body else '<p class="empty">还没有精读内容——挑中的文章补全文翻译、视频补总结后会出现在这里。</p>'

    page = (_head("AI Radar — 精读", _FEED_CSS, maxw="760px")
            + "\n<body>\n" + _top_header("reads", search_ph="搜索内容(中英)…")
            + '\n<main class="wrap"><div class="feed-head"><a href="/" class="back">← 总览</a>'
            + '<h1 id="feed-title">精读</h1>'
            + f'<div class="sub">已翻译 / 已总结的中文深读内容 · {len(reads)} 篇 · 按时间倒序</div></div>\n'
            + body_html
            + '\n<p class="empty" id="empty">没有匹配的内容。</p>\n</main>\n'
            + f'<script>{_THEME_JS}{_FEED_JS}{_LIGHTBOX_JS}</script>\n</body>\n</html>\n')
    (out / "reads.html").write_text(page, encoding="utf-8")


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


_BV_RE = re.compile(r"(BV[0-9A-Za-z]+)")


def _bili_bv(url):
    m = _BV_RE.search(url or "")
    return m.group(1) if m else ""


def _facade(cover, src, badge, data_attr, hint="点击播放", duration="", published=""):
    """通用 lite 门面：封面 + 播放钮 + 角标(badge 顶左 hint 顶右 时长右下);点击才由 _DETAIL_JS 挂 iframe。
    duration/published 留空则不渲染对应角标(诚实空态,不造假)。"""
    dur_html = f'<span class="dur">{_e(duration)}</span>' if duration else ""
    pub_html = f'<span class="pub">{_e(published)}</span>' if published else ""
    return (f'<div class="facade" {data_attr}>'
            f'<img class="thumb" src="{cover}" alt="" loading="lazy">'
            f'<div class="hint">{hint}</div>'
            f'{pub_html}{dur_html}'
            f'<div class="play"><span class="pbtn">{_PLAY_SVG}</span></div>'
            f'<div class="ov"><span class="dotmark">{_e(_monogram(src))}</span>'
            f'<div><div class="nm">{_e(src)}</div><div class="sub2">{badge}</div></div></div></div>')


def _youtube_embed(url, src="", item=None):
    """YouTube 门面;点击才挂 iframe（无注入）。无 vid → ""。
    item 给到则尝试取 published_at 显示。时长目前 ai-radar 没抓→不显示(诚实空态)。"""
    vid = _yt_id(url)
    if not vid:
        return ""
    pub = ""
    if item:
        dt = _effective_dt(item)
        if dt and dt != _MIN_DT:
            pub = dt.strftime("%Y-%m-%d")
    return _facade(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", src, "YouTube", f'data-yt="{vid}"', published=pub)


def _bili_embed(bili_url, yt_url, src="", item=None):
    """B站门面(中文翻译搬运):用 YouTube 同片封面 + 哔哩哔哩角标;点击挂 player.bilibili.com。无 BV → ""。"""
    bv = _bili_bv(bili_url)
    if not bv:
        return ""
    vid = _yt_id(yt_url)
    cover = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else ""
    cid = re.search(r"cid=(\d+)", bili_url or "")  # set_bili.py 取自 B站 API,有则更可靠加载
    data = f'data-bv="{bv}"' + (f' data-cid="{cid.group(1)}"' if cid else "")
    pub = ""
    if item:
        dt = _effective_dt(item)
        if dt and dt != _MIN_DT:
            pub = dt.strftime("%Y-%m-%d") + " 搬运"
    return _facade(cover, src, "哔哩哔哩 · 中文翻译", data, hint="中文翻译 · 点击播放", published=pub)


# v2:文章正文 h2/h3 注入 id 并抽出 outline(供右浮目录使用)。
_H_TAG_RE = re.compile(r'<h([23])([^>]*)>(.+?)</h\1>', re.S)


def _inject_outline_ids(html_str, outline, seen, kept_max=18):
    """对 html_str 里所有 h2/h3:已有 id 跳过、否则按 inner text 生成 slug(去重)并注入。
    同时把前 kept_max 条收入 outline(list of (lvl, slug, text))。"""
    def slug_of(text):
        s = re.sub(r'[^\w一-龥]+', '-', text).strip('-')[:40]
        return s or f"h{len(outline) + 1}"

    def repl(m):
        lvl = int(m.group(1)); attrs = m.group(2) or ""; inner = m.group(3)
        text = re.sub(r'<[^>]+>', '', inner).strip()
        if not text:
            return m.group(0)
        if 'id=' in attrs:
            return m.group(0)
        sl = slug_of(text); base = sl; i = 0
        while sl in seen:
            i += 1; sl = f"{base}-{i}"
        seen.add(sl)
        if len(outline) < kept_max:
            outline.append((lvl, sl, text))
        return f'<h{lvl} id="{sl}"{attrs}>{inner}</h{lvl}>'

    return _H_TAG_RE.sub(repl, html_str)


def _tabs(item):
    """文章态 tabs：原文（content_html）/ 中文翻译（translation_md 有则渲染全文，无则诚实空态）。
    返回 (tabs_html, outline)。outline 优先取译文,无则取原文,从而 outline 内容与默认打开的 tab 一致。"""
    content = _lazy_imgs(item.get("content_html") or "")
    yuanwen = content or '<p style="color:var(--muted)">本条无正文,点上方「打开原文」查看。</p>'
    tmd = (item.get("translation_md") or "").strip()
    if tmd:
        zh, zh_cls = _lazy_imgs(md_to_html(tmd)), "panel doc"
    else:
        zh, zh_cls = _tr_empty("文章"), "panel"
    outline, seen = [], set()
    # 先注 zh 再注原文:译文若有就当主大纲(显示给用户)
    if tmd:
        zh = _inject_outline_ids(zh, outline, seen)
    yuanwen = _inject_outline_ids(yuanwen, outline if not tmd else [], seen if not tmd else set())
    tabs_html = ('<div class="tabs"><button class="tab on" data-panel="p-orig">原文</button>'
                 '<button class="tab" data-panel="p-zh">中文翻译</button></div>'
                 f'<section class="panel on doc" id="p-orig">{yuanwen}</section>'
                 f'<section class="{zh_cls}" id="p-zh">{zh}</section>')
    return tabs_html, outline


def _outline_html(outline):
    """outline list[(lvl,slug,text)] → 右浮目录 HTML。空时返回 ""。"""
    if not outline:
        return ""
    parts = []
    for lvl, slug, text in outline:
        cls = "h3" if lvl == 3 else "h2"
        parts.append(f'<li class="{cls}"><a href="#{slug}">{_e(text)}</a></li>')
    return ('<aside class="outline" id="outline"><div class="outline-k">Contents</div>'
            '<ol>' + "".join(parts) + '</ol></aside>')


# v2:视频总结 markdown 里 '## NN:NN 标题' / '## NN:NN:NN 标题' 形式 → 抽 chapters,改写 h2 加 id 和 ts
_H2_TS = re.compile(r'<h2[^>]*>\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+([^<]+?)\s*</h2>')


def _extract_chapters(html_str):
    """返回 (改写后 html, chapters list)。无时间戳的 h2 原样保留。"""
    chapters = []

    def repl(m):
        ts, ttl = m.group(1), m.group(2).strip()
        sl = re.sub(r'[^\w一-龥]+', '-', ttl).strip('-')[:40] or f"c{len(chapters) + 1}"
        chapters.append({"ts": ts, "title": ttl, "slug": sl})
        return f'<h2 id="{sl}"><span class="ts">{ts}</span>{ttl}</h2>'

    return _H2_TS.sub(repl, html_str), chapters


def _chapters_html(chapters):
    if not chapters:
        return ""
    parts = []
    for c in chapters:
        parts.append(f'<a class="chap" href="#{c["slug"]}" data-anchor="{c["slug"]}">'
                     f'<span class="ts">{_e(c["ts"])}</span>'
                     f'<span class="ttl">{_e(c["title"])}</span></a>')
    parts[0] = parts[0].replace('class="chap"', 'class="chap on"', 1)
    return '<div class="chapters">' + "".join(parts) + '</div>'


def _detail_header(src, cat_cls, with_reader=False):
    """with_reader=True 时(仅文章态)在主题切换前插入阅读偏好工具条:字号 -/+/宽窄/sepia。"""
    reader = ('<div class="reader" role="toolbar" aria-label="阅读偏好">'
              '<button id="font-down" title="缩小字号">A−</button>'
              '<button id="font-up" title="放大字号">A+</button>'
              '<button id="width-toggle" class="opt" data-on="0" title="切宽窄读">⇆</button>'
              '<button id="sepia" class="opt" data-on="0" title="柔光阅读底">◐</button>'
              '</div>') if with_reader else ""
    return (f'<header class="top"><div class="top-in">'
            f'<a id="back" href="{_e(_feed_href(src))}" class="back {cat_cls}">'
            f'{_avatar(src, "av")}<span>← {_e(src) or "AI Radar"}</span></a>'
            f'<div class="top-right">{reader}<button class="icon-btn" id="theme" aria-label="切换深浅色">{_SUNMOON_SVG}</button></div>'
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
        # ---- 视频态:英文(YouTube 原片)/ 中文(B站翻译搬运)双 tab ----
        subtitle = title if (title_zh and title and title_zh != title) else ""
        sub_html = f'<p class="subtitle" style="font-style:normal;font-size:14.5px;color:var(--muted)">{_e(subtitle)}</p>' if subtitle else ""
        desc_en = item.get("summary") or ""
        desc_html = (f'<p style="font-family:var(--serif);font-size:16px;line-height:1.7;color:var(--fg-2);margin-top:18px">{_e(desc_en)}</p>'
                     if desc_en else "")
        en_panel = _youtube_embed(raw_url, src, item) + desc_html
        bili = _bili_embed(item.get("video_url", ""), raw_url, src, item)
        if bili:
            zh_panel = (bili + '<p style="margin-top:14px;font-size:13px;color:var(--muted)">本视频已翻译并搬运至 '
                        f'<a href="{_safe_url(item.get("video_url",""))}" target="_blank" rel="noopener" '
                        'style="color:var(--accent-2);text-decoration:underline">哔哩哔哩</a>;点封面在站内播放中文翻译版。</p>')
        else:
            zh_panel = _tr_empty("视频")
        # v2:总结 tab 抽时间戳章节(`## NN:NN 标题`形式),无时间戳时正常渲染
        summ_md = (item.get("summary_md") or "").strip()
        if summ_md:
            sum_raw = _lazy_imgs(md_to_html(summ_md))
            sum_body, chapters = _extract_chapters(sum_raw)
            sum_panel = _chapters_html(chapters) + sum_body
        else:
            sum_panel = ('<div class="tr-empty"><div class="ico">' + _TR_SVG + '</div>'
                         '<h3>这条视频还没有内容总结</h3>'
                         '<p>挑中的视频可上传一篇中文总结(看完视频提炼要点),在此 tab 阅读。</p>'
                         '<p class="why">上传:src/set_summary.py &lt;hash&gt; &lt;总结.md&gt;</p></div>')
        has_sum = bool(summ_md)
        on_sum, on_en = (" on", "") if has_sum else ("", " on")
        body = (f'<main class="wrap {cat_cls}">'
                f'{meta}<h1 class="title">{_e(head_title)}</h1>{sub_html}'
                f'<div class="actions">'
                f'<a class="btn primary" href="{url}" target="_blank" rel="noopener">{_EXTLINK_SVG}在 YouTube 打开</a>'
                f'<button class="btn" id="copy" data-url="{_e(raw_url)}">{_COPY_SVG}<span>复制链接</span></button></div>'
                f'<div class="tabs"><button class="tab{on_en}" data-panel="p-en">英文</button>'
                f'<button class="tab" data-panel="p-zh">中文</button>'
                f'<button class="tab{on_sum}" data-panel="p-sum">总结</button></div>'
                f'<section class="panel{on_en}" id="p-en">{en_panel}</section>'
                f'<section class="panel" id="p-zh">{zh_panel}</section>'
                f'<section class="panel{on_sum} doc" id="p-sum">{sum_panel}</section></main>')
        progress = ""
        header_html = _detail_header(src, cat_cls, with_reader=False)
    else:
        # ---- 文章态:正文抽 outline,wrap 外面包 .shell-doc 双列(正文 + 右浮目录) ----
        subtitle = title if (title_zh and title and title_zh != title) else ""
        sub_html = f'<p class="subtitle">{_e(subtitle)}</p>' if subtitle else ""
        rt = _read_time(item.get("content_html", ""))
        rt_html = f'<span class="read-time">{rt}</span>' if rt else ""
        tabs_html, outline = _tabs(item)
        outline_html = _outline_html(outline)
        wrap = (f'<main class="wrap {cat_cls}">'
                f'{meta}<h1 class="title">{_e(head_title)}</h1>{sub_html}'
                f'<div class="actions">'
                f'<a class="btn primary" href="{url}" target="_blank" rel="noopener">{_EXTLINK_SVG}打开原文</a>'
                f'<button class="btn" id="copy" data-url="{_e(raw_url)}">{_COPY_SVG}<span>复制链接</span></button>{rt_html}</div>'
                f'{tabs_html}</main>')
        body = f'<div class="shell-doc">{wrap}{outline_html}</div>'
        progress = '<div class="progress" id="progress"></div>'
        header_html = _detail_header(src, cat_cls, with_reader=True)

    page = (_head(head_title + " · AI Radar", _DETAIL_CSS, maxw="680px" if not is_video else "760px")
            + "\n<body>\n" + progress + "\n" + header_html + "\n" + body
            + f'\n<script>{_THEME_JS}{_DETAIL_JS}{_LIGHTBOX_JS}</script>\n</body>\n</html>\n')
    (out / "item" / f"{item.get('hash','')}.html").write_text(page, encoding="utf-8")


def render_site(items, interactions=None, descriptions=None, icons=None, out_dir=None, methods=None):
    """interactions: {source_id: 'detail'|'link'}；descriptions/icons/methods: {source_label: ...}。
    首页=报头+最新头版+来源目录；feed.html=时间流/单来源；item/<hash>.html=文章态/视频态。"""
    global _ICONS
    interactions = interactions or {}
    descriptions = descriptions or {}
    _ICONS = icons or {}
    _img_have_cache[0] = None  # 每次渲染重读 dist/img(丢图防御按当前文件状态判定)
    out = Path(out_dir) if out_dir else DIST
    shutil.rmtree(out / "item", ignore_errors=True)
    (out / "item").mkdir(parents=True, exist_ok=True)
    (out / "sources.html").unlink(missing_ok=True)
    _render_home(items, descriptions, methods or {}, interactions, out)
    _render_feed(items, interactions, out)
    _render_reads(items, interactions, out)
    for it in items:
        if it.get("hash") and interactions.get(it.get("source_id"), "detail") != "link":
            _render_detail(it, out, descriptions)
    return out / "index.html"
