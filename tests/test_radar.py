"""ai-radar 单测：URL 归一化 / 去重 / RSS·Atom 解析 / JSON 解析。零网络。"""

import json
import re
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import content                                         # noqa: E402
import render                                           # noqa: E402
from fetch import normalize_url, resolve_url           # noqa: E402
from parsers import parse_rss_text, parse_json_text, parse_xiaoyuzhou_text  # noqa: E402
from store import init_db, insert_items, all_items, url_hash, hash_exists, purge_old  # noqa: E402

RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Demo</title>
  <item>
    <title>First Post</title>
    <link>https://example.com/a?utm_source=x</link>
    <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
    <pubDate>Wed, 11 Jun 2026 10:00:00 GMT</pubDate>
  </item>
  <item><title>Second</title><link>https://example.com/b</link></item>
</channel></rss>"""

ATOM_FIXTURE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Vid</title>
    <link rel="alternate" href="https://youtu.be/xyz"/>
    <published>2026-06-10T00:00:00Z</published>
  </entry>
</feed>"""

JSON_FIXTURE = """[
  {"paper": {"id": "2606.00001", "title": "Cool Paper", "upvotes": 42}},
  {"paper": {"id": "2606.00002", "title": "Another", "upvotes": 7}}
]"""

HF_CFG = {
    "items_path": "",
    "title": "paper.title",
    "url_template": "https://huggingface.co/papers/{paper.id}",
    "summary_template": "{paper.upvotes} upvotes",
}


class TestNormalize(unittest.TestCase):
    def test_strips_tracking_and_fragment(self):
        self.assertEqual(
            normalize_url("https://Example.com/a/?utm_source=x&id=1#frag"),
            "https://example.com/a?id=1",
        )

    def test_utm_variants_same_hash(self):
        self.assertEqual(
            url_hash("https://example.com/a?utm_source=x"),
            url_hash("https://example.com/a/"),
        )


class TestResolveUrl(unittest.TestCase):
    def test_no_placeholder_unchanged(self):
        self.assertEqual(resolve_url("https://x.com/a"), "https://x.com/a")

    def test_week_placeholder(self):
        self.assertRegex(resolve_url("https://x.com/a?week={week}"), r"\?week=\d{4}-W\d{2}$")

    def test_date_placeholder(self):
        self.assertRegex(resolve_url("https://x.com/{date}"), r"/\d{4}-\d{2}-\d{2}$")


class TestRss(unittest.TestCase):
    def test_rss_two_items_and_clean_summary(self):
        items = parse_rss_text(RSS_FIXTURE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "First Post")
        self.assertEqual(items[0]["url"], "https://example.com/a?utm_source=x")
        self.assertEqual(items[0]["summary"], "Hello world")  # HTML 标签已去除
        self.assertIn("Hello", items[0]["content"])           # content 保留原始正文

    def test_atom_link_href(self):
        items = parse_rss_text(ATOM_FIXTURE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Vid")
        self.assertEqual(items[0]["url"], "https://youtu.be/xyz")

    def test_limit(self):
        self.assertEqual(len(parse_rss_text(RSS_FIXTURE, limit=1)), 1)

    def test_malformed_xml_returns_empty(self):
        self.assertEqual(parse_rss_text("<not xml"), [])

    def test_bare_ampersand_recovered(self):
        # 部分 feed（如 Apple ML）正文有裸 &，不应导致整篇解析失败
        xml = ('<rss version="2.0"><channel><item>'
               '<title>Tom & Jerry & AI</title><link>https://e.com/a</link>'
               '</item></channel></rss>')
        items = parse_rss_text(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Tom & Jerry & AI")


class TestJson(unittest.TestCase):
    def test_dotted_path_and_url_template(self):
        items = parse_json_text(JSON_FIXTURE, HF_CFG)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Cool Paper")
        self.assertEqual(items[0]["url"], "https://huggingface.co/papers/2606.00001")
        self.assertEqual(items[0]["summary"], "42 upvotes")

    def test_malformed_json_returns_empty(self):
        self.assertEqual(parse_json_text("{bad", HF_CFG), [])


class TestXiaoyuzhou(unittest.TestCase):
    def _html(self, podcast):
        return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
                + json.dumps({"props": {"pageProps": {"podcast": podcast}}})
                + "</script></body></html>")

    def test_episodes_to_items(self):
        html_text = self._html({"title": "测试播客", "episodes": [
            {"eid": "abc123", "title": "第一集", "description": "<p>内容</p>",
             "pubDate": "2026-05-23T13:30:00.000Z"},
        ]})
        items = parse_xiaoyuzhou_text(html_text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "第一集")
        self.assertEqual(items[0]["url"], "https://www.xiaoyuzhoufm.com/episode/abc123")
        self.assertEqual(items[0]["summary"], "内容")          # HTML 标签已去
        self.assertEqual(items[0]["published_at"], "2026-05-23")  # ISO → 日期

    def test_no_next_data_returns_empty(self):
        self.assertEqual(parse_xiaoyuzhou_text("<html>nope</html>"), [])


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

    def test_localize_leaves_relative_src(self):
        html_in = '<img src="/local.png">'
        self.assertEqual(content.localize_images(html_in), html_in)

    def test_md_to_html_blocks(self):
        md = ("Title: T\n\nMarkdown Content:\n"
              "# H1\n\npara **bold** and [lk](https://x.com)\n\n- a\n- b\n\n"
              "![alt](https://i/p.png)\n\n> quote")
        out = content.md_to_html(md)
        self.assertNotIn("Markdown Content:", out)              # 头部元信息已剥
        self.assertIn("<h1>H1</h1>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn('<a href="https://x.com">lk</a>', out)
        self.assertIn("<li>a</li>", out)
        self.assertIn('<img src="https://i/p.png"', out)
        self.assertIn("<blockquote>quote</blockquote>", out)

    def test_md_to_html_escapes_html(self):
        self.assertIn("&lt;script&gt;", content.md_to_html("a <script> b"))


class TestRetention(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.source = {"id": "s", "source_label": "S", "category": "Newsletter"}

    def tearDown(self):
        self.conn.close()

    def test_hash_exists(self):
        insert_items([{"url": "https://e.com/x", "title": "x"}], self.source, self.conn)
        self.assertTrue(hash_exists(url_hash("https://e.com/x"), self.conn))
        self.assertFalse(hash_exists(url_hash("https://e.com/y"), self.conn))

    def test_purge_old_keeps_recent(self):
        insert_items([{"url": "https://e.com/new", "title": "new"}], self.source, self.conn)
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        self.conn.execute(
            "INSERT INTO items (hash,source_id,source_label,category,title,url,fetched_at) VALUES (?,?,?,?,?,?,?)",
            ("oldhash", "s", "S", "Newsletter", "old", "https://e.com/old", old),
        )
        self.conn.commit()
        self.assertEqual(len(all_items(self.conn)), 2)
        self.assertEqual(purge_old(30, self.conn), 1)
        rows = all_items(self.conn)
        self.assertEqual([r["title"] for r in rows], ["new"])


class TestRender(unittest.TestCase):
    def test_card_detail_links_to_page(self):
        card = render._card({"hash": "h1", "title": "T", "source_id": "s", "category": "Newsletter"}, "detail")
        self.assertIn('href="/item/h1.html"', card)
        self.assertNotIn("target=", card)

    def test_card_link_goes_external(self):
        card = render._card({"hash": "h1", "title": "T", "url": "https://e.com/x", "category": "播客"}, "link")
        self.assertIn('href="https://e.com/x"', card)
        self.assertIn('target="_blank"', card)
        self.assertNotIn("/item/", card)

    def test_tabs_no_rewrite(self):
        panel = render._tabs({"content_html": "<p>x</p>"})
        self.assertNotIn("乔木风格重写", panel)
        self.assertIn("原文", panel)
        self.assertIn("中文翻译", panel)

    def test_youtube_embed(self):
        for u in ("https://www.youtube.com/watch?v=rzVhPTSNWnE",
                  "https://youtu.be/rzVhPTSNWnE",
                  "https://www.youtube.com/shorts/rzVhPTSNWnE"):
            e = render._youtube_embed(u)
            self.assertIn('data-id="rzVhPTSNWnE"', e)            # 门面携带 video id
            self.assertIn("i.ytimg.com/vi/rzVhPTSNWnE", e)       # 缩略图封面

    def test_youtube_embed_empty_for_non_youtube(self):
        self.assertEqual(render._youtube_embed("https://example.com/x"), "")


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.source = {"id": "s1", "source_label": "Src", "category": "Newsletter"}

    def tearDown(self):
        self.conn.close()

    def test_same_url_dedup(self):
        rows = [{"url": "https://example.com/a?utm_source=x", "title": "A"}]
        self.assertEqual(insert_items(rows, self.source, self.conn), 1)
        # 同一篇换了 utm 参数，应判为重复
        rows2 = [{"url": "https://example.com/a", "title": "A again"}]
        self.assertEqual(insert_items(rows2, self.source, self.conn), 0)
        self.assertEqual(len(all_items(self.conn)), 1)

    def test_distinct_urls(self):
        rows = [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
        ]
        self.assertEqual(insert_items(rows, self.source, self.conn), 2)
        self.assertEqual(len(all_items(self.conn)), 2)


if __name__ == "__main__":
    unittest.main()
