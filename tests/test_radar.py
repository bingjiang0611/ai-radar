"""ai-radar curated publishing tests. No network required."""

import contextlib
import io
import re
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_localize_rewrites_http_src(self):
        with mock.patch.object(content, "_download_image", return_value="/img/deadbeef.png"):
            out = content.localize_images('<img src="https://a/b.png" alt="x">')
        self.assertIn('src="/img/deadbeef.png"', out)
        self.assertNotIn("https://a/b.png", out)

    def test_md_to_html_blocks_and_escapes(self):
        out = content.md_to_html("# H1\n\npara **bold** and [lk](https://x.com)\n\n- a\n\n> q\n\n<script>")
        self.assertIn("<h1>H1</h1>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn('<a href="https://x.com">lk</a>', out)
        self.assertIn("<li>a</li>", out)
        self.assertIn("<blockquote>q</blockquote>", out)
        self.assertIn("&lt;script&gt;", out)

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

    def tearDown(self):
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

    def test_tabs_translation_outline(self):
        panel, outline = render._tabs({"content_html": "<p>x</p>", "translation_md": "## 中文段落\n\n正文"})
        self.assertIn("中文翻译", panel)
        self.assertIn("中文段落", panel)
        self.assertEqual(outline[0][2], "中文段落")

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

    def test_card_cover_uses_article_contain_and_video_cover(self):
        self.assertEqual(
            render._item_cover({"url": "https://www.youtube.com/watch?v=rzVhPTSNWnE"}),
            "https://i.ytimg.com/vi/rzVhPTSNWnE/hq720.jpg",
        )
        content.DIST_IMG.mkdir(parents=True, exist_ok=True)
        (content.DIST_IMG / "cover.png").write_bytes(b"x")
        render._img_have_cache[0] = None
        self.assertEqual(render._item_cover({"translation_md": "![a](/img/cover.png)"}), "/img/cover.png")


if __name__ == "__main__":
    unittest.main()
