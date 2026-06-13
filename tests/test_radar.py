"""ai-radar 单测：URL 归一化 / 去重 / RSS·Atom 解析 / JSON 解析。零网络。"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fetch import normalize_url                       # noqa: E402
from parsers import parse_rss_text, parse_json_text, parse_xiaoyuzhou_text  # noqa: E402
from store import init_db, insert_items, all_items, url_hash  # noqa: E402

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


class TestRss(unittest.TestCase):
    def test_rss_two_items_and_clean_summary(self):
        items = parse_rss_text(RSS_FIXTURE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "First Post")
        self.assertEqual(items[0]["url"], "https://example.com/a?utm_source=x")
        self.assertEqual(items[0]["summary"], "Hello world")  # HTML 标签已去除

    def test_atom_link_href(self):
        items = parse_rss_text(ATOM_FIXTURE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Vid")
        self.assertEqual(items[0]["url"], "https://youtu.be/xyz")

    def test_limit(self):
        self.assertEqual(len(parse_rss_text(RSS_FIXTURE, limit=1)), 1)

    def test_malformed_xml_returns_empty(self):
        self.assertEqual(parse_rss_text("<not xml"), [])


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
