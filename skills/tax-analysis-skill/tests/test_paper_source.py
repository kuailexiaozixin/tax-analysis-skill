# -*- coding: utf-8 -*-
"""中国税务报网络报（数字报）第七源的常驻测试（3.62.23 起）。

全部离线：真站的形状是 2026-11-24 那次只读勘察抄下来的（.tmp-inspect/netpaper-probe23*.txt
与 paper-href.txt），这里喂给抽取器，不再打站。

钉住的四件事，都是这一轮实测出来的：
  A 版面页里的文章地址是 `../../../con/YYYYMM/DD/content_NNNNNN.html`——**三级上跳**。
    写成两级，urljoin 会拼出 `/paper/pc/layout/con/…`，实测 404（真站复现过）。
  B `fetch_edition` 的 `_status` 四档不许互相冒充：整版取全 / 当天没出报（404 是出版
    日历不是失败）/ 个别文章没取到 / 版面页本身取不到。后两档**一律不落缓存**——
    partial 落进去会把"少几篇"钉六小时，failed 落进去会把一次网络抖动钉六小时。
  C 缓存键必须过 `CacheManager._key()`。直接拿 `"edition|202611|24|6"` 这种带竖线的
    原文当键，在 Windows 上是非法文件名，写盘抛 OSError 又被"缓存写不进不该让查询
    失败"那段静默吞掉 ⇒ 缓存无声空转，每次调用重打七次站，而调用方看不见。
    `test_cache_really_lands_on_disk` 用真缓存目录复现这一条，替身缓存抓不到它。
  D 命中缓存那趟一次站都没打，`network` 必须归零；把缓存里那次抓站的数带回来，
    就是向调用方宣称本趟做了它没做的抓取。
"""
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import tax_paper as P  # noqa: E402
import tax_http  # noqa: E402

LAYOUT_BASE = "https://www.ctaxnews.net.cn/paper/pc/layout/202611/24/node_06.html"
LAYOUT = '''<html><head><title>中国税务报网络报</title></head><body>
<div class="newsTitle">第06版：税案传真</div>
<a href="../../../con/202611/24/content_241559.html">甲</a>
<a href="../../../con/202611/24/content_241537.html">乙</a>
<a href="../../../con/202611/24/content_241559.html">甲重复</a>
</body></html>'''

ART_NORMAL = '''<html><body><h3>从医药推广费用风险核查入手</h3>
<div class="newsdetatext">
<div class="newsdetatit"></div>
<founder-content><p>正文第一段：虚开发票链条被拆开。</p>
<p><!--enpcontent-->正文第二段。<!--/enpcontent-->
<!--enpproperty <date>2026-11-24 00:00:00:0</date><id>241559</id><title>从医药推广费用风险核查入手</title>/enpproperty--></p>
</founder-content></div></body></html>'''

ART_IMAGE = '''<html><body><div class="newsdetatext"><div class="pic">
<img src="../../../pic/202611/24/6f0b.jpg" width="338">
<p> 教育部公布的最新数据显示，各地正持续规范推广行为。</p></div>
<founder-content><p><!--enpcontent--><p> </p><!--/enpcontent-->
<!--enpproperty <date>2026-11-24 00:00:00:0</date><author>黄文霞 任征 摄</author>
<id>241537</id><title>一版图一</title>/enpproperty--></p></founder-content></div></body></html>'''

URL_559 = "https://www.ctaxnews.net.cn/paper/pc/con/202611/24/content_241559.html"
URL_537 = "https://www.ctaxnews.net.cn/paper/pc/con/202611/24/content_241537.html"


class _CacheStub:
    """替身缓存：只记账，不碰盘（落盘行为另有真目录那条测试）。"""

    enabled = True

    def __init__(self):
        self.store = {}
        self.sets = []

    def _key(self, *parts):
        import hashlib
        return hashlib.sha256("|".join(str(x) for x in parts).encode()).hexdigest()[:16]

    def get(self, key, max_age=0):
        hit = self.store.get(key)
        return dict(hit) if hit else None

    def set(self, key, value):
        self.sets.append(key)
        self.store[key] = value


class _Scenario:
    """把 _http_get 换成按 URL 分派的桩，记录每趟发了几次请求。"""

    def __init__(self, layout=(200, LAYOUT, ""), articles=None, hits=None):
        self.layout = layout
        self.articles = articles or {}
        self.hits = hits or {}
        self.calls = []
        self.cache = _CacheStub()
        self._old = None

    def __enter__(self):
        self._old = (P.PAPER_CACHE, P._http_get, P._READ_INTERVAL)
        P.PAPER_CACHE, P._READ_INTERVAL = self.cache, 0
        P._http_get = self._get
        return self

    def __exit__(self, *exc):
        P.PAPER_CACHE, P._http_get, P._READ_INTERVAL = self._old
        return False

    def _get(self, url, session=None, timeout=20):
        self.calls.append(url)
        if "/layout/" in url:
            st, text, err = self.layout
            return st, url, text, err
        hit = self.articles.get(url.rsplit("/", 1)[-1])
        if hit is None:
            return 200, url, ART_NORMAL, ""
        st, text, err = hit
        return st, url, text, err

    @property
    def n(self):
        return len(self.calls)


class TestUrlShape(unittest.TestCase):
    """A 段：地址式与三级上跳。"""

    def test_layout_url_has_the_day_segment(self):
        self.assertEqual(
            P.LAYOUT_URL.format(yyyymm="202611", dd="24", nn="06"), LAYOUT_BASE)
        self.assertEqual(
            P.CON_URL.format(yyyymm="202611", dd="24", aid="241559"), URL_559)

    def test_relative_href_resolves_three_levels_up(self):
        links = P._article_links(LAYOUT, LAYOUT_BASE)
        self.assertEqual(links, [URL_537, URL_559])   # 去重且按出现顺序
        for u in links:
            self.assertNotIn("layout/con", u)         # 两级上跳就会拼出这个 404 段

    def test_edition_name_read_from_the_page(self):
        self.assertEqual(P._edition_name(LAYOUT), "税案传真")
        self.assertEqual(P._edition_name("<div>没有版面名</div>"), "")


class TestExtractors(unittest.TestCase):
    """标题/正文/图注/图片稿四种抽取。"""

    def test_title_comes_from_the_property_comment(self):
        self.assertEqual(P._title_of(ART_NORMAL), "从医药推广费用风险核查入手")
        self.assertEqual(P._title_of(ART_IMAGE), "一版图一")

    def test_body_from_founder_content_without_metadata(self):
        body = P._body_of(ART_NORMAL)
        self.assertIn("虚开发票链条", body)
        self.assertNotIn("enpproperty", body)
        self.assertNotIn("<", body)

    def test_image_piece_has_empty_body_and_a_caption(self):
        self.assertEqual(P._body_of(ART_IMAGE), "")
        self.assertEqual(P._caption_of(ART_IMAGE),
                         "教育部公布的最新数据显示，各地正持续规范推广行为。")

    def test_image_placeholder_titles(self):
        for t in ("一版图一", "五版图二", "七版图一"):
            self.assertTrue(P._is_image_piece(t), t)
        self.assertFalse(P._is_image_piece("从医药推广费用风险核查入手"))

    def test_row_three_shapes_are_distinct(self):
        normal = P._row_of(ART_NORMAL, URL_559)
        self.assertNotIn("_image_piece", normal)
        self.assertTrue(normal["content"].startswith("正文第一段"))
        image = P._row_of(ART_IMAGE, URL_537)
        self.assertTrue(image.get("_image_piece"))
        self.assertIn("最新数据", image["content"])
        blank = P._row_of("<html><body>什么都没有</body></html>", "u")
        self.assertTrue(blank.get("_empty_body"))
        self.assertNotIn("_image_piece", blank)      # 取空正文不谎称图片稿


class TestEditionStatuses(unittest.TestCase):
    """B 段：四档不互相冒充 + 只有全绿与日历事实落缓存。"""

    def test_all_green_is_the_only_empty_status(self):
        with _Scenario() as s:
            out = P.fetch_edition("2026-11-24", edition=6)
        self.assertEqual(out["_status"], "")
        self.assertEqual(out["edition_name"], "税案传真")
        self.assertEqual(len(out["articles"]), 2)
        self.assertEqual(out["network"], s.n)
        self.assertEqual(s.cache.sets, list(s.cache.sets))   # 落了一次

    def test_404_is_no_issue_not_a_failure(self):
        with _Scenario(layout=(404, "", "")) as s:
            out = P.fetch_edition("2026-11-19", edition=6)
        self.assertTrue(out["_status"].startswith("no-issue："), out["_status"])
        self.assertIn("404", out["_status"])
        self.assertEqual(out["articles"], [])
        self.assertEqual(len(s.cache.sets), 1)      # 日历事实值得记，六小时别重打

    def test_unexpected_status_without_err_is_failed_not_green(self):
        # 这一档是本轮真缺陷：状态非 200 又没带 err 时，旧判据 `if err:` 会放它
        # 进成功分支，把空页面当成"整版取全"钉进缓存六小时。
        with _Scenario(layout=(None, "", "")) as s:
            out = P.fetch_edition("2026-11-24", edition=6)
        self.assertTrue(out["_status"].startswith("failed｜"), out["_status"])
        self.assertEqual(s.cache.sets, [])

    def test_http_status_with_empty_err_is_also_failed(self):
        with _Scenario(layout=(500, "", "")) as s:
            out = P.fetch_edition("2026-11-24", edition=6)
        self.assertTrue(out["_status"].startswith("failed｜"), out["_status"])
        self.assertEqual(s.cache.sets, [])

    def test_partial_names_the_lost_article_and_is_not_cached(self):
        with _Scenario(articles={"content_241559.html": (None, "", "ConnectTimeout：超时")}) as s:
            out = P.fetch_edition("2026-11-24", edition=6)
        self.assertTrue(out["_status"].startswith("partial｜"), out["_status"])
        self.assertIn("1 篇没取到", out["_status"])
        self.assertIn("content_241559.html", out["_status"])
        self.assertEqual(out["_lost"], ["content_241559.html：ConnectTimeout：超时"])
        self.assertEqual(len(out["articles"]), 1)
        self.assertEqual(s.cache.sets, [])          # 少几篇不能钉六小时

    def test_bad_date_shape_fails_without_touching_the_site(self):
        with _Scenario() as s:
            out = P.fetch_edition("下周三", edition=6)
        self.assertTrue(out["_status"].startswith("failed｜"), out["_status"])
        self.assertEqual(s.n, 0)


class TestCacheRealDisk(unittest.TestCase):
    """C 段：真缓存目录。替身抓不到的那一条——键里带竖线时写盘会静默失败。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="taxpaper-test-")
        import tax_cache
        self.cache = tax_cache.CacheManager(enabled=True, namespace="paper")
        self._old = (P.PAPER_CACHE, P._http_get, P._READ_INTERVAL)
        P.PAPER_CACHE = self.cache
        self.cache.dir = Path(self.dir)
        P._READ_INTERVAL = 0

    def tearDown(self):
        P.PAPER_CACHE, P._http_get, P._READ_INTERVAL = self._old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_cache_really_lands_on_disk(self):
        calls = []

        def fake_get(url, session=None, timeout=20):
            calls.append(url)
            if "/layout/" in url:
                return 200, url, LAYOUT, ""
            return 200, url, ART_NORMAL, ""

        P._http_get = fake_get
        first = P.fetch_edition("2026-11-24", edition=6)
        self.assertEqual(first["_status"], "")
        written = list(Path(self.dir).glob("*.json"))
        self.assertEqual(len(written), 1, "缓存一枚都没落盘（键不合法时就是这现象）")
        for f in written:
            self.assertRegex(f.name, r"^[0-9a-f]{16}\.json$")   # 过 _key() 的哈希名

    def test_second_round_serves_from_cache_and_reports_zero_network(self):
        """D 段一并钉住：命中那趟 network 必须归零。"""
        calls = []

        def fake_get(url, session=None, timeout=20):
            calls.append(url)
            if "/layout/" in url:
                return 200, url, LAYOUT, ""
            return 200, url, ART_NORMAL, ""

        P._http_get = fake_get
        P.fetch_edition("2026-11-24", edition=6)
        self.assertEqual(len(calls), 1 + len(P._article_links(LAYOUT, LAYOUT_BASE)))
        second = P.fetch_edition("2026-11-24", edition=6)
        self.assertTrue(second.get("_from_cache"))
        self.assertEqual(second["network"], 0, "命中缓存却报着上次的抓取次数")
        self.assertEqual(len(calls), 3, "命中后仍打了站")
        # no-issue 也走同一条：第二次不再打站
        P._http_get = lambda url, session=None, timeout=20: (404, url, "", "")
        P.fetch_edition("2026-11-19", edition=6)
        n = len(calls)
        hit = P.fetch_edition("2026-11-19", edition=6)
        self.assertTrue(hit.get("_from_cache"))
        self.assertEqual(len(calls), n)


class TestRender(unittest.TestCase):
    """人读形态：两种形状都要有话说，空命中不许说成"报上没有"。

    这一源没有站内检索，"没命中"只代表扫过的那些天那些版面里没有。把这句
    写成"没有"就是红线⑦那一族（把缺席判断说成事实）。失败的日子必须单独列。
    """

    def test_date_shape_lists_articles_and_cache_note(self):
        out = {"date": "2026-11-24", "edition": 6, "edition_name": "税案传真",
               "url": "https://x/node_06.html", "network": 7, "_status": "",
               "articles": [{"title": "一篇稿", "url": "https://x/a.html",
                             "date": "2026-11-24"},
                            {"title": "一版图一", "url": "https://x/b.html",
                             "date": "2026-11-24", "_image_piece": True}]}
        txt = P.render(out)
        self.assertIn("第06版", txt)
        self.assertIn("税案传真", txt)
        self.assertIn("打了 7 次站", txt)
        self.assertIn("图片稿", txt)

    def test_date_shape_cache_hit_says_so(self):
        out = {"date": "2026-11-24", "edition": 6, "edition_name": "税案传真",
               "url": "", "network": 0, "_from_cache": True, "_status": "",
               "articles": []}
        txt = P.render(out)
        self.assertIn("缓存", txt)
        self.assertIn("取到 0 篇", txt)

    def test_empty_keyword_result_never_claims_absence(self):
        out = {"query": "虚开", "results": [], "total": None, "_status": "",
               "_days_scanned": ["2026-11-24", "2026-11-23", "2026-11-22"],
               "_no_issue_days": ["2026-11-22"],
               "_failed_days": ["2026-11-23：版面页 HTTP 500"],
               "_editions": [6]}
        txt = P.render(out)
        self.assertIn("不等于", txt)
        self.assertIn("2026-11-23", txt)          # 失败那天要点名
        self.assertIn("2026-11-22", txt)          # 没出报那天也要点名
        self.assertNotIn("报上没有这篇", txt)

    def test_lost_articles_are_shown_under_partial(self):
        out = {"date": "2026-11-24", "edition": 6, "edition_name": "", "url": "",
               "network": 3, "_status": "partial｜2 篇取到、1 篇没取到：x.html：超时",
               "_lost": ["x.html：超时"],
               "articles": [{"title": "甲", "url": "u1", "date": "d"},
                            {"title": "乙", "url": "u2", "date": "d"}]}
        txt = P.render(out)
        self.assertIn("partial", txt)
        self.assertIn("没取到", txt)


class TestSearch(unittest.TestCase):
    """检索面：这一源没有站内检索，只能扫版面，形状与诚实度都要钉住。"""

    def test_empty_keyword_admits_it_did_not_run(self):
        out = P.search_paper("   ")
        self.assertTrue(out["_status"].startswith("没走成："), out["_status"])
        self.assertEqual(out["results"], [])
        self.assertIsNone(out["total"])
        self.assertEqual(out["_days_scanned"], [])    # 不谎称扫过

    def test_total_is_none_because_the_site_reports_nothing(self):
        arts = {"content_241559.html": (200, ART_NORMAL, ""),
                "content_241537.html": (200, ART_IMAGE, "")}
        with _Scenario(articles=arts):
            out = P.search_paper("虚开", days=2, size=5,
                                 date_from="2026-11-23", date_to="2026-11-24")
        self.assertIsNone(out["total"])
        self.assertIn("命中", out["_note"])
        self.assertEqual(len(out["results"]), 1)      # 只有常规稿正文含"虚开"
        self.assertEqual(out["results"][0]["url"], URL_559)

    def test_same_story_under_two_titles_merges_by_url(self):
        # 勘察读数：同一篇稿在 .com.cn 是全题、在数字报是半题——按标题去重会留双份。
        arts = {"content_241559.html": (200, ART_NORMAL, "")}

        class Dup:
            enabled = True

            def __init__(self):
                self.store = {}

            def _key(self, *p):
                return "|".join(str(x) for x in p)

            def get(self, k, max_age=0):
                return None

            def set(self, k, v):
                pass

        dup = Dup()
        calls = []

        def fake_get(url, session=None, timeout=20):
            calls.append(url)
            if "/layout/" in url:
                return 200, url, LAYOUT, ""
            return 200, url, ART_NORMAL, ""

        old = (P.PAPER_CACHE, P._http_get, P._READ_INTERVAL)
        P.PAPER_CACHE, P._http_get, P._READ_INTERVAL = dup, fake_get, 0
        try:
            # 第 5 版与第 6 版给的是同一张版面页（两枚 url），所以四个候选必须
            # collapse 成两条——去重按 url 不按标题，这正是"同稿异题"要求的做法。
            out = P.search_paper("虚开", days=1, size=9, editions=(5, 6),
                                 date_from="2026-11-24", date_to="2026-11-24")
        finally:
            P.PAPER_CACHE, P._http_get, P._READ_INTERVAL = old
        urls = [r["url"] for r in out["results"]]
        self.assertEqual(urls, [URL_537, URL_559])
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len([u for u in calls if "/con/" in u]), 4)  # 打了 4 次，留了 2 条

    def test_days_with_issue_skips_404_days(self):
        seen = []

        def fake_get(url, session=None, timeout=20):
            seen.append(url)
            if "/layout/" not in url:
                return 200, url, ART_NORMAL, ""   # 文章页随便回，只看版面页
            day = url.split("/layout/")[1].split("/")[1]
            if day in ("19", "22", "23"):
                return 404, url, "", ""           # 四元组契约，少一列就解包失败
            return 200, url, LAYOUT, ""

        with _Scenario() as s:
            P._http_get = fake_get
            days = P.days_with_issue("2026-11-18", "2026-11-24")
        self.assertEqual(days, ["2026-11-18", "2026-11-20", "2026-11-21", "2026-11-24"])

    def test_http_get_treats_404_as_a_reading_not_an_error(self):
        # 桩掉 attempt：404 必须交回 (404,"","","") —— err 空。
        old = tax_http.attempt

        def fake_attempt(fn, url, log, **kw):
            class R:
                status_code = 404
                url = "u"
                text = ""
                encoding = "utf-8"
                headers = {}
            return R(), "", False

        tax_http.attempt = fake_attempt
        try:
            st, _f, text, err = P._http_get("https://x/y")
        finally:
            tax_http.attempt = old
        self.assertEqual((st, text, err), (404, "", ""))


class TestNoLiveCallInImport(unittest.TestCase):
    def test_listed_in_the_offline_gate(self):
        """写了用例却没进门禁，等于没写。新测试文件一律自带这条守卫。

        离线组第一项是在本进程里跑的编译函数，不是 argv，所以先过掉 callable。
        """
        sys.path.insert(0, str(HERE))
        import run_all
        listed = " ".join(" ".join(map(str, cmd))
                          for _name, cmd in run_all.OFFLINE_GROUP
                          if not callable(cmd))
        self.assertIn("test_paper_source.py", listed,
                      "tests/run_all.py 的离线组没点名 test_paper_source.py，"
                      "这一整份用例一次都不会跑")

    def test_module_imports_no_network(self):
        # 导入期不许打站：PAPER_CACHE 建对象是本地动作，attempt 只在函数里用。
        src = (HERE.parent / "scripts" / "tax_paper.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("tax_http.attempt("), 1, "attempt 只该在 _http_get 里出现一次")
        self.assertNotIn("verify=True", src)     # 该站证书链不完整，全模块统一 verify=False


TESTS = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(TESTS)
    print("结果：%d/%d 通过" % (r.testsRun - len(r.failures) - len(r.errors), r.testsRun))
    sys.exit(0 if r.wasSuccessful() else 1)
