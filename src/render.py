"""Render the curated ai-radar static site.

The public surface is intentionally small: overview cards plus item detail pages.
"""

import html
import json
import re
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path

from store import _parse_dt  # 统一时间解析(兼容 ISO 与 RFC822 pubDate)
from content import md_to_html  # 译文 translation_md(markdown)→ HTML

# 从 youtube 链接抠 11 位 video id（watch?v= / youtu.be / embed / shorts）
_YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})")
_X_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status(?:es)?/(\d+)")

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

# 不引外部字体：Google Fonts(fonts.googleapis.com)在国内受众网络被墙/503，且是渲染阻塞的跨域请求。
# 衬线统一走 --serif 的系统回退链(Iowan Old Style / Source Serif 4 / Charter / Georgia / Songti SC)，零外部依赖。
_FONT_LINKS = ""

# 内联 SVG favicon(data URI，雷达同心圆)：浏览器不再自动请求 /favicon.ico(避免 404)，且不产生网络请求。
_FAVICON = ('<link rel="icon" href="data:image/svg+xml,'
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
            "stroke='%232b6cb0' stroke-width='2'>"
            "<circle cx='12' cy='12' r='9'/><circle cx='12' cy='12' r='4.5'/>"
            "<circle cx='12' cy='12' r='1.4' fill='%232b6cb0' stroke='none'/></svg>\">")

# ---------- 设计系统（基础，全页共用）----------
_BASE_CSS = """
:root{
  --bg:oklch(98.6% 0.004 255);--surface:oklch(100% 0 0);--surface-2:oklch(97% 0.005 255);
  --inset:oklch(95.5% 0.006 255);--fg:oklch(24% 0.018 262);--fg-2:oklch(43% 0.016 262);
  --muted:oklch(55% 0.013 260);--faint:oklch(53% 0.013 260);--border:oklch(91.5% 0.006 262);
  --border-2:oklch(86% 0.008 262);--accent:oklch(54% 0.16 256);--accent-2:oklch(48% 0.16 256);
  --accent-soft:oklch(95.5% 0.03 256);--accent-line:oklch(82% 0.07 256);
  --shadow:0 1px 2px oklch(24% 0.02 262 / .05),0 8px 24px -12px oklch(24% 0.04 262 / .18);
  --c-research:oklch(56% 0.135 255);--c-product:oklch(54% 0.11 165);--c-newsletter:oklch(56% 0.15 300);
  --c-news:oklch(56% 0.13 66);--c-paper:oklch(53% 0.13 212);--c-podcast:oklch(58% 0.16 352);
  --c-video:oklch(57% 0.17 27);--c-tweet:oklch(53% 0.115 196);
  --serif:'Newsreader','Iowan Old Style','Source Serif 4',Charter,Georgia,'Songti SC',serif;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',system-ui,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono','Menlo',monospace;
  --maxw:1200px;--doc-size:18.5px;--doc-maxw:820px;--outline-w:220px;--reader-gap:48px;--reader-pad:48px;
  --reader-maxw:calc(var(--doc-maxw) + var(--outline-w) + var(--reader-gap) + var(--reader-pad));
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
  --muted:oklch(66% 0.014 258);--faint:oklch(67% 0.014 258);--border:oklch(30% 0.014 262);
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
/* 键盘可达性:仅键盘聚焦时显示焦点环(鼠标点击不触发),outline 不受祖先 overflow 裁剪 */
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
a:focus-visible,button:focus-visible,input:focus-visible,.art-card:focus-visible,.pick-banner:focus-visible,.tab:focus-visible,.chap:focus-visible,.outline a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
/* 尊重系统"减少动态效果":关掉过渡/动画/平滑滚动 */
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{transition-duration:.01ms!important;animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important}
  html{scroll-behavior:auto}
  .art-card:hover,.pick-banner:hover{transform:none}
}
.c-research{--cat:var(--c-research)}.c-product{--cat:var(--c-product)}.c-newsletter{--cat:var(--c-newsletter)}
.c-news{--cat:var(--c-news)}.c-paper{--cat:var(--c-paper)}.c-podcast{--cat:var(--c-podcast)}
.c-video{--cat:var(--c-video)}.c-tweet{--cat:var(--c-tweet)}
.top{position:sticky;top:0;z-index:50;background:color-mix(in oklch,var(--bg) 88%,transparent);
  backdrop-filter:saturate(1.4) blur(12px);-webkit-backdrop-filter:saturate(1.4) blur(12px);border-bottom:1px solid var(--border)}
.top-in{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;gap:16px;padding:12px 24px}
.brand{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-weight:600;font-size:13px;letter-spacing:.16em;text-transform:uppercase}
.brand svg{width:20px;height:20px;color:var(--accent);flex:none}
.nav{display:flex;gap:4px;margin-left:6px}
.nav a{font-size:13.5px;font-weight:500;color:var(--muted);padding:5px 11px;border-radius:7px;transition:.15s}
.nav a:hover{color:var(--fg);background:var(--surface-2)}
.nav a.on{color:var(--fg);background:var(--inset)}
.stat{margin-left:6px;font-family:var(--mono);font-size:11.5px;color:var(--faint);letter-spacing:.02em}
.top-right{margin-left:auto;display:flex;align-items:center;gap:9px}
.search{position:relative}
.search input{width:216px;background:var(--surface-2);border:1px solid var(--border);color:var(--fg);
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
  .search{flex:1;min-width:56px;max-width:240px}.search input{width:100%}
  .foot{font-size:12px}}
"""

_HOME_CSS = """
.wrap{max-width:var(--maxw);margin:0 auto;padding:34px 24px 72px}
.home-hero{padding:34px 0 26px;max-width:860px}
.home-eyebrow{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent-2);margin-bottom:14px}
.home-eyebrow::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent)}
.home-title{font-family:var(--sans);font-weight:760;font-size:52px;line-height:1.05;letter-spacing:0;text-wrap:balance}
.home-title .em{color:var(--accent-2)}
.home-tagline{margin-top:12px;color:var(--muted);font-size:15px;line-height:1.6}
.sec{margin-bottom:42px}
.sec-row{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:16px}
.sec-row::after{content:"";height:1px;flex:1;background:var(--border)}
.sec-k{font-family:var(--mono);font-size:11px;font-weight:650;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.sec-more{font-family:var(--mono);font-size:11px;color:var(--accent-2)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px}
.fchip{font-family:var(--mono);font-size:12px;letter-spacing:.02em;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:6px 14px;cursor:pointer;transition:.15s;white-space:nowrap}
.fchip:hover{color:var(--fg);border-color:var(--border-2)}
.fchip.on{color:#fff;background:oklch(52% 0.17 256);border-color:oklch(52% 0.17 256)}
.pick-banner{position:relative;display:grid;grid-template-columns:minmax(0,1.55fr) minmax(340px,.85fr);min-height:430px;border-radius:8px;overflow:hidden;background:var(--surface);color:var(--fg);border:1px solid var(--border);box-shadow:var(--shadow);transition:border-color .16s ease,box-shadow .16s ease}
.pick-banner.fit-wide{grid-template-columns:minmax(0,1.55fr) minmax(340px,.85fr)}
.pick-banner:hover{border-color:var(--accent-line);box-shadow:0 16px 40px -22px color-mix(in oklch,var(--accent) 42%,transparent)}
.pick-banner::after{content:attr(data-word);position:absolute;right:24px;top:24px;font-family:var(--mono);font-weight:800;font-size:58px;line-height:1;letter-spacing:0;color:color-mix(in oklch,var(--cat,var(--accent)) 16%,transparent);pointer-events:none;z-index:1}
.pick-cover{position:relative;min-height:430px;background:linear-gradient(135deg,color-mix(in oklch,var(--cat,var(--accent)) 18%,var(--surface-2)),var(--inset));background-size:cover;background-position:center;overflow:hidden}
.pick-cover.has-img{background:var(--inset)}
.pick-cover.fit-wide.has-img{aspect-ratio:auto}
.pick-cover.poster{display:flex;align-items:flex-end;padding:28px;background:radial-gradient(130% 120% at 86% 8%,color-mix(in oklch,var(--cat,var(--accent)) 22%,var(--surface-2)),var(--inset)),repeating-linear-gradient(90deg,transparent 0 47px,color-mix(in oklch,var(--fg) 4%,transparent) 47px 48px)}
.pick-body{position:relative;z-index:2;display:flex;min-width:0;flex-direction:column;justify-content:flex-end;padding:38px 34px 34px;background:var(--surface);border-left:1px solid var(--border)}
.pick-meta,.art-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:var(--mono);font-size:11px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;background:var(--surface-2);border:1px solid var(--border);color:var(--fg-2)}
.pill.strong{background:color-mix(in oklch,var(--cat,var(--accent)) 15%,var(--surface));border-color:color-mix(in oklch,var(--cat,var(--accent)) 42%,transparent);color:var(--cat,var(--accent))}
.pick-title{font-family:var(--sans);font-weight:760;font-size:30px;line-height:1.2;letter-spacing:0;margin:20px 0 12px;text-wrap:balance;color:var(--fg)}
.pick-dek{max-width:820px;color:var(--muted);font-size:15.5px;line-height:1.58}
.pick-foot{margin-top:18px;font-family:var(--mono);font-size:11.5px;color:var(--faint)}
.art-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
.art-grid.single{grid-template-columns:1fr}
.art-grid.single .art-card{display:grid;grid-template-columns:minmax(260px,42%) minmax(0,1fr)}
.art-grid.single .card-cover{height:100%;min-height:260px;aspect-ratio:auto}
.art-grid.single .card-body{min-height:260px}
.art-card{display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--fg);box-shadow:var(--shadow);transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}
.art-card:hover{transform:translateY(-2px);border-color:var(--accent-line);box-shadow:0 14px 36px -20px color-mix(in oklch,var(--accent) 42%,transparent)}
.card-cover{position:relative;aspect-ratio:16/9;background:linear-gradient(135deg,color-mix(in oklch,var(--cat,var(--accent)) 18%,var(--surface-2)),var(--inset));overflow:hidden}
.card-cover.has-img{background:var(--inset)}
.card-cover.fit-wide.has-img{aspect-ratio:var(--cover-aspect,2.4)}
.cover-img{position:absolute;inset:0;width:100%;height:100%;display:block;object-fit:cover}
.fit-contain .cover-img{object-fit:contain}
.fit-wide .cover-img{object-fit:contain}
.pick-cover.has-img::after,.card-cover.has-img::after{content:"";position:absolute;inset:0;z-index:1;background:linear-gradient(180deg,oklch(0% 0 0 / .02),oklch(0% 0 0 / .08));pointer-events:none}
.card-cover.poster{display:flex;align-items:flex-end;padding:18px;background:radial-gradient(130% 120% at 85% 10%,color-mix(in oklch,var(--cat,var(--accent)) 22%,var(--surface-2)),var(--inset)),repeating-linear-gradient(90deg,transparent 0 31px,color-mix(in oklch,var(--fg) 4%,transparent) 31px 32px)}
.poster-word{position:absolute;right:16px;bottom:12px;z-index:0;font-family:var(--mono);font-size:46px;font-weight:800;line-height:.9;color:color-mix(in oklch,var(--cat,var(--accent)) 26%,transparent);letter-spacing:.04em;text-transform:uppercase}
.poster-title{position:relative;z-index:1;font-family:var(--sans);font-size:20px;font-weight:760;line-height:1.2;letter-spacing:-.01em;color:var(--fg);max-width:13ch;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cover-badge{position:absolute;right:10px;top:10px;z-index:2;background:color-mix(in oklch,var(--cat,var(--accent)) 82%,black);color:#fff;border-radius:6px;padding:4px 8px;font-family:var(--mono);font-size:10px;font-weight:700}
.card-body{display:flex;flex-direction:column;gap:10px;padding:20px 22px 22px;min-height:232px;background:var(--surface);border-top:1px solid var(--border)}
.art-card h3{font-family:var(--sans);font-size:19px;font-weight:720;line-height:1.34;letter-spacing:0;text-wrap:balance;color:var(--fg)}
.art-card:hover h3{color:var(--accent-2)}
.art-dek{color:var(--muted);font-size:14px;line-height:1.58;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.card-foot{margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between;gap:12px;font-family:var(--mono);font-size:11px;color:var(--faint)}
.tag-list{display:flex;flex-wrap:wrap;gap:6px}
.tag-chip{display:inline-flex;align-items:center;border:1px solid var(--border);background:var(--surface-2);border-radius:6px;padding:2px 7px;color:var(--muted);font-family:var(--mono);font-size:10.5px}
@media(max-width:920px){.pick-banner,.pick-banner.fit-wide{grid-template-columns:1fr;min-height:0}
  .pick-cover,.pick-cover.fit-wide.has-img{min-height:0;aspect-ratio:16/9}.pick-body{border-left:0;border-top:1px solid var(--border);padding:30px}
  .pick-banner::after{top:calc(56.25vw + 22px)}
}
@media(max-width:880px){.art-grid{grid-template-columns:repeat(2,1fr)}
  .art-grid.single .art-card{display:flex}.art-grid.single .card-cover{height:auto;min-height:0;aspect-ratio:16/9}
}
@media(max-width:560px){.wrap{padding:20px 16px 52px}.home-hero{padding:24px 0 22px}.home-title{font-size:35px}.home-title .em{display:block}.home-tagline{font-size:14px}
  .filters{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:22px;padding-bottom:4px;scrollbar-width:none}.filters::-webkit-scrollbar{display:none}
  .pick-banner,.pick-banner.fit-wide{grid-template-columns:1fr}.pick-cover,.pick-cover.fit-wide.has-img{aspect-ratio:16/9}.pick-banner::after{font-size:48px;right:16px;top:calc(56.25vw + 18px)}.pick-body{padding:24px 22px 26px}.pick-title{font-size:25px}
  .art-grid{grid-template-columns:1fr}.card-body{min-height:210px}}
"""

_DETAIL_CSS = """
.progress{position:fixed;top:0;left:0;height:2.5px;width:0;background:var(--accent);z-index:60;transition:width .08s linear}
.top-in{max-width:var(--reader-maxw);gap:14px}
.back{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:12px;letter-spacing:.04em;color:var(--muted)}
.back:hover{color:var(--accent-2)}
.wrap{max-width:var(--maxw);margin:0 auto;padding:34px 24px 80px}
.a-meta{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
.tag{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--cat);padding:2px 8px;border-radius:5px;background:color-mix(in oklch,var(--cat) 12%,transparent);border:1px solid color-mix(in oklch,var(--cat) 26%,transparent)}
.tag .dot{width:5px;height:5px;border-radius:50%;background:var(--cat)}
.a-meta .src{font-weight:600;color:var(--fg-2)}
.a-meta .mono{font-family:var(--mono);font-size:11px;color:var(--faint)}
h1.title{font-family:var(--serif);font-weight:600;font-size:clamp(30px,3.4vw,46px);line-height:1.13;letter-spacing:-.015em;margin:18px 0 9px;text-wrap:balance}
.subtitle{font-family:var(--serif);font-style:italic;font-weight:400;font-size:19px;line-height:1.35;color:var(--muted)}
.actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:22px 0 4px}
.btn{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:500;font-family:var(--sans);
  border:1px solid var(--border);background:var(--surface);color:var(--fg);padding:9px 14px;border-radius:8px;cursor:pointer;transition:.15s}
.btn:hover{border-color:var(--accent-line);color:var(--accent-2)}
/* 主按钮用固定深蓝(两主题同值)：白字对比度 5.6:1。--accent 在暗色是浅蓝(白字仅 2.5)，故不随主题。 */
.btn.primary{background:oklch(52% 0.17 256);color:#fff;border-color:oklch(52% 0.17 256)}
.btn.primary:hover{background:oklch(45% 0.17 256);border-color:oklch(45% 0.17 256);color:#fff}
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
.doc .img-fallback{display:block;margin:1.2em 0;padding:12px 14px;border:1px dashed var(--border-2);border-radius:10px;background:var(--surface-2);font-family:var(--sans);font-size:13px;color:var(--accent-2);text-decoration:none}
.doc .table-wrap{overflow-x:auto;margin:1.5em 0;border:1px solid var(--border);border-radius:12px;background:var(--surface);box-shadow:var(--shadow);-webkit-overflow-scrolling:touch}
.doc table{width:100%;min-width:680px;border-collapse:collapse;font-family:var(--sans);font-size:13.5px;line-height:1.55}
.doc th,.doc td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top;text-align:left}
.doc th{font-weight:650;background:var(--surface-2);color:var(--fg)}
.doc tbody tr:last-child td{border-bottom:0}
.doc tbody tr:hover td{background:var(--surface-2)}
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
.facade{position:relative;aspect-ratio:16/9;border-radius:8px;overflow:hidden;cursor:pointer;background:oklch(15% 0.02 262);box-shadow:var(--shadow);border:1px solid var(--border);margin-bottom:4px}
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
.shell-doc{max-width:var(--reader-maxw);margin:0 auto;display:grid;grid-template-columns:var(--doc-maxw) var(--outline-w);gap:var(--reader-gap);padding:0 24px;align-items:start;justify-content:center}
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
.x-embed{display:flex;justify-content:center;margin:18px 0 8px;min-height:260px}
.x-embed .twitter-tweet{margin:0 auto!important}
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
(function(){var input=document.getElementById('search'),cards=[].slice.call(document.querySelectorAll('[data-card]')),empty=document.getElementById('empty');
  var chips=[].slice.call(document.querySelectorAll('.fchip')),secs=[].slice.call(document.querySelectorAll('.sec')),curCat='';
  function apply(){var q=input?input.value.trim().toLowerCase():'',hit=0;
    cards.forEach(function(el){var okQ=!q||(el.dataset.text||'').indexOf(q)>-1;var okC=!curCat||el.dataset.cat===curCat;
      var ok=okQ&&okC;el.style.display=ok?'':'none';if(ok)hit++;});
    secs.forEach(function(s){var any=[].slice.call(s.querySelectorAll('[data-card]')).some(function(c){return c.style.display!=='none';});
      s.style.display=any?'':'none';});
    if(empty)empty.style.display=hit?'none':'block';}
  if(input){input.addEventListener('input',apply);
    input.addEventListener('keydown',function(e){if(e.key==='Escape'){input.value='';apply();}});}
  chips.forEach(function(c){c.addEventListener('click',function(){curCat=c.dataset.cat||'';
    chips.forEach(function(x){var on=x===c;x.classList.toggle('on',on);x.setAttribute('aria-selected',on?'true':'false');});
    apply();});});
  apply();})();
"""

_DETAIL_JS = """
var tabs=[].slice.call(document.querySelectorAll('.tab')),panels=[].slice.call(document.querySelectorAll('.panel'));
tabs.forEach(function(b){b.addEventListener('click',function(){
  tabs.forEach(function(x){x.classList.toggle('on',x===b);});
  panels.forEach(function(p){p.classList.toggle('on',p.id===b.dataset.panel);});});});
(function(){var hp=(location.hash||'').slice(1);if(!hp)return;  // #zh/#sum/#en/#orig → 打开对应 tab(精读页深链用)
  var b=tabs.filter(function(x){return x.dataset.panel==='p-'+hp;})[0];if(b)b.click();})();
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
    ifr.style.cssText='width:100%;aspect-ratio:16/9;border:0;border-radius:8px;display:block';
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
  if(wt){var sw=localStorage.getItem('air-width');if(sw==='680px'){wt.dataset.on='0';root.style.setProperty('--doc-maxw','680px');}else{wt.dataset.on='1';root.style.setProperty('--doc-maxw','820px');}
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
    function fail(){
      var a=document.createElement('a');
      a.className='img-fallback';a.href=im.src;a.target='_blank';a.rel='noopener';
      a.textContent=(im.alt||'图片')+' 加载失败，点此打开原图';
      im.replaceWith(a);
    }
    if(im.complete&&!im.naturalWidth){fail();return;}
    im.addEventListener('error',fail,{once:true});
    im.style.cursor='zoom-in';
    im.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();open(im.currentSrc||im.src);});
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){var l=document.querySelector('.lightbox');if(l)l.remove();}});
})();
"""


_IMG_TAG = re.compile(r"(?i)<img[^>]*>")
_IMG_LOCAL = re.compile(r'src="/img/([^"]+)"')
_IMG_SRC = re.compile(r"""(?i)<img[^>]+src=["']([^"']+)["']""")
_MD_IMG = re.compile(r"""!\[[^\]]*]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)""")
_img_have_cache = [None]


def _img_have():
    """dist/img 现存文件名集合(每次渲染进程缓存一次)。"""
    if _img_have_cache[0] is None:
        from content import DIST_IMG
        _img_have_cache[0] = {
            str(p.relative_to(DIST_IMG)).replace("\\", "/")
            for p in DIST_IMG.rglob("*")
            if p.is_file()
        } if DIST_IMG.exists() else set()
    return _img_have_cache[0]


def _lazy_imgs(html_str):
    """给正文/推文配图补原生懒加载和异步解码(隐藏/未滚到视口不下载);
    并**丢弃 /img 文件已不在站的 <img>**——避免破图图标(图若丢失则优雅地不显示,而非裂图)。"""
    if not html_str:
        return html_str
    have = _img_have()

    def repl(m):
        tag = m.group(0)
        loc = _IMG_LOCAL.search(tag)
        if loc and loc.group(1) not in have:
            return ""  # 站内图文件缺失 → 不渲染该 <img>(无破图)
        if "loading=" not in tag:
            tag = tag.replace("<img", '<img loading="lazy"', 1)
        if "decoding=" not in tag:
            tag = tag.replace("<img", '<img decoding="async"', 1)
        return tag

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


def _yt_id(url):
    m = _YT_RE.search(url or "")
    return m.group(1) if m else ""


def _x_status_url(url):
    m = _X_STATUS_RE.search(url or "")
    if not m:
        return ""
    return f"https://twitter.com/{m.group(1)}/status/{m.group(2)}"


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


def _yt_thumb_url(vid):
    return f"https://i.ytimg.com/vi/{vid}/hq720.jpg"


def _cover_exists(src):
    if not src:
        return False
    if src.startswith("/img/"):
        name = src.removeprefix("/img/")
        return name in _img_have()
    return src.startswith(("http://", "https://"))


def _image_size_from_bytes(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            while i < len(data) and data[i] != 0xFF:
                i += 1
            while i < len(data) and data[i] == 0xFF:
                i += 1
            if i >= len(data):
                break
            marker = data[i]
            i += 1
            if marker in (*range(0xD0, 0xDA), 0x01):
                continue
            if i + 2 > len(data):
                break
            seg_len = struct.unpack(">H", data[i:i + 2])[0]
            if seg_len < 2 or i + seg_len > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 3:i + 7])
                return w, h
            i += seg_len
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
        if data[12:16] == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if data[12:16] == b"VP8L" and len(data) >= 25:
            b0, b1, b2, b3 = data[21:25]
            w = 1 + (((b1 & 0x3F) << 8) | b0)
            h = 1 + ((b3 << 6) | (b2 >> 2) | ((b1 & 0xC0) << 6))
            return w, h
    return None


def _local_image_size(src):
    if not (src or "").startswith("/img/"):
        return None
    root = (DIST / "img").resolve()
    path = (DIST / src.removeprefix("/")).resolve()
    try:
        if root not in path.parents or not path.is_file():
            return None
        return _image_size_from_bytes(path.read_bytes()[:1_000_000])
    except OSError:
        return None


def _cover_layout(item, cover):
    if item.get("category") == "视频":
        return "", "", ""
    cls = " fit-contain"
    size = _local_image_size(cover)
    if not size:
        return cls, "", ""
    w, h = size
    if h and w / h >= 2.15:
        return cls + " fit-wide", f"--cover-aspect:{w / h:.3f};", " fit-wide"
    return cls, "", ""


def _item_cover(item):
    """首页卡片封面:显式 cover > YouTube 缩略图 > 正文/译文/总结首图。"""
    try:
        meta = json.loads(item.get("tweet_meta") or "{}")
    except json.JSONDecodeError:
        meta = {}
    cover = (meta.get("cover") or "").strip()
    if _cover_exists(cover):
        return cover
    for url in (item.get("url", ""), item.get("video_url", "")):
        if vid := _yt_id(url):
            return _yt_thumb_url(vid)
    for m in _IMG_SRC.finditer(item.get("content_html") or ""):
        src = html.unescape(m.group(1) or "").strip()
        if _cover_exists(src):
            return src
    for md in (item.get("translation_md") or "", item.get("summary_md") or ""):
        for m in _MD_IMG.finditer(md):
            src = html.unescape((m.group(1) or "").strip("<>"))
            if _cover_exists(src):
                return src
    return ""


def _deep_kind(item):
    if (item.get("translation_md") or "").strip():
        return "全文翻译"
    if (item.get("summary_md") or "").strip():
        if item.get("category") == "文章":
            return "文章摘要"
        return "视频总结"
    if "bilibili" in (item.get("video_url") or ""):
        return "B站译制"
    return item.get("category") or "精选"


def _excerpt(item, limit=118):
    text = (item.get("summary_zh") or item.get("summary") or "").strip()
    if not text:
        text = ((item.get("summary_md") or "").strip()
                or (item.get("translation_md") or "").strip())
    text = re.sub(r"(?s)^---\s.*?\s---", "", text).strip()
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"!\[\[[^\]]+\]\]", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>\[\]()]|https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:limit].rstrip() + "…") if len(text) > limit else text


def _card_time(item):
    bits = []
    d = _fmt_md(_day(item))
    if d:
        bits.append(d)
    rt = _read_time(item.get("content_html", ""))
    if not rt:
        n = len(re.sub(r"\s+", "", (item.get("summary_md") or item.get("translation_md") or "")))
        if n >= 120:
            rt = f"约 {max(1, round(n / 400))} 分钟读"
    if rt:
        bits.append(rt)
    return " · ".join(bits)


def _item_href(item, interactions):
    """详情态 → 站内 /item/<hash>.html；link 态 → 原文外链。返回 (href, is_ext)。"""
    if interactions.get(item.get("source_id"), "detail") == "link" or not item.get("hash"):
        return _safe_url(item.get("url", "")), True
    return f"/item/{_e(item.get('hash', ''))}.html", False


def _head(title, page_css, maxw="1200px", desc="AI Radar — 人工精选的 AI 文章译文、视频/播客总结与译制内容。"):
    return ('<!doctype html>\n<html lang="zh-CN" data-theme="light">\n<head>\n'
            '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="description" content="{_e(desc)}">\n'
            f'{_FAVICON}\n'
            f'<title>{_e(title)}</title>\n'
            f'<script>{_THEME_PRESET}</script>\n'
            f'{_FONT_LINKS}\n<style>\n{_BASE_CSS}\n:root{{--maxw:{maxw}}}\n{page_css}\n</style>\n</head>')


def _top_header(active, stat="", search_ph="搜索…"):
    home_cls = ' class="on"' if active == "home" else ""
    stat_html = f'<span class="stat">{_e(stat)}</span>' if stat else ""
    return (f'<header class="top"><div class="top-in">'
            f'<a href="/" class="brand" aria-label="AI Radar">{_BRAND_SVG}<span>AI&nbsp;Radar</span></a>'
            f'<nav class="nav"><a href="/"{home_cls}>总览</a></nav>'
            f'{stat_html}'
            f'<div class="top-right"><div class="search">{_SEARCH_SVG}'
            f'<input id="search" type="search" placeholder="{_e(search_ph)}" aria-label="{_e(search_ph)}" autocomplete="off"></div>'
            f'<button class="icon-btn" id="theme" aria-label="切换深浅色">{_SUNMOON_SVG}</button>'
            f'</div></div></header>')


# ---------- 首页 ----------

def _render_home(items, _descriptions, _methods, interactions, out):
    stats = {}
    categories = set()
    dates = []
    for it in items:
        lbl = it.get("source_label", "")
        if lbl:
            stats[lbl] = stats.get(lbl, 0) + 1
        if cat := it.get("category", ""):
            categories.add(cat)
        day = _day(it)
        if day != "未知日期":
            dates.append(day)

    # 总览只展示人工精选卡片:优先人工深读,没有时退回最新非推文,方便空库/迁移期预览。
    jf_items = [it for it in items if _has_zh_deep(it)]
    front_pool = [it for it in items if it.get("category") != "推文"]
    card_pool, seen = [], set()
    for group in (jf_items, front_pool):
        for it in group:
            key = it.get("hash") or it.get("url") or it.get("title")
            if not key or key in seen or it.get("category") == "推文":
                continue
            if not (it.get("title_zh") or it.get("title")):
                continue
            seen.add(key)
            card_pool.append(it)
            if len(card_pool) >= 10:
                break
        if len(card_pool) >= 10:
            break

    def _home_href(it):
        href, is_ext = _item_href(it, interactions)
        if not is_ext and _has_zh_deep(it):
            href += "#en" if it.get("category") == "视频" else "#zh"
        return href, (' target="_blank" rel="noopener"' if is_ext else "")

    def _poster_word(it):
        kind = _deep_kind(it)
        return {
            "全文翻译": "READ",
            "文章摘要": "READ",
            "视频总结": "WATCH",
            "B站译制": "VIDEO",
        }.get(kind, (_CAT_EN.get(it.get("category", ""), "PICK") or "PICK").upper())

    def _cover_html(it, cover=None):
        cat_cls = _cat_class(it.get("category", ""))
        kind = _deep_kind(it)
        cover = cover if cover is not None else _item_cover(it)
        badge = _e(kind)
        if cover:
            fit, layout_style, _banner_fit = _cover_layout(it, cover)
            style = f' style="{layout_style}"' if layout_style else ""
            return (f'<div class="card-cover has-img{fit} {cat_cls}"{style}>'
                    f'<img class="cover-img" src="{_e(cover)}" alt="" loading="lazy" decoding="async">'
                    f'<span class="cover-badge">{badge}</span></div>')
        title = it.get("title_zh") or it.get("title") or ""
        first = (re.split(r"[。.!?？]", title.strip(), 1)[0].strip()[:42] or "AI")
        return (f'<div class="card-cover poster {cat_cls}"><span class="cover-badge">{badge}</span>'
                f'<div class="poster-word">{_e(_poster_word(it))}</div>'
                f'<div class="poster-title">{_e(first)}</div></div>')

    def _pick_cover_html(it, cover=None):
        cat_cls = _cat_class(it.get("category", ""))
        kind = _e(_deep_kind(it))
        cover = cover if cover is not None else _item_cover(it)
        if cover:
            fit, layout_style, _banner_fit = _cover_layout(it, cover)
            style = f' style="{layout_style}"' if layout_style else ""
            return (f'<div class="pick-cover has-img{fit} {cat_cls}"{style}>'
                    f'<img class="cover-img" src="{_e(cover)}" alt="" fetchpriority="high" decoding="async">'
                    f'<span class="cover-badge">{kind}</span></div>')
        title = it.get("title_zh") or it.get("title") or ""
        first = (re.split(r"[。.!?？]", title.strip(), 1)[0].strip()[:60] or "AI")
        return (f'<div class="pick-cover poster {cat_cls}"><span class="cover-badge">{kind}</span>'
                f'<div class="poster-word">{_e(_poster_word(it))}</div>'
                f'<div class="poster-title">{_e(first)}</div></div>')

    def _article_card(it):
        href, ext_attr = _home_href(it)
        cat = it.get("category", "")
        title = it.get("title_zh") or it.get("title") or ""
        dek = _excerpt(it)
        when = _card_time(it)
        tags = [_deep_kind(it)]
        if cat and cat not in tags:
            tags.append(cat)
        src = it.get("source_label", "")
        if src:
            tags.append(src)
        tag_html = "".join(f'<span class="tag-chip">{_e(t)}</span>' for t in tags[:3] if t)
        dek_html = f'<p class="art-dek">{_e(dek)}</p>' if dek else ""
        blob = _e(f"{title} {dek} {src} {cat} {' '.join(tags)}".lower())
        return (f'<a class="art-card {_cat_class(cat)}" data-card data-cat="{_e(cat)}" data-text="{blob}" href="{_e(href)}"{ext_attr}>'
                f'{_cover_html(it)}<div class="card-body">'
                f'<div class="art-meta"><span>{_e(src)}</span><span>·</span><span>{_e(cat)}</span></div>'
                f'<h3>{_e(title)}</h3>{dek_html}'
                f'<div class="card-foot"><span class="tag-list">{tag_html}</span>'
                f'<span>{_e(when)}</span></div></div></a>')

    hero_html = (
        '<section class="home-hero">'
        '<div class="home-eyebrow">Curated AI notes</div>'
        '<h1 class="home-title">AI 精选，<span class="em">读到有收获。</span></h1>'
        '<p class="home-tagline">只放人工挑过的文章译文、视频/播客总结和译制内容。少一点噪音，多一点判断。</p>'
        '</section>')

    pick_html = ""
    if card_pool:
        pick_item = card_pool[0]
        href, ext_attr = _home_href(pick_item)
        cat = pick_item.get("category", "")
        title = pick_item.get("title_zh") or pick_item.get("title") or ""
        dek = _excerpt(pick_item, 150)
        dek_html = f'<p class="pick-dek">{_e(dek)}</p>' if dek else ""
        blob = _e(f"{title} {dek} {pick_item.get('source_label','')} {cat} {_deep_kind(pick_item)}".lower())
        pick_cover = _item_cover(pick_item)
        _fit, _style, banner_fit = _cover_layout(pick_item, pick_cover)
        pick_html = (
            '<section class="sec"><div class="sec-row"><h2 class="sec-k">今日精选</h2></div>'
            f'<a class="pick-banner{banner_fit} {_cat_class(cat)}" data-card data-cat="{_e(cat)}" data-text="{blob}" data-word="{_e(_poster_word(pick_item))}" href="{_e(href)}"{ext_attr}>'
            f'{_pick_cover_html(pick_item, pick_cover)}<div class="pick-body">'
            f'<div class="pick-meta"><span class="pill strong">{_e(_deep_kind(pick_item))}</span>'
            f'<span class="pill">人工精选</span><span>{_e(pick_item.get("source_label",""))}</span>'
            f'<span>·</span><span>{_e(cat)}</span></div>'
            f'<h2 class="pick-title">{_e(title)}</h2>'
            f'{dek_html}'
            f'<div class="pick-foot">{_e(_card_time(pick_item))}</div></div></a></section>')

    latest_html = ""
    if len(card_pool) > 1:
        label = "最新精选" if jf_items else "最新内容"
        latest_items = card_pool[1:10]
        grid_cls = "art-grid single" if len(latest_items) == 1 else "art-grid"
        cards = "\n".join(_article_card(it) for it in latest_items)
        latest_html = (
            f'<section class="sec"><div class="sec-row"><h2 class="sec-k">{label}</h2></div>'
            f'<div class="{grid_cls}">\n{cards}\n</div></section>')

    # 类型过滤条:仅当卡片池里出现 ≥2 个类型时才显示。纯前端过滤已有卡片,不引入计数/收藏。
    # 按卡片实际出现顺序取类型(_CAT_ORDER 用的是"资讯"而非"文章",不能拿它当白名单过滤)。
    filter_html = ""
    cats_present = []
    for it in card_pool:
        c = it.get("category")
        if c and c not in cats_present:
            cats_present.append(c)
    if len(cats_present) > 1:
        chips = '<button class="fchip on" data-cat="" role="tab" aria-selected="true">全部</button>' + "".join(
            f'<button class="fchip" data-cat="{_e(c)}" role="tab" aria-selected="false">{_e(c)}</button>'
            for c in cats_present)
        filter_html = f'<div class="filters" id="filters" role="tablist" aria-label="按类型筛选">{chips}</div>'

    total = sum(stats.values())
    latest = max(dates, default="")
    stat = f"{len(stats)} 来源 · {total} 条 · {_fmt_md(latest)} 更新"

    page = (_head("AI Radar — 精选", _HOME_CSS)
            + "\n<body>\n" + _top_header("home", stat=stat, search_ph="搜内容")
            + '\n<main class="wrap">\n' + hero_html + "\n" + filter_html + "\n" + pick_html + "\n" + latest_html + "\n</main>\n"
            + '<p class="empty" id="empty">没有匹配的精选内容。</p>\n'
            + f'<footer class="foot"><span>AI&nbsp;RADAR</span><span class="sep">·</span>'
            + f'<span>人工精选 · 无登录分享</span><span class="sep">·</span>'
            + f'<span>{len(stats)} 来源 · {len(categories)} 分类 · {total} 条</span></footer>\n'
            + f'<script>{_THEME_JS}{_HOME_JS}</script>\n</body>\n</html>\n')
    (out / "index.html").write_text(page, encoding="utf-8")


def _has_zh_deep(item):
    """有人工中文深读内容:全文翻译(translation_md)/ 视频总结(summary_md)/ B站译制版(video_url 含 bilibili)。"""
    return bool((item.get("translation_md") or "").strip()
                or (item.get("summary_md") or "").strip()
                or "bilibili" in (item.get("video_url") or ""))


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
            f'<img class="thumb" src="{cover}" alt="" fetchpriority="high" decoding="async">'
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
    cover = _item_cover(item) if item else ""
    if not cover:
        cover = _yt_thumb_url(vid)
    pub = ""
    if item:
        dt = _effective_dt(item)
        if dt and dt != _MIN_DT:
            pub = dt.strftime("%Y-%m-%d")
    return _facade(cover, src, "YouTube", f'data-yt="{vid}"', published=pub)


def _bili_embed(bili_url, yt_url, src="", item=None):
    """B站门面(中文翻译搬运):优先用条目封面;点击挂 player.bilibili.com。无 BV → ""。"""
    bv = _bili_bv(bili_url)
    if not bv:
        return ""
    vid = _yt_id(yt_url)
    cover = _item_cover(item) if item else ""
    if not cover:
        cover = _yt_thumb_url(vid) if vid else ""
    cid = re.search(r"cid=(\d+)", bili_url or "")  # publish_item.py 取自 B站 API,有则更可靠加载
    data = f'data-bv="{bv}"' + (f' data-cid="{cid.group(1)}"' if cid else "")
    pub = ""
    if item:
        dt = _effective_dt(item)
        if dt and dt != _MIN_DT:
            pub = dt.strftime("%Y-%m-%d") + " 搬运"
    return _facade(cover, src, "哔哩哔哩 · 中文翻译", data, hint="中文翻译 · 点击播放", published=pub)


def _x_embed(url):
    status_url = _x_status_url(url)
    if not status_url:
        return ""
    return ('<div class="x-embed"><blockquote class="twitter-tweet" data-dnt="true">'
            f'<a href="{_e(status_url)}">在 X 查看视频</a>'
            '</blockquote></div>')


# v2:文章正文标题注入 id 并抽出 outline(供右浮目录使用)。匹配 h1-h6,渲染时钳制层级。
_H_TAG_RE = re.compile(r'<h([1-6])([^>]*)>(.+?)</h\1>', re.S)


def _inject_outline_ids(html_str, outline, seen, kept_max=18):
    """把正文里所有标题(h1-h6)钳制到连续的 h2/h3 层级,注入去重 slug id,按归一后层级收 outline。
    钳制规则:页面 h1 之下,正文标题 ≥h2、≤h3、相对上一级不跳级——保证 heading-order 始终有效,
    不依赖正文是否干净(源站边角料标题也会被压成合法层级;词表截断只是额外的内容清洁)。"""
    def slug_of(text):
        s = re.sub(r'[^\w一-龥]+', '-', text).strip('-')[:40]
        return s or f"h{len(outline) + 1}"

    state = {"prev": 1}  # 页面 h1 = level 1

    def repl(m):
        orig = int(m.group(1)); attrs = m.group(2) or ""; inner = m.group(3)
        text = re.sub(r'<[^>]+>', '', inner).strip()
        if not text:
            return m.group(0)
        lvl = max(2, min(orig, 3, state["prev"] + 1))  # ≥h2、≤h3、不跳级
        state["prev"] = lvl
        mid = re.search(r'id="([^"]*)"', attrs)
        if mid:
            sl, new_attrs = mid.group(1), attrs
        else:
            sl = slug_of(text); base = sl; i = 0
            while sl in seen:
                i += 1; sl = f"{base}-{i}"
            new_attrs = f' id="{sl}"{attrs}'
        seen.add(sl)
        if len(outline) < kept_max:
            outline.append((lvl, sl, text))
        return f'<h{lvl}{new_attrs}>{inner}</h{lvl}>'

    return _H_TAG_RE.sub(repl, html_str)


# 直出正文末尾常见的源站边角料区块标题（相关阅读/最新/订阅等）——渲染时从这里整段截断
_DOC_BOILER_HEADING = re.compile(
    r"(?i)^\s*(related\b|latest\b|more (from|in|stories|on)\b|read more\b|recommended\b"
    r"|most popular\b|popular (stories|posts|articles)\b|trending\b|you might\b"
    r"|sign\s*up\b|subscribe\b|newsletters?\b|editor'?s picks\b|from our\b|sponsored\b|advertisement\b)"
)
_LEAD_H1 = re.compile(r"(?is)^\s*<h1[^>]*>.*?</h1>\s*")


def _strip_doc_boilerplate(html_str):
    """渲染前清理直出正文里混入的源站边角料（只动渲染输出、不碰库）：
    ① 去掉开头与页面标题重复的 <h1>（正文不该有自己的 h1，页面已有 h1.title）；
    ② 从第一个"相关阅读/最新/订阅"等边角料区块标题处整段截断（连同其后的相关链接列表）。
    既清正文与右栏目录，又顺带消除由此引发的 heading-order 跳级。"""
    if not html_str:
        return html_str
    html_str = _LEAD_H1.sub("", html_str, count=1)
    for m in re.finditer(r"(?is)<(h[1-6])[^>]*>(.*?)</\1>", html_str):
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if _DOC_BOILER_HEADING.match(text):
            return html_str[:m.start()].rstrip()
    return html_str


def _tabs(item):
    """文章态 tabs：原文 / 中文翻译或摘要。
    返回 (tabs_html, outline)。outline 优先取中文内容,无则取原文,从而 outline 内容与默认打开的 tab 一致。"""
    content = _strip_doc_boilerplate(_lazy_imgs(item.get("content_html") or ""))
    has_content = bool(content.strip())
    yuanwen = content or '<p style="color:var(--muted)">本条无正文,点上方「打开原文」查看。</p>'
    tmd = (item.get("translation_md") or "").strip()
    smd = (item.get("summary_md") or "").strip()
    has_zh = bool(tmd or smd)
    if tmd:
        zh, zh_cls, zh_label = _lazy_imgs(md_to_html(tmd)), "panel doc", "中文翻译"
    elif smd:
        zh, zh_cls, zh_label = _lazy_imgs(md_to_html(smd)), "panel doc", "中文摘要"
    else:
        zh, zh_cls, zh_label = "", "", ""
    outline, seen = [], set()
    # 先注 zh 再注原文:中文内容若有就当主大纲(显示给用户)
    if has_zh:
        zh = _inject_outline_ids(zh, outline, seen)
    yuanwen = _inject_outline_ids(yuanwen, outline if not has_zh else [], seen if not has_zh else set())
    if not has_zh:
        return ('<div class="tabs"><button class="tab on" data-panel="p-orig">原文</button></div>'
                f'<section class="panel on doc" id="p-orig">{yuanwen}</section>'), outline
    if not has_content:
        tabs_html = (f'<div class="tabs"><button class="tab on" data-panel="p-zh">{zh_label}</button></div>'
                     f'<section class="{zh_cls} on" id="p-zh">{zh}</section>')
        return tabs_html, outline
    tabs_html = ('<div class="tabs"><button class="tab on" data-panel="p-orig">原文</button>'
                 f'<button class="tab" data-panel="p-zh">{zh_label}</button></div>'
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


def _detail_header(src, cat_cls, with_reader=False, maxw=None):
    """with_reader=True 时(仅文章态)在主题切换前插入阅读偏好工具条:字号 -/+/宽窄/sepia。
    maxw 给定时(视频态)把顶栏收窄到与正文列同宽,避免顶栏 920 比窄正文脱节;文章态不传,保持 920 对齐 shell-doc。"""
    reader = ('<div class="reader" role="toolbar" aria-label="阅读偏好">'
              '<button id="font-down" title="缩小字号">A−</button>'
              '<button id="font-up" title="放大字号">A+</button>'
              '<button id="width-toggle" class="opt" data-on="1" title="切宽窄读">⇆</button>'
              '<button id="sepia" class="opt" data-on="0" title="柔光阅读底">◐</button>'
              '</div>') if with_reader else ""
    style = f' style="max-width:{maxw}"' if maxw else ""
    return (f'<header class="top"><div class="top-in"{style}>'
            f'<a id="back" href="/" class="back {cat_cls}">'
            f'<span>← 总览</span></a>'
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
    x_status = _x_status_url(raw_url)
    is_video = cat == "视频" or bool(vid)
    # 视频态宽度:YouTube/B站 16:9 用 920;X/推文 embed 本身仅 ~470-550,收窄到 620 把它框住。
    detail_maxw = "680px" if not is_video else ("620px" if x_status else "920px")

    meta = (f'<div class="a-meta"><span class="tag"><span class="dot"></span>{_e(cat)}</span>'
            f'<span class="src">{_e(src)}</span><span class="mono">· {_e(when)}</span></div>')

    if is_video:
        # ---- 视频态:英文(YouTube 原片)/ 中文(B站翻译搬运)双 tab ----
        subtitle = title if (title_zh and title and title_zh != title) else ""
        sub_html = f'<p class="subtitle" style="font-style:normal;font-size:14.5px;color:var(--muted)">{_e(subtitle)}</p>' if subtitle else ""
        desc_en = item.get("summary") or ""
        desc_html = (f'<p style="font-family:var(--serif);font-size:16px;line-height:1.7;color:var(--fg-2);margin-top:18px">{_e(desc_en)}</p>'
                     if desc_en else "")
        if vid:
            en_panel = _youtube_embed(raw_url, src, item) + desc_html
            open_label = "在 YouTube 打开"
        elif x_status:
            en_panel = _x_embed(raw_url) + desc_html
            open_label = "在 X 打开"
        else:
            en_panel = desc_html
            open_label = "打开原视频"
        bili = _bili_embed(item.get("video_url", ""), raw_url, src, item)
        zh_panel = ""
        if bili:
            zh_panel = (bili + '<p style="margin-top:14px;font-size:13px;color:var(--muted)">本视频已翻译并搬运至 '
                        f'<a href="{_safe_url(item.get("video_url",""))}" target="_blank" rel="noopener" '
                        'style="color:var(--accent-2);text-decoration:underline">哔哩哔哩</a>;点封面在站内播放中文翻译版。</p>')
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
                         '<p class="why">上传:src/publish_item.py --summary &lt;总结.md&gt;</p></div>')
        tabs = ['<button class="tab on" data-panel="p-en">英文</button>']
        panels = [f'<section class="panel on" id="p-en">{en_panel}</section>']
        if zh_panel:
            tabs.append('<button class="tab" data-panel="p-zh">中文</button>')
            panels.append(f'<section class="panel" id="p-zh">{zh_panel}</section>')
        tabs.append('<button class="tab" data-panel="p-sum">总结</button>')
        panels.append(f'<section class="panel doc" id="p-sum">{sum_panel}</section>')
        body = (f'<main class="wrap {cat_cls}">'
                f'{meta}<h1 class="title">{_e(head_title)}</h1>{sub_html}'
                f'<div class="actions">'
                f'<a class="btn primary" href="{url}" target="_blank" rel="noopener">{_EXTLINK_SVG}{open_label}</a>'
                f'<button class="btn" id="copy" data-url="{_e(raw_url)}">{_COPY_SVG}<span>复制链接</span></button></div>'
                f'<div class="tabs">{"".join(tabs)}</div>'
                f'{"".join(panels)}</main>')
        progress = ""
        header_html = _detail_header(src, cat_cls, with_reader=False, maxw=detail_maxw)
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

    x_widget = ('\n<script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>'
                if is_video and x_status else "")
    page = (_head(head_title + " · AI Radar", _DETAIL_CSS, maxw=detail_maxw)
            + "\n<body>\n" + progress + "\n" + header_html + "\n" + body
            + f'\n<script>{_THEME_JS}{_DETAIL_JS}{_LIGHTBOX_JS}</script>{x_widget}\n</body>\n</html>\n')
    (out / "item" / f"{item.get('hash','')}.html").write_text(page, encoding="utf-8")


def render_site(items, interactions=None, descriptions=None, icons=None, out_dir=None, methods=None):
    """Render overview plus detail pages."""
    global _ICONS
    interactions = interactions or {}
    descriptions = descriptions or {}
    _ICONS = icons or {}
    _img_have_cache[0] = None  # 每次渲染重读 dist/img(丢图防御按当前文件状态判定)
    out = Path(out_dir) if out_dir else DIST
    shutil.rmtree(out / "item", ignore_errors=True)
    (out / "item").mkdir(parents=True, exist_ok=True)
    (out / "sources.html").unlink(missing_ok=True)
    (out / "feed.html").unlink(missing_ok=True)
    (out / "reads.html").unlink(missing_ok=True)
    _render_home(items, descriptions, methods or {}, interactions, out)
    for it in items:
        if it.get("hash") and interactions.get(it.get("source_id"), "detail") != "link":
            _render_detail(it, out, descriptions)
    # Cloudflare Pages 缓存策略：进站图按内容寻址、几乎不变 → 长缓存；HTML 留默认。
    (out / "_headers").write_text(
        "/img/*\n  Cache-Control: public, max-age=604800\n",
        encoding="utf-8",
    )
    return out / "index.html"
