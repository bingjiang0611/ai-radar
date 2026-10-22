"""ai-radar curated publishing tests. No network required."""

import contextlib
import io
import re
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import content  # noqa: E402
import publish_item  # noqa: E402
import render  # noqa: E402
import run  # noqa: E402
from store import all_items, init_db, insert_items, normalize_url, purge_old, url_hash  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_strips_tracking_and_fragment(self):
        self.assertEqual(
            normalize_url("https://Example.com/a/?utm_source=x&id=1#frag"),
            "https://example.com/a?id=1",
        )

    def test_query_param_order_same_hash(self):
        self.assertEqual(
            url_hash("https://e.com/a?b=2&a=1"),
            url_hash("https://e.com/a?a=1&b=2"),
        )

    def test_keeps_legit_reference_id(self):
        out = normalize_url("https://e.com/a?reference_id=9&reflink=spam")
        self.assertIn("reference_id=9", out)
        self.assertNotIn("reflink", out)


class TestContent(unittest.TestCase):
    def test_sanitize_keeps_img_strips_script(self):
        out = content.sanitize('<p>x</p><img src="https://a/b.png"><script>bad()</script>')
        self.assertIn("<img", out)
        self.assertNotIn("<script", out)

    def test_generated_links_are_sanitized(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.links.append(dict(attrs))

        for convert in (content.sanitize, content.normalize_article_html, content.md_to_html):
            for source in (
                '[click](javascript:alert`1`)',
                '[click](https://example.com/"onmouseover="alert`1`)',
            ):
                with self.subTest(convert=convert.__name__, source=source):
                    parser = Links()
                    parser.feed(convert(source))
                    self.assertEqual(len(parser.links), 1)
                    attrs = parser.links[0]
                    self.assertFalse(attrs.get("href", "").lower().startswith("javascript:"))
                    self.assertNotIn("onmouseover", attrs)

    def test_sanitized_math_keeps_layout_and_accessibility(self):
        out = content.sanitize(r'<p>$$ \frac{x}{y} $$</p>')
        self.assertIn('class="math-block"', out)
        self.assertIn('class="math-frac"', out)
        self.assertIn('role="math"', out)
        self.assertIn('aria-label="', out)
        self.assertNotIn("$$", out)

    def test_localize_rewrites_http_src(self):
        with mock.patch.object(content, "_download_image", return_value="/img/deadbeef.png"):
            out = content.localize_images('<img src="https://a/b.png" alt="x">')
        self.assertIn('src="/img/deadbeef.png"', out)
        self.assertNotIn("https://a/b.png", out)

    def test_md_to_html_blocks_and_escapes(self):
        out = content.md_to_html("# H1\n\npara **bold** and [lk](https://x.com)\n\n- a\n\n> q\n\n<script>")
        self.assertIn("<h1>H1</h1>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn('<a href="https://x.com" rel="noopener noreferrer">lk</a>', out)
        self.assertIn("<li>a</li>", out)
        self.assertIn("<blockquote>q</blockquote>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_md_to_html_pipe_table(self):
        out = content.md_to_html(
            "| 路线 | 证据 |\n"
            "|---|---|\n"
            "| ACE | **中到高** |\n"
            "| DGM | [paper](https://example.com) |\n"
        )
        self.assertIn('<div class="table-wrap">', out)
        self.assertIn("<table>", out)
        self.assertIn("<th>路线</th>", out)
        self.assertIn("<td>ACE</td>", out)
        self.assertIn("<strong>中到高</strong>", out)
        self.assertIn('<a href="https://example.com" rel="noopener noreferrer">paper</a>', out)
        self.assertNotIn("<p>| 路线", out)

    def test_md_to_html_repairs_etch_footnotes(self):
        out = content.md_to_html(
            "正文<sup>1</sup>\n\n* * *\n\n"
            "1. 注释一 [↩](https://example.com/#one \"返回\")\n\n"
            "2. 注释二 [↩](https://example.com/#two \"返回\")"
        )
        self.assertIn("正文<sup>1</sup>", out)
        self.assertIn("<hr>", out)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertIn('<a href="https://example.com/#one" rel="noopener noreferrer">↩</a>', out)

    def test_md_to_html_renders_display_math(self):
        out = content.md_to_html(
            r"$$ \\mathrm{Verbosity}=\\frac{|x\\cup y|}{\\mathrm{LOC}} $$"
        )
        self.assertIn('class="math-block"', out)
        self.assertIn('class="math-frac"', out)
        self.assertIn("∪", out)
        self.assertNotIn("$$", out)

    def test_normalize_article_html_repairs_escaped_sup_and_math(self):
        out = content.normalize_article_html(
            r'<p>x&lt;sup&gt;<a href="#n">1</a>&lt;/sup&gt;</p><p>$$ \\sqrt{x} $$</p>'
            r'<ol><li>* *</li></ol><ol><li>one [↩](https://example.com/#one "back")</li></ol>'
            r'<ol><li>two</li></ol>'
        )
        self.assertIn('<sup><a href="#n" rel="noopener noreferrer">1</a></sup>', out)
        self.assertIn('class="math-root"', out)
        self.assertIn('<hr><ol>', out)
        self.assertEqual(out.count('<ol>'), 1)
        self.assertIn('<a href="https://example.com/#one" rel="noopener noreferrer">↩</a>', out)

    def test_download_image_accepts_short_timeouts(self):
        old_dist_img = content.DIST_IMG
        fake_png = b"\x89PNG\r\n\x1a\nabc"
        with TemporaryDirectory() as td:
            content.DIST_IMG = Path(td)
            fake = mock.Mock(returncode=0, stdout=fake_png)
            try:
                with mock.patch.object(content.subprocess, "run", return_value=fake) as subprocess_run:
                    self.assertTrue(content._download_image("https://example.com/a.png", max_time=3, timeout=4))
                args, kwargs = subprocess_run.call_args
                curl_args = args[0]
                self.assertEqual(curl_args[curl_args.index("--max-time") + 1], "3")
                self.assertEqual(kwargs["timeout"], 4)
            finally:
                content.DIST_IMG = old_dist_img

    def test_large_local_image_is_optimized_for_markdown(self):
        old_dist_img = content.DIST_IMG
        with TemporaryDirectory() as td:
            content.DIST_IMG = Path(td)
            source = content.DIST_IMG / "cover.png"
            source.write_bytes(b"x" * 300_000)

            def fake_cwebp(args, **_kwargs):
                Path(args[-1]).write_bytes(b"webp")
                return mock.Mock(returncode=0)

            try:
                with mock.patch.object(content.shutil, "which", return_value="/usr/bin/cwebp"), \
                     mock.patch.object(content.subprocess, "run", side_effect=fake_cwebp):
                    out = content.optimize_markdown_images("![cover](/img/cover.png)")
                self.assertEqual(out, "![cover](/img/cover.webp)")
                self.assertTrue((content.DIST_IMG / "cover.webp").exists())
            finally:
                content.DIST_IMG = old_dist_img


class TestStore(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.source = {"id": "s", "source_label": "S", "category": "文章"}

    def tearDown(self):
        self.conn.close()

    def test_insert_dedups_by_normalized_url(self):
        self.assertEqual(insert_items([{"url": "https://example.com/a?utm_source=x", "title": "A"}], self.source, self.conn), 1)
        self.assertEqual(insert_items([{"url": "https://example.com/a", "title": "A again"}], self.source, self.conn), 0)
        self.assertEqual(len(all_items(self.conn)), 1)

    def test_purge_old_keeps_curated_content(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        self.conn.execute(
            """INSERT INTO items
               (hash,source_id,source_label,category,title,url,published_at,fetched_at,translation_md)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("deep", "s", "S", "文章", "deep", "https://e.com/deep", old, old, "译文"),
        )
        self.conn.execute(
            """INSERT INTO items
               (hash,source_id,source_label,category,title,url,published_at,fetched_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("old", "s", "S", "文章", "old", "https://e.com/old", old, old),
        )
        self.conn.commit()
        self.assertEqual(purge_old(30, self.conn), 1)
        self.assertEqual([r["title"] for r in all_items(self.conn)], ["deep"])


class TestRun(unittest.TestCase):
    def test_fetch_flag_is_gone(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run.parse_args(["--fetch"])

    def test_render_current_filters_to_curated_items(self):
        curated = {"hash": "h1", "source_id": "user-curated", "source_label": "用户精选",
                   "title": "curated", "url": "https://e.com/curated", "content_html": ""}
        raw = {"hash": "h2", "source_id": "rss", "source_label": "RSS",
               "title": "raw", "url": "https://e.com/raw", "content_html": ""}
        with mock.patch.object(run, "purge_old", return_value=0), \
             mock.patch.object(run, "all_items", return_value=[curated, raw]), \
             mock.patch.object(run.content, "gc_images", return_value=0), \
             mock.patch.object(run, "render_site", return_value=Path("dist")) as render_site, \
             contextlib.redirect_stdout(io.StringIO()):
            run.render_current()
        self.assertEqual(render_site.call_args.args[0], [curated])


class TestPublishItem(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.tmp = TemporaryDirectory()
        self._old_publish_dist_img = publish_item.DIST_IMG
        publish_item.DIST_IMG = Path(self.tmp.name) / "img"
        publish_item.DIST_IMG.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        publish_item.DIST_IMG = self._old_publish_dist_img
        self.conn.close()
        self.tmp.cleanup()

    def _md(self, name, text):
        p = Path(self.tmp.name) / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_publish_translation_creates_curated_item(self):
        md = self._md("zh.md", "# 中文标题\n\n正文")
        args = publish_item.parse_args([
            "--url", "https://example.com/post?utm_source=x",
            "--kind", "article",
            "--translation", md,
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            h = publish_item.publish(args, self.conn)
        row = self.conn.execute("SELECT * FROM items WHERE hash=?", (h,)).fetchone()
        self.assertEqual(row["source_id"], "user-curated")
        self.assertEqual(row["source_label"], "用户精选")
        self.assertEqual(row["category"], "文章")
        self.assertEqual(row["title"], "中文标题")
        self.assertEqual(row["translation_md"], "# 中文标题\n\n正文")
        self.assertEqual(row["published_at"], "")

    def test_publish_summary_updates_existing_item(self):
        insert_items([{"url": "https://youtu.be/rzVhPTSNWnE", "title": "Old"}],
                     {"id": "yt", "source_label": "YouTube", "category": "视频"}, self.conn)
        md = self._md("sum.md", "# 新总结\n\n要点")
        args = publish_item.parse_args([
            "--url", "https://youtu.be/rzVhPTSNWnE",
            "--title", "New",
            "--kind", "video",
            "--summary", md,
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            h = publish_item.publish(args, self.conn)
        row = self.conn.execute("SELECT * FROM items WHERE hash=?", (h,)).fetchone()
        self.assertEqual(row["title"], "New")
        self.assertEqual(row["source_label"], "用户精选")
        self.assertEqual(row["summary_md"], "# 新总结\n\n要点")

    def test_publish_cover_updates_tweet_meta(self):
        (publish_item.DIST_IMG / "x-cover.jpg").write_bytes(b"x")
        md = self._md("sum.md", "# 总结\n\n要点")
        args = publish_item.parse_args([
            "--url", "https://x.com/shao__meng/status/2075764484027932963",
            "--title", "Motion atlas",
            "--kind", "video",
            "--summary", md,
            "--cover", "/img/x-cover.jpg",
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            h = publish_item.publish(args, self.conn)
        row = self.conn.execute("SELECT * FROM items WHERE hash=?", (h,)).fetchone()
        self.assertIn('"/img/x-cover.jpg"', row["tweet_meta"])

    def test_publish_x_video_rejects_missing_cover(self):
        md = self._md("sum.md", "# 总结\n\n要点")
        args = publish_item.parse_args([
            "--url", "https://x.com/shao__meng/status/2075764484027932963",
            "--title", "Motion atlas",
            "--kind", "video",
            "--summary", md,
        ])
        with self.assertRaisesRegex(ValueError, "X 视频必须提供真实封面"):
            publish_item.publish(args, self.conn)

    def test_validate_dist_rejects_x_video_poster_fallback(self):
        old_root = publish_item.ROOT
        with TemporaryDirectory() as td:
            try:
                publish_item.ROOT = Path(td)
                item_dir = publish_item.ROOT / "dist" / "item"
                item_dir.mkdir(parents=True)
                (publish_item.ROOT / "dist" / "index.html").write_text(
                    '<a class="pick-banner c-video" data-cat="视频" href="/item/xh1.html#en">'
                    '<div class="pick-cover poster c-video"></div></a>',
                    encoding="utf-8",
                )
                (item_dir / "xh1.html").write_text('<blockquote class="twitter-tweet"></blockquote>', encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "X 视频首页卡片缺封面"):
                    publish_item.validate_dist("xh1")
            finally:
                publish_item.ROOT = old_root

    def test_validate_dist_allows_article_with_shared_twitter_styles(self):
        old_root = publish_item.ROOT
        with TemporaryDirectory() as td:
            try:
                publish_item.ROOT = Path(td)
                item_dir = publish_item.ROOT / "dist" / "item"
                item_dir.mkdir(parents=True)
                (publish_item.ROOT / "dist" / "index.html").write_text(
                    '<a class="pick-banner c-research" data-cat="文章" href="/item/a1.html#zh">'
                    '<div class="pick-cover has-img c-research"></div></a>',
                    encoding="utf-8",
                )
                (item_dir / "a1.html").write_text(
                    '<style>.x-embed .twitter-tweet{margin:0 auto}</style>',
                    encoding="utf-8",
                )
                publish_item.validate_dist("a1")
            finally:
                publish_item.ROOT = old_root

    def test_publish_rejects_obsidian_embeds(self):
        md = self._md("bad.md", "# T\n\n![[attachments/a.png]]")
        args = publish_item.parse_args([
            "--url", "https://example.com/post",
            "--title", "T",
            "--kind", "article",
            "--translation", md,
        ])
        with self.assertRaises(ValueError):
            publish_item.publish(args, self.conn)


class TestRender(unittest.TestCase):
    def test_translation_lead_h1_matching_title_is_stripped(self):
        item = {"title": "How the Claude Code team does code review", "title_zh": "Claude Code 团队如何进行代码审查"}
        html = content.md_to_html("# Claude Code 团队如何进行代码审查\n\n正文段落")
        out = render._strip_dup_title(html, item)
        self.assertNotIn("<h1", out)
        self.assertIn("正文段落", out)

    def test_translation_lead_h1_unrelated_is_kept(self):
        item = {"title": "Some English title", "title_zh": ""}
        html = content.md_to_html("# 另一个小标题\n\n正文段落")
        self.assertIn("另一个小标题", render._strip_dup_title(html, item))

    def setUp(self):
        self._tmp_img_dir = TemporaryDirectory()
        self._old_dist_img = content.DIST_IMG
        content.DIST_IMG = Path(self._tmp_img_dir.name)
        render._img_have_cache[0] = None

    def tearDown(self):
        content.DIST_IMG = self._old_dist_img
        render._img_have_cache[0] = None
        self._tmp_img_dir.cleanup()

    def test_youtube_embed_uses_direct_hq_cover(self):
        html = render._youtube_embed("https://www.youtube.com/watch?v=rzVhPTSNWnE")
        self.assertIn('data-yt="rzVhPTSNWnE"', html)
        self.assertIn("https://i.ytimg.com/vi/rzVhPTSNWnE/hq720.jpg", html)
        self.assertNotIn("/thumb/", html)

    def test_video_facade_prefers_explicit_cover(self):
        content.DIST_IMG.mkdir(parents=True, exist_ok=True)
        (content.DIST_IMG / "video-cover.jpg").write_bytes(b"x")
        render._img_have_cache[0] = None
        item = {"tweet_meta": '{"cover": "/img/video-cover.jpg"}'}
        html = render._youtube_embed("https://www.youtube.com/watch?v=rzVhPTSNWnE", item=item)
        self.assertIn('src="/img/video-cover.jpg"', html)
        self.assertNotIn("https://i.ytimg.com/vi/rzVhPTSNWnE/hq720.jpg", html)

    def test_x_video_detail_uses_native_embed(self):
        item = {
            "hash": "xh1",
            "source_id": "user-curated",
            "source_label": "Berryxia.AI",
            "category": "视频",
            "title": "Context engineering",
            "title_zh": "Anthropic 上下文工程",
            "summary": "A public X video.",
            "summary_zh": "",
            "url": "https://x.com/berryxia/status/2070911343293825059",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "published_at": "",
            "content_html": "",
            "translation_md": "",
            "summary_md": "## 要点\n\n上下文管理。",
            "video_url": "",
        }
        with TemporaryDirectory() as td:
            out = Path(td)
            render.render_site([item], interactions={"user-curated": "detail"}, out_dir=out)
            index = (out / "index.html").read_text(encoding="utf-8")
            detail = (out / "item" / "xh1.html").read_text(encoding="utf-8")
        self.assertIn('href="/item/xh1.html#en"', index)
        self.assertIn('class="twitter-tweet"', detail)
        self.assertIn("https://twitter.com/berryxia/status/2070911343293825059", detail)
        self.assertIn("https://platform.twitter.com/widgets.js", detail)
        self.assertIn("在 X 打开", detail)
        self.assertIn('class="tab on" data-panel="p-en"', detail)
        self.assertIn('class="panel on" id="p-en"', detail)
        self.assertNotIn('data-panel="p-zh"', detail)
        self.assertNotIn("这条视频还没有中文字幕", detail)
        self.assertIn('data-panel="p-sum"', detail)

    def test_bili_video_home_link_defaults_to_english_tab(self):
        item = {
            "hash": "bv1",
            "source_id": "user-curated",
            "source_label": "Google DeepMind",
            "category": "视频",
            "title": "Don't Ship Skills Without Evals",
            "title_zh": "",
            "summary": "",
            "summary_zh": "",
            "url": "https://www.youtube.com/watch?v=rzVhPTSNWnE",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "published_at": "",
            "content_html": "",
            "translation_md": "",
            "summary_md": "",
            "video_url": "https://www.bilibili.com/video/BV1xx411c7mD/?cid=1",
            "tweet_meta": "",
        }
        with TemporaryDirectory() as td:
            out = Path(td)
            render.render_site([item], interactions={"user-curated": "detail"}, out_dir=out)
            index = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/item/bv1.html#en"', index)
        self.assertNotIn('href="/item/bv1.html#zh"', index)

    def test_x_article_detail_stays_article(self):
        item = {
            "hash": "xa1",
            "source_id": "user-curated",
            "source_label": "ClaudeDevs",
            "category": "文章",
            "title": "Model and effort",
            "title_zh": "Claude Code 中的 model 与 effort",
            "summary": "",
            "summary_zh": "",
            "url": "https://x.com/ClaudeDevs/status/2074900291062034618",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "published_at": "",
            "content_html": "<p>original</p>",
            "translation_md": "## 中文译文\n\n正文",
            "summary_md": "",
            "video_url": "",
        }
        with TemporaryDirectory() as td:
            out = Path(td)
            render.render_site([item], interactions={"user-curated": "detail"}, out_dir=out)
            detail = (out / "item" / "xa1.html").read_text(encoding="utf-8")
        self.assertIn("打开原文", detail)
        self.assertIn("中文翻译", detail)
        self.assertNotIn('class="twitter-tweet"', detail)
        self.assertNotIn("platform.twitter.com/widgets.js", detail)

    def test_tabs_translation_outline(self):
        panel, outline = render._tabs({"content_html": "<p>x</p>", "translation_md": "## 中文段落\n\n正文"})
        self.assertIn("中文翻译", panel)
        self.assertIn("中文段落", panel)
        self.assertEqual(outline[0][2], "中文段落")

    def test_article_without_chinese_hides_chinese_tab(self):
        panel, outline = render._tabs({"content_html": "<h2>Original</h2><p>x</p>"})
        self.assertIn('data-panel="p-orig"', panel)
        self.assertNotIn('data-panel="p-zh"', panel)
        self.assertNotIn("这篇还没有中文全文", panel)
        self.assertEqual(outline[0][2], "Original")

    def test_article_summary_uses_article_labels(self):
        item = {"category": "文章", "content_html": "", "summary_md": "## 摘要\n\n要点"}
        panel, outline = render._tabs(item)
        self.assertEqual(render._deep_kind(item), "文章摘要")
        self.assertIn("中文摘要", panel)
        self.assertIn('class="tab on" data-panel="p-zh"', panel)
        self.assertNotIn('data-panel="p-orig"', panel)
        self.assertNotIn("本条无正文", panel)
        self.assertIn("摘要", panel)
        self.assertEqual(outline[0][2], "摘要")

    def test_wide_article_cover_uses_wide_layout(self):
        old_render_dist = render.DIST
        old_content_dist_img = content.DIST_IMG
        with TemporaryDirectory() as td:
            root = Path(td)
            try:
                render.DIST = root
                content.DIST_IMG = root / "img"
                content.DIST_IMG.mkdir(parents=True)
                png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                       + (1200).to_bytes(4, "big") + (400).to_bytes(4, "big")
                       + b"\x08\x02\x00\x00\x00\x00\x00\x00\x00")
                (content.DIST_IMG / "wide.png").write_bytes(png)
                item = {
                    "hash": "wide1",
                    "source_id": "user-curated",
                    "source_label": "antirez",
                    "category": "文章",
                    "title": "Wide cover",
                    "title_zh": "横幅封面",
                    "summary": "summary",
                    "summary_zh": "",
                    "url": "https://example.com/wide",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "published_at": "",
                    "content_html": "",
                    "translation_md": "",
                    "summary_md": "## 摘要\n\n要点",
                    "video_url": "",
                    "tweet_meta": '{"cover": "/img/wide.png"}',
                }
                item2 = dict(item, hash="wide2", url="https://example.com/wide-2", title="Wide cover 2")
                out = root / "out"
                render.render_site([item, item2], interactions={"user-curated": "detail"}, out_dir=out)
                index = (out / "index.html").read_text(encoding="utf-8")
            finally:
                render.DIST = old_render_dist
                content.DIST_IMG = old_content_dist_img
                render._img_have_cache[0] = None
        self.assertIn("pick-banner fit-wide", index)
        self.assertIn("pick-cover has-img fit-contain fit-wide", index)
        self.assertIn("--cover-aspect:3.000;", index)
        self.assertIn('<img class="cover-img" src="/img/wide.png" alt="" fetchpriority="high" decoding="async">', index)
        self.assertIn('<img class="cover-img" src="/img/wide.png" alt="" loading="lazy" decoding="async">', index)

    def test_render_site_outputs_only_overview_and_details(self):
        item = {
            "hash": "h1",
            "source_id": "user-curated",
            "source_label": "用户精选",
            "category": "文章",
            "title": "English",
            "title_zh": "中文标题",
            "summary": "",
            "summary_zh": "中文摘要",
            "url": "https://example.com/a",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "published_at": "",
            "content_html": "<p>original</p>",
            "translation_md": "## 中文段落\n\n正文",
            "summary_md": "",
            "video_url": "",
        }
        with TemporaryDirectory() as td:
            out = Path(td)
            render.render_site([item], interactions={"user-curated": "detail"}, out_dir=out)
            index = (out / "index.html").read_text(encoding="utf-8")
            detail = (out / "item" / "h1.html").read_text(encoding="utf-8")
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "item" / "h1.html").exists())
            self.assertFalse((out / "feed.html").exists())
            self.assertFalse((out / "reads.html").exists())
            self.assertIn("data-card", index)
            self.assertNotIn("reads.html", index)
            self.assertIn('href="/"', detail)
            self.assertIn("← 总览", detail)
            self.assertNotIn('class="av"', detail)
            self.assertNotIn('class="av-img"', detail)
            self.assertIn("--doc-maxw:820px", detail)
            self.assertIn(".top-in{max-width:var(--reader-maxw)", detail)
            self.assertIn(".shell-doc{max-width:var(--reader-maxw)", detail)
            self.assertIn('id="width-toggle" class="opt" data-on="1"', detail)

    def test_card_cover_uses_article_contain_and_video_cover(self):
        self.assertEqual(
            render._item_cover({"url": "https://www.youtube.com/watch?v=rzVhPTSNWnE"}),
            "https://i.ytimg.com/vi/rzVhPTSNWnE/hq720.jpg",
        )
        self.assertEqual(
            render._item_cover({"tweet_meta": '{"cover": "https://example.com/x.jpg"}'}),
            "https://example.com/x.jpg",
        )
        content.DIST_IMG.mkdir(parents=True, exist_ok=True)
        (content.DIST_IMG / "cover.png").write_bytes(b"x")
        render._img_have_cache[0] = None
        self.assertEqual(render._item_cover({"translation_md": "![a](/img/cover.png)"}), "/img/cover.png")


if __name__ == "__main__":
    unittest.main()
