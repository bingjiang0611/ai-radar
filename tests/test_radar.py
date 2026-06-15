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
from fetch import normalize_url, resolve_url, is_paywalled  # noqa: E402
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

    def test_query_param_order_same_hash(self):
        # 参数顺序不同应算同一 URL(排序后归一)——旧版漏判会产生重复行
        self.assertEqual(
            url_hash("https://e.com/a?b=2&a=1"),
            url_hash("https://e.com/a?a=1&b=2"),
        )

    def test_hard_paywall_detected_metered_kept(self):
        # 硬付费墙(正文拿不到)→ 跳过;计量墙但直连能抓全文的(wired/MIT TR)保留
        self.assertTrue(is_paywalled("https://www.wsj.com/tech/ai/x"))
        self.assertTrue(is_paywalled("https://www.bloomberg.com/news/x"))
        self.assertTrue(is_paywalled("https://ft.com/content/x"))
        self.assertFalse(is_paywalled("https://www.wired.com/story/x"))
        self.assertFalse(is_paywalled("https://techcrunch.com/2026/x"))

    def test_keeps_legit_ref_prefix_param(self):
        # reference_id 是合法参数,不能因前缀 "ref" 被删(旧版 bug);reflink 是真追踪,要删
        self.assertIn("reference_id=9", normalize_url("https://e.com/a?reference_id=9&reflink=spam"))
        self.assertNotIn("reflink", normalize_url("https://e.com/a?reference_id=9&reflink=spam"))


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


class TestSourceFailure(unittest.TestCase):
    def test_parse_rss_raises_on_fetch_failure(self):
        # fetch 返 None(网络/超时/HTTP≥400)→ parse_rss 抛异常,让 run.py 报 ✗,区别于"抓到内容但 0 条"
        import parsers
        with mock.patch.object(parsers, "fetch", return_value=None):
            with self.assertRaises(RuntimeError):
                parsers.parse_rss({"url": "https://down.example/feed", "limit": 10})

    def test_parse_rss_empty_feed_returns_empty_not_raise(self):
        # 抓到合法但空的 feed(如 arXiv 周末)→ 返 [] 不抛,显示"抓到 0 条"
        import parsers
        empty = '<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>'
        with mock.patch.object(parsers, "fetch", return_value=empty):
            self.assertEqual(parsers.parse_rss({"url": "https://e.com/feed"}), [])


class TestTweetNoise(unittest.TestCase):
    def test_tweet_text_keeps_links(self):
        import fetch_x
        # 作者分享的链接不丢:无展开地址 → 保留 t.co
        self.assertIn("t.co/nB032", fetch_x._tweet_text({"text": "下载地址：https://t.co/nB032Ad9KF"}))
        # 有 urls 展开 → 替换成真实地址(按序);媒体/引用即便有也不删链接
        out = fetch_x._tweet_text({"text": "Github：https://t.co/aaa https://t.co/bbb",
                                   "urls": ["https://github.com/x/y"], "media": [{"type": "photo"}],
                                   "quotedTweet": {"id": "1"}})
        self.assertIn("github.com/x/y", out)   # 第一个 t.co 展开
        self.assertIn("t.co/bbb", out)         # 没展开的保留(绝不误删)
        # API 文本是 HTML 转义的 → unescape
        self.assertIn("5 < 10", fetch_x._tweet_text({"text": "5 &lt; 10"}))

    def test_is_noise_filters_giveaway_keeps_real(self):
        import fetch_x
        # 抽奖/转发求互动噪音 → True(即便含 AI 词)
        self.assertTrue(fetch_x.is_noise("🎟️抽奖啦！抽 10 个人送《AI 提效实战指南》"))
        self.assertTrue(fetch_x.is_noise("由于 Grok 拿不到“转发”名单，只能从“评论”或“引用”里面抽，请补一个评论"))
        # 正常 AI 推 → False
        self.assertFalse(fetch_x.is_noise("Claude Fable 5 在 agentic 编码上的表现远超 GPT"))
        self.assertFalse(fetch_x.is_noise("我们对 7 个前沿模型做了 autoresearch 基准测试"))


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

    def test_extract_article_picks_body_drops_chrome(self):
        body = "A" * 220  # 够长的正文段(过 200 字正文闸门)
        html = (f"<html><body><nav>menu links here all over</nav>"
                f"<article><h2>Heading</h2><p>{body}</p>"
                f"<p>short</p><script>junk()</script></article>"
                f"<footer>{'F' * 90}</footer></body></html>")
        out = content._extract_article(html)
        self.assertIn(f"<p>{body}</p>", out)       # 长正文段保留
        self.assertIn("<h2>Heading</h2>", out)     # 小标题保留
        self.assertNotIn("short", out)             # <60 字短段丢弃
        self.assertNotIn("menu links", out)        # nav 剥掉
        self.assertNotIn("junk()", out)            # script 剥掉
        self.assertNotIn("FFF", out)               # footer 剥掉

    def test_extract_article_drops_boilerplate(self):
        real = "Real article sentence number one that is long enough to count. " * 4
        html = (f"<article><p>{real}</p>"
                f"<p>Sign up for our weekly newsletter to get the latest news delivered.</p>"
                f"<p>Jane Doe is a freelance contributor for the site and writes about tech.</p>"
                f"<p>Get an inside look at what it takes to scale and succeed at the event.</p>"
                f"</article>")
        out = content._extract_article(html)
        self.assertIn("Real article sentence", out)
        self.assertNotIn("newsletter", out)
        self.assertNotIn("freelance contributor", out)
        self.assertNotIn("Get an inside look", out)

    def test_extract_article_too_short_returns_empty(self):
        # 付费墙 stub / 纯导航:正文 <200 字 → 视为没抓到
        self.assertEqual(content._extract_article("<article><p>" + "x" * 70 + "</p></article>"), "")


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

    def test_card_tweet_avatar_name_quote(self):
        import json as _json
        import content
        content.DIST_IMG.mkdir(parents=True, exist_ok=True)
        (content.DIST_IMG / "q-img.png").write_bytes(b"x")   # 引用配图文件存在 → _lazy_imgs 保留
        (content.DIST_IMG / "q-av.jpg").write_bytes(b"x")    # 引用作者头像文件存在
        render._img_have_cache[0] = None
        item = {"hash": "tw1", "category": "推文", "source_label": "X · 关注",
                "title": "@blackanger：基于决策阶梯，给 AI 一段 prompt", "title_zh": "",
                "tweet_meta": _json.dumps({"name": "AlexZ", "handle": "blackanger", "avatar": "/img/av.jpg",
                                           "verified": True, "rt": "",
                                           "quote": {"name": "Tech with Mak", "handle": "techNmak",
                                                     "text": "A dev got so frustrated",
                                                     "text_zh": "一位开发者非常沮丧",
                                                     "image": "/img/q-img.png",
                                                     "avatar": "/img/q-av.jpg"}}, ensure_ascii=False)}
        try:
            card = render._card(item, "link")
        finally:
            (content.DIST_IMG / "q-img.png").unlink(missing_ok=True)
            (content.DIST_IMG / "q-av.jpg").unlink(missing_ok=True)
            render._img_have_cache[0] = None
        self.assertIn('src="/img/av.jpg"', card)        # 真头像
        self.assertIn("AlexZ", card)                     # 作者名
        self.assertIn("tw-vf", card)                     # 认证徽章
        self.assertIn('it-title">基于决策阶梯', card)    # 正文(it-title)已去 "@handle：" 前缀,直接从文本开头
        self.assertNotIn('it-title">@blackanger', card)  # 正文不再以 @handle 开头(data-text 搜索域仍保留原文)
        self.assertIn("Tech with Mak", card)             # 引用作者
        self.assertIn("A dev got so frustrated", card)   # 引用文本
        self.assertIn("一位开发者非常沮丧", card)         # 引用中译(text_zh)显示在英文下
        self.assertIn("tw-q-zh", card)                   # 中译用独立样式行
        self.assertIn('class="tw-q-av"', card)           # 引用作者头像(二次抓补的)
        self.assertIn('src="/img/q-img.png"', card)      # 引用配图(父推不给,二次抓补)
        self.assertIn("tw-q-media", card)                # 引用配图容器

    def test_card_search_blob_has_english_and_chinese(self):
        # 显示中文标题,但搜索域 data-text 须中英都含——否则英文关键词搜不到
        card = render._card({"hash": "h", "category": "资讯", "source_label": "S",
                             "title": "English Original Title", "title_zh": "中文标题",
                             "summary": "english summary text", "summary_zh": "中文摘要"})
        m = re.search(r'data-text="([^"]*)"', card)
        self.assertIn("english original title", m.group(1))   # 英文原标题在搜索域
        self.assertIn("中文标题", m.group(1))                  # 中译也在

    def test_lazy_imgs_adds_loading_and_drops_missing(self):
        import content
        content.DIST_IMG.mkdir(parents=True, exist_ok=True)
        (content.DIST_IMG / "lz-a.png").write_bytes(b"x")   # a 存在 → 保留+lazy
        render._img_have_cache[0] = None                    # 清渲染缓存,让其重读
        try:
            out = render._lazy_imgs('<p><img src="/img/lz-a.png"> <img src="/img/lz-gone.png"></p>')
            self.assertIn('<img loading="lazy" src="/img/lz-a.png"', out)  # 存在的:加 lazy
            self.assertNotIn("lz-gone.png", out)             # 文件缺失的:整个 <img> 丢掉(无破图)
            self.assertEqual(out.count("<img"), 1)
        finally:
            (content.DIST_IMG / "lz-a.png").unlink(missing_ok=True)
            render._img_have_cache[0] = None

    def test_has_zh_deep_and_card_anchor(self):
        self.assertTrue(render._has_zh_deep({"translation_md": "译文"}))
        self.assertTrue(render._has_zh_deep({"summary_md": "总结"}))
        self.assertTrue(render._has_zh_deep({"video_url": "https://www.bilibili.com/video/BV1x"}))  # B站译制
        self.assertFalse(render._has_zh_deep({"translation_md": "", "summary_md": "", "video_url": ""}))
        self.assertFalse(render._has_zh_deep({}))
        # anchor 拼进详情 href(精读页深链直接开对应 tab)
        card = render._card({"hash": "h9", "category": "资讯", "source_label": "S",
                             "title": "T"}, "detail", "#zh")
        self.assertIn('href="/item/h9.html#zh"', card)

    def test_tabs_no_rewrite(self):
        panel, _outline = render._tabs({"content_html": "<p>x</p>"})  # _tabs 返回 (html, 大纲)
        self.assertNotIn("乔木风格重写", panel)
        self.assertIn("原文", panel)
        self.assertIn("中文翻译", panel)

    def test_youtube_embed(self):
        for u in ("https://www.youtube.com/watch?v=rzVhPTSNWnE",
                  "https://youtu.be/rzVhPTSNWnE",
                  "https://www.youtube.com/shorts/rzVhPTSNWnE"):
            e = render._youtube_embed(u)
            self.assertIn('data-yt="rzVhPTSNWnE"', e)            # 门面携带 video id
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
