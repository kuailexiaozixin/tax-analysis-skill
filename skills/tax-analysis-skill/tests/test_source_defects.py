#!/usr/bin/env python3
"""⑩「源缺陷」六条的离线用例。不联网、不开浏览器。

这六条是人肉规则——程序解决不了、用的时候要留神：

  1. NPC 有限流，检索串行跑；评测时不要并行别的 NPC 检索
  2. 搜狗被拦时地方口径这一层、税屋这一层都是空的，
     要在答案里明说、不要拿别的源顶替
  3. fgk 翻得越深相关性越差，深页条目必须回 L1 核对
  4. 元宝公众号检索主路是 POST 取数接口，页型分结果、限流（429_outer 那枚文案）、
     熔断短接与验证码墙，三档阶梯共用一把串行闸和一份盘上频次账
  5. `_reliability: medium` 说的是这条的召回方式，要落成一句具体提醒
  6. `_reliability: low` 同样只提醒核对，不折算成分数、不从挑选里剔除

"靠人记住"等于没有约束：第 5、6 条若只在输出里印一行、定级层不读它，标了 low
的条目照样能被挑成主依据、还打出"可作依据引用（法律）"。六条
都落进代码，这里逐条钉住，并附带自检（确认规则不是永远绿的）。
"""

import ast
import contextlib
import io
import builtins
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# 本文件的缓存必须落在临时目录，不能落在用户真实 ~/.cache/tax-analysis-skill。
# 2026-11-24 逐文件实测（.tmp-inspect/cache_write_per_file.py，31 枚离线测试）：
# 只有本文件会往用户盘漏条目——每跑一遍新增 2 枚详情档（id 形如 SHARED-OK-<12hex>
# 与 SHARED-NOCACHE-<12hex>），因为 _detail_call 的 bbbs_id 带 uuid 每次不同：
# id 必须每次不同（否则上一轮缓存冒充本轮结果），于是污染只增不减，盘上已积 167 枚。
# 改道走 TAX_CACHE_DIR（tax_cache.CacheManager 建实例时读它）而不是逐个换 .dir：
# 本文件有二十多处缓存触点，逐处换 .dir 迟早漏一枚；这行放在导入 scripts 之前，
# 因为 tax_detail 的模块级 _detail_cache 在导入那一刻就按当时的环境变量定型。
# 直接跑本文件（python tests/test_source_defects.py）与 pytest 两条路都经过这里；
# tests/run_all.py 另外在子进程环境里兜了一层，挡的是"以后新测试忘了设"。
os.environ.setdefault("TAX_CACHE_DIR", tempfile.mkdtemp(prefix="tax-test-cache-"))

import tax_ctax as CT      # noqa: E402
import tax_cache             # noqa: E402
import tax_detail as DT      # noqa: E402
import tax_answer as ANS     # noqa: E402
import tax_evidence as E     # noqa: E402
import tax_fgk as FGK        # noqa: E402
import tax_formatter as FMT  # noqa: E402
import tax_http              # noqa: E402
import tax_search as T       # noqa: E402
import tax_shui5 as SH       # noqa: E402
import tax_sogou as SOG      # noqa: E402
import tax_wechat as W       # noqa: E402
import tax_aggregator as AGG  # noqa: E402
import tax_related as REL     # noqa: E402
import tax_web_search as WS   # noqa: E402
from tax_web_search import FGK_MARKER  # noqa: E402

HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _fgk_hit(n: int, page_tag: str) -> list:
    return [{
        "title": f"财税文件{page_tag}-{i}",
        "url": f"https://fgk.chinatax.gov.cn/{FGK_MARKER}/{page_tag}{i}.htm",
        "date": "2025-01-0%d" % (i + 1),
        "document_number": f"财税〔2025〕{page_tag}{i}号",
        "publisher": "财政部",
        "snippet": "……",
    } for i in range(n)]


# ── ③ fgk 深页条目必须带页码与可靠性标记 ───────────────────────────────────
class TestFgkDeepPageMarker(unittest.TestCase):
    """翻得越深越松，深页条目只可用于定位。这件事不落进代码就靠人记页码。"""

    def _scan(self, pages):
        """pages: {页码: 该页法规库条目数}"""
        def fake_search(keyword, page=1, size=10, filters=None, **opts):
            n = pages.get(page, 0)
            return {"total": 99, "results": _fgk_hit(n, "p%d" % page)}

        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search):
            return FGK._scan_list("测试词", size=99, max_pages=max(pages),
                                  adaptive=False)

    def test_shallow_page_items_carry_page_and_no_marker(self):
        out = self._scan({1: 2})
        self.assertEqual(2, out["total"])
        for it in out["results"]:
            self.assertEqual(1, it["page"], "每条都要能看出取自第几页")
            self.assertNotIn("_reliability", it, "第 1 页是浅页，不该被降级")

    def test_deep_page_items_are_marked_locate_only(self):
        out = self._scan({1: 1, 2: 1})
        deep = [it for it in out["results"] if it["page"] == 2]
        self.assertEqual(1, len(deep), "第 2 页那条应该被收进结果")
        self.assertEqual("medium", deep[0]["_reliability"])
        self.assertIn("第 2 页", deep[0]["_reliability_note"])
        self.assertIn("核对上位法", deep[0]["_reliability_note"])

    def test_marker_threshold_is_configurable(self):
        """阈值是常量，不是散在代码里的魔法数。"""
        old = FGK.FGK_SHALLOW_PAGES
        try:
            FGK.FGK_SHALLOW_PAGES = 2
            out = self._scan({1: 1, 2: 1})
            self.assertTrue(all("_reliability" not in it for it in out["results"]),
                            "阈值放到 2 之后，前两页都不该被降级")
        finally:
            FGK.FGK_SHALLOW_PAGES = old


# ── ③b 中途空页不能当列表尽头（红线⑦同族，判据是页码不是行数）───────────────
class TestFgkMidPageDropout(unittest.TestCase):
    """`_scan_list` 旧写法 `if not page_items: break` 把中途空页当尽头。

    判据前提实测（2026-11-24，`.tmp-inspect\\fgk_page_honesty.py`，四词）：空页页码
    恒等于 ceil(total/10)+1 —— total=62 逐页 [10,10,10,10,10,10,2] 空页第 8 页；
    total=16 [10,6] 空页第 3 页；total=47 [10,10,10,10,7] 空页第 6 页；total=2 首屏
    给满不发第二页。所以空页落在 ceil(total/10) 之内只可能是这一页没取到。
    """

    def _scan(self, total, pages, errors=None, **kw):
        """pages: {页码: 该页条目数}；errors: {页码: 该页 _error}"""
        calls = []
        errors = errors or {}

        def fake_search(keyword, page=1, size=10, filters=None, **opts):
            calls.append(page)
            n = pages.get(page, 0)
            out = {"total": total, "results": _fgk_hit(n, "p%d" % page)}
            if page in errors:
                out["_error"] = errors[page]
                out["results"] = []
            return out

        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search):
            r = FGK._scan_list("测试词", size=kw.pop("size", 99),
                               max_pages=kw.pop("max_pages",
                                                max(pages) + 3 if pages else 4),
                               adaptive=kw.pop("adaptive", False), **kw)
        return r, calls

    def test_mid_crawl_empty_page_is_flagged_as_dropout(self):
        """站点报 62 条、第 2 页就给空：必须说"断供"，不能交回 10 条装完整。"""
        r, calls = self._scan(62, {1: 10})
        self.assertEqual([1, 2], calls, "第 2 页空应当即停，不再往后翻")
        self.assertEqual(10, r["total"])
        self.assertEqual(62, r["total_hits"], "站点总数照旧透出，两个数要能并排看")
        self.assertIn("断供", r["_error"])
        self.assertIn("不是这一词的完整清单", r["_error"])
        self.assertEqual(r["_error"], r["_empty_reason"],
                         "tax_answer.py:603 认的是 _empty_reason，两者必须同源")

    def test_honest_end_of_list_is_not_flagged_as_dropout(self):
        """控制组：total=12，第 1 页 10 条、第 2 页 2 条、第 3 页才空 —— 自然尽头。"""
        r, calls = self._scan(12, {1: 10, 2: 2})
        self.assertEqual([1, 2, 3], calls)
        self.assertEqual(12, r["total"])
        self.assertNotIn("_error", r, "吐满之后的空页不是断供，不许报错")
        self.assertNotIn("断供", r.get("_empty_reason", ""))

    def test_request_failure_on_later_page_is_not_blamed_on_the_source(self):
        """第 2 页是请求失败（交回空 results）：那档归 first_error，不判断供。

        少了判据里 `not found.get("_error")` 那一枚条件，我们的网络问题就会被写成
        "站点提前给了空页"，把责任记到清单源头上去。
        """
        r, calls = self._scan(62, {1: 10}, errors={2: "HTTP 500"})
        self.assertEqual([1, 2], calls)
        self.assertIn("HTTP 500", r["_error"])
        self.assertNotIn("断供", r["_error"])
        self.assertTrue(r.get("_fetch_failed"), "取数失败这一枚标记不能被断供分支吃掉")

    def test_genuine_zero_hit_is_still_zero_hit(self):
        """控制组：total=0 首屏即空 —— 仍是"翻完未筛出"，不是断供也不是取数失败。"""
        r, calls = self._scan(0, {})
        self.assertEqual([1], calls)
        self.assertEqual(0, r["total"])
        self.assertNotIn("断供", r.get("_error", ""))
        self.assertNotIn("断供", r.get("_empty_reason", ""))


# ── ② 缺了哪一层由程序说，不靠人推断 ───────────────────────────────────────
class TestAggregatorGaps(unittest.TestCase):
    """源级失败要翻译成"缺了哪一层、能不能拿别的源顶"。"""

    def _agg(self, *, sogou=None, shui5=None, wechat=None):
        ok = lambda n: {"total": n, "results": [{"title": "财税〔2025〕1号",
                                                 "url": "https://x.test/a"}] if n else []}
        with mock.patch.object(AGG, "search_tax", return_value=ok(1)), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok(1)), \
             mock.patch.object(AGG, "sogou_search",
                               return_value=sogou if sogou is not None else ok(1)), \
             mock.patch.object(AGG, "search_shui5",
                               return_value=shui5 if shui5 is not None else ok(0)), \
             mock.patch.object(AGG, "search_wechat",
                               return_value=wechat if wechat is not None else ok(0)), \
             mock.patch.object(AGG, "search_ctax", return_value=ok(1)):
            return AGG.aggregate_search("测试词", size=5)

    def test_no_gap_when_nothing_failed(self):
        r = self._agg()
        self.assertEqual([], r["gaps"])
        self.assertEqual("", r["degraded_note"])

    def test_blocked_source_yields_a_gap_with_impact_and_no_substitute(self):
        r = self._agg(sogou={"_error": "搜狗熔断中：约 600 秒后到期", "results": []})
        gaps = {g["source"]: g for g in r["gaps"]}
        self.assertIn("sogou", gaps)
        self.assertEqual("搜狗熔断中：约 600 秒后到期", gaps["sogou"]["reason"])
        self.assertIn("地方口径", gaps["sogou"]["impact"])
        self.assertTrue(gaps["sogou"]["do_not_substitute"])
        # 断这句话的两个要点：不许拿别的源顶替 + 必须说明缺的是哪一层。
        # 别截半句去匹配——"不要用其他源顶替"在实现文案里并不连续
        # （实现写的是"不要用其他源的条目顶替缺失层"），断半句是形式审查。
        self.assertIn("不要用其他源的条目顶替", r["degraded_note"])
        self.assertIn("要明说缺的是哪一层", r["degraded_note"])

    def test_shui5_empty_is_attributed_to_sogou_when_only_sogou_was_walked(self):
        """税屋链接靠搜狗的 site:shui5.cn 检索取——搜狗被拦、站内没走，税屋的空是连带的。"""
        r = self._agg(sogou={"_error": "搜狗触发反爬", "results": []},
                      shui5={"total": 0, "results": [],
                             "_channels": {"搜狗": "被拦：搜狗触发反爬",
                                           "站内": "没走成：搜狗那一路没回来"}})
        shui5 = [g for g in r["gaps"] if g["source"] == "shui5"]
        self.assertEqual(1, len(shui5), "税屋该被单独标一条，说明它是被连带空掉的")
        self.assertEqual("sogou", shui5[0]["blocked_by"])
        self.assertIn("不代表税屋没有内容", shui5[0]["impact"])

    def test_shui5_own_failure_is_not_attributed_to_sogou(self):
        r = self._agg(shui5={"_error": "WAF 挑战未通过", "results": []})
        shui5 = [g for g in r["gaps"] if g["source"] == "shui5"]
        self.assertEqual(1, len(shui5))
        self.assertNotIn("blocked_by", shui5[0], "税屋自己报错时不该甩给搜狗")
        self.assertIn("WAF", shui5[0]["reason"])

    def test_note_counts_hits_and_names_the_layer(self):
        r = self._agg(sogou={"_error": "搜狗触发反爬", "results": []},
                      shui5={"total": 0, "results": [],
                             "_channels": {"搜狗": "被拦：搜狗触发反爬",
                                           "站内": "没走成：搜狗那一路没回来"}})
        # 分母取的是这一轮实际发出的源名单长度，不是文案里的常量：名单加到六枚，
        # 这句就得跟着改，改了才发现漏了。打桩给的是 npc／chinatax／ctax 三路有命中。
        self.assertIn("3/6", r["degraded_note"], r["degraded_note"])
        self.assertIn("税屋", r["degraded_note"])


# ── ②″ 清单取到了、逐枚没取全：第四种形状必须在四个面上都有话 ──────────────
class TestPartialRoundLoss(unittest.TestCase):
    """`_partial_error`：站点给了清单，逐枚正文/地址却没取回来。

    2026-11-24 探针 `.tmp-inspect/partial_loss_surfaces.py`（双臂 × 三面，控制组
    先过才认读数）在旧搜狗入口实测：三枚里两枚还原失败时，实务那一路交回 1 条而
    说明为空，读成「网上只有 1 篇解读」；三枚全失败时读成「网上没有解读」。迁移后
    的元宝入口直接给微信文章直链，下面的夹具用「两枚结果链接无效」复现同一契约。
    税屋那一路三枚里两枚正文为空时交回 3 条（两条空正文）说明也为空，答案层把空
    正文条目照常送进 evidence，读起来像「这三篇都核过了」。聚合层 errors={}、
    gaps=0，全是静的。

    为什么不借用顶层 `_error` 说这件事：那枚的语义是「这一路整体没取到」，
    `_rows_and_error` 见到它就把条目全部作废（`tax_answer.py:296-297`），
    而这里清单确实取回了。两枚可以并存（站内断供 + 半截正文），所以下面
    `test_both_shapes_coexist` 钉的是两条 gap 各说各的，不是合并成一条。
    """

    # 三枚标题都冠上检索词「增值税」：主路加了相关性过滤之后，标题不含分词的条目会被
    # 当成站点推词兜底滤掉——这一族钉的是「清单/正文丢失」，不能被过滤改意（2026-11-27）。
    TITLES = ("增值税即征即退的操作口径", "增值税留抵退税的申报表单变化",
              "增值税六税两费减免的适用主体")

    def _wx_block(self, i: int, valid_link: bool = True) -> str:
        href = ("https://mp.weixin.qq.com/s?k=%d" % i if valid_link
                else "https://example.test/article/%d" % i)
        return ('<a data-x="linkid&quot;:&quot;source&quot;">'
                '<span>财税小课堂%d</span><span>http://mp.weixin.qq.com</span>'
                '<span>%d天前</span></a>'
                '<a href="%s" data-x="linkid&quot;:&quot;title&quot;">%s</a>'
                '<div class="sa-text">摘要 %d</div>' %
                (i, i, href, self.TITLES[i - 1], i))

    def _wx_page(self, n: int, n_ok: int = 3) -> str:
        return "<html><body>" + "".join(
            self._wx_block(i, i <= n_ok) for i in range(1, n + 1)) + "</body></html>"

    def _wechat_round_trip(self, n_ok: int, read_body: bool = False, n_body: int = 3):
        page = self._wx_page(3, n_ok=n_ok)

        def fake_get(sess, url, **kw):
            return _WxResp(page, ISEARCH_URL)

        def fake_post(sess, url, **kw):
            """主路那两发回熔断形：这一族钉的是 GET 页型的清单/正文丢失，
            不给 POST 桩就会真的打出网络去（2026-11-27 报告 §7 的"不 hermetic"）。"""
            return _WxResp(_dead_shape(), NEXT_PAGE_URL)

        def fake_read(url):
            idx = int(url.rsplit("k=", 1)[1])
            if idx <= n_body:
                return "正文 %d" % idx, ""
            return "", "正文容器未命中（可能已删除）"

        old = (W._yuanbao_get, W._yuanbao_post, W.read_article, W.time.sleep, W.DEAD_COOLDOWN)
        try:
            W._yuanbao_get, W._yuanbao_post = fake_get, fake_post
            W.read_article = fake_read
            W.time.sleep = lambda s: None
            W.DEAD_COOLDOWN = 0.0
            return W.search_wechat("增值税", size=3, read_body=read_body)
        finally:
            (W._yuanbao_get, W._yuanbao_post, W.read_article, W.time.sleep,
             W.DEAD_COOLDOWN) = old

    def test_wechat_all_links_valid_says_nothing(self):
        """控制组：三枚直链都有效 ⇒ 不许凭空编出一条"没取全"来。"""
        r = self._wechat_round_trip(3)
        self.assertEqual(3, r["total"])
        self.assertNotIn("_partial_error", r, r.get("_partial_error"))
        self.assertNotIn("_error", r)

    def test_wechat_partial_link_loss_names_the_loss(self):
        """无链的条目不交付（交付它等于给下游一个空 link），但丢失必须点名。

        2026-11-27 改口：旧写法把 3 条全交回去、只在顶层带一句"2/3 条没有有效微信直链"，
        于是 `total` 里含着两条取不到正文的死条目。现在 `total` 就是能用的条数，
        差额写在 `_partial_error` 里——两个数都在，读者不用猜。
        """
        r = self._wechat_round_trip(1)
        self.assertEqual(1, r["total"], "只有那一条有直链，就该交付那一条")
        self.assertNotIn("_error", r, "借顶层 _error 会把已取回的那条一起作废")
        note = r["_partial_error"]
        self.assertIn("元宝给出 3 条，交付 1 条", note, note)
        self.assertIn("2 条没有有效微信直链、已剔除", note, note)
        self.assertIn("不能当成完整的一轮用", note, note)

    def test_wechat_total_link_failure_is_fetch_failure_not_zero_hit(self):
        r = self._wechat_round_trip(0)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("没有一条有效的微信文章直链", r["_error"])

    def test_wechat_lost_body_is_counted_apart_from_lost_link(self):
        r = self._wechat_round_trip(3, read_body=True, n_body=1)
        note = r["_partial_error"]
        self.assertIn("2/3 条没取到正文", note, note)
        self.assertNotIn("没有有效微信直链", note, "地址都有效，别混说")
        self.assertEqual(3, r["total"])
        r2 = self._wechat_round_trip(1, read_body=True, n_body=0)
        both = r2["_partial_error"]
        self.assertIn("2 条没有有效微信直链、已剔除", both, both)
        self.assertIn("1/1 条没取到正文", both, both)
        self.assertEqual(1, r2["total"])

    def test_shui5_partial_body_is_headed_at_the_top(self):
        """税屋：三篇里一篇正文没取到，顶层必须带出 `_partial_error`。"""
        rows = [{"title": self.TITLES[i], "url": "https://www.shui5.cn/article/%d.html" % (i + 1),
                 "date": "2026-02-0%d" % (i + 1), "snippet": "摘要"} for i in range(3)]
        arts = [{"url": r["url"], "content": "正文 %d" % (i + 1), "pages": 1, "title": r["title"],
                 "date": r["date"], "summary": "摘要"} for i, r in enumerate(rows)]
        arts[2]["content"] = ""
        arts[2]["_error"] = "正文容器未命中"

        old_sg, old_read, old_sleep = SH.sogou_search, SH.read_articles, SH.time.sleep
        try:
            SH.sogou_search = lambda q, site=None, size=5: {"results": rows, "total": 3,
                                                            "searched_at": "2026-11-24"}
            SH.read_articles = lambda urls, session=None: arts
            SH.time.sleep = lambda s: None
            r = SH.search_shui5("增值税", size=3, read_body=True)
        finally:
            SH.sogou_search, SH.read_articles, SH.time.sleep = old_sg, old_read, old_sleep
        self.assertEqual(3, r["total"])
        self.assertNotIn("_error", r, "正文逐枚失败不是整路失败")
        self.assertIn("1/3 篇正文一篇都没取到", r["_partial_error"], r["_partial_error"])

    def test_shui5_half_read_pages_is_its_own_phrase(self):
        """续页没取到 = 正文只读到半截，与"一篇都没取到"分开说。"""
        rows = [{"title": self.TITLES[0], "url": "https://www.shui5.cn/article/9.html",
                 "date": "2026-02-01", "snippet": "摘要"}]
        arts = [{"url": rows[0]["url"], "content": "只有一段", "pages": 1,
                 "_pages_error": "第 2 页取不到（HTTP 500），正文止于第 1 页"}]
        old_sg, old_read = SH.sogou_search, SH.read_articles
        try:
            SH.sogou_search = lambda q, site=None, size=5: {"results": rows, "total": 1,
                                                            "searched_at": "2026-11-24"}
            SH.read_articles = lambda urls, session=None: arts
            r = SH.search_shui5("增值税", size=1, read_body=True)
        finally:
            SH.sogou_search, SH.read_articles = old_sg, old_read
        self.assertIn("正文只读到半截", r["_partial_error"], r["_partial_error"])

    def test_shui5_batch_lane_reports_partial_too(self):
        """`search_many`（多枚词一轮发）自己也汇了一遍正文——这一档不能只修单词那条路。

        2026-11-24 读源码：`tax_shui5.py:931-936` 与 `search_shui5` 各调一次
        `_partial_note`；只修前者的话，CLI 的 `--keywords` 那一路依旧静默。
        """
        rows = [{"title": self.TITLES[i], "date": "2026-02-0%d" % (i + 1),
                 "url": "https://www.shui5.cn/article/%d.html" % (i + 1),
                 "matched_keywords": [self.TITLES[i]]} for i in range(2)]
        arts = [{"url": rows[0]["url"], "content": "正文 1", "pages": 1, "_how": "打桩会话"},
                {"url": rows[1]["url"], "content": "", "pages": 0,
                 "_error": "正文容器未命中"}]
        one = {"total": 1, "results": [rows[0]], "searched_at": "2026-11-24",
               "_channel": "站内", "_channels": {"站内": "命中 1 条"}}
        two = {"total": 1, "results": [dict(rows[1], matched_keywords=[self.TITLES[1]])],
               "searched_at": "2026-11-24", "_channel": "站内",
               "_channels": {"站内": "命中 1 条"}}
        old_one, old_many = SH.search_shui5, SH.read_articles
        with mock.patch.object(SH, "_pass_waf", return_value=(None, "打桩过 WAF")), \
             mock.patch.object(SH.time, "sleep", lambda s: None):
            calls = iter([one, two])

            def fake_one(keyword, size=5, read_body=False, **kw):
                return dict(next(calls))

            try:
                SH.search_shui5 = fake_one
                SH.read_articles = lambda urls, session=None: arts
                r = SH.search_many([self.TITLES[0], self.TITLES[1]], size=1)
            finally:
                SH.search_shui5, SH.read_articles = old_one, old_many
        self.assertEqual(2, r["total"], "两枚词各一条、按 url 合并不该吞掉")
        self.assertNotIn("_error", r, "整路是成功的")
        self.assertIn("1/2 篇正文一篇都没取到", r["_partial_error"], r["_partial_error"])

    def test_aggregator_gap_line_is_the_only_channel_for_it(self):
        """聚合层 emit 那一支单独钉：收键与建档是两件事，漏任一件都静默。"""
        ok = {"total": 1, "results": [{"title": "财税〔2025〕1号", "url": "https://x.test/a"}]}
        shui5 = {"total": 1, "results": [{"title": self.TITLES[0],
                                         "url": "https://www.shui5.cn/article/1.html",
                                         "content": ""}],
                 "_partial_error": "清单取回 1 条，但 1/1 篇正文一篇都没取到",
                 "_channels": {"搜狗": "命中 1 条", "站内": "命中 1 条"}}
        with mock.patch.object(AGG, "search_tax", return_value=ok), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok), \
             mock.patch.object(AGG, "sogou_search", return_value=ok), \
             mock.patch.object(AGG, "search_shui5", return_value=shui5), \
             mock.patch.object(AGG, "search_wechat", return_value={"total": 0, "results": []}), \
             mock.patch.object(AGG, "search_ctax", return_value=ok):
            r = AGG.aggregate_search("测试词", size=5)
        self.assertEqual({}, r["errors"], "逐枚失败不该记成整源失败")
        g = [g for g in r["gaps"] if g["source"] == "shui5"]
        self.assertEqual(1, len(g), r["gaps"])
        self.assertTrue(g[0].get("partial"), g[0])
        self.assertNotIn("税屋（清单取到", r["degraded_note"].replace("缺失：", ""),
                         "degraded_note 只报层名，长句留在 gaps 里")
        self.assertIn("税屋", r["degraded_note"], r["degraded_note"])

    def test_practice_lane_carries_the_note_per_source(self):
        """实务那一路：逐枚失败要按源名进说明，不能只留条目。"""
        shui5 = {"total": 2, "results": [
            {"title": self.TITLES[0], "url": "https://www.shui5.cn/article/1.html",
             "date": "2026-02-01", "content": "有正文"},
            {"title": self.TITLES[1], "url": "https://www.shui5.cn/article/2.html",
             "date": "2026-02-02", "content": ""}]}
        wechat = {"total": 1, "results": [
            {"title": self.TITLES[2], "url": "", "date": "2026-01-03", "_error": "HTTP 500"}],
            "_partial_error": "元宝给出了 1 条，但 1/1 条没有有效微信直链"}
        with mock.patch.object(REL, "search_shui5", return_value=shui5), \
             mock.patch.object(REL, "search_wechat", return_value=wechat):
            items, note = REL.search_practice_sources("增值税", n=3)
        self.assertIn("微信公众号", note, note)
        self.assertIn("没有有效微信直链", note, note)
        self.assertEqual(2, len(items), "税屋两枚照常交出（空正文那条也是真条目）")
        self.assertEqual({"税屋"}, {i["source"] for i in items},
                         "微信那枚没有地址，不该混进结果里")

    def test_practice_lane_whole_source_failure_outranks_partial(self):
        """整路失败与逐枚失败同时存在时，先说整路：那句已经足够严重。"""
        d = {"total": 0, "results": [], "_error": "WAF 挑战未通过",
             "_partial_error": "清单取回 2 条，但 2/2 篇正文一篇都没取到"}
        with mock.patch.object(REL, "search_shui5", return_value=d), \
             mock.patch.object(REL, "search_wechat", return_value={"total": 0, "results": []}):
            _items, note = REL.search_practice_sources("增值税", n=3)
        self.assertIn("WAF", note, note)
        self.assertNotIn("一篇都没取到", note, "两枚不该并列——顶层失败那条说了算")

    def test_aggregator_files_it_as_a_gap_not_an_error(self):
        """聚合层：这一档进 gaps（带 partial 标记），不进 errors（那话术是"没取到内容"）。"""
        ok = {"total": 1, "results": [{"title": "财税〔2025〕1号", "url": "https://x.test/a"}]}
        wechat = {"total": 3, "results": [{"title": self.TITLES[0], "url": "",
                                           "_error": "HTTP 500"}],
                  "_partial_error": "元宝给出了 3 条，但 2/3 条没有有效微信直链"}
        with mock.patch.object(AGG, "search_tax", return_value=ok), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok), \
             mock.patch.object(AGG, "sogou_search", return_value=ok), \
             mock.patch.object(AGG, "search_shui5", return_value={"total": 0, "results": []}), \
             mock.patch.object(AGG, "search_wechat", return_value=wechat), \
             mock.patch.object(AGG, "search_ctax", return_value=ok):
            r = AGG.aggregate_search("测试词", size=5)
        self.assertNotIn("wechat", r["errors"], r["errors"])
        g = [g for g in r["gaps"] if g["source"] == "wechat"]
        self.assertEqual(1, len(g), r["gaps"])
        self.assertTrue(g[0]["partial"], g[0])
        self.assertIn("清单取到、逐枚没取全", g[0]["label"], g[0]["label"])
        self.assertIn("不能当成这一层已经看全", g[0]["impact"], g[0]["impact"])
        self.assertIn("微信公众号", r["degraded_note"], r["degraded_note"])

    def test_aggregator_keeps_both_shapes_when_they_coexist(self):
        """站内断供（顶层 _error）与半截正文（_partial_error）同时成立：两条 gap 并存。"""
        ok = {"total": 1, "results": [{"title": "财税〔2025〕1号", "url": "https://x.test/a"}]}
        shui5 = {"total": 3, "results": [{"title": self.TITLES[0],
                                         "url": "https://www.shui5.cn/article/1.html"}],
                 "_error": "第 3 页返回空，但站点报这一词共 61 条：判为断供",
                 "_partial_error": "清单取回 3 条，但 1/3 篇正文一篇都没取到",
                 "_channels": {"搜狗": "命中 3 条", "站内": "命中 3 条"}}
        with mock.patch.object(AGG, "search_tax", return_value=ok), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok), \
             mock.patch.object(AGG, "sogou_search", return_value=ok), \
             mock.patch.object(AGG, "search_shui5", return_value=shui5), \
             mock.patch.object(AGG, "search_wechat", return_value={"total": 0, "results": []}), \
             mock.patch.object(AGG, "search_ctax", return_value=ok):
            r = AGG.aggregate_search("测试词", size=5)
        sh = [g for g in r["gaps"] if g["source"] == "shui5"]
        self.assertEqual(2, len(sh), "两件事各一条，合并就把断供说成没取全")
        self.assertEqual({True, False}, {bool(g.get("partial")) for g in sh}, sh)
        self.assertIn("shui5", r["errors"], "断供那档仍要走老通道")

    def test_rows_and_error_carries_the_note_without_voiding_the_rows(self):
        """答案层的三枚返回：行照常交出、说明另带——这是本轮最容易写错的一处。"""
        d = {"total": 2, "results": [{"title": "a"}, {"title": "b"}],
             "_partial_error": "清单取回 2 条，但 1/2 篇正文一篇都没取到"}
        rows, err, partial = ANS._rows_and_error(d)
        self.assertEqual(2, len(rows), "并进 err 会把已取回的两条一起作废")
        self.assertEqual("", err)
        self.assertIn("一篇都没取到", partial)
        failed = {"results": [], "_error": "WAF 挑战未通过",
                  "_partial_error": "清单取回 3 条，但 3/3 篇正文一篇都没取到"}
        rows, err, partial = ANS._rows_and_error(failed)
        self.assertEqual(([], "WAF 挑战未通过", ""), (rows, err, partial),
                         "整路失败时第三枚让位：那一句已经涵盖了这一轮不可用")
        empty = {"total": 0, "results": [], "_partial_error": "站点给了 0 条"}
        self.assertEqual(([], "", ""), ANS._rows_and_error(empty),
                         "没有条目时逐枚说明没有落点，不该冒出话来")

    def test_round_functions_hand_the_note_up_as_the_third_slot(self):
        for nm, mod, fn in (("_wechat_round", "WX", ANS._wechat_round),
                            ("_shui5_round", "S5", ANS._shui5_round)):
            env = {"total": 1, "results": [{"title": "x", "url": "https://y.test/1"}],
                   "_partial_error": "清单取回 1 条，但 1/1 篇正文一篇都没取到"}
            with mock.patch.object(getattr(ANS, mod),
                                   "search_wechat" if nm.startswith("_wechat") else "search_shui5",
                                   return_value=env):
                rows, err, partial = fn("增值税", 3)
            self.assertEqual(1, len(rows), nm)
            self.assertEqual("", err, nm)
            self.assertIn("一篇都没取到", partial, nm)

    def test_gather_routes_it_to_partial_notes_not_errors(self):
        """plan 里两条通道必须各走各的：errors 的话术是"取数失败"。"""
        g = TestRoundFailureIsNotSilent("test_source_error_names_the_round_and_the_source")._gather(
            partial=("shui5",))
        self.assertTrue(g["partial_notes"], g)
        self.assertFalse([e for e in g["errors"] if "一篇都没取到" in e],
                         g["errors"])
        a = ANS.compose(g)
        self.assertTrue(a["partial_note"], a["partial_note"])
        self.assertFalse(a["fetch_errors"], "这一档不是取数失败，别混进那一串")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ANS._print_answer(a)
        self.assertIn("【清单取到、逐枚没取全】", out.getvalue())
        self.assertNotIn("【取数失败】", out.getvalue())


# ── ②' 网页端要把缺口显示出来，不能显示成普通的 0 条 ──────────────────────
class TestFrontendShowsDegradedNote(unittest.TestCase):
    def test_render_results_shows_degraded_note(self):
        body = HTML[HTML.index("function renderResults(data){"):
                    HTML.index("KEYWORD HIGHLIGHT")]
        self.assertIn("degraded_note", body)
        self.assertIn("esc(result.degraded_note)", body)

    def test_empty_state_keeps_the_causes_apart(self):
        """空清单有四种成因，页面要分流、原样显示，不得全塌成"未找到"。

        对应的缺陷：翻过末页、维度拼窄、接口没给清单是"没取到/取法不对"，
        取数失败（_fetch_failed）更是服务侧故障。都渲染成"未找到相关政策"就
        等于页面替用户说了"库里没有这份文件"——用户会换个词重搜，而真相是
        要么稍后再试、要么把维度放宽。分流顺序按"越靠近真相越先看"，取数失败
        排最前，不能和其余三种共用未找到那一句。
        """
        body = HTML[HTML.index("function renderResults(data){"):
                    HTML.index("KEYWORD HIGHLIGHT")]
        # 取数失败走独立分支：有专门的标题，且这一句排在"未找到"之前
        self.assertIn("result._fetch_failed", body)
        self.assertIn("取数失败", body)
        self.assertLess(body.index("result._fetch_failed"), body.index("未找到相关政策"),
                        "取数失败被并进了未找到分支")
        # 其余三种成因仍逐字透出：filter_note / empty_reason / error 都进 why 链
        self.assertIn("result._filter_note", body)
        self.assertIn("result._empty_reason", body)
        # 透出的句子来自外部检索结果，必须走 esc() 才拼进 HTML
        self.assertIn("esc(why)", body)

    def test_render_results_shows_routing_note(self):
        """换源提示和"没归类"提示都由后端给整句，页面只照抄。

        对应的缺陷：归不出税种时后端拿原话做字面标题检索，实测回 687 条无关
        法条。页面不显示这句，一摞无关法条就看起来像按本题找出来的依据。
        """
        body = HTML[HTML.index("function renderResults(data){"):
                    HTML.index("KEYWORD HIGHLIGHT")]
        self.assertIn("_routed", body)
        self.assertIn("esc(result._routed)", body)


# ── 录入项带来的文号/时效/效力级别，页面不能继续显示"时效未标注" ──────────
class TestFrontendShowsSourceMetadata(unittest.TestCase):
    """NPC 条目给数字状态码，总局法规库条目给的是录入项文本。

    缺陷形态很具体：接口已经回 `xxgk_aging="全文有效"`，页面只读
    `status_code`，于是这份现行有效的文件在界面上显示成"⚪ 时效未标注"，
    和真的没标的条目长得一模一样。
    """

    OLD_BADGE = ("function statusBadge(item){\n"
                 "  const cls = statusMap[item.status_code] || 's-unknown';\n"
                 "  return `<span class=\"status-badge ${cls}\">"
                 "${statusNames[item.status_code] || '时效未标注'}</span>`;\n}\n")

    @staticmethod
    def _badge():
        return HTML[HTML.index("function statusBadge(item){"):
                    HTML.index("items.forEach((item,i)=>{")]

    @staticmethod
    def _card():
        return HTML[HTML.index("function renderResults(data){"):
                    HTML.index("KEYWORD HIGHLIGHT")]

    def test_badge_reads_both_the_code_and_the_text(self):
        b = self._badge()
        self.assertIn("item.status_code", b)
        self.assertIn("item.status", b)
        # 文本要分四类，"全文有效"不能掉进未标注
        for word in ("废止", "尚未生效", "修改", "有效"):
            self.assertIn(word, b, word)

    def test_card_shows_document_number_and_effect_level(self):
        body = self._card()
        self.assertIn("item.document_number", body)
        self.assertIn("item.effect_level", body)
        self.assertIn("statusBadge(item)", body)

    def test_date_falls_back_to_the_source_field(self):
        """单源 chinatax/fgk 的条目用 `date`，聚合后才统一成 `publish_date`。"""
        self.assertIn("item.publish_date||item.date", self._card())

    def test_placeholder_status_is_not_shown_as_a_source_value(self):
        """NPC 缺 status 时程序自己拼"未知(None)"，那是缺省值不是法规写的时效。

        界面要把它换成"时效未标注"，否则读者的判断依据从"来源没给"变成了
        "来源给了一个叫未知的值"。
        """
        self.assertIn("/^未知/", self._badge())
        self.assertIn("'时效未标注'", self._badge())

    def test_rules_can_actually_fail(self):
        """把同一套断言作用在违规写法上，确认它拦得住。"""
        for word in ("废止", "尚未生效", "修改", "有效"):
            self.assertNotIn(word, self.OLD_BADGE, word)
        self.assertNotIn("item.status||", self.OLD_BADGE)
        self.assertNotIn("document_number", self.OLD_BADGE)


# ── ⑤⑥ 定级层读到 `_reliability` 后要给出可核对的提醒 ──────────────────────
class TestReliabilityBecomesAReminder(unittest.TestCase):
    """来源标记要说清"疑在哪一处、要核对什么"，不许再用降权代替核对。

    断言的是提醒，不是否决。"标了 low 就把分清零、整组不许挑主依据"是在限制材料
    的作用——读者只看到一个小标签，既不知道为什么，
    也无从下手。同样的来源信息写成逐条提醒，材料照常参与分层。
    """

    LAW = "中华人民共和国企业所得税法"

    def test_low_carries_a_checkable_reminder(self):
        g = E.grade({"title": self.LAW, "_reliability": "low"})
        self.assertEqual("low", g["reliability"])
        self.assertIn(E.RELIABILITY_CAVEAT["low"], g["caveats"])
        self.assertNotIn("不得作为依据引用", g["citation_hint"])

    def test_medium_reminder_is_the_sources_own_sentence(self):
        """同是 medium，三条来源各说各的原因，提醒必须用来源自己那句。

        `medium` 在本仓库有三个出处：NPC 正文检索按全文分词命中、总局法规库第 2
        页起排序变松、立法过程件不在六个源的收录范围内。定级层若按档位配一句
        固定话（"这一条来自清单靠后的页位"），三处里只有法规库那处对得上，另两处
        给的是假提醒——全文检索和站内检索没有"页位"这件事。

        变异自检：把 `tax_evidence._caveats` 里那句改回
        `RELIABILITY_CAVEAT[rel] + "；" + rel_note`，`assertEqual` 与
        `not in` 两组断言同时报红；把 `RELIABILITY_CAVEAT["medium"]` 改写成带
        某个具体机制的说法，最后一条断言报红。
        """
        fgk = E.grade({"title": self.LAW, "_reliability": "medium",
                       "_reliability_note": FGK.FGK_DEEP_NOTE.format(page=3)},
                      topic="企业所得税")
        npc = E.grade({"title": self.LAW, "_reliability": "medium",
                       "_reliability_note": T.RELIABILITY_NOTES["medium"]},
                      topic="企业所得税")
        self.assertEqual(FGK.FGK_DEEP_NOTE.format(page=3), fgk["caveats"][-1])
        self.assertEqual(T.RELIABILITY_NOTES["medium"], npc["caveats"][-1])
        for g in (fgk, npc):
            self.assertTrue(all(E.RELIABILITY_CAVEAT["medium"] not in c
                                for c in g["caveats"]), g["caveats"])
        self.assertNotIn("第 3 页", "；".join(npc["caveats"]),
                         "全文检索的条目不该被告知自己来自法规库的第 3 页")

    def test_marker_without_a_note_falls_back_to_a_neutral_reminder(self):
        """只有档位、没有原因说明时，兜底句不许断言某个具体机制。"""
        g = E.grade({"title": self.LAW, "_reliability": "medium"})
        self.assertIn(E.RELIABILITY_CAVEAT["medium"], g["caveats"])
        for word in ("页位", "分词", "页"):
            self.assertNotIn(word, E.RELIABILITY_CAVEAT["medium"], word)
            self.assertNotIn(word, E.RELIABILITY_CAVEAT["low"], word)

    def test_unmarked_item_gets_no_reliability_reminder(self):
        g = E.grade({"title": self.LAW, "status": "全文有效"}, topic="企业所得税")
        self.assertEqual("ok", g["reliability"])
        self.assertEqual([], [c for c in g["caveats"]
                              if c in (E.RELIABILITY_CAVEAT["low"],
                                       E.RELIABILITY_CAVEAT["medium"])])
        self.assertEqual("direct", g["role"])

    def test_reliability_does_not_change_the_pick(self):
        """标了 low 的《企业所得税法》不再被整组剔除，也不再因此让位。

        变异自检：把 `_reliability` 塞回 `_order_key`（例如 low 时 tier 取 0），
        这一条与下一条都会报红——那正是本文件不许回来的做法。
        """
        g = E.pick_primary([
            E.grade({"title": self.LAW, "_reliability": "low",
                     "_reliability_note": "全文检索偏题"}, topic="企业所得税"),
            E.grade({"title": "国家税务总局公告2018年第28号"}, topic="企业所得税"),
        ])
        self.assertEqual(self.LAW, g["title"])
        self.assertEqual("low", g["reliability"])
        self.assertIn("全文检索偏题", g["_why"])

    def test_pick_is_by_role_not_by_marker(self):
        """两条在能不能引、角色、时效、层级、主题对应上全相等时，标记不参与排队。

        先断言两条真的并列，否则这条测的是排队规则而不是标记——上一次它就用一份
        未定级的通知去比一份总局公告，角色本来就不同，结论说明不了任何事。

        变异自检：把 `_reliability` 塞进 `_order_key`（low 排后），两次断言里
        必有一次报红。
        """
        a = E.grade({"title": "国家税务总局公告2018年第28号",
                     "_reliability": "low"}, topic="企业重组")
        b = E.grade({"title": "国家税务总局公告2019年第11号"}, topic="企业重组")
        self.assertEqual(E._order_key(a), E._order_key(b),
                         (a["rank"], a["role"], a["validity"], a["on_topic"]))
        self.assertEqual("low", a["reliability"])
        self.assertEqual(a["title"], E.pick_primary([a, b])["title"])
        self.assertEqual(b["title"], E.pick_primary([b, a])["title"])

    def test_every_candidate_keeps_its_own_caveats(self):
        """全组都带标记时照样挑得出来，且落选项在 `_runners_up` 里带着提醒。"""
        best = E.pick_primary([E.grade({"title": self.LAW, "_reliability": "low"},
                                       topic="企业所得税")])
        self.assertEqual(self.LAW, best["title"])
        self.assertIn(E.RELIABILITY_CAVEAT["low"], best["_why"])
        run = E.pick_primary([
            E.grade({"title": self.LAW, "status": "全文有效"}, topic="企业所得税"),
            E.grade({"title": "中华人民共和国增值税暂行条例", "status": "全文有效",
                     "_reliability": "medium"}, topic="企业所得税"),
        ])["_runners_up"]
        self.assertIn(E.RELIABILITY_CAVEAT["medium"], run[0]["caveats"])


# ── ⑤'' 聚合层带下来的标记必须说得出原因 ──────────────────────────────────
class TestAggregatorCarriesTheReminder(unittest.TestCase):
    """整源标记按定义就是"这一窗条目共同的取回方式"，逐条带上不算冤枉。

    它只在源自己的输出里印一次、不带进聚合的话，聚合清单上看不出这些条目来自
    全文检索，定级层与界面都收不到这句提醒。

    变异自检：把 `tax_aggregator` 里 `item["_reliability_note"] = source_note`
    那两行删掉，第一条断言报红；把命令行摘要改回按档位配一句固定话（低档写
    "不得作为权威依据引用"），第二条报红。
    """

    NPC_NOTE = "NPC 正文检索按全文分词命中，可能偏题；请回到标题检索确定条文归属"
    DEEP_NOTE = "取自总局检索第 3 页：深页条目可能只是沾了检索词"

    def _agg(self):
        npc = {"total": 1, "results": [{"title": "中华人民共和国增值税暂行条例",
                                        "url": "http://x/npc"}],
               "_reliability": "medium", "_reliability_note": self.NPC_NOTE}
        chinatax = {"total": 1, "results": [{"title": "国家税务总局公告2025年第3号",
                                             "url": "http://x/ct"}]}
        empty = {"total": 0, "results": []}
        with mock.patch.object(AGG, "search_tax", return_value=npc), \
             mock.patch.object(AGG, "search_chinatax", return_value=chinatax), \
             mock.patch.object(AGG, "sogou_search", return_value=empty), \
             mock.patch.object(AGG, "search_shui5", return_value=empty), \
             mock.patch.object(AGG, "search_wechat", return_value=empty), \
             mock.patch.object(AGG, "search_ctax", return_value=empty):
            return AGG.aggregate_search("增值税", size=5, scope="fulltext")

    def test_source_level_marker_reaches_each_item_with_its_note(self):
        r = self._agg()
        row = [i for i in r["items"] if i["_source"] == "npc"][0]
        self.assertEqual("medium", row["_reliability"])
        self.assertEqual(self.NPC_NOTE, row["_reliability_note"])
        # 没带标记的那一路不能被连坐
        self.assertNotIn("_reliability",
                         [i for i in r["items"] if i["_source"] == "chinatax"][0])

    def test_cli_prints_the_reminder_text_not_a_level_ban(self):
        """命令行摘要印每条自带的提醒原文；按档位配死一句禁令是旧做法。"""
        res = {"searched_at": "2026-10-03 00:00:00",
               "source_summary": {"npc": 1, "chinatax": 1},
               "items": [{"_source": "npc", "title": "A",
                          "_reliability": "medium", "_reliability_note": self.NPC_NOTE},
                         {"_source": "chinatax", "title": "B",
                          "_reliability": "medium", "_reliability_note": self.DEEP_NOTE},
                         {"_source": "npc", "title": "C",
                          "_reliability": "low"}],
               "gaps": [], "errors": {}}
        out = io.StringIO()
        with mock.patch.object(AGG, "aggregate_search", return_value=res), \
             mock.patch.object(sys, "argv", ["tax_aggregator.py", "增值税"]), \
             contextlib.redirect_stdout(out):
            AGG.main()
        text = out.getvalue()
        self.assertIn(self.NPC_NOTE, text)
        self.assertIn(self.DEEP_NOTE, text)
        self.assertIn("未写明存疑在哪一处", text, "只有档位没有说明时要明说缺的是什么")
        for ban in ("不得作为权威依据引用", "只能参考", "不得作为依据引用"):
            self.assertNotIn(ban, text, ban)


# ── ⑤' 显示层也不许把标记吞掉 ──────────────────────────────────────────────
class TestFormatterShowsReliability(unittest.TestCase):
    """标记进了数据、却印不出来，等于没标记。

    `tax_formatter.py --mode single` 必须读响应级的 `_reliability`：把 NPC 全文
    检索（恒带 medium）的结果灌进去，输出里一个字都不提"可能偏题"，读者只看到
    "共 N 条法规"，会当成能引用的清单。多源归并那条路径印了，单源这条不许漏。
    """

    def _render(self, **extra):
        """喂一份 tax_search 真实会返回的最小响应，返回渲染出的 markdown。"""
        resp = {
            "keyword": "研发费用加计扣除", "total": 8833,
            "scope": "fulltext", "search_type": "fuzzy",
            "results": [{"title": "中华人民共和国企业所得税法", "id": "x1",
                         "status_code": 3, "publish_date": "2018-12-29"}],
        }
        resp.update(extra)
        return FMT.format_search_response(resp, intent="policy_lookup")

    def test_medium_marker_reaches_the_markdown(self):
        md = self._render(_reliability="medium",
                          _reliability_note="结果已排序但可能偏题（全文分词匹配）")
        self.assertIn("可靠性 medium", md)
        self.assertIn("可能偏题", md)
        # 警告要出现在条目之前，不能等读者看完清单才看到
        self.assertLess(md.index("可靠性"), md.index("中华人民共和国企业所得税法"))

    def test_local_wording_is_the_fallback(self):
        """数据里没带说明时用本地兜底文案，而不是印出空的破折号。"""
        md = self._render(_reliability="medium")
        self.assertIn("可靠性 medium", md)
        self.assertIn(FMT._RELIABILITY_NOTE, md)

    def test_no_marker_no_warning(self):
        """回归：标题检索不带标记，就不能凭空多出一句警告。"""
        self.assertNotIn("可靠性", self._render())


# ── ④ 元宝公众号检索要进闸，不能靠"别并发"的提醒 ───────────────────────────
class _FakeSession:
    """记录并发峰值的假会话，用来验证闸真的把并发压成 1。

    3.62.49 起主路是 POST，两枚都得有——只留 get，测出来的"并发峰值 1"就只覆盖了
    兜底那一发，取数那两发根本没进闸也没人知道。
    """

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def _one(self, url, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return object()
        finally:
            with self._lock:
                self.active -= 1

    def get(self, url, **kwargs):
        return self._one(url, **kwargs)

    def post(self, url, **kwargs):
        return self._one(url, **kwargs)


class TestWechatYuanbaoGate(unittest.TestCase):
    def test_yuanbao_requests_go_through_the_gate(self):
        """闸的判据按函数面写，不按 `search_wechat` 里出现哪个帮手名写。

        2026-11-27 主路换成 POST 之后，旧那句 `assertIn("_yuanbao_get", body)` 只是
        被字符串换了个落点就红掉，什么也没证明。现在钉的是真正的不变量：全文件只有
        `_yuanbao_get`/`_yuanbao_post` 两枚帮手能碰 session 方法，且两枚都在闸里。
        """
        src = (SCRIPTS_DIR / "tax_wechat.py").read_text(encoding="utf-8")
        self.assertEqual(2, len(re.findall(r"sess\.(?:get|post)\(", src)),
                         "只许两枚闸内帮手调用 session 的 get/post")
        for name in ("def _yuanbao_get", "def _yuanbao_post"):
            start = src.index(name)
            helper = src[start:src.index("\ndef ", start)]
            self.assertIn("with yuanbao_gate:", helper, name + " 没进闸")
            self.assertIn("_pace_reserve()", helper, name + " 没在闸内留频次账")
        # 握手那一发也是真请求：旧写法裸 sess.get 绕闸（报告 §5.8）
        start = src.index("def _approve_handshake")
        helper = src[start:src.index("\ndef ", start)]
        self.assertIn("_yuanbao_get(sess", helper, "approve 握手绕开串行闸")

    def test_gate_is_the_shared_implementation_with_its_own_lock(self):
        self.assertIsInstance(W.yuanbao_gate, tax_http.SerialGate)
        self.assertIsInstance(T.npc_gate, tax_http.SerialGate)
        self.assertIsInstance(T.npc_gate, T.NpcSerialGate)
        self.assertNotEqual(
            W.yuanbao_gate.path, T.npc_gate.path,
            "两个站必须各用一把锁，共用一把会让不相关的请求互相排队甚至死等")

    def test_concurrent_callers_are_serialized(self):
        sess = _FakeSession()
        old = W.YUANBAO_MIN_INTERVAL
        try:
            W.YUANBAO_MIN_INTERVAL = 0.0
            threads = [threading.Thread(
                target=W._yuanbao_get,
                args=(sess, "https://so.qq.com/isearch?tab=weixin_article&query=x"))
                for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            W.YUANBAO_MIN_INTERVAL = old
        self.assertEqual(1, sess.max_active,
                         "并发峰值 %d：闸没起作用" % sess.max_active)

    def test_get_and_post_share_one_gate(self):
        """两档共用一把闸：GET 与 POST 混着并发，峰值仍是 1（分开记账＝绕过自己定的冷却）。"""
        sess = _FakeSession()
        old_int, old_pace, old_at = W.YUANBAO_MIN_INTERVAL, W._PACE_PATH, W._last_yuanbao_at
        try:
            W.YUANBAO_MIN_INTERVAL = 0.0
            W._PACE_PATH = Path(tempfile.mkdtemp()) / "pace.json"
            W._last_yuanbao_at = 0.0
            threads = []
            for index in range(4):
                fn = W._yuanbao_get if index % 2 else W._yuanbao_post
                threads.append(threading.Thread(target=fn, args=(sess, "https://so.qq.com/x")))
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            W.YUANBAO_MIN_INTERVAL, W._PACE_PATH, W._last_yuanbao_at = old_int, old_pace, old_at
        self.assertEqual(1, sess.max_active, "混发并发峰值 %d：两档没共用一把闸" % sess.max_active)

    def test_min_interval_is_enforced(self):
        sess = _FakeSession()
        old_int, old_at = W.YUANBAO_MIN_INTERVAL, W._last_yuanbao_at
        old_pace = W._PACE_PATH
        try:
            # 盘上那枚时刻必须从空文件起算，否则上一枚用例留下的戳会把这一发拖住
            W._PACE_PATH = Path(tempfile.mkdtemp()) / "pace.json"
            W.YUANBAO_MIN_INTERVAL = 0.4
            W._last_yuanbao_at = 0.0
            t0 = time.monotonic()
            W._yuanbao_get(sess, "https://so.qq.com/isearch?tab=weixin_article&query=x")
            W._yuanbao_get(sess, "https://so.qq.com/isearch?tab=weixin_article&query=y")
            dt = time.monotonic() - t0
        finally:
            W.YUANBAO_MIN_INTERVAL, W._last_yuanbao_at, W._PACE_PATH = old_int, old_at, old_pace
        self.assertGreaterEqual(dt, 0.4, "两次请求之间没有按最小间隔让路")

    def test_the_interval_is_held_inside_the_gate(self):
        """报告 §5.9：sleep 必须在闸**里面**。旧写法在闸外各算各的 gap，两进程
        configured=1.0 秒、实测间隔 0.0019 秒就一起发出去了。

        另一进程留下的时刻只能从盘上看（`_PACE_PATH`）——这一发把盘上戳写成
        "刚刚"，本进程内存里是 0.0，只有闸内读盘才会等。
        """
        events = []

        class _Gate:
            def __enter__(self):
                events.append("enter")
                return self

            def __exit__(self, *exc):
                events.append("exit")
                return False

        sess = _FakeSession()
        old = (W.yuanbao_gate, W.YUANBAO_MIN_INTERVAL, W._PACE_PATH, W._last_yuanbao_at,
               W.time.sleep)
        try:
            W.yuanbao_gate = _Gate()
            W.YUANBAO_MIN_INTERVAL = 5.0
            W._PACE_PATH = Path(tempfile.mkdtemp()) / "pace.json"
            W._last_yuanbao_at = 0.0
            W._write_pace_stamp(time.time())
            W.time.sleep = lambda secs: events.append("sleep")
            W._yuanbao_get(sess, "https://so.qq.com/isearch?tab=weixin_article&query=x")
        finally:
            (W.yuanbao_gate, W.YUANBAO_MIN_INTERVAL, W._PACE_PATH, W._last_yuanbao_at,
             W.time.sleep) = old
        self.assertIn("sleep", events, "另一个进程的时刻没被看见")
        self.assertLess(events.index("enter"), events.index("sleep"),
                        "间隔在进闸之前等——闸外 sleep 挡不住第二个进程")
        self.assertLess(events.index("sleep"), events.index("exit"))


class _WxResp:
    def __init__(self, html, url, status=200):
        self.text = html
        self.content = html.encode("utf-8")
        self.url = url
        self.status_code = status
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class TestWechatCaptchaGate(unittest.TestCase):
    """微信正文这道墙按**落地 URL** 判，不按正文关键词判。

    2026-11-23 实测：手机版 UA 取回的那份 wappoc_appmsgcaptcha 落地页，正文里
    「环境异常/验证/去验证/tcaptcha」一个都不出现（验证控件是脚本注入的），
    所以旧实现按正文关键词的分支从不命中，验证码门被误报成"未找到正文容器"。
    """

    CAPTCHA_URL = "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=x"
    # 真实落地页正文的压缩形态：只有壳文案，没有任何验证词。
    CAPTCHA_BODY = ('<html><body><div class="weui-msg"><div class="bd">'
                    '<div>视频</div><div>小程序</div><div>赞</div>'
                    '<div>在看</div></div></div></body></html>')
    ARTICLE_URL = "https://mp.weixin.qq.com/s?src=11&timestamp=1&ver=1"
    # 真实文章页里 js_content 的闭合 </div> 后面紧跟 <script>（extractor 的正则依赖
    # 这个页面形态），fixture 必须照实搭，不能直接 </body> 收尾。
    ARTICLE_BODY = ('<html><body><div id="js_content"><p>第一段正文</p>'
                    '<p>第二段正文</p></div>'
                    '<script>var biz="";</script></body></html>')

    def _read_with(self, html, landed_url, status=200):
        calls = {}

        def fake_get(url, **kw):
            calls["url"] = url
            calls["kw"] = kw
            return _WxResp(html, landed_url, status)

        old = W.requests.get
        try:
            W.requests.get = fake_get
            return W.read_article("https://mp.weixin.qq.com/s?src=11&original=1"), calls
        finally:
            W.requests.get = old

    def test_captcha_landing_is_named_as_captcha_not_missing_selector(self):
        (body, err), _ = self._read_with(self.CAPTCHA_BODY, self.CAPTCHA_URL)
        self.assertEqual("", body, "验证码门不该返回正文")
        self.assertIn("验证码门", err, "落地验证码页必须报成验证码门：%r" % err)
        self.assertNotIn("未找到正文容器", err,
                         "又退回老 bug：把验证码门误报成正文容器缺失")

    def test_the_body_really_carries_no_verification_word(self):
        """判据必须落在 URL 上——这条把"正文无验证词"这一实测前提钉住。"""
        for word in ("环境异常", "验证", "去验证", "tcaptcha", "js_content"):
            self.assertNotIn(word, self.CAPTCHA_BODY,
                             "fixture 里混进了 %s，判据就不再是 URL 了" % word)

    def test_healthy_article_still_reads_through(self):
        (body, err), _ = self._read_with(self.ARTICLE_BODY, self.ARTICLE_URL)
        self.assertEqual("", err, "正常文章页不该报错：%r" % err)
        self.assertIn("第一段正文", body)
        self.assertIn("第二段正文", body)

    def test_non_200_is_still_http_status(self):
        (_, err), _ = self._read_with(self.CAPTCHA_BODY, self.ARTICLE_URL, status=503)
        self.assertIn("HTTP 503", err, "状态码分支先于 URL 判据")

    def test_body_keyword_branch_is_only_a_fallback(self):
        """URL 不是验证码页、但正文确实带验证词时，兜底分支仍要认出来。"""
        (body, err), _ = self._read_with(
            "<html><body>当前环境异常，完成验证后即可继续访问</body></html>",
            self.ARTICLE_URL)
        self.assertEqual("", body)
        self.assertIn("验证页", err)

    def test_classifier_uses_landed_url_not_the_requested_one(self):
        """判据读 r.url（跟完重定向的落地），不是读传进来的原始 URL。"""
        (_, err), calls = self._read_with(self.CAPTCHA_BODY, self.CAPTCHA_URL)
        self.assertIn("验证码门", err)
        # 原始 URL 里没有 appmsgcaptcha；若实现误用入参判，就不会命中
        self.assertNotIn("appmsgcaptcha", calls["url"])


# ── 3.62.49 三档阶梯的离线驱动 ─────────────────────────────────────────────
NEXT_PAGE_URL = "https://so.qq.com/searchweb/api/search/next-page"
ISEARCH_URL = "https://so.qq.com/isearch?tab=weixin_article&query=x"
ARTICLE_URL = "https://mp.weixin.qq.com/s?__biz=MzA&idx=1"


def _dead_shape():
    """熔断形原文（2026-11-27 实测 112 字节）：cards 空，timings 里连 search 都没有。

    这一形必须读成「通道被短接」，不是「站内没这个词」——所以阶梯的默认桩就用它：
    两档 POST 都回熔断形，用例就能落到旧 GET 兜底那一支，GET 那批页型判据照旧逐枚有效。
    """
    return json.dumps({"ok": True, "cards": [], "hasMore": False, "uuid": "u-1",
                       "searchUuid": "u-1", "antispiderToken": "t-1",
                       "timings": {"antispider": 23}})


def _vm_vertical(title, link=None, account="公众号名称", summary="摘要内容",
                 publish_time="2026-11-26 09:00:00", pub_time=1764000000,
                 host="http://mp.weixin.qq.com"):
    """垂直档一张卡（cards[].data.vm 形）。

    title 外面裹上站点自己插的私有区高亮边界符 U+E40A/U+E40B——真响应 25 张里 23 张
    带，解析层不剥就把脏字符交付给下游（2026-11-27 yb64mark.py 现读）。
    """
    return {"data": {
        "vm": {"title": "\ue40a" + title + "\ue40b", "summary": summary,
               "authorName": account, "publishTime": publish_time,
               "jumpUrl": link if link is not None else
               "http://mp.weixin.qq.com/s?__biz=MzA&idx=" + str(pub_time),
               "host": host, "docId": "d", "imgUrl": "",
               "isIweixin": 1, "isWxmpTab": 1, "cardInfo": {"classId": "30010612"}},
        "item": {"jsonData": {"pub_time": pub_time, "doc_from": "q2q"}}}}


def _vm_plain(title, link=ARTICLE_URL, author="山东税务", publish_time="2026-09-16 17:31:10",
              content="摘要内容", host="https://www.qq.com"):
    """综合档一张卡（card30010608 形：h5Url/author/publishTime，不是 url/showname/date）。

    `host` 给门户域名：真页上非 mp 结果的 host 就是站点域名，只有 `h5Url` 才是文章
    直链——缺 h5Url 时把 host 当直链交付是错的（与 `_parse_vertical_cards` 撤掉 host
    回落同一条道理）。
    """
    return {"data": {"vm": {"title": title, "content": content, "author": author,
                            "publishTime": publish_time, "h5Url": link,
                            "host": host, "showname": "微信公众平台",
                            "sourceType": "wechat", "cardInfo": {"classId": "30010608"}}}}


def _days_ago_ts(days):
    """相对今天的 epoch 秒——时间窗判据不能钉死绝对日期，否则隔一日本身就红。"""
    return int(time.time()) - days * 86400


def _cards_payload(cards, search_ms=744, has_more=False):
    """把若干张卡包成一份取数响应；search_ms 是"上游检索真跑了"的那枚读数。"""
    return json.dumps({"ok": True, "cards": cards, "hasMore": has_more, "uuid": "u-2",
                       "searchUuid": "u-2", "antispiderToken": "t-2",
                       "timings": {"antispider": 20, "oas": 0, "search": search_ms}},
                      ensure_ascii=False)


def _wx_run(get_html="", get_url=ISEARCH_URL, get_status=200, vertical=None, plain=None,
            keyword="某词", size=3, gate_timeout=False, calls=None, **kw):
    """离线跑一遍 `search_wechat`：两枚闸内帮手一起替。

    `vertical`/`plain` 不给就是熔断形（这一档没拿到货）；给了就是这一档的真响应。
    `calls` 传一个列表，逐发填 `{"method","url","kwargs"}`——注意 approve 握手那一发
    也走 `_yuanbao_get`，按 URL 过滤。`DEAD_COOLDOWN` 归零，否则重发前要真空等 12 秒。
    """
    calls = calls if calls is not None else []
    old = (W._yuanbao_get, W._yuanbao_post, W.DEAD_COOLDOWN)

    def fake_get(sess, url, **kwargs):
        calls.append({"method": "GET", "url": url, "kwargs": kwargs})
        if gate_timeout:
            raise TimeoutError("等待元宝串行闸超过 0 秒")
        return _WxResp(get_html, get_url, get_status)

    def fake_post(sess, url, **kwargs):
        calls.append({"method": "POST", "url": url, "kwargs": kwargs})
        if gate_timeout:
            raise TimeoutError("等待元宝串行闸超过 0 秒")
        # 档位认请求体里的 sp.tab，不认第几发：垂直档短接后阶梯会冷却重发同一档，
        # 按计数分档就把综合档的响应喂给了垂直档解析器。
        raw = kwargs.get("data") or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        try:
            sp = (json.loads(raw.decode("utf-8")) or {}).get("sp") or {}
        except ValueError:
            sp = {}
        chosen = vertical if sp.get("tab") else plain
        return _WxResp(chosen if chosen is not None else _dead_shape(), NEXT_PAGE_URL)

    try:
        W._yuanbao_get = fake_get
        W._yuanbao_post = fake_post
        W.DEAD_COOLDOWN = 0.0
        return W.search_wechat(keyword, size=size, **kw)
    finally:
        W._yuanbao_get, W._yuanbao_post, W.DEAD_COOLDOWN = old


class _WxSession:
    """替身 Session：`_yuanbao_get`/`_yuanbao_post` 只用 headers.update、get、post 三件事。"""

    def __init__(self, resp):
        self.resp = resp
        self.headers = {}
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kw):
        self.get_calls.append(url)
        return self.resp

    def post(self, url, **kw):
        self.post_calls.append((url, kw))
        return self.resp


class TestWechatSearchZeroHit(unittest.TestCase):
    """元宝检索：零命中、登录墙、验证码墙与页面改版必须分开。"""

    # 2026-11-27 修报告 §5.3 之后：判「站内没货」只认站点自己的空结果文案
    # （SITE_EMPTY_MARK），结果容器不算证据。夹具把这句一并带上——真页面上
    # 容器与站点文案同时出现（chunk module 868170 的空结果组件）。
    ZERO_HIT_HTML = ('<html><body><div class="js-results">'
                     '<p>没有找到相关的微信公众号文章。</p>'
                     '<p>抱歉，没有找到相关网页</p></div></body></html>')
    LOGIN_HTML = ('<html><body><a data-x="linkid&quot;:&quot;login_page&quot;">'
                  '请登录后继续查看内容</a></body></html>')
    CAPTCHA_HTML = ('<html><head><script src="/static/antispider.min.js"></script></head>'
                    '<body>环境异常，请完成验证</body></html>')
    BROKEN_HTML = "<html><body> totally restructured, no blocks, no marker </body></html>"
    RESULT_HTML = ('<html><body><div class="js-results antispiderToken">'
                   '<a data-x="linkid&quot;:&quot;source&quot;"><span>财税小课堂</span>'
                   '<span>2天前</span></a><a href="https://mp.weixin.qq.com/s?k=1" '
                   'data-x="linkid&quot;:&quot;title&quot;">某词留抵退税问答</a>'
                   '<div class="sa-text">摘要提到验证码，但不是拦截页</div>'
                   '</div></body></html>')

    def _search_with(self, html, url=ISEARCH_URL, status=200):
        # 两档 POST 默认回熔断形 ⇒ 阶梯落到 GET 兜底，这一族钉的还是 GET 页型
        return _wx_run(get_html=html, get_url=url, get_status=status)

    def test_genuine_zero_hit_is_clean_not_a_failed_channel(self):
        r = self._search_with(self.ZERO_HIT_HTML)
        self.assertEqual(0, r["total"])
        self.assertFalse(r.get("_error"))
        self.assertEqual([], r["results"])
        self.assertTrue(r.get("_zero_hit"))
        self.assertFalse(r.get("_fetch_failed"))

    def test_rate_limit_page_is_a_fetch_failure_not_a_login_wall(self):
        """「请登录后继续查看内容」是站点自己的限流标题，不是账号墙。

        逐字来自前端 chunk `getRateLimitTitle`：`case"429_outer":return"请登录后继续
        查看内容"`，渲染器 `WebLoginRequiredPlaceholder` 只在 `allowLogin` 时才给登录
        入口。旧判据把它读成"登录墙"，于是限流窗口被交付成"你得登录"——本层从未有
        登录态可言，这一句把读者和使用方一起带偏（报告 §5.1 的误伤点）。
        """
        r = self._search_with(self.LOGIN_HTML)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("限流", r["_error"])
        self.assertIn("429_outer", r["_error"])
        self.assertNotIn("需要登录", r["_error"])

    def test_captcha_wall_is_a_fetch_failure_not_zero_hit(self):
        r = self._search_with(self.CAPTCHA_HTML)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("验证或拦截页", r["_error"])

    def test_antispider_landing_url_is_a_fetch_failure(self):
        r = self._search_with(self.BROKEN_HTML,
                              url="https://so.qq.com/antispider/?query=x")
        self.assertTrue(r.get("_fetch_failed"))
        self.assertIn("跳转到反爬或验证页", r["_error"])

    def test_structurally_broken_page_still_reports_error(self):
        r = self._search_with(self.BROKEN_HTML)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("页面结构可能已变", r["_error"])

    def test_http_failure_is_not_zero_hit(self):
        r = self._search_with(self.ZERO_HIT_HTML, status=503)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("HTTP 503", r["_error"])

    def test_result_page_wins_over_keywords_and_antispider_token(self):
        r = self._search_with(self.RESULT_HTML)
        self.assertEqual(1, r["total"])
        self.assertFalse(r.get("_error"))
        self.assertIn("留抵退税问答", r["results"][0]["title"])

    def test_zero_result_markers_are_discriminating(self):
        self.assertEqual(("js-results", "result-card"), W.ZERO_RESULT_MARKS)
        self.assertTrue(any(mark in self.ZERO_HIT_HTML for mark in W.ZERO_RESULT_MARKS))
        self.assertFalse(any(mark in self.BROKEN_HTML for mark in W.ZERO_RESULT_MARKS))

    def test_only_exact_wechat_article_hosts_are_accepted(self):
        accepted = ("https://mp.weixin.qq.com/s?src=11",
                    "http://mp.weixin.qq.com/s?src=11")
        rejected = ("https://mp.weixin.qq.com.evil.test/s?src=11",
                    "https://mp.weixin.qq.com:443/s?src=11",
                    "https://user@mp.weixin.qq.com/s?src=11",
                    "ftp://mp.weixin.qq.com/s?src=11",
                    "/link?url=x", "")
        for link in accepted:
            self.assertEqual(link, W._safe_mp_link(link))
        for link in rejected:
            self.assertEqual("", W._safe_mp_link(link), link)

    def test_dates_and_accounts_do_not_shift_to_the_previous_card(self):
        html = ('<a data-x="linkid&quot;:&quot;source&quot;"><span>第一账号</span>'
                '<span>2026-11-20</span></a>'
                '<a href="https://mp.weixin.qq.com/s?k=1" '
                'data-x="linkid&quot;:&quot;title&quot;">第一篇</a>'
                '<a data-x="linkid&quot;:&quot;source&quot;"><span>第二账号</span>'
                '<span>3天前</span></a>'
                '<a href="https://mp.weixin.qq.com/s?k=2" '
                'data-x="linkid&quot;:&quot;title&quot;">第二篇</a>')
        rows = W._parse_results(html)
        self.assertEqual([("第一账号", "2026-11-20", False),
                          ("第二账号", "3天前", True)],
                         [(r["account"], r["date_text"], r["date_approx"]) for r in rows])

    def test_all_invalid_links_are_failure_not_a_delivered_zero_hit(self):
        r = self._search_with('<a href="https://example.test/a" '
                              'data-x="linkid&quot;:&quot;title&quot;">某词题名</a>')
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("没有一条有效的微信文章直链", r["_error"])


class TestWechatEmptyBodyIsItsOwnShape(unittest.TestCase):
    """HTTP 200 / 0 字节是空响应，不能改称零命中或页面改版。"""

    def _search_with(self, html):
        return _wx_run(get_html=html)

    def test_zero_byte_page_says_the_channel_gave_nothing(self):
        r = self._search_with("")
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_fetch_failed"), "0 字节是取数失败，不是 0 命中")
        self.assertNotIn("0 命中", r["_error"])
        self.assertIn("0 字节", r["_error"])

    def test_the_empty_body_sentence_does_not_blame_relayout(self):
        """断供那一发不能同时说「可能改版」——那是把读者往错方向带。"""
        r = self._search_with("")
        self.assertNotIn("改版", r["_error"])
        self.assertNotIn("验证页", r["_error"])

    def test_three_shapes_are_three_sentences(self):
        """0 命中 / 0 字节 / 有内容但认不出结构——三件事三句话，两两不同。"""
        zero = self._search_with(TestWechatSearchZeroHit.ZERO_HIT_HTML)
        empty = self._search_with("")
        broken = self._search_with(TestWechatSearchZeroHit.BROKEN_HTML)
        self.assertFalse(zero.get("_error"), "真 0 命中必须不带说明")
        self.assertTrue(zero.get("_zero_hit"))
        self.assertTrue(empty.get("_error"))
        self.assertTrue(broken.get("_error"))
        self.assertNotEqual(empty["_error"], broken["_error"],
                            "0 字节与有内容认不出被写成同一句，读者就分不开成因")
        self.assertIn("页面结构可能已变", broken["_error"],
                      "有内容却认不出结构那一支才该提改版")

    def test_a_nonempty_marker_free_page_still_reports_relayout(self):
        """有正文、无结果、无登录或验证锚，仍走页面结构可能已变。"""
        r = self._search_with("<html><body>一段与检索无关的门户页</body></html>")
        self.assertIn("页面结构可能已变", r["_error"])


class TestWechatLadderShapes(unittest.TestCase):
    """3.62.49 主路（两档 POST）自己的形状：交付、短接、推词兜底、白名单、时间筛。

    这一族是报告 §7 那句「测试没跟上主路」的正面补：GET 那批钉的是兜底档，
    垂直档/综合档/熔断/兜底旗标的判据在旧测试里一枚都没有。
    """

    KEYWORD = "研发费用加计扣除"

    def test_vertical_tier_delivers_and_strips_highlight(self):
        body = _cards_payload([_vm_vertical("研发费用加计扣除的比例", pub_time=1)])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3)
        self.assertEqual(1, r["total"])
        item = r["results"][0]
        self.assertEqual("研发费用加计扣除的比例", item["title"],
                         "站点插的私有区高亮边界符必须剥掉，否则脏字符交付给下游")
        self.assertNotIn("\ue40a", json.dumps(r, ensure_ascii=False))
        self.assertTrue(item["url"].startswith("http://mp.weixin.qq.com/s?"))
        self.assertEqual("公众号名称", item["account"])
        self.assertEqual("2026-11-26 09:00:00", item["date"])
        self.assertFalse(r.get("_error"))
        self.assertIn("只出一页", r["_caveat"], "hasMore=False 这件事要告诉读者")

    def test_plain_tier_reads_h5url_author_publishTime(self):
        """综合档卡片的键名与垂直档不同（h5Url/author/publishTime）——照垂直档取就全空。"""
        body = _cards_payload([_vm_plain("增值税即征即退的适用范围")])
        r = _wx_run(plain=body, keyword="增值税 即征即退", size=3)
        self.assertEqual(1, r["total"])
        item = r["results"][0]
        self.assertEqual(ARTICLE_URL, item["url"])
        self.assertEqual("山东税务", item["account"], "取成 showname 就是「微信公众平台」")
        self.assertEqual("2026-09-16", item["date"], "取成 date 就丢日期")
        self.assertIn("改用综合档", r["_caveat"])

    def test_dead_channel_is_a_failure_not_a_zero_hit(self):
        """两档都短接、GET 也只给骨架壳：报通道故障，绝不报「站内没这个词」。"""
        r = _wx_run(get_html=TestWechatSearchZeroHit.BROKEN_HTML, keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("短接", r["_error"])

    def test_empty_batch_is_not_evidence_of_nothing_on_site(self):
        """报告 §5.4：上游真跑了（search=744ms）却回 0 张卡——这不是站内没货的证据。

        旧写法拿「垂直档回 0 张卡」当空证据，后两档再失败就交付成一份干净的零命中，
        通道故障被伪装成「这个词站里没有」。
        """
        empty = json.dumps({"ok": True, "cards": [], "hasMore": False,
                            "timings": {"antispider": 20, "search": 744}})
        r = _wx_run(vertical=empty, plain=empty,
                    get_html=TestWechatSearchZeroHit.BROKEN_HTML, keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"), r)
        self.assertFalse(r.get("_zero_hit"), "0 张卡不许判成零命中")
        self.assertIn("0 张卡", r["_error"], r["_error"])

    def test_recommendation_batch_is_a_zero_hit_with_its_reason(self):
        """整批不含检索词的分词＝站点的推词兜底：报零命中，并把判据写在 _caveat 里。"""
        body = _cards_payload([_vm_vertical("生产企业免抵退申报操作流程", pub_time=1)])
        r = _wx_run(vertical=body, get_html='<p>抱歉，没有找到相关网页</p>',
                    keyword=self.KEYWORD)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"), r.get("_error"))
        self.assertFalse(r.get("_fetch_failed"))
        self.assertIn("推词兜底", r["_caveat"])

    def test_invalid_link_is_a_failure_not_a_zero_hit(self):
        """报告 §5.2：站点给了货但链形不对，是通道故障，不是站内没这个词。"""
        body = _cards_payload([_vm_vertical("研发费用加计扣除的比例",
                                           link="https://example.test/a")])
        r = _wx_run(vertical=body, get_html=TestWechatSearchZeroHit.BROKEN_HTML,
                    keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"), r.get("_error"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("不是 mp.weixin.qq.com 文章直链", r["_error"])

    def test_a_missing_jumpUrl_does_not_fall_back_to_the_channel_host(self):
        """报告 §5.2 的第二半：`vm.host` 是频道首页，它自己也过 mp 白名单。

        2026-11-27 注入证伪：把 `or vm.get("host")` 塞回取值链，上一枚用例照样绿——
        夹具的 host 正是 `http://mp.weixin.qq.com`，白名单认它。缺 jumpUrl 的卡只能
        记进 bad_link：把首页当"直链"交回去，读者点了什么文章都进不去。
        """
        body = _cards_payload([_vm_vertical("研发费用加计扣除的比例", link="",
                                           host="http://mp.weixin.qq.com")])
        r = _wx_run(vertical=body, get_html=TestWechatSearchZeroHit.BROKEN_HTML,
                    keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"), r.get("_error"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("不是 mp.weixin.qq.com 文章直链", r["_error"])
        for item in r["results"]:
            self.assertNotEqual("http://mp.weixin.qq.com", item["url"],
                                "频道首页被当成文章直链交付了")

    def test_first_card_dead_second_card_delivered(self):
        """报告 §5.7 验收：第一条无效、第二条有效、size=1 ⇒ 交付第二条。"""
        body = _cards_payload([_vm_vertical("研发费用加计扣除的口径", link="http://evil.test/x"),
                              _vm_vertical("研发费用加计扣除的比例", pub_time=2)])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=1)
        self.assertEqual(1, r["total"])
        self.assertEqual("研发费用加计扣除的比例", r["results"][0]["title"])
        self.assertIn("另有 1 张卡被微信直链白名单挡掉", r["_caveat"])

    def test_time_filter_reaches_both_post_tiers(self):
        """报告 §5.6：时间筛只给垂直档，落到综合档就悄悄丢了读者的限定。"""
        calls = []
        _wx_run(keyword=self.KEYWORD, time_filter="1m", calls=calls)
        posts = [c for c in calls if c["method"] == "POST"]
        self.assertTrue(posts)
        for entry in posts:
            sp = json.loads(entry["kwargs"]["data"].decode("utf-8"))["sp"]
            self.assertEqual("1m", sp.get("timeFilter"), entry["kwargs"]["data"][:120])
        plain = json.loads(posts[-1]["kwargs"]["data"].decode("utf-8"))["sp"]
        self.assertNotIn("tab", plain, "最后一发是综合档，不该带垂直档的 tab")

    def test_the_vertical_tier_is_filtered_locally_by_the_window(self):
        """报告 §5.6 定性：垂直档不执行 `sp.timeFilter`，本地必须按发布日筛。

        yb76tf/yb78tf3 真网各两发对照：同一词带 `timeFilter:"1m"` 与不带，回的是
        同一批卡、同一顺序（25 张／28 张逐枚相同，复跑一致）。参数照发、站点照忽略，
        所以这一档交付前由我们筛——并且要说清是本地筛的，不能让读者以为是站点筛的。
        """
        body = _cards_payload([_vm_vertical("研发费用加计扣除的新政", pub_time=_days_ago_ts(1)),
                               _vm_vertical("研发费用加计扣除的旧口径", pub_time=_days_ago_ts(200))])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3, time_filter="1m")
        self.assertEqual(1, r["total"], r.get("_error"))
        self.assertEqual("研发费用加计扣除的新政", r["results"][0]["title"])
        self.assertIn("垂直档不执行站点时间筛", r["_caveat"], r["_caveat"])
        self.assertIn("本地筛近 30 天：2 张里留 1 张", r["_caveat"], r["_caveat"])

    def test_a_window_that_clears_every_item_is_a_zero_hit_not_a_failure(self):
        """站内有货、只是都不在窗内：这是零命中（带成因），不能报成通道坏了。

        这一支绝不能落进「整批推词兜底」那一路，否则时间窗把「站内没这个词」这件
        真没发生的事伪造出来；也不能落进失败信封，否则读者以为站点连不上。
        """
        body = _cards_payload([_vm_vertical("研发费用加计扣除的旧口径一",
                                            pub_time=_days_ago_ts(200)),
                               _vm_vertical("研发费用加计扣除的旧口径二",
                                            pub_time=_days_ago_ts(300))])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3, time_filter="1m")
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"), r)
        self.assertFalse(r.get("_fetch_failed"), "窗内清空是筛选的正常结局，不是取数失败")
        self.assertIn("都不在所选时间窗内", r["_caveat"], r["_caveat"])

    def test_an_item_without_a_readable_date_is_counted_not_delivered(self):
        """日期读不出来的条目宁可少给，但那个数必须告诉读者。"""
        body = _cards_payload([_vm_vertical("研发费用加计扣除的新政", pub_time=_days_ago_ts(2)),
                               _vm_vertical("研发费用加计扣除的无日期", publish_time="",
                                            pub_time="not-a-number")])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3, time_filter="1m")
        self.assertEqual(1, r["total"], r.get("_error"))
        self.assertIn("读不出发布日期未计入", r["_caveat"], r["_caveat"])

    def test_the_window_note_stays_out_when_nothing_was_dropped(self):
        """全批都在窗内时不记账——「2 张里留 2 张」这种话是给读者的噪声。"""
        body = _cards_payload([_vm_vertical("研发费用加计扣除的新政", pub_time=_days_ago_ts(2))])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3, time_filter="1m")
        self.assertEqual(1, r["total"], r.get("_error"))
        self.assertNotIn("本地筛", r.get("_caveat", ""), r.get("_caveat"))

    def test_the_plain_tier_is_window_filtered_too(self):
        """综合档站点自己会筛（probe58tf 那组），但 yb77tf2 那轮没复现——不能当保证，
        交付前同样再过一遍；这一档不能断言「站点不执行」，只能说本地复核了窗口。"""
        plain = _cards_payload([_vm_plain("研发费用加计扣除的旧闻",
                                          publish_time="2025-09-01 10:00:00",
                                          link="http://mp.weixin.qq.com/s?__biz=MzA&idx=9")])
        r = _wx_run(plain=plain, keyword=self.KEYWORD, size=3, time_filter="1y")
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"), r)
        self.assertFalse(r.get("_fetch_failed"))
        self.assertIn("综合档", r["_caveat"], r["_caveat"])
        self.assertIn("时间窗", r["_caveat"], r["_caveat"])

    def test_the_window_filter_falls_back_to_the_date_string(self):
        """`pub_time` 给不成整数时（站点换成串或给了 0），窗口按日期串判，不能整批判空。"""
        body = _cards_payload([_vm_vertical("研发费用加计扣除的新政",
                                            publish_time=time.strftime(
                                                "%Y-%m-%d 09:00:00",
                                                time.localtime(time.time() - 86400)),
                                            pub_time="1795654800")])
        r = _wx_run(vertical=body, keyword=self.KEYWORD, size=3, time_filter="1m")
        self.assertEqual(1, r["total"], r.get("_error"))
        self.assertNotIn("未计入", r.get("_caveat", ""), r.get("_caveat"))

    def test_vertical_tier_sends_the_original_uri_header(self):
        """档位由 `sp.tab` 与 `x-original-uri` 两枚一起决定，缺一回 0 张卡（实测）。"""
        calls = []
        _wx_run(keyword=self.KEYWORD, calls=calls)
        first = [c for c in calls if c["method"] == "POST"][0]
        self.assertEqual(NEXT_PAGE_URL, first["url"])
        headers = first["kwargs"]["headers"]
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertTrue(headers["x-original-uri"].startswith("/iweixin?tab=weixin_article&query="),
                        headers["x-original-uri"])
        self.assertNotIn("x-original-uri",
                         [c for c in calls if c["method"] == "POST"][-1]["kwargs"]["headers"],
                         "综合档不发这枚头")

    def test_truncated_response_is_refused(self):
        """报告 §6.5：被截断的 JSON 不能当成一份完整清单用。"""
        big = _cards_payload([_vm_vertical("研发费用加计扣除" + "长" * 400)])
        with mock.patch.object(W, "MAX_BODY_BYTES", 128):
            r = _wx_run(vertical=big, plain=big, keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertIn("上限并被截断", r["_error"], r["_error"])

    def test_a_result_container_alone_is_not_evidence_of_an_empty_site(self):
        """报告 §5.3：`js-results`/`result-card` 只是容器，客户端骨架页同样带壳。

        把这一支读成 site-empty，通道故障就被交付成一份干净的「站内没这个词」。
        正面证据只有两种：站点自己的空结果文案，或整批推词兜底。
        2026-11-27 注入证伪：这一枚改回 "site-empty" 时全族没报红。
        """
        shell = ('<html><body><div class="js-results">'
                 '<div class="result-card"></div></div></body></html>')
        r = _wx_run(get_html=shell, keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"), r)
        self.assertFalse(r.get("_zero_hit"), "有结果容器不等于站里没货")
        self.assertIn("一张卡都没解析出来", r["_error"], r["_error"])

    def test_finalize_filters_dead_links_before_truncating(self):
        """报告 §5.7 的合同要由 `_finalize` 自己钉住。

        阶梯用例测不到这一枚：垂直档已在上游把无链卡剔掉，交下来的清单本来就
        全有链。2026-11-27 注入证伪把顺序倒回「先截 size 再滤」，全绿。GET 兜底
        那一路会把带 `_error` 的无链条目直接交给 `_finalize`，这条合同必须有尺。
        """
        dead = {"title": "研发费用加计扣除的口径", "url": "", "date": "", "account": "",
                "summary": "", "date_text": "", "date_approx": False, "timestamp": None,
                "_error": "元宝结果链接不是 mp.weixin.qq.com 文章直链"}
        alive = {"title": "研发费用加计扣除的比例",
                 "url": "http://mp.weixin.qq.com/s?__biz=MzA&idx=2",
                 "date": "2026-11-25", "account": "公众号名称", "summary": "摘要",
                 "date_text": "2026-11-25 09:00:00", "date_approx": False,
                 "timestamp": 2}
        out = W._finalize("研发费用加计扣除", [dead, alive], 1, False)
        self.assertEqual(1, out["total"], out.get("_error"))
        self.assertEqual("研发费用加计扣除的比例", out["results"][0]["title"],
                         "第一条无效就把整轮判成「一条有效直链都没有」，把能交付的第二条挡掉了")
        self.assertNotIn("_error", out)

    def test_gate_timeout_becomes_an_envelope(self):
        """报告 §5.10：串行闸的 TimeoutError 不许穿透公共函数。"""
        r = _wx_run(keyword=self.KEYWORD, gate_timeout=True)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("串行闸", r["_error"], r["_error"])

    def test_bad_arguments_are_envelopes_not_exceptions(self):
        """报告 §6.4：size="10"/1.5/True 都该报错回来，不该抛 TypeError。"""
        for bad in ("10", 1.5, True, 0):
            calls = []
            r = _wx_run(keyword=self.KEYWORD, size=bad, calls=calls)
            self.assertIn("size 必须是正整数", r["_error"], repr(bad))
            self.assertEqual([], calls, "参数没过校验就不该发任何请求")
        calls = []
        r = _wx_run(keyword=self.KEYWORD, time_filter="1h", calls=calls)
        self.assertIn("time_filter 只认", r["_error"])
        self.assertEqual([], calls)

    def test_non_numeric_timings_do_not_crash_the_shape_check(self):
        """站点把 timings.search 给成字符串甚至缺失时不能崩在判据里（报告 §6.4）。"""
        shape = json.dumps({"ok": True, "cards": [], "hasMore": False,
                            "timings": {"search": "19"}})
        r = _wx_run(vertical=shape, plain=shape,
                    get_html=TestWechatSearchZeroHit.BROKEN_HTML, keyword=self.KEYWORD)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertIn("短接", r["_error"])

    def test_session_is_closed_on_every_exit(self):
        """报告 §6.2：一轮检索最多五次 HTTP，Session 不能留在进程里。"""
        closed = []

        class _ClosingSession:
            def __init__(self):
                self.headers = {}

            def get(self, url, **kw):
                return _WxResp("", ISEARCH_URL)

            def post(self, url, **kw):
                return _WxResp(_dead_shape(), NEXT_PAGE_URL)

            def close(self):
                closed.append(True)

        old = W.requests.Session
        try:
            W.requests.Session = _ClosingSession
            # 闸与频次账绕开：这一枚只钉「关没关」
            W.search_wechat("研发费用加计扣除", size=2)
        finally:
            W.requests.Session = old
        self.assertEqual([True], closed, "Session 没被关掉")


class TestWechatReadArticleUrlBoundary(unittest.TestCase):
    """报告 §5.1：正文那一发的 URL 边界——离线复现里 `http://127.0.0.1/private` 真的发了请求。"""

    def _capture(self):
        calls = []

        def fake_get(url, **kw):
            calls.append((url, kw))
            return _WxResp('<div id="js_content"><p>正文</p></div>', url)

        return calls, mock.patch.object(W.requests, "get", fake_get)

    def test_a_local_url_never_reaches_the_network(self):
        calls, patcher = self._capture()
        with patcher:
            body, error = W.read_article("http://127.0.0.1/private")
        self.assertEqual([], calls, "白名单之外的 URL 必须在出网之前就拒掉")
        self.assertEqual("", body)
        self.assertIn("已拒绝读取", error)

    def test_lookalike_host_port_and_userinfo_are_refused(self):
        calls, patcher = self._capture()
        for link in ("https://mp.weixin.qq.com.evil.test/s?x=1",
                     "https://mp.weixin.qq.com:443/s?x=1",
                     "https://user@mp.weixin.qq.com/s?x=1",
                     "ftp://mp.weixin.qq.com/s?x=1", "/s?x=1", ""):
            with patcher:
                body, error = W.read_article(link)
            self.assertEqual("", body, link)
            self.assertIn("已拒绝读取", error, link)
        self.assertEqual([], calls, "六枚非法 URL 一枚都不该出网")

    def test_a_cross_host_redirect_is_not_followed(self):
        """被 302 带去别的主机＝落地页不再是微信文章，拒绝读，不跟。"""
        calls = []

        def fake_get(url, **kw):
            calls.append((url, kw))
            resp = _WxResp("", url, status=302)
            resp.headers = {"Location": "https://evil.test/landing"}
            return resp

        with mock.patch.object(W.requests, "get", fake_get):
            body, error = W.read_article(ARTICLE_URL)
        self.assertEqual(1, len(calls))
        self.assertEqual(False, calls[0][1]["allow_redirects"], "必须自己攥住重定向")
        self.assertEqual("", body)
        self.assertIn("不跟随", error)
        self.assertIn("evil.test/landing", error)

    def test_a_same_host_upgrade_is_followed(self):
        """真网形状：http 版文章地址被 301 升级到同主机 https，要跟上去。

        2026-11-27 端到端实测（yb74e2e.py）：检索交付 `http://mp.weixin.qq.com/s?…`，
        微信 301 到 `https://mp.weixin.qq.com/s?…`。一律拒跳会让正文这一路全断，
        而拒跳真正要防的是被带去**别的**主机。
        """
        calls = []

        def fake_get(url, **kw):
            calls.append((url, kw))
            if len(calls) == 1:
                resp = _WxResp("", url, status=301)
                resp.headers = {"Location": url.replace("http://", "https://")}
                resp.closed = False
                return resp
            return _WxResp('<div id="js_content"><p>升级后的正文</p></div>'
                           '<script>var biz="";</script>', url)

        with mock.patch.object(W.requests, "get", fake_get):
            body, error = W.read_article("http://mp.weixin.qq.com/s?__biz=MzA&idx=1")
        self.assertEqual("", error)
        self.assertEqual("升级后的正文", body)
        self.assertEqual(2, len(calls), "只该跟一跳")
        self.assertTrue(calls[1][0].startswith("https://mp.weixin.qq.com/s"))
        self.assertEqual(False, calls[0][1]["allow_redirects"], "仍要自己攥住跳转")

    def test_a_redirect_loop_is_capped(self):
        """同主机互跳不能无界跟随：到上限就报失败，不发第 N+1 发。"""
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            resp = _WxResp("", url, status=302)
            resp.headers = {"Location": url + "&bump=%d" % len(calls)}
            return resp

        with mock.patch.object(W.requests, "get", fake_get):
            body, error = W.read_article(ARTICLE_URL)
        self.assertEqual("", body)
        self.assertIn("跳转次数超限", error)
        self.assertEqual(W.MAX_REDIRECT_HOPS + 1, len(calls))

    def test_a_relative_location_stays_on_wechat(self):
        """Location 是相对路径时按当前地址解析，仍然只有微信主机能过白名单。"""
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if len(calls) == 1:
                resp = _WxResp("", url, status=302)
                resp.headers = {"Location": "/mp/wappoc_appmsgcaptcha?poc_token=x"}
                return resp
            return _WxResp('<div id="js_content"><p>过验证后的正文</p></div>', url)

        with mock.patch.object(W.requests, "get", fake_get):
            body, error = W.read_article(ARTICLE_URL)
        self.assertIn("mp.weixin.qq.com/mp/wappoc_appmsgcaptcha", calls[1])
        self.assertIn("验证码门", error)
        self.assertEqual("", body)

    def test_the_body_is_size_capped(self):
        huge = '<div id="js_content">' + "<p>正文很长</p>" * 400 + "</div>"

        def fake_get(url, **kw):
            return _WxResp(huge, url)

        with mock.patch.object(W.requests, "get", fake_get), \
             mock.patch.object(W, "MAX_BODY_BYTES", 256):
            body, error = W.read_article(ARTICLE_URL)
        self.assertEqual("", body)
        self.assertIn("上限并被截断", error)

    def test_the_response_is_closed(self):
        resp = _WxResp('<div id="js_content"><p>正文</p></div>', ARTICLE_URL)
        with mock.patch.object(W.requests, "get", lambda url, **kw: resp):
            W.read_article(ARTICLE_URL)
        self.assertTrue(resp.closed, "响应没关掉")


class _NpcResp:
    """够用的 NPC 响应替身：HTTP 永远 200，业务状态只活在 JSON 里。"""

    def __init__(self, payload):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.content = payload.encode("utf-8")
        self.text = payload

    def raise_for_status(self):
        return None

    def json(self):
        import json as _json
        return _json.loads(self.text)


class TestNpcAppErrorIsNotZeroHits(unittest.TestCase):
    """NPC 出错时回 HTTP 200 + {"msg":"系统异常","code":500}，不能读成"0 条命中"。

    2026-11-23 实测的正常信封是 {"total":36,"rows":[…],"code":200,"msg":"查询成功"}
    ——**健康响应自己也带 code/msg**，所以判据只能是"code 存在且不是 200"，
    不能是"带 code 就算错"，否则会把每一次正常检索都拦掉。
    """

    def _search_with(self, payload):
        import tax_search as TS
        old = TS._request
        try:
            TS._request = lambda method, url, **kw: _NpcResp(payload)
            return TS.search_tax("增值税", scope="title", search_type=2, size=5)
        finally:
            TS._request = old

    def test_business_error_raises_instead_of_empty_result(self):
        for payload, why in (
            ('{"msg":"系统异常","code":500}', "载荷字段名错"),
            ('{"msg":"Request method \'GET\' not supported","code":500}', "方法不对"),
            ('{"msg":"Content type \'x\' not supported","code":500}', "Content-Type 不对"),
        ):
            with self.subTest(why):
                try:
                    r = self._search_with(payload)
                except RuntimeError as e:
                    self.assertIn("业务失败", str(e), why)
                    self.assertIn("没有命中", str(e),
                                  "报错要明说这不是空结果，免得下游当空答：%s" % why)
                    continue
                self.fail("应用层错误被静默读成结果了（%s）：%r" % (why, r.get("total")))

    def test_healthy_envelope_still_passes(self):
        """控制组：真实信封带 code=200，守卫必须放行——这条防止判据写反。"""
        r = self._search_with(
            '{"total":36,"code":200,"msg":"查询成功",'
            '"rows":[{"bbbs":"x1","flfgname":"中华人民共和国增值税法","sxx":3}]}')
        self.assertEqual(36, r["total"])
        self.assertEqual(1, len(r["results"]))

    def test_string_code_200_does_not_false_alarm(self):
        """code 若是 "200" 字符串形态，归一化后仍算成功，不许发假警。"""
        r = self._search_with('{"total":12,"code":"200","msg":"查询成功","rows":[]}')
        self.assertEqual(12, r["total"])

    def test_legacy_envelope_without_code_key_passes(self):
        """老式信封没有 code 键：照旧放行，不误伤。"""
        r = self._search_with('{"total":7,"rows":[]}')
        self.assertEqual(7, r["total"])

    def test_code_zero_is_not_treated_as_success(self):
        """0 是 falsy：用 is not None 判，不能写成 if code and code != 200。"""
        with self.assertRaises(RuntimeError):
            self._search_with('{"total":9,"code":0,"msg":"x"}')

    def test_genuine_zero_hits_stays_a_normal_answer(self):
        """真 0 条（code=200 + total=0）绝不能报错——否则"查无此法"会被说成接口坏了。"""
        r = self._search_with('{"total":0,"rows":[],"code":200,"msg":"查询成功"}')
        self.assertEqual(0, r["total"])
        self.assertEqual([], r["results"])


class _NpcEnvelopeResp:
    """一枚够用的 NPC 响应替身：HTTP 永远 200，业务状态只活在 JSON 里。"""

    def __init__(self, payload):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.text = payload
        self.content = payload.encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)


class TestNpcSharedBusinessGuard(unittest.TestCase):
    """判据只在 tax_http 一处，检索／详情／下载三条路共用它。

    三条路各抄一份正是本仓反复踩的"三处重复必漂移"，也是 short_reason 当初
    要收进 tax_http 的理由。这里既验判据本身，也验两条后接的路确实在用它。
    实测信封（2026-11-23 现拉）：检索正常 {"total":36,"rows":[…],"code":200,
    "msg":"查询成功"}；详情正常 {"msg":"操作成功","code":200,"data":{…}}；
    下载正常 {"msg":"操作成功","code":200,"data":{"urlIn":…,"url":…}}；
    三者出错都是 {"msg":"系统异常","code":500} 而 HTTP 仍 200。
    """

    def test_helper_truth_table(self):
        for payload, should_flag in (
            ({"code": 200, "msg": "查询成功"}, False),
            ({"code": 500, "msg": "系统异常"}, True),
            ({"code": "200"}, False),          # 字符串 200 不得发假警
            ({"code": "500"}, True),
            ({"code": 0, "msg": "x"}, True),   # 0 是 falsy，不能写成 if code and ...
            ({"msg": "没有 code 键"}, False),
            ({}, False),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(should_flag,
                                 tax_http.npc_business_error(payload) is not None)

    def test_helper_tolerates_non_dict(self):
        """接口哪天回个 list／字符串／None，判据不能自己先炸。"""
        for bad in ([], "text", None, 5):
            with self.subTest(value=bad):
                self.assertIsNone(tax_http.npc_business_error(bad))

    def test_error_message_says_it_is_not_an_empty_result(self):
        reason = tax_http.npc_business_error({"code": 500, "msg": "系统异常"})
        self.assertIn("业务失败", reason)
        self.assertIn("没有命中", reason)

    def _detail_call(self, payload, tag):
        """用一次性 bbbs_id 走详情路。

        id 必须每次不同：fetch_detail 命中缓存就直接返回、根本不碰 _request，
        固定 id 会让上一轮（尤其是注入变异那一轮）留下的缓存条目冒充本轮结果，
        测出来的红绿与实现无关。
        """
        old = DT._request
        try:
            DT._request = lambda url, **kw: _NpcEnvelopeResp(payload)
            return DT.fetch_detail("SHARED-%s-%s" % (tag, uuid.uuid4().hex[:12]))
        finally:
            DT._request = old

    def test_detail_business_error_raises_not_empty_title(self):
        """详情出错时旧行为是 title=''，再被 preview_law 翻成 ValueError("Law not found")。"""
        try:
            d = self._detail_call('{"msg":"系统异常","code":500}', "ERR")
        except RuntimeError as e:
            self.assertIn("业务失败", str(e))
            return
        self.fail("详情错误信封被静默读成空标题了：%r" % d.get("title"))

    def test_detail_healthy_envelope_still_parses(self):
        d = self._detail_call(
            '{"msg":"操作成功","code":200,'
            '"data":{"title":"中华人民共和国增值税法","sxx":3}}', "OK")
        self.assertEqual("中华人民共和国增值税法", d["title"])

    def test_empty_detail_is_not_cached(self):
        """取不到就不落缓存：一次抖动被钉住整个 TTL 后，每轮都回放空壳、不再重试。"""
        bbbs = "SHARED-NOCACHE-" + uuid.uuid4().hex[:12]
        old = DT._request
        try:
            DT._request = lambda url, **kw: _NpcEnvelopeResp(
                '{"msg":"操作成功","code":200,"data":{"title":"","sxx":0}}')
            first = DT.fetch_detail(bbbs)
            self.assertEqual("", first["title"])
            self.assertFalse(first.get("_from_cache"), "空结果不该进缓存")
            # 换成健康载荷再取：若空壳被缓存了，这里会拿到缓存的空标题而不是新数据
            DT._request = lambda url, **kw: _NpcEnvelopeResp(
                '{"msg":"操作成功","code":200,"data":{"title":"中华人民共和国增值税法","sxx":3}}')
            again = DT.fetch_detail(bbbs)
        finally:
            DT._request = old
        self.assertEqual("中华人民共和国增值税法", again["title"],
                         "空标题被缓存住了：一次取空会回放整个 TTL")

    def test_download_business_error_raises_not_none(self):
        old = DT._request
        try:
            DT._request = lambda url, **kw: _NpcEnvelopeResp('{"msg":"系统异常","code":500}')
            with self.assertRaises(RuntimeError):
                DT.get_download_url("SHARED-DL")
        finally:
            DT._request = old

    def test_download_genuine_no_file_still_returns_none(self):
        """真没有该格式附件（code=200 而 data 里无 url）必须照旧回 None，不许报错。"""
        old = DT._request
        try:
            DT._request = lambda url, **kw: _NpcEnvelopeResp(
                '{"msg":"操作成功","code":200,"data":{}}')
            self.assertIsNone(DT.get_download_url("SHARED-NONE"))
        finally:
            DT._request = old

    # ---- 加宽那一轮也必须判：同一个端点的第二次请求 ----

    def _two_round_search(self, first_payload, second_payload):
        """按调用次序发两份信封：第 1 次是主检索，第 2 次是 title 精确路径的加宽过取。

        加宽轮只在 `search_type=2 and scope=='title' and page==1` 且 fetch_size != size
        时发出（`tax_search.py:866`），所以 size 必须小于 max(size*3, 20) 才会走到。
        """
        seq = {"n": 0}

        def fake(method, url, **kw):
            seq["n"] += 1
            return _NpcEnvelopeResp(first_payload if seq["n"] == 1 else second_payload)

        old = T._request
        try:
            T._request = fake
            r = T.search_tax("增值税", scope="title", search_type=2, size=2, page=1)
            return r, seq["n"]
        finally:
            T._request = old

    def test_wide_round_healthy_still_widens(self):
        """控制组：两轮都健康时加宽照常生效，不得因为新加的判据而误拦。"""
        r, calls = self._two_round_search(
            '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9},'
            '{"bbbs":"A2","flfgname":"增值税暂行条例","sxx":3,"score":8}],'
            '"code":200,"msg":"查询成功"}',
            '{"total":60,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9},'
            '{"bbbs":"B9","flfgname":"关税税则委员会公告","sxx":3,"score":1}],'
            '"code":200,"msg":"查询成功"}')
        self.assertEqual(2, calls, "加宽轮没发出去，测的就不是这条路径")
        self.assertTrue(any(x["id"] == "A1" for x in r["results"]))

    def test_wide_round_business_error_raises_not_silently_skipped(self):
        """加宽轮出错绝不能被读成"没有更多候选"：那会让标题排序照旧偏、且无痕迹。"""
        with self.assertRaises(RuntimeError) as cm:
            self._two_round_search(
                '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9}],'
                '"code":200,"msg":"查询成功"}',
                '{"msg":"系统异常","code":500}')
        self.assertIn("业务失败", str(cm.exception))
    def test_wide_round_total_follows_the_pool_the_rows_came_from(self):
        """加宽轮真并进新候选、两档 total 不同 ⇒ 报出去的 total 取候选那一档，主发档留 source_total。

        桩照 2026-11-26 实测的两档形状：主发（pageSize=2）报 45、加宽（pageSize=20）报 60，
        加宽那份带回一枚主发里没有的 B9。生产「环境保护」size=5 那次就是这个形状——
        报 3108、给的五条却全在 pageSize=20 那一档里（与 size=20 结果交集 5/5）。
        """
        r, calls = self._two_round_search(
            '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9},'
            '{"bbbs":"A2","flfgname":"增值税暂行条例","sxx":3,"score":8}],'
            '"code":200,"msg":"查询成功"}',
            '{"total":60,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9},'
            '{"bbbs":"B9","flfgname":"关税税则委员会公告","sxx":3,"score":1}],'
            '"code":200,"msg":"查询成功"}')
        self.assertEqual(2, calls, "加宽轮没发出去，测的就不是这条路径")
        self.assertEqual(60, r["total"], "候选取自加宽那一档，total 就不该再报主发那一档的数")
        self.assertEqual(45, r.get("source_total"), "主发那一档的数要留着，别让人以为接口只报一个数")
        self.assertIn("_total_note", r, "两档各报什么要写进 _total_note，不能只换个数字不留痕迹")

    def test_wide_round_with_the_same_total_writes_no_extra_keys(self):
        """控制组：两档 total 相同（「增值税」实测 45/45）⇒ 什么都不补，口径自洽。"""
        r, calls = self._two_round_search(
            '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9}],'
            '"code":200,"msg":"查询成功"}',
            '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9},'
            '{"bbbs":"B9","flfgname":"关税税则委员会公告","sxx":3,"score":1}],'
            '"code":200,"msg":"查询成功"}')
        self.assertEqual(2, calls)
        self.assertEqual(45, r["total"])
        self.assertNotIn("source_total", r, "两档同数时不该凭空造一个 source_total")
        self.assertNotIn("_total_note", r)

    def test_wide_round_adding_nothing_keeps_the_main_total(self):
        """加宽轮没带回任何新候选（merged=0）⇒ 这批还是主发那一档的，total 不许换。"""
        r, calls = self._two_round_search(
            '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9}],'
            '"code":200,"msg":"查询成功"}',
            '{"total":60,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9}],'
            '"code":200,"msg":"查询成功"}')
        self.assertEqual(2, calls)
        self.assertEqual(45, r["total"], "没并进新东西就把 total 换了，等于凭空改口径")
        self.assertNotIn("source_total", r)

    def test_no_widening_round_leaves_total_alone(self):
        """size=100 时 fetch_size==size、加宽那一支根本不进 ⇒ 新加的那两个键都不该出现。"""
        import tax_search as TS
        calls = {"n": 0}

        def fake(method, url, **kw):
            calls["n"] += 1
            return _NpcEnvelopeResp(
                '{"total":45,"rows":[{"bbbs":"A1","flfgname":"中华人民共和国增值税法","sxx":3,"score":9}],'
                '"code":200,"msg":"查询成功"}')

        old = TS._request
        try:
            TS._request = fake
            r = TS.search_tax("增值税", scope="title", search_type=2, size=100, page=1)
        finally:
            TS._request = old
        self.assertEqual(1, calls["n"], "size=100 不该再发第二发")
        self.assertEqual(45, r["total"])
        self.assertNotIn("source_total", r)
        self.assertNotIn("_total_note", r)



# ── ①b 法院两站的业务码：同一族病症、不同的成功值，不能套 NPC 那把尺 ──────
class TestCourtSharedBusinessGuard(unittest.TestCase):
    """裁判文书网与人民法院案例库都用 HTTP 200 装业务失败，但成功值是 code=0。

    2026-11-25 首次实测（此前本机一次请求都没发过）：
      案例库 POST /cpws_al_api/api/cpwsAl/search 匿名四发 + searchTop10 +
        getGroupDatas + 左侧聚类，全部 200 / 30 字节 {"msg":"未登录","code":401}；
        补 UA/Referer/X-Requested-With 不松墙；只有 recordSearchLog 用真 401。
      文书网 POST /website/parse/rest.q4w 三发（空 body、只带 construct、
        带明文假 ciphertext）全部 200 / 76 字节
        {"code":9,"description":null,"secretKey":null,"result":null,"success":false}；
        /api/fp/ah、/api/fp/cprq、/api/fp/gjjsClick 回 200 / 0 字节；
        /down/isDown 200 / {"msg":"文书解码失败，无法下载!","code":1}。
    判据先备好而不接源，是因为本仓栽过的不是「没接这个源」，而是「接了之后
    把墙读成 0 条」——红线⑦那一族。探针 probe30g 实测：这六只原始信封喂现判据
    is_fetch_failure 全 False、喂 tax_answer._rows_and_error 全读成 rows=0 无错，
    也就是全部会被答成「库里没有」。
    """

    def test_helper_truth_table(self):
        for payload, should_flag in (
            ({"code": 0, "msg": "获取成功！"}, False),      # 案例库健康形状
            ({"code": 0, "success": True, "result": {"datas": []}}, False),
            ({"code": 401, "msg": "未登录"}, True),
            ({"code": "401", "msg": "未登录"}, True),        # 字符串码也要认
            ({"code": 9, "success": False, "result": None}, True),
            ({"code": 1, "msg": "文书解码失败，无法下载!"}, True),
            ({"success": False}, True),                     # 没有 code 也要认 success
            ({"code": "0"}, False),                         # 字符串 0 不得发假警
            ({"msg": "两枚键都没有"}, False),
            ({}, False),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(should_flag,
                                 tax_http.court_business_error(payload) is not None)

    def test_helper_tolerates_non_dict(self):
        """接口哪天回个 list／字符串／None（文书网那三枚 0 字节就是这种风险），判据不能自己先炸。"""
        for bad in ([], "text", None, 5):
            with self.subTest(value=bad):
                self.assertIsNone(tax_http.court_business_error(bad))

    def test_error_message_says_it_is_not_an_empty_result(self):
        reason = tax_http.court_business_error({"code": 401, "msg": "未登录"})
        self.assertIn("业务失败", reason)
        self.assertIn("库里没有", reason, "得让读者看见这不是「没有」而是「没连上」")

    def test_the_two_guards_are_not_one_ruler(self):
        """NPC 认 200 为成功、法院两站认 0 为成功。合并任何一把都会误伤另一族。"""
        healthy_court = {"code": 0, "msg": "获取成功！"}
        healthy_npc = {"code": 200, "msg": "查询成功"}
        self.assertIsNotNone(tax_http.npc_business_error(healthy_court),
                             "NPC 那把尺会把案例库的正常响应拦下来——这正是不能合并的证据")
        self.assertIsNotNone(tax_http.court_business_error(healthy_npc),
                             "法院那把尺会把 NPC 的正常响应拦下来")
        self.assertIsNone(tax_http.npc_business_error(healthy_npc))
        self.assertIsNone(tax_http.court_business_error(healthy_court))

    def test_require_court_ok_raises_instead_of_returning_empty(self):
        with self.assertRaises(RuntimeError) as cm:
            tax_http.require_court_ok({"code": 401, "msg": "未登录"})
        self.assertIn("业务失败", str(cm.exception))
        tax_http.require_court_ok({"code": 0, "msg": "获取成功！"})

    def test_a_legal_zero_still_passes_the_court_guard(self):
        """0 条命中是合法答案，判据不许把它拦成失败——否则红线⑦反过来犯一次。"""
        self.assertIsNone(tax_http.court_business_error(
            {"code": 0, "msg": "获取成功！",
             "data": {"datas": [], "totalCount": 0}}))

    def test_the_court_sentence_does_not_vouch_for_a_status_code(self):
        """判据只看信封里的 code/success，它收不到 status——所以句子不许替状态码作保。

        2026-11-26 复量：案例库 `/cpws_al_api/api/user/recordSearchLog` 回的是**真 401**
        （首测 2026-11-25 也记过这一枚，只是判据当时没对着它跑）。旧句子开口就是
        「法院站回 HTTP 200 但业务失败」，喂给这封真 401 就成了一句假话——而这句话
        是要进日志、进答句的，读者会照着它去查「为什么 200 会失败」。
        """
        for payload in ({"code": 401, "msg": "用户未登录！"},
                        {"code": 9, "success": False, "result": None}):
            with self.subTest(code=payload.get("code")):
                reason = tax_http.court_business_error(payload)
                self.assertIsNotNone(reason, "这两封都得报，别退回静默")
                self.assertNotIn("HTTP 200", reason,
                                 "判据看不见状态码，句子里不许写死 HTTP 200")

    def test_the_status_code_claim_lives_in_the_note_not_the_message(self):
        """「多数失败用 200 装着」这句是**统计陈述**，留在文档与注释里；
        真读数（401 那一枚）与它并列时才不至于变成绝对断言。这里钉住文档面。"""
        for rel in ("search_source/wenshu/NOTE.md", "search_source/rmfyalk/NOTE.md"):
            with self.subTest(note=rel):
                t = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn("2026-11-26", t,
                              "这份 NOTE 没记 2026-11-26 那轮复量，判据句改口的依据就没了")


# ── ① NPC 闸要包住下载路径 ────────────────────────────────────────────────
class TestNpcGateCoversDownload(unittest.TestCase):
    def test_get_download_url_uses_the_gated_request(self):
        src = (SCRIPTS_DIR / "tax_detail.py").read_text(encoding="utf-8")
        body = src[src.index("def get_download_url"):src.index("def download_bytes")]
        self.assertIn("_request(", body, "取下载地址没走带闸的 _request")
        self.assertNotIn("tax_http.get(", body, "取下载地址还在闸外裸调")

    def test_npc_gate_is_a_subclass_not_a_copy(self):
        """一份实现两个用户：闸本体在 tax_http，NPC 只是钉了默认值。"""
        self.assertTrue(issubclass(T.NpcSerialGate, tax_http.SerialGate))
        npc_body = (SCRIPTS_DIR / "tax_search.py").read_text(encoding="utf-8")
        npc_body = npc_body[npc_body.index("class NpcSerialGate"):
                            npc_body.index("npc_gate = NpcSerialGate()")]
        self.assertNotIn("msvcrt", npc_body,
                         "NPC 子类里又抄了一遍文件锁实现，说明没共用")

    def test_eval_and_server_both_use_download_bytes(self):
        for rel in ("scripts/tax_server.py", "tests/eval_answer.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("law-search/" + "download/pc", text,
                             "{} 自己拼了下载地址".format(rel))
            self.assertIn("download_bytes", text)


class TestGradingReadsFgkMetadata(unittest.TestCase):
    """法规库清单带来的三个定级口子：解读件、已修改、标题里的书名号。

    翻页基准修正后清单里同时出现了公告原文、公告的解读、以及公告正文援引的
    配套文件（《关于企业重组业务所得税处理有关征管问题的公告》，2026年第13号），
    定级层一照面就把解读按被解读文件的形态判成了规范性文件。
    """

    def test_interpretation_is_not_the_document_it_explains(self):
        t = "国家税务总局关于企业重组业务企业所得税征收管理若干问题的公告的解读"
        self.assertEqual("technical", E.rank_of(t)["rank"])
        # 带 effect_level 也不该被分类规则顶成原文的位阶
        self.assertEqual("technical",
                         E.rank_of(t, category="税务规范性文件")["rank"])

    def test_amended_document_still_in_force(self):
        v = E.judge_validity({"status": "已修改"}, "2026-09-29")
        self.assertEqual("effective", v["validity"])
        self.assertIn("修改后的版本", v["note"])
        # 认不出的状态仍然只能报未标明，不猜
        self.assertEqual("unknown",
                         E.judge_validity({"status": "待定"}, "2026-09-29")["validity"])

    def test_title_with_book_marks_still_ranks(self):
        t = "国家税务总局关于发布《企业重组业务企业所得税管理办法》的公告"
        r = E.rank_of(t)
        self.assertEqual("normative", r["rank"])
        self.assertEqual(55, r["tier"])
        # 判成"未定性"时层级掉到 0、角色掉到待核对线索——那才是这个用例要拦的
        # 回归，所以两条都断言，而不是断言掉了几分
        g = E.grade({"title": t}, topic="企业重组")
        self.assertEqual("normative", g["rank"])
        self.assertEqual(55, g["rank_tier"])
        self.assertEqual("direct", g["role"])
        # 主题词对不上时它仍是有层级的法定文件，落"上位依据与授权"：
        # "待核对线索"只留给层级与主题两头都空着的那类（见 `role_of`）。
        self.assertEqual("superior",
                         E.grade({"title": t}, topic="留抵退税")["role"])
        off = E.grade({"title": t}, topic="留抵退税")
        self.assertIs(False, off["on_topic"])
        self.assertIn("标题与正文里都没有本题的主题词", "；".join(off["caveats"]))


class TestNormativeIsABasisNotReference(unittest.TestCase):
    """总局公告是本题的直接规定，不该被任何一根"参考"线挡在依据之外。

    断言的是角色，不是"分数够不够 50 那条线"——那根线是把能不能引和该不该让位
    乘成一个分数的合成判据，两根轴各判各的才分得开。规范性文件在与本题对得上、
    且没废止时就是"本题的直接规定"，并且挑得主依据，压过层级更高的法律。
    """

    ANN = "国家税务总局关于企业重组业务所得税处理有关征管问题的公告"

    def test_current_announcement_is_a_direct_basis(self):
        g = E.grade({"title": self.ANN, "status": "全文有效"},
                    at="2026-09-29", topic="企业重组")
        self.assertEqual("effective", g["validity"])
        self.assertEqual("direct", g["role"])

    def test_a_higher_tier_law_does_not_steal_the_headline(self):
        """问企业重组的征管口径时，头条要给规定这件事的公告，不给《企业所得税法》。

        变异自检：把 `pick_primary` 的排序键换成单按 `rank_tier` 降序，这一条
        立刻报红——法律 90 压公告 55。旧的可引用性公式就是这个形状。
        """
        g = E.grade_all([
            {"title": "中华人民共和国企业所得税法", "status": "全文有效"},
            {"title": self.ANN, "status": "全文有效"},
        ], at="2026-09-29", topic="企业重组")
        best = E.pick_primary(g)
        self.assertEqual(self.ANN, best["title"])
        self.assertEqual("direct", best["role"])

    def test_validity_problem_becomes_a_reminder_not_a_ban(self):
        """时效那一栏照常是唯一带后果的轴，但后果写成"要核对什么"。"""
        for status, want in (("", "unknown"), ("尚未生效", "pending"),
                             ("全文废止", "repealed")):
            g = E.grade({"title": self.ANN, "status": status},
                        at="2026-09-29", topic="企业重组")
            self.assertEqual(want, g["validity"], status)
            self.assertIn(E.VALIDITY_CAVEAT[want], g["caveats"], status)
        # 已废止的那条角色转成政策沿革，仍在分层里列出，没有被删掉
        self.assertEqual("history",
                         E.grade({"title": self.ANN, "status": "全文废止"},
                                 at="2026-09-29", topic="企业重组")["role"])

    def test_practice_layer_keeps_its_own_role(self):
        """税屋、公众号与官方解读各归"执行口径"，不再被压成不能引用的那堆。

        判的次序是"废止 → 实务形态 → 主题对得上 → 层级未定"：一份层级判不出来
        的稿子只要字面上就在讲本题，它就是"本题的直接规定"，层级未定那件事由提醒
        那几句话说清；层级与主题都落空的才落"待核对线索"。
        """
        cases = (
            ({"title": "关于企业重组业务所得税处理有关征管问题的公告的解读"},
             "technical", "practice"),
            ({"title": "解读：企业重组特殊性税务处理怎么备案"},
             "technical", "practice"),
            ({"title": "六税两费减免的十个易错点", "source": "税屋 (shui5.cn)"},
             "interpretation", "practice"),
            ({"title": "实务问答：留抵退税的口径", "source": "微信公众号 (元宝搜索)"},
             "technical", "practice"),
            ({"title": "上海市税务局关于做好企业重组备案工作的通知"},
             "local_normative", "direct"),
            ({"title": "企业重组有关的几点提示"}, "unknown", "direct"),
            ({"title": "几点提示"}, "unknown", "unmatched"),
        )
        for item, want_rank, want_role in cases:
            g = E.grade(dict(item, status="全文有效"), at="2026-09-29",
                        topic="企业重组")
            self.assertEqual(want_rank, g["rank"], item["title"])
            self.assertEqual(want_role, g["role"], item["title"])
        # 层级未定但主题对得上的那条，提醒里必须写着"层级没判出来"这件事
        g = E.grade({"title": "企业重组有关的几点提示", "status": "全文有效"},
                    at="2026-09-29", topic="企业重组")
        self.assertEqual("标题形态与来源都不足以定级", g["rank_by"])

    def test_pending_without_effective_date_cannot_be_read_as_in_force(self):
        """判 --at 时"没查到施行日期"不等于"日期一定在过去"。

        时点分支若只要没取到 effective_date 就落回 effective，一份标着尚未生效
        的公告会在带 --at 的用法下直接顶成主依据；只有日期确认早于观察时点才
        允许转正。转正那一条另配一句"生效日不晚于观察时点"的常规交代，它不是
        提醒，所以 `qualified` 为假。
        """
        for it in ({"status": "尚未生效"},
                   {"status": "尚未生效", "publish_date": "2026-07-08"},
                   {"status": "未生效", "effective_date": ""}):
            g = E.grade(dict(it, title=self.ANN), at="2026-09-29", topic="企业重组")
            self.assertEqual("pending", g["validity"], it)
            self.assertIn(E.VALIDITY_CAVEAT["pending"], g["caveats"], it)
        g = E.grade({"title": self.ANN, "status": "尚未生效",
                     "effective_date": "2026-01-01"}, at="2026-09-29",
                    topic="企业重组")
        self.assertEqual("effective", g["validity"])
        self.assertNotIn("生效日 2026-01-01 不晚于观察时点 2026-09-29",
                         g["caveats"], "这是判据来源的交代，不该占一条提醒")
        # 不传 --at 时本来就是纯状态判定，pending 不受影响
        self.assertEqual("pending",
                         E.judge_validity({"status": "尚未生效"}, "")["validity"])


class TestConstitutionIsNotTheHeadline(unittest.TestCase):
    """宪法位阶最高，但不能顶当主依据——位阶×时效的乘法会给它 100×1.0 的全场最高分。"""

    def test_flagged_and_yielded_to_the_law(self):
        c = E.grade({"title": "中华人民共和国宪法", "category": "宪法"},
                    at="2026-09-29", topic="税收法定")
        self.assertEqual(100, c["rank_tier"])
        self.assertTrue(c["not_directly_quotable"])
        self.assertIn(E.CONSTITUTION_NOTE, c["caveats"])
        self.assertEqual(E.CONSTITUTION_NOTE, c["citation_hint"].split("；")[1])
        mixed = [c, E.grade({"title": "中华人民共和国税收征收管理法",
                             "status": "全文有效"}, at="2026-09-29",
                            topic="税收法定")]
        self.assertEqual("中华人民共和国税收征收管理法",
                         E.pick_primary(mixed)["title"])

    def test_alone_it_is_picked_but_told_to_go_down_to_law(self):
        """一组里只有宪法时仍要挑它，同时说明它对税务机关不构成征税依据。

        变异自检：若改成"宪法一律不挑"，这一条报红——那时候答案会连一条
        规定税收法定原则的文件都提不出来，而题问的正是这个原则。
        """
        only = [E.grade({"title": "中华人民共和国宪法", "category": "宪法"},
                        at="2026-09-29", topic="税收法定")]
        best = E.pick_primary(only)
        self.assertEqual("中华人民共和国宪法", best["title"])
        self.assertIn("不构成征税依据", best["_why"])


class TestNoSynthesisedCitationScore(unittest.TestCase):
    """不设可引用性合成分数：留一个字段名就会被下游重新拿去排队。"""

    def test_grade_exposes_the_axes_not_a_product(self):
        g = E.grade({"title": "中华人民共和国企业所得税法", "status": "全文有效"},
                    at="2026-09-29", topic="企业所得税")
        for key in ("rank_tier", "validity", "on_topic", "role", "caveats",
                    "not_directly_quotable"):
            self.assertIn(key, g)
        self.assertNotIn("score", g)
        self.assertNotIn("score", E.rank_of("中华人民共和国宪法"))

    def test_removed_symbols_stay_removed(self):
        for name in ("authority_score", "PRIMARY_THRESHOLD", "RELIABILITY_BLOCK"):
            self.assertFalse(hasattr(E, name), name)

    def test_no_consumer_reads_a_score(self):
        for rel in ("scripts/tax_answer.py", "scripts/tax_server.py",
                    "tests/eval_answer.py", "frontend/index.html"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn('get("score"', text, rel)
            self.assertNotIn("PRIMARY_THRESHOLD", text, rel)

    def test_frontend_prints_the_reminder_not_a_downweight_badge(self):
        """界面上"⚪ 仅参考"那个角标换成了一句看得见的提醒。

        角标只给一个记号：读者既不知道疑在哪一处，也无从核对，只能整条忽略。
        现在卡面直接印提醒，句子取自条目自带的 `_reliability_note`。界面不再存
        第二份文案：同一档位在不同来源里原因不同，按档位配死一句就会有一句是假的
        （判据与定级层同一处，见 `tax_evidence._caveats`）。

        变异自检：把角标那段 `${item._reliability==='medium'?...仅参考...}` 抄回
        index.html，第一条断言报红；把 `rel-note` 那一行删掉，第二、三条报红；
        在界面里另存一份按档位配的固定文案，第四条报红。
        """
        self.assertNotIn("仅参考", HTML, "降权标签不能留在界面上")
        self.assertIn('class="rel-note"', HTML, "提醒要印在卡面上，不能只挂在 title 里")
        self.assertIn("item._reliability_note", HTML, "提醒要用来源自己那句")
        self.assertNotIn("RELIABILITY_NOTE", HTML, "界面不另存一份按档位配的文案")


class TestValidityCorroboratedByCitation(unittest.TestCase):
    """「财税文件」那一栏根本不录时效，援引证据补这一格。

    59 号、109 号是点名公告正文列明的制定依据，却是这道题的上位规则；
    因为法规库这两条的时效录入项为空（财税〔2003〕16 号那个位置上是
    字符串 "null"），它们全被压在依据线以下，答案只能说"只能参考"。详情页也只有
    成文日期，没有时效栏可回填。
    """

    ANN = "国家税务总局关于企业重组业务所得税处理有关征管问题的公告"
    BODY = ("根据《中华人民共和国企业所得税法》及其实施条例、《财政部 国家税务总局关于"
            "企业重组业务企业所得税处理若干问题的通知》（财税〔2009〕59号）、《财政部 国家"
            "税务总局关于促进企业重组有关企业所得税处理问题的通知》（财税〔2014〕109号）"
            "等文件规定，现对企业重组业务所得税处理有关征管问题公告如下：\n"
            "一、对于企业合并、分立业务……")
    AT = "2026-09-29"

    def _rows(self):
        return [
            {"title": self.ANN, "status": "全文有效", "document_number": "国家税务总局公告2026年第13号",
             "url": "u13", "_cited_target": True, "body": self.BODY},
            {"title": "财政部 国家税务总局关于企业重组业务企业所得税处理若干问题的通知",
             "document_number": "财税〔2009〕59号", "url": "u59"},
            {"title": "财政部 国家税务总局关于促进企业重组有关企业所得税处理问题的通知",
             "document_number": "财税〔2014〕109号", "url": "u109"},
            {"title": "财政部 国家税务总局关于营业税若干政策问题的通知",
             "document_number": "财税〔2003〕16号", "url": "u16"},
        ]

    def test_cited_basis_docs_become_citable(self):
        rows = self._rows()
        tagged = ANS.corroborate_validity_from_target(rows, self.AT)
        self.assertEqual(["财政部 国家税务总局关于企业重组业务企业所得税处理若干问题的通知",
                          "财政部 国家税务总局关于促进企业重组有关企业所得税处理问题的通知"],
                         tagged)
        # 没被援引的那份不补，正文里出现的《企业所得税法》也不动（它本来就有效）
        self.assertNotIn("u16", [r["url"] for r in rows if r.get("corroborated_by")])
        for r in rows:
            if r.get("corroborated_by") != self.ANN:
                continue
            g = E.grade(r, at=self.AT, topic="企业重组")
            self.assertEqual("effective", g["validity"])
            self.assertIn("制定依据判定在效", g["validity_note"])
            # 这一条的"现行有效"是佐证出来的，不是法规库录的：必须占一条提醒，
            # 免得读的人把它当成源里的时效字段
            self.assertIn("引用前按该文自身的时效复核", "；".join(g["caveats"]),
                          g["caveats"])

    def test_explicit_status_beats_citation_evidence(self):
        """明文写着废止或未生效的，援引证据不能翻案。"""
        for status, want in (("全文废止", "repealed"), ("尚未生效", "pending")):
            it = {"title": "财政部 国家税务总局关于某事项的通知", "status": status,
                  "corroborated_by": self.ANN}
            self.assertEqual(want, E.judge_validity(it, self.AT)["validity"], status)

    def test_unusable_target_corrobs_nothing(self):
        """援引方自己时效不明、或是解读件，就不具备给别的文件作证的资格。"""
        rows = self._rows()
        rows[0]["status"] = ""
        self.assertEqual([], ANS.corroborate_validity_from_target(rows, self.AT))
        rows = self._rows()
        rows[0]["_is_interpretation"] = True
        self.assertEqual([], ANS.corroborate_validity_from_target(rows, self.AT))
        rows = self._rows()
        rows[0].pop("body")
        self.assertEqual([], ANS.corroborate_validity_from_target(rows, self.AT))

    def test_preamble_only_is_parsed(self):
        """只读"根据……规定"那一段，正文条款里援引的文件不算制定依据。"""
        rows = self._rows()
        rows[0]["body"] = ("根据《中华人民共和国企业所得税法》规定，现公告如下：\n"
                           "四、本公告自发布之日起施行，《财政部 国家税务总局关于企业重组"
                           "业务企业所得税处理若干问题的通知》（财税〔2009〕59号）同时废止。")
        self.assertEqual([], ANS.corroborate_validity_from_target(rows, self.AT))

    def test_null_placeholder_is_not_a_status(self):
        self.assertEqual("", WS.aging_of("null"))
        self.assertEqual("", WS.aging_of(" NULL "))
        self.assertEqual("", WS.aging_of(None))
        self.assertEqual("全文有效", WS.aging_of("全文有效"))


# ── 轮次取数失败与"这一轮 0 条"必须分得开 ──────────────────────────────────
class TestRoundFailureIsNotSilent(unittest.TestCase):
    """源挂了不许被记成 found=0，否则主依据会静默降级而输出看不出来。

    NPC 那一轮静默失败时，90 分的现行有效法律不见了，顶上【主依据】的是
    70 分的《个体工商户建账管理暂行办法》，而 `rounds_done` 只写着 found=0、
    `errors` 是空的——读的人无法区分"库里没有"和"这一轮没取回来"。
    """

    Q = "增值税小规模纳税人月销售额10万，应纳增值税多少"
    规章 = {"title": "个体工商户建账管理暂行办法", "category": "税务部门规章",
            "status": "现行有效", "url": "http://x/规章"}
    法律 = {"title": "中华人民共和国税收征收管理法", "category": "法律",
            "status": "现行有效", "url": "http://x/法律"}

    def _gather(self, fail=(), with_law=True, partial=()):
        """把所有源换成打桩客户端：fail 里的源报"取数失败"，partial 里的报"清单
        取到、逐枚没取全"，其余回条目。

        桩的返回形必须与 `_FETCHERS` 的真实契约同元数（三元）。桩形错位时解包
        抛 ValueError、被 gather 的 `except Exception` 吞掉，测试照样绿却钉不住
        契约——这一课在 3.62.13 记过一次，同形再来一遍。
        """
        def make(src):
            def fn(term, size):
                if src in fail:
                    return [], "响应不是 JSON: Expecting value: line 1 column 1 (char 0)", ""
                if src in partial:
                    return [dict(self.规章)], "", "清单取回 1 条，但 1/1 篇正文一篇都没取到"
                rows = [dict(self.规章)] + ([dict(self.法律)] if with_law and src == "npc" else [])
                return rows, "", ""
            return fn
        with mock.patch.dict(ANS._FETCHERS,
                             {s: make(s) for s in ("npc", "fgk", "shui5", "wechat", "legis")}):
            return ANS.gather(self.Q, at="2026-09-29")

    def test_source_error_names_the_round_and_the_source(self):
        g = self._gather(fail=("npc",))
        self.assertTrue(any("第1轮 npc 取数失败" in e for e in g["errors"]), g["errors"])
        self.assertIn("npc", g["rounds_done"][0]["failed"], g["rounds_done"])
        a = ANS.compose(g)
        self.assertTrue(a["fetch_errors"] and a["fetch_note"], a["fetch_note"])
        # 这一趟只剩部门规章：主依据确实被降级，靠 fetch_note 才读得出来
        self.assertEqual(self.规章["title"], a["primary"]["title"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ANS._print_answer(a)
        self.assertIn("【取数失败】", out.getvalue())
        self.assertIn("不等于库里没有", out.getvalue())

    def test_clean_empty_round_stays_silent(self):
        """干净的空结果不许编出一条失败来——两种"没有"分开，也得各自成立。"""
        with mock.patch.dict(ANS._FETCHERS,
                             {s: (lambda t, n: ([], "", ""))
                              for s in ("npc", "fgk", "shui5", "wechat", "legis")}):
            g = ANS.gather(self.Q, at="2026-09-29")
        self.assertEqual([], g["errors"])
        self.assertEqual([], g["partial_notes"])
        self.assertEqual([], [f for r in g["rounds_done"] for f in r["failed"]])
        a = ANS.compose(g)
        self.assertEqual("", a["fetch_note"])
        self.assertEqual("", a["partial_note"])
        self.assertTrue(a["evidence_gap"], "一条依据都没取到时该说证据缺口，不是取数失败")

    def test_legislation_lane_items_cannot_become_primary(self):
        """立法过程实位取回的条目带 `legislative_process`，定级层据此不挑它当主依据。

        人大网站的草案与审议公告是"找到文本的线索"，本身不是已公布的规定。
        这一条拒绝的理由是"它不是已公布的条文"这个事实，不是降权：
        `_reliability: medium` 只负责附带一句提醒，
        真正把这一层挡在头条之外的是 `legislative_process` 这个标记。
        """
        page = {"results": [{"title": "法律草案审议 中国人大网",
                             "url": "http://www.npc.gov.cn/npc/c2/x.html"}], "total": 1}
        with mock.patch.object(ANS.SG, "sogou_search", return_value=page) as hit:
            rows, err, partial = ANS._legis_round("税收征收管理法 修订草案", 8)
        self.assertEqual("", err)
        self.assertEqual("", partial)
        self.assertEqual("npc.gov.cn", hit.call_args.kwargs["site"])
        self.assertEqual("medium", rows[0]["_reliability"])
        self.assertTrue(rows[0]["legislative_process"])
        graded = [E.grade(r, at="2026-09-29") for r in rows]
        best = E.pick_primary(graded)
        self.assertEqual("", best.get("title", ""), "立法过程线索不能被选成主依据")
        self.assertIn("立法过程线索", best["_why"])
        # 掺进一条正常依据时，主依据让位给那条，线索仍不能靠兜底上位
        mixed = graded + [E.grade({"title": "中华人民共和国税收征收管理法",
                                   "status": "全文有效"}, at="2026-09-29")]
        self.assertNotEqual("法律草案审议 中国人大网",
                            E.pick_primary(mixed)["title"])
        # 但它没有被删掉：落选清单里仍列着这一条
        self.assertIn("法律草案审议 中国人大网",
                      [r["title"] for r in best["_runners_up"]])

    def test_draft_round_also_searches_shui5_and_wechat(self):
        """草案那一轮必须连带搜税屋与公众号：草案解读文章只活在这两个源里。

        草案轮若只排 sources=["legis"]（人大网站内），税屋与公众号一次都不查，
        会把最有料的实务解读整层漏掉：search_shui5("税收征管法 修订草案") 首条
        即国务院法制办征求意见稿通知、含"修订重点逐条解读"多篇。
        """
        plan = ANS.build_plan("请解读《税收征管法》修订草案，已提请全国人大常委会审议")
        rnd = [r for r in plan["rounds"] if "legis" in r["sources"]]
        self.assertEqual(1, len(rnd), "应有且仅有一轮立法取证")
        self.assertEqual({"legis", "shui5", "wechat"} & set(rnd[0]["sources"]),
                         {"legis", "shui5", "wechat"},
                         "立法取证轮要覆盖人大网+税屋+公众号三个源")
        self.assertEqual("legis", rnd[0].get("term_key"),
                         "这一轮三个源统一用草案词，不用各源的主题短词")

    def test_draft_round_uses_draft_term_not_short_term(self):
        """税屋/公众号在草案轮拿到的词必须含"草案"，否则搜回的是现行规定。

        打桩三个 fetcher，跑 gather，抓每源被调用时收到的检索词。

        桩必须**连 `FGK.search_fgk` 一起打**：这句题面点了《税收征管法》的名，
        gather 在轮次循环之前先走点名定位（`locate_cited_document →
        search_fgk → tax_web_search.search_chinatax`），这条路**不经过
        `_FETCHERS`**，只桩取数函数时它照发真 HTTPS（2026-11-24 实测：一枚用例
        18 次 connect、`urllib3` 报 Unverified HTTPS request to
        www.chinatax.gov.cn，而异常被源层吞成 `_error`，用例仍然绿）。
        同文件 `_跑一趟` L2208 那处就是这么双打的，这里原本漏了半边。
        check_citations 一并关掉：文号回库核对本身要发检索。
        """
        seen = {}

        def make(src):
            def fn(term, size):
                seen.setdefault(src, []).append(term)
                return [], "", ""
            return fn

        Q = "请解读《税收征管法》修订草案，已提请全国人大常委会审议"
        with mock.patch.dict(ANS._FETCHERS,
                             {s: make(s) for s in ("npc", "fgk", "shui5",
                                                   "wechat", "legis",
                                                   "whole_site")}), \
             mock.patch.object(FGK, "search_fgk",
                               lambda kw, size=6, **kw2: {"results": []}):
            ANS.gather(Q, at="2026-09-29", check_citations=False)
        # 草案轮与非草案轮的 shui5 调用词并存，取含"草案"的那一次
        terms_used = seen.get("shui5", [])
        self.assertTrue(any("草案" in t for t in terms_used),
                        f"shui5 在草案轮应拿到含'草案'的词，实际 {terms_used}")
        self.assertTrue(any("草案" in t for t in seen.get("wechat", [])),
                        f"wechat 在草案轮应拿到含'草案'的词，实际 {seen.get('wechat')}")


# ── 返回形态守门：注解写了 tuple，每一条 return 就得真的给元组 ────────────────
def _tuple_contract_offenders(path):
    """扫一个文件，列出 `-> tuple[...]` 却返回别的形状的 [(函数名, 行号, 返回表达式)]。

    只看直接写在该函数体里的 return，嵌套函数与 lambda 内部的归它们自己的注解管，
    不然一个元组函数里写个返回字符串的闭包会被误报。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for fn in (n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        ann = fn.returns
        if not ann or not ast.unparse(ann).startswith("tuple["):
            continue
        arity = (len(ann.slice.elts)
                 if isinstance(ann, ast.Subscript) and isinstance(ann.slice, ast.Tuple)
                 else None)
        # `tuple[str, ...]` 是变长注解，不是「几个元素」的约定：把省略号也数进 arity
        # 就会要求 `return tuple(...)` 写成元组字面量，这是门禁的盲区而不是代码的缺陷
        # （2026-11-27 `_query_tokens` 撞过一次）。变长一律只钉「必须是元组」，不钉长度。
        if (arity is not None and ann.slice.elts
                and isinstance(ann.slice.elts[-1], ast.Constant)
                and ann.slice.elts[-1].value is Ellipsis):
            arity = None
        inner = set()
        for sub in ast.walk(fn):
            if sub is fn or not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                 ast.Lambda)):
                continue
            inner.update(id(x) for x in ast.walk(sub))
        for r in (n for n in ast.walk(fn)
                  if isinstance(n, ast.Return) and n.value is not None
                  and id(n) not in inner):
            # `tuple(...)` 也是元组，只是字面量长度看不出来（2026-11-27 `_query_tokens`
            # 撞过一次）：固定枚数的注解仍要求写字面量，变长注解放过调用形式。
            literal = isinstance(r.value, ast.Tuple)
            called = (isinstance(r.value, ast.Call)
                      and isinstance(r.value.func, ast.Name)
                      and r.value.func.id == "tuple")
            is_tuple = literal or called
            if arity is None:
                right_arity = True
            else:
                right_arity = literal and len(r.value.elts) == arity
            if not (is_tuple and right_arity):
                offenders.append((fn.name, r.lineno, ast.unparse(r.value)))
    return offenders


class TestTupleReturnContract(unittest.TestCase):
    """`-> tuple[list, str]` 这类函数，成功分支必须和失败分支给同样多的值。

    起因是真缺陷：`tax_server._search_web_broad` 注解与文档都写着返回
    (结果, 拦截说明)，失败分支给了二元组，成功分支却 `return results` 交回裸列表，
    调用方按二元组解包。列表长度说了算：1 条与 3 条都抛 ValueError，被调用方的
    `except Exception` 吞成空结果；正好 2 条时两个名字各接住一个 dict，接口回 500
    （报错原文 `'str' object has no attribute 'get'`）。
    路由用例若把桩打在 `_search_web_broad` 上、桩形用二元组，就会与被测函数的真实
    返回形态不一致，这条断路在测试里一直是绿的。

    这一条把它变成编译期就拦得住的形状：全项目扫一遍，一处不合规门禁就红。
    """

    def test_scripts_and_tests_honour_their_tuple_annotations(self):
        offenders = []
        for d in ("scripts", "tests"):
            for p in sorted((ROOT / d).glob("*.py")):
                for name, lineno, expr in _tuple_contract_offenders(p):
                    offenders.append("{}:{}  {} 返回 {}".format(p.name, lineno, name, expr))
        self.assertEqual(
            [], offenders,
            "注解是 tuple 却返回别的形状（调用方按元组解包会静默丢数据或报 500）：\n  "
            + "\n  ".join(offenders))

    def test_scanner_sees_the_shape_that_caused_the_bug(self):
        """自检：把当年那一行喂进扫描器，必须报出来；不报就说明守门是假的。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "bad.py"
            tmp.write_text(
                "def ok(q):\n"
                "    if q:\n"
                "        return [], '拦了'\n"
                "    return [], ''\n"
                "\n"
                "def bad(q):\n"
                "    results = []\n"
                "    return results\n",
                encoding="utf-8",
            )
            # 两份都注解成二元组，只有 bad 的返回形状不对
            src = tmp.read_text(encoding="utf-8").replace(
                "def ok(q):", "def ok(q) -> tuple[list, str]:").replace(
                "def bad(q):", "def bad(q) -> tuple[list, str]:")
            tmp.write_text(src, encoding="utf-8")
            offenders = _tuple_contract_offenders(tmp)
        self.assertEqual([("bad", 8, "results")], offenders)


class TestPracticeCitationCheck(unittest.TestCase):
    """实务材料的口径要追到一份现行有效的法定文件上，逐条核对。

    这一层替代的是"给税屋/公众号打 10 分、标成只能参考"：降权既不告诉读者哪条
    口径有文件托着，也不告诉读者哪条悬空。现在按文号回官方库查存在与时效。
    全部用例用打桩的库，不发真实检索。
    """

    @staticmethod
    def _文章(content="", source="税屋 (shui5.cn)"):
        row = {"title": "减征车辆购置税的执行口径", "source": source,
               "url": "https://www.shui5.cn/article/9/1.html"}
        if content:
            row["content"] = content
        return row

    def _核对(self, rows, 库里=None, 库报错="", 命中数=None, 响应=None, **kw):
        """跑一次核对，带回 (统计, 发出去查的检索词列表)。

        `库报错` 走 `_fetch_failed` 标记——真实接口零命中时也会写一句 `_error`
        当说明（`tax_fgk._scan_list`），本层认的是标记不是句子。要看接口原样
        回的东西就用 `响应`，它绕过上面两个参数。
        """
        calls = []

        def lookup(term):
            calls.append(term)
            if 响应 is not None:
                return dict(响应)
            if 库报错:
                return {"_error": 库报错, "_fetch_failed": True}
            return {"results": 库里 or [], "total_hits": 命中数}

        stats = ANS.check_practice_citations(rows, at="2026-09-29",
                                             lookup=lookup, **kw)
        return stats, calls

    有效件 = {"title": "财政部 税务总局关于减征车辆购置税的公告",
              "document_number": "财政部 税务总局公告2023年第19号",
              "status": "现行有效", "url": "http://x/19"}

    def test_citation_found_in_library_is_named_with_its_number(self):
        文 = self._文章("依据财政部 税务总局公告2023年第19号，新能源车免征购置税")
        stats, calls = self._核对([文], 库里=[dict(self.有效件)])
        # 发出去的是带机关的宽写法（实测裸短形在库里零命中），记下来的还是
        # 文章里那枚短形——两头各管一件事
        self.assertEqual(["财政部 税务总局公告2023年第19号"], calls)
        st = 文["official_status"]
        self.assertEqual("effective", st["outcome"], st)
        self.assertEqual("2023年第19号", st["doc_number"], "记的是文章援引的那个短形")
        self.assertEqual(self.有效件["title"], st["title"], "文件名要取库里的规范名")
        self.assertEqual("http://x/19", st["url"])
        self.assertEqual({"effective": 1}, stats["by_outcome"])
        self.assertEqual(1, stats["checked"])

    def test_reminder_lands_in_the_graded_caveats(self):
        """核对结果只写进字段不算交付；定级那一条必须把它说成人话。"""
        文 = self._文章("依据财政部 税务总局公告2023年第19号执行")
        self._核对([文], 库里=[dict(self.有效件)])
        g = E.grade(文, at="2026-09-29", topic="车辆购置税")
        self.assertTrue(any("2023年第19号" in c and "税务总局法规库" in c
                            for c in g["caveats"]), g["caveats"])

    def test_repealed_citation_says_reread_the_current_text(self):
        库 = dict(self.有效件, status="全文废止")
        文 = self._文章("按财政部 税务总局公告2023年第19号的规定免征")
        self._核对([文], 库里=[库])
        line = E.official_caveat(文["official_status"])
        self.assertEqual("repealed", 文["official_status"]["outcome"])
        self.assertIn("不再执行的规则", line)

    def test_library_miss_is_stated_as_a_miss_not_as_repealed(self):
        """库里没有这一份，与库里有但已废止，是两条完全不同的下一步动作。"""
        文 = self._文章("按国税发〔1999〕43号执行")
        stats, _ = self._核对([文], 库里=[])
        self.assertEqual("not_in_library", 文["official_status"]["outcome"], stats)
        self.assertIn("没有对上同一份文件", E.official_caveat(文["official_status"]))

    def test_zero_hit_with_an_explained_empty_is_a_miss_not_a_failure(self):
        """接口自己说"这次没命中"和"这轮没连上"，不能读成同一件事。

        真实 `search_fgk` 的形态（实测）：零命中时带一句 `_error` 但**不带**
        `_fetch_failed`；请求或解析失败才带 `_fetch_failed`。拿 `_error` 当故障，
        每一篇援引了生僻文号的文章都会被写成"连不上库、补一轮"，而补一百轮也
        还是零命中。反向弄错同样糟：真挂了报成"库里没有这一份"，读者会去怀疑
        自己抄错文号。所以两个方向都在这里钉住。
        """
        文 = self._文章("按财税〔1999〕43号执行")
        stats, _ = self._核对([文], 响应={"results": [], "total_hits": 0,
                                          "_error": "未检索到相关内容"})
        self.assertEqual("not_in_library", 文["official_status"]["outcome"], stats)
        self.assertIn("检索零命中", E.official_caveat(文["official_status"]))

        挂 = self._文章("按财税〔1999〕43号执行")
        self._核对([挂], 响应={"results": [], "_error": "连接超时",
                              "_fetch_failed": True})
        self.assertEqual("lookup_failed", 挂["official_status"]["outcome"])

    def test_retrieval_term_borrows_the_issuer_not_the_prose(self):
        """补前缀只能借原文里的机关名，借不到就用裸文号。

        喂进 `_citation_phrase` 的是标题+正文拼起来的一整段（实测形态），
        按字符宽度从右截会把"减征车辆购置税的执行口径 依据"一起当成检索词。
        这种词在库里一个也命中不了，于是"现行有效"被写成"库里没对上"——
        假结论还带一句看起来有据的说明。裸文号最坏是命中宽，不会指错文件。
        """
        self.assertEqual(
            "财政部 税务总局公告2023年第19号",
            ANS._citation_phrase("减征车辆购置税的执行口径 依据财政部 税务总局公告"
                                 "2023年第19号", "2023年第19号"))
        self.assertEqual(
            "国家税务总局公告2021年第5号",
            ANS._citation_phrase("国家税务总局公告2021年第5号", "2021年第5号"))
        # 本身就带机关名的写法原样返回；认不到机关名不猜前缀
        self.assertEqual("财税〔2016〕36号",
                         ANS._citation_phrase("依据财税〔2016〕36号附件",
                                              "财税〔2016〕36号"))
        self.assertEqual("2024年第1号",
                         ANS._citation_phrase("某单位关于优惠的公告2024年第1号",
                                              "2024年第1号"))
        # 原文里文号常被排版拆开（"2021 年第 5 号"），而 `tax_terms` 交回来的是
        # 去过空格的短形：按字面 find 会找不到，前缀也就补不上了
        self.assertEqual(
            "国家税务总局公告2021年第5号",
            ANS._citation_phrase("根据国家税务总局公告 2021 年第 5 号的规定",
                                 "2021年第5号"))

    def test_empty_library_document_number_does_not_count_as_a_match(self):
        """只认 want 是 got 的子串：库里那条没录文号时不能算命中，否则任何一篇
        正文里提到文号的文章都会匹配上这条空记录。"""
        文 = self._文章("按国税发〔1999〕43号执行")
        self._核对([文], 库里=[{"title": "某文件", "document_number": "",
                                "status": "现行有效"}])
        self.assertEqual("not_in_library", 文["official_status"]["outcome"])

    def test_lookup_failure_is_not_read_as_missing(self):
        文 = self._文章("按财税〔2016〕36号的规定")
        self._核对([文], 库报错="响应不是 JSON")
        st = 文["official_status"]
        self.assertEqual("lookup_failed", st["outcome"], st)
        line = E.official_caveat(st)
        self.assertIn("不能把「查不到」读成「库里没有」", line)
        self.assertNotIn("没有对上同一份文件", line)

    def test_missing_body_is_not_reported_as_missing_citation(self):
        """`--no-body` 那一趟只有标题：说"这篇没写文号"是假的，要说"没读正文"。"""
        无正文 = self._文章()
        有正文 = self._文章("这篇文章讲的是地方执行的口径细节，没引文号")
        stats, calls = self._核对([无正文, 有正文])
        self.assertEqual("no_body", 无正文["official_status"]["outcome"], stats)
        self.assertEqual("no_citation", 有正文["official_status"]["outcome"], stats)
        self.assertEqual([], calls)
        self.assertIn("没读正文", E.official_caveat(无正文["official_status"]))
        self.assertNotIn("没读正文", E.official_caveat(有正文["official_status"]))

    def test_limit_stops_further_requests_and_says_so(self):
        rows = [self._文章(f"依据国家税务总局公告202{i}年第5号执行") for i in range(1, 4)]
        stats, calls = self._核对(rows, 库里=[dict(self.有效件)], limit=2)
        self.assertEqual(2, len(calls), calls)
        self.assertEqual(1, stats["skipped"], stats)
        self.assertEqual("not_checked", rows[2]["official_status"]["outcome"])
        self.assertIn("上限", E.official_caveat(rows[2]["official_status"]))
        self.assertNotIn("没有对上同一份文件", E.official_caveat(rows[2]["official_status"]))

    def test_same_number_is_looked_up_once_for_all_articles(self):
        rows = [self._文章("按财政部 税务总局公告2023年第19号执行") for _ in range(3)]
        stats, calls = self._核对(rows, 库里=[dict(self.有效件)])
        self.assertEqual(1, len(calls), calls)
        self.assertEqual(1, stats["checked"], stats)
        self.assertEqual(3, stats["by_outcome"]["effective"], stats)
        self.assertEqual({r["official_status"]["title"] for r in rows},
                         {self.有效件["title"]})

    def test_statutory_rows_are_left_alone(self):
        """法定层自己有 status 字段可判时效，不该被这一层重复劳动一遍。"""
        法 = {"title": "中华人民共和国车辆购置税法", "category": "法律",
              "status": "现行有效", "url": "http://x/law"}
        stats, calls = self._核对([法, self._文章("按2023年第19号执行")],
                                  库里=[dict(self.有效件)])
        self.assertNotIn("official_status", 法)
        self.assertEqual(["2023年第19号"], calls)
        self.assertEqual({"effective": 1}, stats["by_outcome"], stats)

    def test_practice_recognition_shares_the_graders_vocabulary(self):
        """认源用 `tax_evidence.PRACTICE_MARKS`：这里各写一套源名就会静默空转。

        实测过的三种真实形态都要认出来——税屋的标签、公众号的标签、360 回填的纯域名。
        """
        for src in ("税屋 (shui5.cn)", "微信公众号", "shui5.cn"):
            row = self._文章("按财税〔2016〕36号执行", source=src)
            self.assertTrue(ANS._is_practice_row(row), src)
        self.assertFalse(ANS._is_practice_row(
            {"title": "车辆购置税法", "source": "🏛️ 国家税务总局"}))

    def test_official_qa_rows_are_practice_in_both_places(self):
        """官方答复栏目在两处判据里都是实务层，一处判出另一条必然判出。

        本轮实跑漏的就是这一类：税务总局货物和劳务税司政策问答那一条（法规库
        政策问答栏目，URL 栏目段 c100024）带着文号，而 `_is_practice_row` 只按
        税屋与公众号的源名认，核对首跑回 `{"checked": 0, "skipped": 0}`；同一条
        在 `rank_of` 那里也只判成"未定性"。两处现在都走
        `tax_evidence.is_practice_layer` 与同一份 `PRACTICE_MARKS`。
        """
        问答 = {"title": "货物和劳务税司政策问答：留抵退税的办理口径",
                "source": "税务总局法规库",
                "url": "https://fgk.chinatax.gov.cn/zcfgk/c100024/c5245218/content.html",
                "content": "依据财政部 税务总局公告2023年第19号，留抵退税按此办理"}
        答疑 = {"title": "12366 答疑：印花税税目税率表怎么用",
                "source": "国家税务总局",
                "url": "https://www.chinatax.gov.cn/12366/zcwd.html",
                "content": "按《印花税法》所附税目税率表执行"}
        for row in (问答, 答疑):
            self.assertTrue(ANS._is_practice_row(row), row["title"])
            r = E.rank_of(row["title"], "", E.practice_text(row))
            self.assertIn(r["rank"], E.PRACTICE_RANKS, r["by"])
            self.assertEqual("practice", E.role_of(r["rank"], "effective", True))
        # 认出来还得真去查：这一条带着文号，核对必须发出去
        stats, calls = self._核对([问答], 库里=[dict(self.有效件)])
        self.assertEqual(["财政部 税务总局公告2023年第19号"], calls)
        self.assertEqual(1, stats["checked"], stats)
        self.assertEqual("effective", 问答["official_status"]["outcome"], stats)
        # 反向：法规库里的文件本体不被这套判据拉进实务层
        本体 = {"title": "中华人民共和国印花税法", "source": "税务总局法规库",
                "url": "https://fgk.chinatax.gov.cn/zcfgk/c100009/c5000000/content.html"}
        self.assertFalse(ANS._is_practice_row(本体), "政策问答的标记不能把法律本体认成实务")
        self.assertEqual("law", E.rank_of(本体["title"], "", E.practice_text(本体))["rank"])

    def test_nine_outcomes_are_all_reachable_and_each_has_a_sentence(self):
        """九种结果逐一跑出来，一种都不许只在表里挂着。

        这是这套用例自己的覆盖率检查：`OFFICIAL_CAVEAT` 里多一条却没有场景能产出它，
        就说明本层的分支已经和文档对不上；少一条则这里直接红。
        """
        库 = {"results": [dict(self.有效件)]}
        seen = set()

        def 跑(rows, **kw):
            ANS.check_practice_citations(rows, at="2026-09-29", **kw)
            seen.update(r["official_status"]["outcome"] for r in rows
                        if r.get("official_status"))

        def 库内(status):
            return lambda t: {"results": [dict(self.有效件, status=status)]}

        # 库里查到了这一份的四种时效（结果名直接取 `judge_validity` 的取值）
        for status in ("现行有效", "全文废止", "尚未生效", ""):
            跑([self._文章("按财政部 税务总局公告2023年第19号执行")],
               lookup=库内(status))
        # 库里没有同一份 / 正文没写文号 / 没取正文 / 库没连上 / 轮次用满
        跑([self._文章("按财税〔1999〕43号执行")], lookup=lambda t: {"results": []})
        跑([self._文章("只讲口径，没引文号")], lookup=lambda t: 库)
        跑([self._文章()], lookup=lambda t: 库)
        跑([self._文章("按2023年第19号执行")],
           lookup=lambda t: {"_error": "超时", "_fetch_failed": True})
        跑([self._文章(f"依据国家税务总局公告202{i}年第5号执行") for i in range(1, 4)],
           lookup=lambda t: 库, limit=1)
        self.assertEqual(set(E.OFFICIAL_CAVEAT), seen,
                         f"用例产出的结果与提醒表不一致：{sorted(seen)}")
        self.assertEqual(set(E.OFFICIAL_CAVEAT), set(E.OFFICIAL_OUTCOME_LABEL),
                         "两张表必须同键，否则汇总句里会漏出英文键名")
        for key, tpl in E.OFFICIAL_CAVEAT.items():
            self.assertTrue(E.official_caveat({"outcome": key}),
                            f"{key} 的提醒句格式化后为空")

    def test_every_outcome_literal_in_the_producer_has_a_caveat(self):
        """新增核对结果却忘了配句子时，提醒会静默消失——这条拦字面量那一类漏配。

        不跑代码，只读源码：把 `check_practice_citations` 里所有写进字典值的
        小写英文字面量取出来（结果名都是这个形态），逐个要求在两张表里有条目。
        时效那四种结果名来自 `judge_validity` 的取值，不在这个函数里写字面量，
        由上面那条用例逐场景覆盖。
        """
        src = Path(ANS.__file__).read_text(encoding="utf-8")
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "check_practice_citations")
        emitted = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Dict):
                for v in node.values:
                    for s in ([v.value] if isinstance(v, ast.Constant) else
                              ([v.body.value, v.orelse.value]
                               if isinstance(v, ast.IfExp)
                               and all(isinstance(x, ast.Constant)
                                       for x in (v.body, v.orelse)) else [])):
                        if isinstance(s, str) and re.fullmatch(r"[a-z][a-z_]{3,}", s):
                            emitted.add(s)
        self.assertTrue(emitted, "没从源码里取出任何结果字面量，用例失效了")
        self.assertEqual(set(), emitted - set(E.OFFICIAL_CAVEAT),
                         f"这些结果没有提醒句：{sorted(emitted - set(E.OFFICIAL_CAVEAT))}")

    def test_unknown_outcome_is_not_silently_dropped(self):
        """认不出的结果要报出来，不能和"没核对过"共用一个空串。"""
        line = E.official_caveat({"outcome": "someday", "doc_number": "2023年第19号"})
        self.assertIn("someday", line)
        self.assertEqual("", E.official_caveat({}))


class TestCitationCheckReachesTheAnswer(unittest.TestCase):
    """核对要一路走到答案输出，不能停在 gather 的字典里。"""

    # 判成 lookup 的问句只走 npc/fgk 两轮，永远碰不到税屋那一轮，这一层就没得核对；
    # 换成算税题，第 3 轮才是实务材料源。
    Q = "增值税小规模纳税人月销售额10万，应纳增值税多少"

    def _跑一趟(self, check_citations=True, with_practice=True):
        文 = {"title": "新能源车购置税免税口径", "source": "税屋 (shui5.cn)",
              "url": "https://www.shui5.cn/article/9/1.html",
              "content": "依据财政部 税务总局公告2023年第19号免征"}
        法 = {"title": "中华人民共和国车辆购置税法", "category": "法律",
              "status": "现行有效", "url": "http://x/law"}
        库 = {"results": [{"title": "财政部 税务总局关于减征车辆购置税的公告",
                          "document_number": "财政部 税务总局公告2023年第19号",
                          "status": "现行有效", "url": "http://x/19"}]}
        calls = []

        def fake_fgk(term, size=5, **rest):
            calls.append(term)
            return dict(库)

        def make(src):
            """按源发桩：返回 fetcher，取数契约是 (条目, 失败说明, 逐枚没取全的说明)。"""
            if src == "shui5":
                return lambda term, size: ([dict(文)] if with_practice else [], "", "")
            if src == "npc":
                return lambda term, size: ([dict(法)], "", "")
            return lambda term, size: ([], "", "")

        with mock.patch.dict(ANS._FETCHERS,
                             {s: make(s) for s in ("npc", "fgk", "shui5",
                                                   "wechat", "legis")}), \
             mock.patch.object(FGK, "search_fgk", fake_fgk):
            return ANS.gather(self.Q, at="2026-09-29",
                              check_citations=check_citations), calls

    def test_gather_records_progress_and_compose_says_it(self):
        plan, calls = self._跑一趟()
        self.assertEqual(["财政部 税务总局公告2023年第19号"], calls)
        self.assertEqual(1, plan["citation_check"]["checked"], plan["citation_check"])
        a = ANS.compose(plan)
        self.assertIn("税务总局法规库核对 1 个", a["citation_note"], a["citation_note"])
        self.assertIn("在库且现行有效 1 条", a["citation_note"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ANS._print_answer(a)
        self.assertIn("文号已回税务总局法规库核对", out.getvalue())

    def test_turning_the_check_off_leaves_a_visible_empty_not_a_fake_zero(self):
        plan, calls = self._跑一趟(check_citations=False)
        self.assertEqual([], calls)
        self.assertIsNone(plan["citation_check"])
        self.assertEqual("", ANS.compose(plan)["citation_note"])

    def test_no_practice_row_says_none_needed_instead_of_nothing_found(self):
        """一道纯法条题：这一栏要说"没有文号需要核对"，不是留空让人猜。"""
        plan, calls = self._跑一趟(with_practice=False)
        self.assertEqual([], calls)
        self.assertEqual({"checked": 0, "skipped": 0, "by_outcome": {}},
                         plan["citation_check"])
        note = ANS.compose(plan)["citation_note"]
        self.assertIn("没有取回税屋或公众号的文章", note)


# ── ②'' 税屋：正文收口、续页读到末页、站内检索这一路 ──────────────────────
# 下面三份 DOM 全部照 2026-10-18 实测的站点结构搭：
#   文章页  <div class="arcContent"> 之后紧跟 <div class="left2e">（点赞＋分享＋扫码块），
#           再往后才是 left2b 相关阅读、pagebreak 页码区
#   结果页  每行 <div class="xwt2">，标题在 xwt2_a>a 的 title 属性里（带 <font> 高亮），
#           摘要 xwt2_c>p.p1、日期 <p class="p3">、栏目 <p class="p4"><a>
#   提示页  文案两种：「没有搜索到相关的内容」＝这一轮没命中，
#           「系统限制的搜索时间间隔为 2 秒,请稍后再搜索」＝请求太密（两者只差 31 字节）
class _Resp:
    def __init__(self, html, url="", status=200):
        self.content = html.encode("utf-8")
        self.text = html
        self.url = url
        self.status_code = status


def _article_page(body, own_pages=(), other_pages=(), with_share=True):
    """搭一篇文章页。own_pages 是本篇 pagebreak 里列出的页码。"""
    links = " ".join(
        '<a href="https://www.shui5.cn/article/42/70138%s.html">%d</a>'
        % (("" if n == 1 else "$%d" % n), n) for n in own_pages)
    others = " ".join('<a href="https://www.shui5.cn/article/9/%d$2.html">x</a>' % i
                      for i in other_pages)
    share = ('<div class="left2e"><div class="diggnum">点赞（）</div>'
             '<div class="showshare">微信 微博</div>'
             '<div class="qrcode_wrap hidden">× 用微信扫码二维码 分享至好友和朋友圈</div></div>'
             if with_share else "")
    return ('<html><body><h1>测试文章</h1>'
            '<div class="articleResource">时间：2026-08-10</div>'
            '<div class="articleDes">这是摘要</div>'
            '<div class="arcContent"><p>%s</p></div>'
            '%s'
            '<div class="left2b">相关阅读 %s</div>'
            '<div class="pagebreak">本文章更多内容：%s</div>'
            '</body></html>' % (body, share, others, links))


class _ReadSession:
    """按 URL 发页面的假会话；记下请求顺序，代码要了没准备的地址就直接 KeyError。"""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []
        self.cookies = type("_C", (), {"set": lambda *a, **k: None})()

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self.pages[url]


P1 = "https://www.shui5.cn/article/42/70138.html"


def _pp(n):
    return P1 if n == 1 else "https://www.shui5.cn/article/42/70138$%d.html" % n


class TestShui5BodyBoundary(unittest.TestCase):
    """P2：正文容器后面第一个兄弟容器是 left2e，旧边界没有它，抽样 12 篇尾部全混入。"""

    def test_share_block_is_cut_off(self):
        art = SH._parse_article(
            _article_page("正文第一段", own_pages=(1, 2)), P1)
        self.assertEqual("正文第一段", art["content"], repr(art["content"]))
        for noise in ("点赞", "分享至好友和朋友圈", "相关阅读", "本文章更多内容"):
            self.assertNotIn(noise, art["content"])

    def test_old_boundary_names_still_work_as_backups(self):
        """站点改版把 left2e 换掉时，left2b / blank20 还该收得住。"""
        page = ('<div class="arcContent"><p>正文</p></div>'
                '<div class="blank20"></div><div class="left2b">别的</div>')
        self.assertEqual("正文", SH._parse_article(page, P1)["content"])

    def test_meta_and_title_still_parsed_after_the_change(self):
        art = SH._parse_article(_article_page("正文", own_pages=(1,)), P1)
        self.assertEqual("测试文章", art["title"])
        self.assertEqual("2026-08-10", art["date"])
        self.assertEqual("这是摘要", art["summary"])


class TestShui5ContinuationPages(unittest.TestCase):
    """P1：长文按本篇 ID 枚举续页读到末页；越界页被站点钳回已有内容，不靠 404 试探。"""

    def _fetch(self, pages, **kw):
        sess = _ReadSession(pages)
        return SH.fetch_shui5(P1, session=sess, page_interval=0, **kw), sess

    def test_reads_every_page_listed_for_this_article(self):
        sess_pages = {
            _pp(1): _Resp(_article_page("第一段", own_pages=(1, 2, 3))),
            _pp(2): _Resp(_article_page("第二段", own_pages=(1, 2, 3))),
            _pp(3): _Resp(_article_page("第三段", own_pages=(1, 2, 3))),
        }
        art, sess = self._fetch(sess_pages)
        self.assertEqual(3, art["pages"])
        self.assertEqual("第一段\n第二段\n第三段", art["content"])
        self.assertEqual([_pp(1), _pp(2), _pp(3)], sess.requested,
                          "页码只到 3，不该再去要 $4")
        self.assertNotIn("_pages_error", art)

    def test_clamped_page_beyond_the_end_is_never_appended(self):
        """实测 $4、$5 回 200 与同一份正文：文本重复即到底，不拼第二份、不计页数。"""
        sess_pages = {
            _pp(1): _Resp(_article_page("第一段", own_pages=(1, 2, 3))),
            _pp(2): _Resp(_article_page("第二段", own_pages=(2, 3, 4))),
            _pp(3): _Resp(_article_page("第三段", own_pages=(3, 4))),
            _pp(4): _Resp(_article_page("第三段", own_pages=(4, 5))),  # 钳回第三段
        }
        art, sess = self._fetch(sess_pages)
        self.assertEqual(3, art["pages"], art)
        self.assertEqual(1, art["content"].count("第三段"), art["content"])
        self.assertEqual([_pp(1), _pp(2), _pp(3), _pp(4)], sess.requested)

    def test_other_articles_page_links_do_not_make_a_single_page_article_multi_page(self):
        """相关阅读里混着别人文章的 $2 链接：按链接形态数会把单页文章判成分页文章。"""
        art, sess = self._fetch({_pp(1): _Resp(
            _article_page("只有第一段", own_pages=(1,), other_pages=(111, 222)))})
        self.assertEqual(1, art["pages"])
        self.assertEqual([_pp(1)], sess.requested)
        self.assertEqual("只有第一段", art["content"])

    def test_window_style_page_list_expands_while_reading(self):
        """页码区只列相邻几页时，读一页就把新页码并进队列，不能停在第 2 页。"""
        sess_pages = {
            _pp(1): _Resp(_article_page("第一段", own_pages=(1, 2))),
            _pp(2): _Resp(_article_page("第二段", own_pages=(2, 3))),
            _pp(3): _Resp(_article_page("第三段", own_pages=(3,))),
        }
        art, _ = self._fetch(sess_pages)
        self.assertEqual(3, art["pages"], art)
        self.assertEqual("第一段\n第二段\n第三段", art["content"])

    def test_a_page_that_cannot_be_read_stops_and_says_where(self):
        """中间某一页取不到：正文停在已读部分并留原因，不能整篇当没有。"""
        sess_pages = {
            _pp(1): _Resp(_article_page("第一段", own_pages=(1, 2, 3))),
            _pp(2): _Resp("", status=404),
        }
        art, sess = self._fetch(sess_pages)
        self.assertEqual("第一段", art["content"])
        self.assertEqual(1, art["pages"])
        self.assertIn("第 2 页取不到", art["_pages_error"])
        self.assertIn("正文止于第 1 页", art["_pages_error"])
        self.assertNotIn(_pp(3), sess.requested)

    def test_page_cap_stops_the_loop(self):
        sess_pages = {_pp(n): _Resp(_article_page("第%d段" % n,
                                                  own_pages=tuple(range(1, 9))))
                      for n in range(1, 9)}
        art, sess = self._fetch(sess_pages, max_pages=3)
        self.assertEqual(3, art["pages"])
        self.assertEqual(3, len(sess.requested))


class TestShui5NativeSearch(unittest.TestCase):
    """P0：站内原生检索——行解析、总数、两份提示页、翻页去重。"""

    RESULT_URL = SH.SEARCH_RESULT + "?page=0&searchid=12345"

    def _row(self, n, url=None, column="税收问答"):
        return ('<div class="xwt2">'
                '<div class="xwt2_a"><a href="%s" title="留抵<font color=\'red\'>退税</font>口径%d"'
                '>\u53ef\u89c1\u6587\u672c%d</a></div>'
                '<div class="xwt2_c"><p class="p1">摘要%d<font color=\'red\'>词</font></p></div>'
                '<div class="xwt2_d"><p class="p1">来源</p></div>'
                '<p class="p3">2026-08-%02d</p>'
                '<p class="p4"><a href="/e/action/ListInfo/?classid=9">%s</a></p>'
                '</div>' % (url or "https://www.shui5.cn/article/42/%d.html" % (100 + n),
                            n, n, n, n + 1, column))

    def _result_page(self, rows, total=420):
        return ("<div>%d条关于 留抵退税 的搜索结果</div>%s" % (total, "".join(rows)))

    def test_rows_carry_date_column_and_clean_title(self):
        rows = SH._search_rows(self._result_page([self._row(1), self._row(2)]))
        self.assertEqual(2, len(rows))
        self.assertEqual("留抵退税口径1", rows[0]["title"], rows[0]["title"])
        self.assertEqual("2026-08-02", rows[0]["date"])
        self.assertEqual("税收问答", rows[0]["column"])
        self.assertEqual("摘要1词", rows[0]["snippet"])
        self.assertEqual("https://www.shui5.cn/article/42/101.html", rows[0]["url"])
        # 两条通道共用行形状：搜狗那一路给的键，站内这路必须全有；栏目是站内独有
        self.assertEqual({"title", "url", "date", "snippet", "source",
                          "source_label", "column"}, set(rows[0]))

    def test_total_count_sentence_is_read(self):
        t = SH._TOTAL_RE.search("420条关于 留抵退税 的搜索结果")
        self.assertEqual("420", t.group(1))

    def _search(self, pages, size=5, keyword="留抵退税"):
        """pages: 依次回给 post 的页面；get 按 URL 取。"""

        class S:
            def __init__(self, posts, gets, landing):
                self.posts, self.gets, self.landing = list(posts), gets, landing
                self.post_urls = []
                self.get_urls = []

            def post(self, url, **kwargs):
                self.post_urls.append(url)
                return _Resp(self.posts.pop(0), url=self.landing)

            def get(self, url, **kwargs):
                self.get_urls.append(url)
                return _Resp(self.gets[url])

        s = S(pages.get("posts", []), pages.get("gets", {}), self.RESULT_URL)
        return SH.search_native(keyword, size=size, session=s, gap=0), s

    def test_no_result_marker_means_zero_rows_not_a_failed_channel(self):
        r, _ = self._search({"posts": ["<div>%s</div>" % SH.NO_RESULT_MARK], "gets": {}})
        self.assertEqual([], r["results"])
        self.assertEqual(0, r["total"])
        self.assertTrue(r["_status"].startswith("0 条"), r["_status"])

    def test_zero_hit_status_hands_both_causes_to_the_caller(self):
        r, _ = self._search({"posts": ["<div>%s</div>" % SH.NO_RESULT_MARK], "gets": {}})
        self.assertIn("两种成因分不开", r["_status"],
                      "同一份页面既是真零命中也可能是参数被拒，归因要随读数交出去")
        self.assertIn("站内确实没有", r["_status"])
        self.assertIn("不接受", r["_status"])

    def test_rate_limit_marker_retries_once_and_can_still_come_back_empty(self):
        limit = "<div>%s,请稍后再搜索</div>" % SH.RATE_LIMIT_MARK
        r, s = self._search({"posts": [limit, "<div>%s</div>" % SH.NO_RESULT_MARK],
                             "gets": {}})
        self.assertEqual(2, len(s.post_urls), "限流只该重发一次")
        self.assertEqual(0, r["total"])
        self.assertTrue(r["_status"].startswith("0 条"), r["_status"])

    def test_still_limited_after_the_retry_is_reported_as_not_walked(self):
        limit = "<div>%s,请稍后再搜索</div>" % SH.RATE_LIMIT_MARK
        r, s = self._search({"posts": [limit, limit], "gets": {}})
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
        self.assertIsNone(r["total"], "限流轮不能报成 0 条")

    def test_waf_challenge_is_reported_as_not_walked(self):
        page = ('<textarea id="renderData">{"arg1":"%s"}</textarea>' % ("A" * 40))
        r, _ = self._search({"posts": [page], "gets": {}})
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
        self.assertIn("WAF", r["_status"])

    def test_pages_are_walked_and_duplicates_dropped(self):
        posts = [self._result_page([self._row(1)], total=3)]
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=12345":
                self._result_page([self._row(2), self._row(1)]),   # 第 1 条重复
                SH.SEARCH_RESULT + "?page=2&searchid=12345":
                self._result_page([self._row(3)])}
        r, s = self._search({"posts": posts, "gets": gets}, size=3)
        self.assertEqual(["留抵退税口径1", "留抵退税口径2", "留抵退税口径3"],
                         [x["title"] for x in r["results"]],
                         "翻页要接着落点页往后取，重复的那条不能算新结果")
        # 落点页本身就是 page=0，往后从 1 起翻——再请求一次 0 会把首屏那行当新结果重复收
        self.assertEqual([SH.SEARCH_RESULT + "?page=1&searchid=12345",
                          SH.SEARCH_RESULT + "?page=2&searchid=12345"], s.get_urls)
        self.assertEqual(3, r["total"], "站点报的总条数原样带出")
        self.assertIn("这一词站内共 3 条", r["_status"])


class TestSogouWebSearch(unittest.TestCase):
    """搜狗那一路的解析与失败分流：反爬、零结果、结构改版不能混成"0 条"。"""

    WEB = "https://www.sogou.com/web?query=x"

    def setUp(self):
        # 预算、熔断与缓存都是跨进程共享的真实状态；用例必须各用各的临时盘，
        # 否则一条用例触发的熔断会把后面的用例一并挡住。
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (("_STATE_PATH", Path(tmp.name) / "state.json"),
                            ("_cache", tax_cache.CacheManager(enabled=False)),
                            ("SEARCH_MIN_GAP", 0)):
            patcher = mock.patch.object(SOG, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _block(self, title, url, cite="2026-06-16", snippet="摘要"):
        return ('<div class="vrwrap">'
                '<h3 class="vr-title  "><a href="/link?url=abc"><em>研发费用</em>'
                + title + '</a></h3>'
                '<div class="img-flex"></div>'
                '<div class="fz-mid space-txt">' + snippet + '</div>'
                '<div class="r-sech" data-url="' + url + '"></div>'
                '<a class="citeLinkClass"><img class="footerIcon" src="x">'
                '<span>税屋</span><span>https://www.shui5.cn/a...</span>'
                + ('<span class="cite-date">' + cite + '</span>' if cite else '') +
                '</a></div>')

    def _search(self, html, site="shui5.cn", size=10, final=None):
        with mock.patch.object(SOG, "_fetch",
                               return_value=(html, final or self.WEB, "", False)):
            return SOG.sogou_search("研发费用加计扣除", site=site, size=size)

    def _mobile(self, title, url, cite="2026-06-16", snippet="摘要", quote='"'):
        from urllib.parse import quote as encode

        return (f"<div class={quote}vrResult{quote}><h3 class=vr-tit>"
                f'<a class=resultLink href="/tc?url={encode(url, safe="")}&amp;linkid=title">'
                f"<em>{title}</em></a></h3><div class=citeurl>{cite}</div>"
                f"<a class='txt-summary space-txt'>{snippet}</a></div>")

    def test_mobile_quote_variants_extract_full_metadata(self):
        for quote in ('"', "'", ""):
            with self.subTest(quote=quote):
                html = self._mobile("研发费用 &amp; 扣除", P1, quote=quote,
                                    snippet="甲" * 260 + " <em>末段</em>")
                row = self._search(html)["results"][0]
                self.assertEqual("研发费用 & 扣除", row["title"])
                self.assertEqual(P1, row["url"])
                self.assertEqual("2026-06-16", row["date"])
                self.assertEqual("甲" * 260 + " 末段", row["snippet"])

    def test_mobile_dates_do_not_use_summary_or_invalid_calendar_dates(self):
        for cite, expected in (("", ""), ("2026-02-30", ""),
                               ("1995-01-27", "1995-01-27"),
                               ("2024-01-01.html 2025-03-05", "2025-03-05")):
            with self.subTest(cite=cite):
                html = self._mobile("标题", P1, cite=cite, snippet="2020-01-01 验证码说明")
                self.assertEqual(expected, self._search(html)["results"][0]["date"])
                self.assertFalse(SOG._looks_like_verify_page(html))

    def test_mobile_ignores_non_article_links_and_normalizes_duplicates(self):
        html = ('<div class=vrResult><a class=resultLink href="/tc?url=https%3A%2F%2Fexample.com">'
                '推荐词</a></div><div class=vrResult><h3>广告</h3>'
                '<a href="/ad">推广</a></div>')
        html += self._mobile("甲", "https://www.shui5.cn/article/90/40872.html")
        html += self._mobile("乙", "https://www.shui5.cn/article/90/40872$2.html")
        rows, raw, area = SOG._parse(html, size=100)
        self.assertTrue(area)
        self.assertEqual(2, raw)
        self.assertEqual(1, len(rows))
        self.assertEqual("甲", rows[0]["title"])

    def test_mobile_host_filter_rejects_spoofed_domains_and_non_http_urls(self):
        targets = ("https://shui5.cn.evil.test/a", "https://evil.test/?site=shui5.cn",
                   "https://shui5.cn@evil.test/a", "https://notshui5.cn/a",
                   "javascript:alert(1)", "https://[broken/a", "https://m.sogou.com/a")
        html = "".join(self._mobile("站外", url) for url in targets)
        html += self._mobile("站内", "https://sub.shui5.cn/a?x=1&y=2")
        rows = self._search(html)["results"]
        self.assertEqual(["https://sub.shui5.cn/a?x=1&y=2"], [row["url"] for row in rows])

    def test_mobile_result_area_with_zero_marker_is_not_cached_as_empty(self):
        html = '<div class=vrResult><h3>没有找到直链</h3></div>'
        out = self._search(html)
        self.assertIn("结构可能改版", out["_error"])

    def test_mobile_class_name_in_script_is_not_a_result_area(self):
        html = '<script>const template="vrResult";</script><p>请输入验证码</p>'
        self.assertTrue(SOG._looks_like_verify_page(html))
        self.assertFalse(SOG._parse(html)[2])
        desktop = '<script>const template="vrResult";</script>' + self._block("标题", P1)
        self.assertEqual(1, len(self._search(desktop)["results"]))

    def test_mobile_multiple_citation_lines_keep_the_date(self):
        html = self._mobile("标题", P1, cite="国家税务总局 权威机构")
        html = html.replace("</h3>", "</h3><div class=citeurl>2011-02-23</div>")
        self.assertEqual("2011-02-23", self._search(html)["results"][0]["date"])

    def _site_none(self, site="shui5.cn", word="增值税", quote='"'):
        """站点在手机入口自报「这个站内没有匹配内容」的那一档（2026-11-26 量到的形状）。"""
        return ('<div class=results><div class={q}vrResult site-vr-none{q}>'
                '<p class=site-text>抱歉，未找到“{s}”站内包含“{w}”的内容</p>'
                '</div></div>').format(q=quote, s=site, w=word)

    def test_site_none_class_is_a_real_zero_not_a_structure_error(self):
        """真 0 条不能被写成取数失败：_zero_hit 在位、_error 不在位。"""
        out = self._search(self._site_none())
        self.assertNotIn("_error", out)
        self.assertFalse(out.get("_fetch_failed"))
        self.assertTrue(out.get("_zero_hit"))
        self.assertEqual([], out["results"])

    def test_a_header_with_no_items_is_still_read_as_a_structure_change(self):
        """有表头没条目那一档（yanfa 页）仍报结构改版，不能被新判据一并吞掉。"""
        html = ('<div class=vrResult><div class=vr-site190910><p class=site-text>'
                '以下是网页“shui5.cn”中包含“研发费用加计扣除”的结果</p></div></div>')
        out = self._search(html)
        self.assertIn("结构可能改版", out["_error"])
        self.assertTrue(out["_fetch_failed"])
        self.assertNotIn("_zero_hit", out)

    def test_the_site_none_name_in_a_script_is_not_a_zero_result(self):
        """类名只出现在脚本里不算站点自报无结果——与 vrResult 同一枚理由。"""
        html = ('<script>var t="site-vr-none vrResult";</script>'
                '<p>请输入验证码</p>')
        self.assertFalse(SOG._declares_no_site_results(html))
        self.assertTrue(SOG._looks_like_verify_page(html))

    def test_a_real_zero_page_gets_cached_but_a_structure_error_does_not(self):
        """真 0 条可以缓存（这一轮跑成了）；结构改版每轮重取，不能把坏页钉住。"""
        cache = tax_cache.CacheManager(enabled=True, namespace="sogou")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache.dir = Path(tmp.name)
        with mock.patch.object(SOG, "_cache", cache):
            with mock.patch.object(SOG, "_fetch",
                                   return_value=(self._site_none(), self.WEB, "", False)):
                first = SOG.sogou_search("增值税", site="shui5.cn", size=5)
            second = SOG.sogou_search("增值税", site="shui5.cn", size=5)
        self.assertTrue(first.get("_zero_hit"))
        self.assertFalse(first.get("_from_cache"))
        self.assertTrue(second.get("_from_cache"), "真 0 条应当被记住")

        with mock.patch.object(SOG, "_cache", cache):
            broken = ('<div class=vrResult><h3>以下是网页“shui5.cn”中包含“甲”的结果</h3></div>')
            with mock.patch.object(SOG, "_fetch",
                                   return_value=(broken, self.WEB, "", False)):
                bad = SOG.sogou_search("甲", site="shui5.cn", size=5)
                again = SOG.sogou_search("甲", site="shui5.cn", size=5)
        self.assertIn("结构可能改版", bad["_error"])
        self.assertFalse(again.get("_from_cache"), "失败的那一轮不该进缓存")

    def test_the_split_class_named_in_code_is_the_one_documented(self):
        """分流用的 class 串改了而文档没跟上，这一条要报红（判定值不许漂）。"""
        code = (ROOT / "scripts" / "tax_sogou.py").read_text(encoding="utf-8")
        m = re.search(r'_SITE_NONE_CLASS = "([^"]+)"', code)
        self.assertTrue(m, "tax_sogou 里的分流常量不在了")
        note = (ROOT / "search_source" / "sogou" / "NOTE.md").read_text(encoding="utf-8")
        self.assertIn(m.group(1), note,
                      "代码认的 class 与 NOTE 记的不是同一串")
        self.assertIn(m.group(1), (ROOT / "search_source" / "shui5" / "NOTE.md")
                      .read_text(encoding="utf-8"))

    def test_full_page_cache_is_shared_across_requested_sizes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = tax_cache.CacheManager(enabled=True, namespace="sogou")
        cache.dir = Path(tmp.name)
        for mobile in (True, False):
            with self.subTest(mobile=mobile):
                build = self._mobile if mobile else self._block
                html = "".join(build(f"标题{i}", f"https://www.shui5.cn/article/42/{i}.html")
                               for i in range(12))
                with mock.patch.object(SOG, "_cache", cache), mock.patch.object(
                        SOG, "_fetch", return_value=(html, self.WEB, "", False)) as hit:
                    outputs = [SOG.sogou_search(f"缓存查询{mobile}", site="shui5.cn", size=n)
                               for n in (1, 5, 100)]
                self.assertEqual(1, hit.call_count)
                self.assertEqual([1, 5, 12], [out["total"] for out in outputs])
                self.assertEqual([False, True, True], [out["_from_cache"] for out in outputs])
                self.assertEqual(1, len({out["searched_at"] for out in outputs}))

    def test_invalid_size_is_rejected_before_network(self):
        with mock.patch.object(SOG, "_fetch") as hit:
            for value in (0, -1, True, 1.5, "10", None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    SOG.sogou_search("增值税", size=value)
        hit.assert_not_called()

    def test_only_server_errors_are_retried(self):
        for status in (201, 400, 401, 404, 500, 503):
            with self.subTest(status=status):
                response = type("R", (), {"status_code": status,
                    "url": self.WEB, "headers": {}, "content": b""})()
                with mock.patch.object(SOG, "_get", return_value=response) as hit, \
                        mock.patch.object(SOG.time, "sleep") as wait:
                    _, _, error, blocked = SOG._fetch("离线查询")
                expected = SOG.MAX_RETRIES if status >= 500 else 1
                self.assertEqual(expected, hit.call_count)
                self.assertEqual(expected - 1, wait.call_count)
                self.assertIn(f"HTTP {status}", error)
                self.assertFalse(blocked)

    def test_network_failure_can_retry_and_recover(self):
        response = type("R", (), {"status_code": 200,
            "url": self.WEB, "headers": {}, "content": b"ok"})()
        with mock.patch.object(SOG, "_get", side_effect=[
                SOG.requests.ConnectionError("offline"), response]) as hit, \
                mock.patch.object(SOG.time, "sleep") as wait:
            html, _, error, blocked = SOG._fetch("离线查询")
        self.assertEqual(("ok", "", False), (html, error, blocked))
        self.assertEqual(2, hit.call_count)
        wait.assert_called_once_with(1.5)

    def test_mobile_challenge_does_not_retry_switch_endpoint_or_wait(self):
        class R:
            status_code = 302
            url = SOG.SEARCH_URL % "x"
            headers = {"Location": "https://m.sogou.com/antispider/?antip=wap_hd"}

        with mock.patch("requests.Session.get", return_value=R()) as hit, \
                mock.patch.object(SOG.time, "sleep") as wait:
            first = SOG.sogou_search("查询甲")
            second = SOG.sogou_search("查询乙")
        self.assertTrue(first["_blocked"] and second["_blocked"])
        self.assertEqual(1, hit.call_count)
        self.assertTrue(hit.call_args.args[0].startswith("https://m.sogou.com/web/searchList.jsp?"))
        self.assertFalse(hit.call_args.kwargs["allow_redirects"])
        wait.assert_not_called()

    def test_rows_carry_title_date_and_normalized_url(self):
        out = self._search(self._block(
            "加计扣除常见误区_税屋——第一时间传递财...",
            "https://www.shui5.cn/article/90/40872$2.html"))
        self.assertEqual(1, out["total"])
        row = out["results"][0]
        self.assertEqual("研发费用加计扣除常见误区_税屋——第一时间传递财...", row["title"])
        self.assertEqual("https://www.shui5.cn/article/90/40872.html", row["url"],
                         "第 2 页地址要归回首页，否则正文从中间读起")
        self.assertEqual("2026-06-16", row["date"])
        self.assertEqual("摘要", row["snippet"])
        self.assertEqual("shui5.cn", row["source"])

    def test_same_article_listed_on_two_pages_is_one_row(self):
        html = (self._block("甲", "https://www.shui5.cn/article/90/40872.html")
                + self._block("乙", "https://www.shui5.cn/article/90/40872$2.html"))
        out = self._search(html)
        self.assertEqual(1, out["total"], "归一后同一条只该留一行")

    def test_date_comes_from_the_cite_line_not_the_snippet(self):
        html = self._block("甲", P1, cite="", snippet="文中举例 2020-01-01 的口径")
        self.assertEqual("", self._search(html)["results"][0]["date"],
                         "摘要里的日期不是发布日，不能拿来顶")
        html = self._block("甲", P1,
                           cite="https://www.shui5.cn/a/2024-01-01.html 2025-03-05")
        self.assertEqual("2025-03-05", self._search(html)["results"][0]["date"],
                         "引用行里有多个日期时取最后一个（发布日）")

    def test_antispider_redirect_is_blocked_and_not_retried(self):
        class R:
            url = "https://www.sogou.com/antispider/?m=1&antip=web_hd"
            status_code = 200
            content = b""

        with mock.patch.object(SOG, "_get", return_value=R()) as hit:
            out = SOG.sogou_search("增值税", site="shui5.cn")
        self.assertTrue(out.get("_blocked"))
        self.assertIn("反爬", out["_error"])
        self.assertEqual(0, out["total"])
        self.assertEqual(1, hit.call_count, "反爬页重发只会把封禁时间拖长")

    def test_zero_result_page_is_not_an_error(self):
        out = self._search("<html><body>抱歉，站内没有找到能和“x”匹配的内容。</body></html>")
        self.assertEqual(0, out["total"])
        self.assertNotIn("_error", out, "真 0 条要能跟取数失败分开")

    def test_results_area_without_links_is_a_structure_error(self):
        out = self._search('<div class="vrwrap"><h3 class="vr-title">标题</h3></div>')
        self.assertIn("结构可能改版", out["_error"])

    def test_page_without_results_area_or_marker_is_a_verify_page_error(self):
        out = self._search("<html><body>请输入验证码</body></html>")
        self.assertIn("验证页", out["_error"])

    def test_site_filter_drops_other_domains_without_error(self):
        html = (self._block("站外", "https://example.com/a.html")
                + self._block("站内", P1))
        out = self._search(html)
        self.assertEqual(1, out["total"])
        self.assertEqual(P1, out["results"][0]["url"])
        out = self._search(self._block("站外", "https://example.com/a.html"))
        self.assertEqual(0, out["total"], "全被 site: 过滤＝目标站没有，不是取数失败")
        self.assertNotIn("_error", out)

    def test_size_caps_rows(self):
        html = "".join(self._block("标题%d" % i,
                                   "https://www.shui5.cn/article/42/%d.html" % (100 + i))
                       for i in range(3))
        self.assertEqual(2, len(self._search(html, size=2)["results"]))

    def test_antispider_location_trips_the_breaker_without_following(self):
        """302 的 Location 就够判反爬，跟随会把 302 变成 200、还多花一次请求。"""
        seen = {}

        class Sess:
            def get(self, url, **kw):
                seen.update(kw)
                return type("R", (), {
                    "status_code": 302,
                    "url": "https://www.sogou.com/web?query=x",
                    "headers": {"Location": "https://www.sogou.com/antispider/?antip=web_hd"},
                })()

        SOG._get(Sess(), self.WEB)
        self.assertFalse(seen["allow_redirects"])
        self.assertGreater(SOG._read_state()["blocked_until"], time.time())

    def test_active_breaker_refuses_before_any_request(self):
        SOG._write_state({"blocked_until": time.time() + 120})
        with mock.patch("requests.Session.get",
                        side_effect=AssertionError("熔断期内不该发请求")):
            out = SOG.sogou_search("增值税", site="shui5.cn")
        self.assertTrue(out["_blocked"])
        self.assertEqual(0, out["total"])
        self.assertIn("熔断", out["_error"])

    def test_a_gate_wait_timeout_is_a_failure_envelope(self):
        """报告 §5.10：串行闸等超时的 TimeoutError 不许从公共函数穿出去。

        2026-11-27 注入证伪：把 `_fetch` 里那枚 `except TimeoutError` 换成永不发生
        的异常，整族全绿——当时没有任何用例打过这一支。闸被别的进程占住是常态，
        调用方拿到裸异常就等于拿到一次崩溃。
        """
        def angry(*a, **kw):
            raise TimeoutError("等待搜狗串行闸超过 0 秒——说明另有进程正在打搜狗")

        with mock.patch.object(SOG, "_get", side_effect=angry):
            out = SOG.sogou_search("增值税", site="shui5.cn")
        self.assertTrue(out.get("_fetch_failed"), out)
        self.assertFalse(out.get("_zero_hit"))
        self.assertIn("串行闸", out["_error"], out["_error"])

    def test_budget_full_refuses_before_any_request(self):
        now = time.time()
        SOG._write_state({"recent": [now] * SOG.BUDGET_MAX,
                          "last_request_at": now})
        with mock.patch("requests.Session.get",
                        side_effect=AssertionError("预算用尽后不该发请求")):
            out = SOG.sogou_search("增值税", site="shui5.cn")
        self.assertFalse(out.get("_blocked", False),
                         "预算用尽不是站点反爬，别让上层按被拦处理")
        self.assertIn("预算已用尽", out["_error"])

    def test_verify_page_without_result_area_trips_the_breaker(self):
        class R:
            status_code = 200
            url = self.WEB
            headers = {}
            content = b"<html><body>seccodeImage</body></html>"

        with mock.patch.object(SOG, "_get", return_value=R()):
            html, _, err, blocked = SOG._fetch("增值税")
        self.assertEqual("", html)
        self.assertTrue(blocked)
        self.assertIn("验证页", err)
        self.assertGreater(SOG._read_state()["blocked_until"], time.time())

    def test_verify_page_marker_is_narrow(self):
        self.assertFalse(SOG._looks_like_verify_page(
            "<html>没有找到匹配内容，请勿输入验证码</html>"),
            "页面已经说没有结果时，摘要里的验证码字样不能把它推翻")
        self.assertTrue(SOG._looks_like_verify_page("<html>请输入验证码</html>"))

    def test_repeat_query_is_served_from_cache_without_a_second_request(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = tax_cache.CacheManager(enabled=True, namespace="sogou")
        cache.dir = Path(tmp.name)
        html = self._block("甲", P1)
        with mock.patch.object(SOG, "_cache", cache), \
             mock.patch.object(SOG, "_fetch",
                               return_value=(html, self.WEB, "", False)) as hit:
            first = SOG.sogou_search("研发费用加计扣除", site="shui5.cn", size=10)
            second = SOG.sogou_search("研发费用加计扣除", site="shui5.cn", size=10)
        self.assertEqual(1, hit.call_count, "同词同条数的第二次查询不该再花预算")
        self.assertFalse(first["_from_cache"])
        self.assertTrue(second["_from_cache"])
        self.assertEqual(first["results"], second["results"])

    def test_error_is_not_cached(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = tax_cache.CacheManager(enabled=True, namespace="sogou")
        cache.dir = Path(tmp.name)
        with mock.patch.object(SOG, "_cache", cache), \
             mock.patch.object(SOG, "_fetch",
                               return_value=("", self.WEB,
                                             "触发搜狗反爬（antispider）", True)):
            SOG.sogou_search("增值税", site="shui5.cn")
            again = SOG.sogou_search("增值税", site="shui5.cn")
        self.assertFalse(again["_from_cache"])
        self.assertTrue(again["_blocked"], "失败结果不能靠缓存翻成成功或零结果")


class TestSogouMobileDataIsland(unittest.TestCase):
    """2026-11-26 量到的手机入口新形状：结果搬进 `<script type="application/json">`
    数据岛，HTML 里只剩壳。旧解析器只看 `a.resultLink` 的 `url=` 参数，于是
    「有结果区、零直链」被判成页面改版（`_fetch_failed`），而页面里明明躺着六条
    可点直链。这一类钉的是：数据岛要读得出、读不出时旧三支分流不能回归、
    岛上的日期字段有一枚是抓取日不能当发布日。

    依据是当日真页 `tests/fixtures/msogou_dataisland_20261126.html`（脱敏后
    318,013 字节；本机 IP 与会话 qid 与反爬 token 已打码），复现过程见
    search_source/sogou/NOTE.md。
    """

    WEB = "https://www.sogou.com/web?query=x"
    FIX = ROOT / "tests" / "fixtures" / "msogou_dataisland_20261126.html"

    @classmethod
    def setUpClass(cls):
        cls.page = cls.FIX.read_text(encoding="utf-8")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (("_STATE_PATH", Path(tmp.name) / "state.json"),
                            ("_cache", tax_cache.CacheManager(enabled=False)),
                            ("SEARCH_MIN_GAP", 0)):
            patcher = mock.patch.object(SOG, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _search(self, html, site="", size=10):
        with mock.patch.object(SOG, "_fetch",
                               return_value=(html, self.WEB, "", False)):
            return SOG.sogou_search("研发费用加计扣除", site=site, size=size)

    def test_the_real_page_has_islands_and_no_clickable_html_anchor(self):
        """前置事实：这页里 `a.resultLink` 只有百科卡那一枚可用直链。"""
        self.assertGreaterEqual(self.page.count('type="application/json"'), 6)
        rows, raw, area = SOG._parse_mobile(self.page, "", 100)
        self.assertTrue(area)
        self.assertEqual(0, raw)

    def test_islands_are_parsed_into_rows(self):
        rows, raw, area = SOG._parse(self.page, "", 100)
        self.assertTrue(area)
        self.assertEqual(6, raw)
        self.assertEqual(6, len(rows))
        hosts = sorted(r["source"] for r in rows)
        self.assertIn("chinatax.gov.cn", hosts)
        self.assertIn("gov.cn", hosts)
        self.assertTrue(all(r["url"].startswith("http") for r in rows))

    def test_island_titles_and_snippets_have_highlight_tags_stripped(self):
        rows, _, _ = SOG._parse(self.page, "", 100)
        for r in rows:
            with self.subTest(title=r["title"][:24]):
                self.assertNotIn("<em>", r["title"])
                self.assertNotIn("<span>", r["title"])
                self.assertNotIn("<em>", r["snippet"])
        hit = [r for r in rows if "研发费用加计扣除" in r["title"]]
        self.assertTrue(hit, "高亮剥掉后检索词要还在标题里")

    def test_a_sogou_self_link_or_a_domainless_url_is_not_a_result(self):
        """岛层那两道筛（自家域、无域名）也得有用例盯着。

        2026-11-26 注入证伪时发现：把 `_island_rows` 里「非 sogou 域才收」那一行
        整条撤掉，这一类用例全绿——说明当时只钉了「读得到六枚」，没钉「读不出
        百科卡与配置块」。站点自家链接（百科卡、翻页 URL）与没有域名的对象
        （相对路径、空串）都不算结果。
        """
        island = ('<script type="application/json">'
                  + json.dumps({"url": "https://baike.sogou.com/v175633099.htm",
                                "title": "研发费用加计扣除 - 搜狗百科"})
                  + '</script>'
                  + '<script type="application/json">'
                  + json.dumps({"url": "/web/searchList.jsp?keyword=x",
                                "title": "没有域名的相对路径"})
                  + '</script>'
                  + '<script type="application/json">'
                  + json.dumps({"url": "", "title": "空址"})
                  + '</script>')
        rows, raw = SOG._island_rows(island, "")
        self.assertEqual(raw, 0, "自家域与无域名的一枚都不该计数：%r" % raw)
        self.assertEqual(rows, [], "自家域与无域名的一枚都不该交回：%r" % rows)

    def test_island_time_is_not_used_as_a_publish_date(self):
        """岛上的 `showSiteAndDate.time` 不能当发布日印出去：本轮这页里两枚卡片
        （税费知识库、海南那份 2023 年的 PDF 指引）标的是抓取当天，另外几枚标的是
        站点收录/更新时间。宁可留空，也不把一个说不清的日期印进答案。
        """
        self.assertIn('"time":"2026-11-26"', self.page)
        rows, _, _ = SOG._parse(self.page, "", 100)
        self.assertTrue(rows)
        for r in rows:
            with self.subTest(host=r["source"]):
                self.assertEqual("", r["date"])

    def test_a_card_with_the_right_shape_but_not_the_query_is_not_a_result(self):
        """报告 §5.5 的第二道闸：带 `cardInfo` 也不等于这一轮的答案。

        2026-11-27 注入证伪：把 `_island_title_hit` 那一枚查询参数抹成空串（等于
        相关性闸永不生效），整类全绿——站点在推荐位上照样给出结构完整的卡片，
        只查归属查不出它不是这条查询的结果。
        """
        island = ('<script type="application/json">'
                  + json.dumps({"url": "https://www.chinatax.gov.cn/a",
                                "title": "今日税收要闻", "content": "与检索词无关",
                                "cardInfo": {"classId": "30010582"}})
                  + '</script>')
        rows, raw = SOG._island_rows(island, "", "研发费用加计扣除")
        self.assertEqual(0, raw, "不含检索词的推荐卡一枚都不该计数：%r" % raw)
        self.assertEqual([], rows)

    def test_a_recommendation_page_is_a_failure_not_a_zero_hit(self):
        """整页都是推荐位时报取数失败，不交付「站内没这个词」。

        这一支原先写在函数末支——「有结果区、零直链」在那之前就被结构改版那支
        接走了，所以末支那段判据永远不会命中（注入证伪时改坏没报红）。2026-11-27
        把它移到改版那支之前。HTML 卡层被 site: 过滤掉那一路仍判零命中：那是站点
        真给了相关结果、只是不在目标站上。
        """
        html = ('<div class=vrResult>'
                '<script type="application/json">'
                + json.dumps({"url": "https://www.shui5.cn/a",
                              "title": "今日税收要闻", "content": "与检索词无关",
                              "cardInfo": {"classId": "30010582"}})
                + '</script></div>')
        out = self._search(html, site="shui5.cn")
        self.assertTrue(out.get("_fetch_failed"), out)
        self.assertFalse(out.get("_zero_hit"), "推荐位不能交付成站内没货")
        self.assertIn("推荐位", out["_error"], out["_error"])

    def test_site_filter_applies_to_island_rows(self):
        rows = self._search(self.page, site="chinatax.gov.cn")["results"]
        self.assertTrue(rows)
        for r in rows:
            with self.subTest(url=r["url"]):
                self.assertTrue(r["source"].endswith("chinatax.gov.cn"))
        self.assertNotIn("gov.cn", [r["source"] for r in rows])

    def test_sogou_search_returns_rows_instead_of_a_structure_error(self):
        out = self._search(self.page)
        self.assertNotIn("_error", out)
        self.assertNotIn("_fetch_failed", out)
        self.assertEqual(6, out["total"])

    def test_a_json_payload_outside_an_island_tag_is_not_a_result(self):
        """纪律：只在 `type="application/json"` 的容器里读，脚本正文提一句不算。"""
        jsonq = '{"url":"https://www.shui5.cn/a","title":"串里"}'
        html = ('<div class=vrResult><h3>没有找到直链</h3></div>'
                '<script>var hint = ' + jsonq + ';</script>')
        rows, raw, area = SOG._parse(html, "", 10)
        self.assertEqual([], rows)
        self.assertEqual(0, raw)

    def test_malformed_island_json_falls_back_to_the_old_outcome(self):
        """JSON 畸形不许抛异常；抛了就把「改版」升级成崩溃。"""
        html = ('<div class=vrResult><h3>结果区</h3></div>'
                '<script type="application/json">{"url":"https://x.test/a",</script>')
        rows, raw, area = SOG._parse(html, "", 10)
        self.assertEqual([], rows)
        self.assertEqual(0, raw)
        self.assertTrue(area)

    def test_a_real_zero_page_still_reads_as_a_real_zero(self):
        """旧分流不许回归：site-vr-none 仍是 `_zero_hit`，不是失败。"""
        html = ('<div class=results><div class="vrResult site-vr-none">'
                '<p class=site-text>抱歉，未找到“shui5.cn”站内包含“增值税”的内容</p>'
                '</div></div>')
        out = self._search(html, site="shui5.cn")
        self.assertNotIn("_error", out)
        self.assertTrue(out.get("_zero_hit"))

    def test_a_page_with_neither_area_nor_hint_still_says_verify_page(self):
        out = self._search("<html><body>空</body></html>")
        self.assertIn("验证页", out["_error"])
        self.assertTrue(out.get("_fetch_failed"))


class TestShui5ChannelRouting(unittest.TestCase):
    """auto 先走搜狗、它没取到才启浏览器；两条通道各 0 条是"没有"，不是"没取到"。"""

    def _run(self, sogou, native, channel="auto"):
        calls = []

        def fake_sogou(keyword, site="", size=5):
            calls.append("搜狗")
            return sogou

        def fake_native(keyword, size=5, **kw):
            calls.append("站内")
            return native

        with mock.patch.object(SH, "sogou_search", fake_sogou), \
             mock.patch.object(SH, "search_native", fake_native):
            return SH.search_shui5("留抵退税", size=5, channel=channel), calls

    def test_hit_from_sogou_does_not_start_a_browser(self):
        r, calls = self._run({"total": 1,
                              "results": [{"title": "留抵退税实务_税屋——第一时间传递财...",
                                           "url": P1, "date": "2026-06-16", "snippet": "摘要"}]},
                             {"results": [], "total": None, "_status": "没走成：无浏览器"})
        self.assertEqual(["搜狗"], calls)
        self.assertEqual("搜狗", r["_channel"])
        self.assertEqual("未走（指定通道）", r["_channels"]["站内"])
        self.assertEqual("留抵退税实务", r["results"][0]["title"],
                         "搜狗截断的标语后缀也要剥掉")
        self.assertEqual("2026-06-16", r["results"][0]["date"],
                         "搜狗给的发布日期要带进行里")

    def test_sogou_cache_metadata_survives_shui5_routing(self):
        original_time = "2026-01-02 03:04:05"
        for cached in (False, True):
            with self.subTest(cached=cached):
                r, calls = self._run({
                    "results": [{"title": "税屋解读", "url": P1}],
                    "searched_at": original_time, "_from_cache": cached,
                }, {"results": [], "_status": "未走"})
                self.assertEqual(["搜狗"], calls)
                self.assertEqual(original_time, r["searched_at"])
                self.assertEqual(cached, r["_from_cache"])
        r, calls = self._run({
            "results": [], "searched_at": original_time, "_from_cache": True,
        }, {"results": [SH._row_dict("站内解读", P1, "", "")], "_status": "命中 1 条"})
        self.assertEqual(["搜狗", "站内"], calls)
        self.assertFalse(r["_from_cache"])
        self.assertNotEqual(original_time, r["searched_at"])

    def test_blocked_sogou_falls_through_to_native(self):
        r, calls = self._run({"_error": "触发搜狗反爬（antispider），0 条不代表没有匹配结果",
                              "_blocked": True, "results": []},
                             {"results": [SH._row_dict("站内标题", P1, "2026-08-10", "摘要")],
                              "total": 1, "_status": "命中 1 条"})
        self.assertEqual(["搜狗", "站内"], calls)
        self.assertEqual("站内", r["_channel"])
        self.assertEqual(1, r["total"])
        self.assertNotIn("_error", r, "换通道换到了就不该报整体失败")
        self.assertTrue(r["_channels"]["搜狗"].startswith("被拦"))

    def test_forced_channels_each_touch_only_their_own_source(self):
        _, calls = self._run({"total": 0, "results": []},
                             {"results": [], "total": None, "_status": "没走成"},
                             channel="sogou")
        self.assertEqual(["搜狗"], calls)
        _, calls = self._run({"total": 1, "results": [{"title": "t", "url": P1}]},
                             {"results": [], "total": None, "_status": "没走成"},
                             channel="native")
        self.assertEqual(["站内"], calls)

    def test_both_channels_genuinely_empty_is_not_an_error(self):
        r, _ = self._run({"total": 0, "results": []},
                         {"results": [], "total": 0, "_status": "0 条：站点回「没有搜索到相关的内容」"})
        self.assertEqual(0, r["total"])
        self.assertNotIn("_error", r, "两条都跑通、各 0 条＝这一轮没命中，不是取数失败")
        self.assertEqual("", r["_channel"])

    def test_both_channels_failing_says_which_and_why(self):
        r, _ = self._run({"_error": "触发搜狗反爬（antispider）", "_blocked": True,
                          "results": []},
                         {"results": [], "total": None, "_status": "没走成：无浏览器，改纯 HTTP 直连"})
        self.assertIn("两条检索通道都没取到", r["_error"])
        self.assertIn("搜狗 被拦", r["_error"])
        self.assertIn("站内 没走成", r["_error"])

    def test_a_real_zero_from_sogou_is_blamed_as_zero_not_as_failure(self):
        """3.62.40：site-vr-none 那档判成真 0 条后，归因句是「0 条」，不进 failed。"""
        r, calls = self._run({"total": 0, "results": [], "_zero_hit": True},
                             {"results": [SH._row_dict("站内解读", P1, "2026-11-20", "摘要")],
                              "total": 1, "_status": "命中 1 条"})
        self.assertEqual(["搜狗", "站内"], calls, "真 0 条照样退回站内")
        self.assertEqual("0 条", r["_channels"]["搜狗"])
        self.assertNotIn("_error", r)
        self.assertEqual("站内", r["_channel"])

    def test_a_structure_error_from_sogou_still_says_没走成(self):
        """有表头没条目那一档仍是失败：归因句不能与真 0 条混成同一句。"""
        r, calls = self._run({"total": 0, "results": [], "_fetch_failed": True,
                              "_error": "搜狗返回了结果区，但没有解析出可用直链：页面结构可能改版"},
                             {"results": [SH._row_dict("站内解读", P1, "2026-11-20", "摘要")],
                              "total": 1, "_status": "命中 1 条"})
        self.assertEqual(["搜狗", "站内"], calls)
        self.assertTrue(r["_channels"]["搜狗"].startswith("没走成"))


def _xwt2_row(n, column="财税实务"):
    """结果页/栏目页/标签页共用的那一行 HTML，编号进 URL 保证每行地址唯一。"""
    return ('<div class="xwt2"><div class="xwt2_a">'
            '<a href="https://www.shui5.cn/article/42/%d.html" title="标题%d">可见%d</a></div>'
            '<div class="xwt2_c"><p class="p1">摘要%d</p></div>'
            '<p class="p3">2026-08-%02d</p>'
            '<p class="p4"><a href="/e/action/ListInfo/?classid=9">%s</a></p></div>'
            % (n, n, n, n, n % 28 + 1, column))


def _list_page(start, count, total):
    return ("<div>%d条关于 增值税 的搜索结果</div>%s"
            % (total, "".join(_xwt2_row(i) for i in range(start, start + count))))


class TestShui5ScopedSearch(unittest.TestCase):
    """限定参数那一组（栏目 / 区间 / 匹配域 / 取全）的换算、下推与归因。

    用例只钉关系，不钉站点某天报的总数：逗号两栏 == 两单栏之和、只给起始 == 没限定、
    取全翻到总数那一页为止——换词换天都成立，具体读数会过期。
    """

    TABLE = [
        {"dir": "BeiJingShiCaiShuiFaGui", "nav": "", "label": "北京", "classid": 152,
         "columns": ["北京市法规"], "pages": 178, "records": 6198},
        {"dir": "ShenZhenShiCaiShuiFaGui", "nav": "", "label": "深圳", "classid": 12673,
         "columns": ["深圳市法规"], "pages": 3, "records": 75},
        {"dir": "category_181", "nav": "", "label": "山西", "classid": 181,
         "columns": ["山西省法规"], "pages": 9, "records": 300},
        {"dir": "ShanXiShengCaiShuiFaGui", "nav": "", "label": "陕西", "classid": 175,
         "columns": ["陕西省法规"], "pages": 11, "records": 400},
    ]
    LANDING = SH.SEARCH_RESULT + "?page=0&searchid=999"

    def setUp(self):
        p = mock.patch.object(SH, "load_columns", return_value=self.TABLE)
        p.start()
        self.addCleanup(p.stop)

    class _Form:
        """把发出去的表单字段留下，页面按调用方给的清单依次回。"""

        def __init__(self, first_page, landing, gets=None):
            self.sent = []
            self.first_page = first_page
            self.landing = landing
            self.gets = gets or {}
            self.get_urls = []

        def post(self, url, data=None, **kw):
            self.sent.append(dict(data or {}))
            return _Resp(self.first_page, url=self.landing)

        def get(self, url, **kw):
            self.get_urls.append(url)
            return _Resp(self.gets[url])

    def _native(self, total=61, **kw):
        s = self._Form(_list_page(1, 30, total), self.LANDING)
        return SH.search_native("增值税", size=kw.pop("size", 5), session=s, gap=0, **kw), s

    def test_comma_spec_resolves_each_part_however_it_is_written(self):
        self.assertEqual("152,12673", SH.classid_spec("北京,深圳"))
        self.assertEqual("152,12673", SH.classid_spec("152,深圳市法规"))
        self.assertEqual("152,12673", SH.classid_spec(
            "BeiJingShiCaiShuiFaGui,ShenZhenShiCaiShuiFaGui"))

    def test_pipe_and_bracket_forms_never_reach_the_site(self):
        """站点只认逗号：竖线那一路实测只取第一段，classid[] 回空页，所以换算必须拒绝。"""
        self.assertEqual("", SH.classid_spec("152|12673"))
        self.assertEqual("", SH.classid_spec("北京,不存在的栏"))

    def test_unresolvable_part_voids_the_whole_spec_and_nothing_is_posted(self):
        s = self._Form(_list_page(1, 30, 61), self.LANDING)
        r = SH.search_native("增值税", size=5, session=s, gap=0, classid="北京,不存在的栏")
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
        self.assertIn("栏目表", r["_status"])
        self.assertEqual([], s.sent, "半截限定不该发出去——那看着像收窄了其实没有")

    def test_resolved_classid_and_the_other_three_dimensions_are_posted(self):
        _, s = self._native(classid="北京,深圳", match="title",
                            date_from="2025-01-01", date_to="2025-12-31")
        sent = s.sent[0]
        self.assertEqual("152,12673", sent["classid"])
        self.assertEqual("title", sent["show"], "show 是匹配域，不是排版参数")
        self.assertEqual("2025-01-01", sent["starttime"])
        self.assertEqual("2025-12-31", sent["endtime"])

    def test_date_from_alone_is_flagged_instead_of_read_as_a_narrowing(self):
        r, s = self._native(date_from="2025-01-01")
        self.assertEqual("2025-01-01", s.sent[0]["starttime"])
        self.assertNotIn("endtime", s.sent[0])
        self.assertIn("不过滤", r["_filter_note"], "站点单给 starttime 不收窄，这个缺口要写出来")

    def test_unscoped_call_carries_no_filter_note(self):
        r, _ = self._native()
        self.assertNotIn("_filter_note", r)

    def test_fetch_all_walks_to_the_total_the_page_reports(self):
        total = 61
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=999": _list_page(31, 30, total),
                SH.SEARCH_RESULT + "?page=2&searchid=999": _list_page(61, 1, total)}
        s = self._Form(_list_page(1, 30, total), self.LANDING, gets)
        r = SH.search_native("增值税", size=5, session=s, gap=0, fetch_all=True)
        self.assertEqual(61, len(r["results"]), "取全按页面总数走，不受 size 约束")
        self.assertEqual([SH.SEARCH_RESULT + "?page=1&searchid=999",
                          SH.SEARCH_RESULT + "?page=2&searchid=999"], s.get_urls)

    def test_fetch_all_names_the_cap_when_it_could_not_reach_the_total(self):
        total = 61
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=999": _list_page(31, 30, total)}
        s = self._Form(_list_page(1, 30, total), self.LANDING, gets)
        with mock.patch.object(SH, "SEARCH_ALL_MAX_PAGES", 1):
            r = SH.search_native("增值税", size=5, session=s, gap=0, fetch_all=True)
        self.assertEqual(30, len(r["results"]))
        self.assertIn("翻到上限 1 页只取了 30 条", r["_status"],
                      "撞到上限时必须写明只取了多少，不能报成取全了")

    # ---- 中途空页：断供不是尽头 ----

    def test_mid_crawl_empty_page_is_flagged_as_dropout(self):
        """站点报 61 条、只收到 60 条就遇到空页 ⇒ 判为断供，且不许借用"翻到上限"那句。"""
        total = 61
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=999": _list_page(31, 30, total),
                SH.SEARCH_RESULT + "?page=2&searchid=999": _list_page(61, 0, total)}
        s = self._Form(_list_page(1, 30, total), self.LANDING, gets)
        r = SH.search_native("增值税", size=5, session=s, gap=0, fetch_all=True)
        self.assertEqual(60, len(r["results"]))
        self.assertIn("断供", r["_status"], r["_status"])
        self.assertIn("不是这一词的完整集合", r["_status"])
        self.assertNotIn("翻到上限", r["_status"],
                         "这一轮只读了 2 页，cap 还有 3 页没用完——报成上限是替站点圆场")
        self.assertEqual(r["_error"], r["_status"].split("；", 1)[1].rstrip("）"),
                         "断供话术要原样进 _error，聚合层只认 _error")

    def test_honest_end_of_list_is_not_flagged_as_dropout(self):
        """控制组：站点吐满 31 条后循环自己收口，一条都不许报成断供。"""
        total = 31
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=999": _list_page(31, 1, total)}
        s = self._Form(_list_page(1, 30, total), self.LANDING, gets)
        r = SH.search_native("增值税", size=5, session=s, gap=0, fetch_all=True)
        self.assertEqual(31, len(r["results"]))
        self.assertNotIn("断供", r["_status"], r["_status"])
        self.assertNotIn("_error", r, "正常取全不该有 _error")

    def test_cap_at_max_pages_is_still_the_cap_message(self):
        """控制组：真撞到 SEARCH_ALL_MAX_PAGES 时话术仍是"翻到上限"，不与断供混成一团。"""
        total = 61
        gets = {SH.SEARCH_RESULT + "?page=1&searchid=999": _list_page(31, 30, total)}
        s = self._Form(_list_page(1, 30, total), self.LANDING, gets)
        with mock.patch.object(SH, "SEARCH_ALL_MAX_PAGES", 1):
            r = SH.search_native("增值税", size=5, session=s, gap=0, fetch_all=True)
        self.assertIn("翻到上限 1 页", r["_status"])
        self.assertNotIn("断供", r["_status"])
        self.assertNotIn("_error", r)

    def test_wrapper_passes_native_dropout_through_to_error(self):
        """包装层要接住站内的断供：半截清单 results 非空，旧写法只在"两路都空"才写 _error。"""
        nat = {"results": [SH._row_dict("标题1", P1, "2026-08-10", "摘要")],
               "total": 900,
               "_status": "命中 1 条（这一词站内共 1000 条；第 2 页返回空，判为断供）",
               "_error": "第 2 页返回空，但站点报这一词共 1000 条、只收了 30 条：判为断供"}
        r, calls = self._route({"results": [], "total": 0}, nat, channel="native")
        self.assertEqual(["站内"], calls)
        self.assertEqual(nat["_error"], r["_error"],
                         "断供不接出去，上层就只看到 total=1 像是这一词只有 1 条")

    def _route(self, sogou, native, **kw):
        calls = []

        def fake_sogou(keyword, site="", size=5):
            calls.append("搜狗")
            return sogou

        def fake_native(keyword, size=5, **inner):
            calls.append("站内")
            self.inner = inner
            return native

        with mock.patch.object(SH, "sogou_search", fake_sogou), \
             mock.patch.object(SH, "search_native", fake_native):
            return SH.search_shui5("增值税", size=5, **kw), calls

    def test_scoped_params_move_auto_off_sogou_and_say_why(self):
        hit = {"results": [SH._row_dict("站内标题", P1, "2026-08-10", "摘要")],
               "total": 1, "_status": "命中 1 条"}
        r, calls = self._route({"total": 9, "results": [{"title": "t", "url": P1}]},
                               hit, column="北京")
        self.assertEqual(["站内"], calls, "搜狗那一路没有栏目维度，这一轮压根不该问它")
        self.assertTrue(r["_channels"]["搜狗"].startswith("没问"), r["_channels"]["搜狗"])
        self.assertNotEqual("未走（指定通道）", r["_channels"]["搜狗"],
                            "换路是限定参数逼的，不是调用方指定的")

    def test_forced_sogou_with_scoped_params_reports_that_they_did_not_apply(self):
        r, calls = self._route({"total": 9,
                                "results": [{"title": "t", "url": P1}]},
                               {"results": [], "total": None, "_status": "没走成"},
                               channel="sogou", date_from="2025-01-01", date_to="2025-12-31")
        self.assertEqual(["搜狗"], calls)
        self.assertIn("限定没加上", r["_filter_note"],
                      "指定了搜狗又给限定：结果看着像收窄了，其实一条都没下推")

    def test_unscoped_auto_still_asks_sogou_first(self):
        r, calls = self._route({"total": 1, "results": [{"title": "t", "url": P1}]},
                               {"results": [], "total": None, "_status": "没走成"})
        self.assertEqual(["搜狗"], calls)
        self.assertEqual("命中 1 条", r["_channels"]["搜狗"])
        self.assertNotIn("_filter_note", r)


class TestShui5ColumnTable(unittest.TestCase):
    """随仓库发货的栏目表：归属只认行里的 column 字段，表里不能有猜出来的值。"""

    def test_every_shipped_row_is_resolvable_by_its_own_dir_and_classid(self):
        rows = SH.load_columns()      # 读的是随仓库发货的 data/shui5_columns.json
        self.assertTrue(len(rows) >= 40, "栏目表整表丢失时这一条要报红")
        for r in rows:
            self.assertIsInstance(r["classid"], int, r)
            for key in ("dir", "classid"):
                got = SH.resolve_column(r[key])
                self.assertIsNotNone(got, f"{key}={r[key]} 查不到")
                self.assertEqual(r["classid"], got["classid"], f"{key}={r[key]}")
        self.assertEqual(len(rows), len({r["dir"] for r in rows}), "目录名不该重复")

    def test_pinyin_dir_that_looks_like_shanxi_is_actually_shaanxi(self):
        """目录名的拼音串与行内栏目名不同源：猜目录名会把陕西的栏当成山西的栏。"""
        p = mock.patch.object(SH, "load_columns", return_value=TestShui5ScopedSearch.TABLE)
        p.start()
        self.addCleanup(p.stop)
        self.assertEqual("陕西省法规", SH.resolve_column("ShanXiShengCaiShuiFaGui")["columns"][0])
        self.assertEqual("山西省法规", SH.resolve_column("category_181")["columns"][0])

    def test_shipped_table_keeps_those_two_rows_apart(self):
        """同一条判据也要钉住随仓库发货的那份表，不然表被改错时上一条约查不出。"""
        by_dir = {r["dir"]: r for r in SH.load_columns()}
        self.assertEqual(["陕西省法规"], by_dir["ShanXiShengCaiShuiFaGui"]["columns"])
        self.assertEqual(["山西省法规"], by_dir["category_181"]["columns"])

    def test_unknown_column_is_refused_before_any_request(self):
        r = SH.list_column("这个栏目名站点没有")
        self.assertEqual([], r["results"])
        self.assertIn("栏目表里没有", r["_status"])


class TestShui5ClassidIntegrity(unittest.TestCase):
    """栏目表里 classid 不可用的两种行（上一轮没取到的失败行 / 无链接的健康页），
    谁都不许把整张表毒掉、不许拼出 'None' 发出去、不许造出站点上不存在的翻页地址。

    判据前提（2026-11-24 实测）：
    - 失败行旧形状 `{"dir","nav","_error"}` 照样落盘，下游 `resolve_column`/`classid_of`
      按 classid 查任何一栏都抛 KeyError，`list_column` 先发一个请求再半途崩；
    - `classid=None` 的行让 `str(None)=="None"` 成真值，`classid_spec('安徽,深圳')`
      实际发出 `classid='None,12673'`，真站直发这一串回"没有搜索到相关内容"
      （total=None、0 行）——不是退回全站，是被我们自己的 'None' 盖掉的 0 条；
    - classid 在 47 栏跨 37 天零漂移（同期 pages 变 6 枚、records 变 39 枚），
      所以失败行继承上一轮的 classid 不算把旧读数当本轮读数，但必须写明来源。
    """

    GOOD = TestShui5ScopedSearch.TABLE

    # 旧 build_column_table 写出的失败行形状：只有三枚键，classid 键整个缺失。
    # 这一组用例钉的是"表里已经躺着一枚这样的行"时读取侧必须自保——发货表今天
    # 没有这种行（上一轮 47/47 全取到），但旧版本写过的表、或别的途径落盘的表
    # 都可能带，读取侧不能赌写入侧永远正确。
    POISONED = [
        {"dir": "AnHuiShengCaiShuiFaGui", "nav": "", "_error": "HTTP 500"},
        GOOD[1], GOOD[2],
    ]

    NONE_ROW = [
        {"dir": "AnHuiShengCaiShuiFaGui", "nav": "", "label": "安徽", "classid": None,
         "columns": ["安徽省法规"], "pages": None, "records": None},
        GOOD[1], GOOD[2],
    ]

    def _load(self, table):
        p = mock.patch.object(SH, "load_columns", return_value=table)
        p.start()
        self.addCleanup(p.stop)
        return table

    def test_poisoned_row_does_not_break_classid_lookup(self):
        """一枚失败行不许把整表的 classid 查法毒掉。

        必须按数字 classid 查一遍：目录名那一支在 `resolve_column` 第一个分支就 return
        了，碰不到按 classid 查那一段——2026-11-24 我用注入把那段还原成旧的下标
        `str(r["classid"])` 时，只查目录名的用例全绿，是覆盖不足不是实现好。旧写法的
        真症状是"表里有一枚失败行 ⇒ 按 classid 查任何一栏都 KeyError"。
        """
        self._load(self.POISONED)
        got = SH.resolve_column("ShenZhenShiCaiShuiFaGui")
        self.assertIsNotNone(got)
        self.assertEqual(12673, got["classid"])
        self.assertEqual("12673", SH.classid_of("ShenZhenShiCaiShuiFaGui"))
        # POISONED 里留下的两枚完好行是 GOOD[1] 深圳(12673) 与 GOOD[2] 山西(181)；
        # 北京(152) 那一枚被换成失败行了，所以按 152 查应当是"查不到"而不是炸。
        for key, want in (("12673", "ShenZhenShiCaiShuiFaGui"),
                          ("181", "category_181")):
            hit = SH.resolve_column(key)
            self.assertIsNotNone(hit, f"失败行把按 classid {key} 查这一栏毒成了查不到")
            self.assertEqual(want, hit["dir"])
            self.assertEqual(key, SH.classid_of(key))
        # 表里真没有的那个编号必须交回 None（旧写法在这里抛 KeyError，把"没有"变成崩）
        self.assertIsNone(SH.resolve_column("152"), "表里没有的 classid 应当查不到")
        self.assertEqual("", SH.classid_of("152"))

    def test_failed_row_in_table_is_refused_without_any_request(self):
        """失败行交给 list_column：拒绝发请求、说明是上一轮的失败行，而不是先发一发再崩。"""
        self._load(self.POISONED)
        sent = []

        class S:
            def get(self, url, **kw):
                sent.append(url)
                raise AssertionError("失败行不该触发任何请求")

        r = SH.list_column("AnHuiShengCaiShuiFaGui", pages=2, session=S(), gap=0)
        self.assertEqual([], sent, "失败行不该触发任何请求")
        self.assertEqual([], r["results"])
        self.assertIn("没取到", r["_status"])
        self.assertIn("HTTP 500", r["_status"])
        self.assertIn("classid", r["_status"])
        self.assertIn("HTTP 500", r.get("_error", ""))

    def test_column_without_classid_yields_empty_string_not_none_string(self):
        """健康页无链接 => classid=None：classid_of 必须交回空串，不能是 str(None) 的 'None'。"""
        self._load(self.NONE_ROW)
        self.assertEqual("", SH.classid_of("AnHuiShengCaiShuiFaGui"),
                         "str(None)=='None' 是真值，交出去就会被当有效编号拼进请求")

    def test_classid_spec_never_wires_the_word_none(self):
        """传栏名换算 classid：表里有 None 行时宁可整体拒绝，也不把 'None' 拼进串里发出去。"""
        self._load(self.NONE_ROW)
        self.assertEqual("", SH.classid_spec("安徽,深圳"))

    def test_none_classid_column_reads_first_page_only_and_says_so(self):
        """无编号的栏翻页地址造不出来：只读第 1 页并写明，不许造 None_2.html 这种地址。"""
        self._load(self.NONE_ROW)
        urls = []

        class R:
            status_code = 200
            url = "https://www.shui5.cn/article/x/"
            content = ("<html><body>"
                       '<div class="xwt2"><div class="xwt2_a">'
                       '<a href="https://www.shui5.cn/article/42/9.html" title="标题9">可见9</a>'
                       "</div></div></body></html>").encode("utf-8")

        class S:
            def get(self, url, **kw):
                urls.append(url)
                return R()

        r = SH.list_column("AnHuiShengCaiShuiFaGui", pages=3, session=S(), gap=0)
        self.assertEqual([SH.SHUI5_BASE + "article/AnHuiShengCaiShuiFaGui/"], urls)
        self.assertIn("没有可用 classid", r["_status"])
        self.assertIn("只读了第 1 页", r["_status"])

    def test_shipped_table_survives_a_poisoned_row(self):
        """控制组 + 回归：健康表与盘上发货表都不受这些改动影响。"""
        rows = SH.load_columns()
        self.assertTrue(len(rows) >= 40)
        self.assertEqual("12673", SH.classid_of("深圳"))
        self._load(self.GOOD)
        self.assertEqual("12673", SH.classid_of("深圳"))

    def test_failed_row_keeps_keys_and_records_source(self):
        """重建时某一栏取不到：那一行必须键齐（classid 继承上一轮并写明来源、
        pages/records 留空），并把这一栏点名进 _status 与 _error。"""
        self._load(self.GOOD)
        home = ('<html><body>'
                '<a href="https://www.shui5.cn/article/ShenZhenShiCaiShuiFaGui/">深圳</a>'
                '<a href="https://www.shui5.cn/article/BeiJingShiCaiShuiFaGui/">北京</a>'
                '</body></html>').encode("utf-8")
        ok = ('<html><body>'
              '<a href="https://www.shui5.cn/article/152_1.html">p</a>'
              '<a href="https://www.shui5.cn/article/152_2.html">q</a>'
              '<div class="xwt2"><div class="xwt2_a">'
              '<a href="https://www.shui5.cn/article/42/7.html" title="标题7">可见7</a>'
              '</div></div></body></html>').encode("utf-8")

        class R:
            def __init__(self, content, code=200):
                self.content = content
                self.status_code = code
                self.url = "https://www.shui5.cn/"

        class S:
            def get(self, url, **kw):
                if "BeiJingShiCaiShuiFaGui" in url:
                    return R(b"", 500)
                return R(home if url.rstrip("/") + "/" == SH.SHUI5_BASE else ok)

        t = SH.build_column_table(session=S(), gap=0)
        by = {r["dir"]: r for r in t["columns"]}
        bad = by["BeiJingShiCaiShuiFaGui"]
        for k in ("dir", "nav", "label", "classid", "columns", "pages", "records", "_error"):
            self.assertIn(k, bad, f"失败行少了 {k} 这一枚键，下游就会 KeyError")
        self.assertEqual(152, bad["classid"], "classid 实测跨 37 天零漂移，可以继承")
        self.assertEqual("上一轮的表", bad["_classid_from"])
        self.assertIsNone(bad["pages"])
        self.assertIsNone(bad["records"])
        self.assertIn("HTTP 500", bad["_error"])
        self.assertIn("1 栏这一轮没取到", t["_status"])
        self.assertIn("不能当成这一轮的读数", t["_status"])
        self.assertIn("BeiJingShiCaiShuiFaGui", t.get("_error", ""))
        # 完好那栏照常按 classid 查得到，一枚失败行不毒全表
        self.assertIsNotNone(SH.resolve_column("152") or by.get("ShenZhenShiCaiShuiFaGui"))

    def test_control_round_of_build_reports_no_failure(self):
        """控制组：全栏都取到时不许出现任何"没取到"的字样，也不许有 _error。"""
        self._load(self.GOOD)
        home = ('<html><body>'
                '<a href="https://www.shui5.cn/article/ShenZhenShiCaiShuiFaGui/">深圳</a>'
                '</body></html>').encode("utf-8")
        ok = ('<html><body>'
              '<a href="https://www.shui5.cn/article/12673_1.html">p</a>'
              '<a href="https://www.shui5.cn/article/12673_2.html">q</a>'
              '<div class="xwt2"><div class="xwt2_a">'
              '<a href="https://www.shui5.cn/article/42/7.html" title="标题7">可见7</a>'
              '</div></div></body></html>').encode("utf-8")

        class R:
            def __init__(self, content):
                self.content = content
                self.status_code = 200
                self.url = "https://www.shui5.cn/"

        class S:
            def get(self, url, **kw):
                return R(home if url.rstrip("/") + "/" == SH.SHUI5_BASE else ok)

        t = SH.build_column_table(session=S(), gap=0)
        self.assertNotIn("_error", t)
        self.assertNotIn("没取到", t["_status"])
        self.assertEqual(12673, t["columns"][0]["classid"])
        self.assertNotIn("_classid_from", t["columns"][0])

    def test_classid_zero_is_not_mistaken_for_missing(self):
        """classid 一律 `is None` 判，不许用真值判。

        3.62.5 那条同族教训：`if code and code != 200` 会漏判 code=0。这里同理，
        `if not cid` 会把编号 0 读成"这一栏没有编号"，于是一栏明明能用却拒绝翻页、
        还被写明"没有可用 classid"——把判据自己造出来的缺失说成站点的缺失。
        今天表里没有 classid=0（47 栏实测最小 152），这条钉的是判据写法不是站点现状。
        """
        zero = [{"dir": "LingShiCaiShuiFaGui", "nav": "零号", "label": "零号栏",
                 "classid": 0, "columns": [], "pages": 2, "records": 10},
                self.GOOD[1], self.GOOD[2]]
        self._load(zero)
        self.assertEqual("0", SH.classid_of("LingShiCaiShuiFaGui"),
                         "0 是有效编号，不能读成空串")
        self.assertEqual("0", SH.classid_spec("零号"))
        urls = []

        class R:
            status_code = 200
            url = "https://www.shui5.cn/article/x/"
            content = ("<html><body>"
                       '<div class="xwt2"><div class="xwt2_a">'
                       '<a href="https://www.shui5.cn/article/42/9.html" title="标题9">可见9</a>'
                       "</div></div></body></html>").encode("utf-8")

        class S:
            def get(self, url, **kw):
                urls.append(url)
                return R()

        r = SH.list_column("LingShiCaiShuiFaGui", pages=2, session=S(), gap=0)
        self.assertEqual([SH.SHUI5_BASE + "article/LingShiCaiShuiFaGui/",
                          SH.SHUI5_BASE + "article/LingShiCaiShuiFaGui/0_2.html"], urls,
                         "classid=0 的栏必须照常翻页，不能当成没有编号")
        self.assertNotIn("_error", r)
        self.assertNotIn("没有可用 classid", r["_status"])


class TestAggregatorShui5Attribution(unittest.TestCase):
    """搜狗被拦时税屋的空算不算被连带，由这一轮站内那一路的回报决定，不再靠推断。"""

    def _agg(self, channels):
        ok = lambda n: {"total": n, "results": [{"title": "财税〔2025〕1号",
                                                "url": "https://x.test/a"}] if n else []}
        shui5 = {"total": 0, "results": [], "_channels": channels}
        with mock.patch.object(AGG, "search_tax", return_value=ok(1)), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok(1)), \
             mock.patch.object(AGG, "sogou_search",
                               return_value={"_error": "搜狗触发反爬", "results": []}), \
             mock.patch.object(AGG, "search_shui5", return_value=shui5), \
             mock.patch.object(AGG, "search_wechat", return_value=ok(0)), \
             mock.patch.object(AGG, "search_ctax", return_value=ok(1)):
            return AGG.aggregate_search("测试词", size=5)

    def _shui5_gap(self, r):
        g = [x for x in r["gaps"] if x["source"] == "shui5"]
        self.assertEqual(1, len(g), r["gaps"])
        return g[0]

    def test_native_ran_but_empty_is_own_not_inherited(self):
        g = self._shui5_gap(self._agg({"搜狗": "被拦：搜狗触发反爬",
                                       "站内": "0 条：站点回「没有搜索到相关的内容」"}))
        self.assertNotIn("blocked_by", g, "站内那一路跑通了，就不能再甩给搜狗")
        self.assertIn("站内原生检索这一轮也没命中", g["reason"])

    def test_native_not_walked_keeps_the_inheritance(self):
        g = self._shui5_gap(self._agg({"搜狗": "被拦：搜狗触发反爬",
                                       "站内": "没走成：无浏览器，改纯 HTTP 直连"}))
        self.assertEqual("sogou", g["blocked_by"])
        self.assertIn("不代表税屋没有内容", g["impact"])
        self.assertIn("只走了搜狗的 site:shui5.cn 那一路", g["reason"])

    def test_channel_report_absent_makes_no_claim(self):
        """没带 _channels 的结果（打桩、缓存）不推断税屋通道状态：
        拿聚合器自己 sogou 源的失败去猜，会把两次独立请求混成一件事。"""
        ok = lambda n: {"total": n, "results": [{"title": "t", "url": "https://x.test/a"}]
                        if n else []}
        with mock.patch.object(AGG, "search_tax", return_value=ok(1)), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok(1)), \
             mock.patch.object(AGG, "sogou_search",
                               return_value={"_error": "搜狗触发反爬", "results": []}), \
             mock.patch.object(AGG, "search_shui5", return_value=ok(0)), \
             mock.patch.object(AGG, "search_wechat", return_value=ok(0)), \
             mock.patch.object(AGG, "search_ctax", return_value=ok(1)):
            r = AGG.aggregate_search("测试词", size=5)
        self.assertEqual(["sogou"], [g["source"] for g in r["gaps"]],
                         "没有 _channels 时税屋那一条不该被推断出来")


class TestShui5DocNumberLookup(unittest.TestCase):
    """--find-doc 的查询阶梯。税屋标题里的文号一律写半角方括号，
    官方那种六角括号要换过去再查，否则站内 0 条会被读成"税屋没有这份文件"。
    阶梯各档的实测读数（2026-10-18，站内标题匹配）：`财税[2019]13号` 7 条、
    `财税〔2019〕13号` 0 条、`财税[2016]36号` 20 条、`财税〔2016〕36号` 4 条。
    """

    def setUp(self):
        self.calls = []
        # 阶梯档与档之间按 SEARCH_MIN_GAP 隔开发，用例里不等
        p = mock.patch.object(SH.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def _run(self, doc, hits=None, session=object()):
        """hits: 第几档命中（None 表示逐档走完都空）。session 传 None 走自己过 WAF 那一路。"""
        def fake(q, size=5, session=None, match="title", **kw):
            self.calls.append(q)
            hit = (hits == len(self.calls))
            return {"results": [SH._row_dict("命中：" + q, P1, "2019-01-17", "摘要")]
                    if hit else [],
                    "total": 1 if hit else 0,
                    "_status": "命中 1 条" if hit else "0 条：站点回「没有搜索到相关的内容」"}

        with mock.patch.object(SH, "search_native", fake):
            return SH.find_by_doc_number(doc, session=session)

    def test_full_width_is_asked_in_half_width_first(self):
        r = self._run("财税〔2019〕13号", hits=1)
        self.assertEqual(["财税[2019]13号"], self.calls, "第一档就该是半角形态")
        self.assertEqual("财税[2019]13号", r["_query"])
        self.assertEqual(1, len(r["_queries_tried"]), "命中了不再往后试")

    def test_spaces_in_the_number_go_but_agency_spaces_stay(self):
        """站点按整串匹配，编号里多一个空格就是另一条查询；机关名之间那个空格是文号的一部分。"""
        self._run("财税〔 2019 〕 13 号", hits=1)
        self.assertEqual(["财税[2019]13号"], self.calls)
        self.calls.clear()
        self._run("财政部 税务总局公告2019年第13号", hits=1)
        self.assertEqual(["财政部 税务总局公告2019年第13号"], self.calls)
        self.calls.clear()
        self._run("财税 〔2019〕13号", hits=1)
        self.assertEqual(["财税[2019]13号"], self.calls,
                         "括号前面带空格也要整形——靠的就是字符类里那一枚开括号，"
                         "去掉它这一串只能整串提交")

    def test_the_ladder_ends_with_the_number_without_the_issuer(self):
        r = self._run("税总发[1999]999号")
        self.assertEqual(["税总发[1999]999号", "税总发〔1999〕999号", "[1999]999号"],
                         self.calls)
        self.assertTrue(r["_status"].startswith("0 条"),
                        "跑通的阶梯不能报成没走成——聚合侧靠这一句分辨税屋空还是被连带")
        for q in self.calls:
            self.assertIn(q, r["_caveat"], "0 条要把试过的写法都交出去")
        self.assertIn("不代表税屋没有这份文件", r["_caveat"])

    def test_announcement_form_skips_the_full_width_stage(self):
        """没有方括号就没有全角形态可试，第二档直接去掉机关名只留「2019年第13号」。"""
        r = self._run("财政部 税务总局公告2019年第13号", hits=2)
        self.assertEqual(["财政部 税务总局公告2019年第13号", "2019年第13号"], self.calls)
        self.assertEqual(2, len(r["_queries_tried"]))
        self.assertIn("与给进来的写法不同", r["_caveat"], "改过查询串要说明")

    def test_a_half_width_hit_is_not_reported_as_rewritten(self):
        r = self._run("财税[2016]36号", hits=1)
        self.assertNotIn("写法不同", r["_caveat"])
        self.assertIn("子串匹配", r["_caveat"], "候选里混着地方同号文件与解读文章，这条提醒常驻")

    def test_garbage_input_is_asked_once_as_given(self):
        """落不进「编号」那一段的串（如整句正文）按原样提交一次，不编出写法来。"""
        r = self._run("执行至2024年4月15日，令第108号")
        self.assertEqual(["执行至2024年4月15日，令第108号"], r["_queries_tried"])
        self.assertNotIn("〔", r["_caveat"], "换不出全角形态，就不能在提醒里报出这一档")

    def test_empty_input_asks_the_site_nothing(self):
        r = self._run("   ")
        self.assertEqual([], self.calls)
        self.assertIn("没给文号", r["_status"])

    def test_no_browser_sends_no_search(self):
        with mock.patch.object(SH, "_pass_waf",
                               return_value=(None, "无浏览器，改纯 HTTP 直连")):
            r = self._run("财税[2016]36号", session=None)
        self.assertEqual([], self.calls)
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])

    def test_size_defaults_to_twenty_candidates(self):
        seen = []

        def fake(q, size=5, session=None, match="title", **kw):
            seen.append((q, size, match))
            return {"results": [SH._row_dict("t", P1, "", "摘要")], "total": 1,
                    "_status": "命中 1 条"}

        with mock.patch.object(SH, "search_native", fake):
            SH.find_by_doc_number("财税[2019]13号", session=object())
        self.assertEqual([("财税[2019]13号", 20, "title")], seen,
                         "文号定位要交候选，只给 5 条会把中央那份挤掉")


class TestShui5StatusMark(unittest.TestCase):
    """行标题尾部的站点时效标记，取值 2026-10-18 检索标记词的标题读数定为五种。"""

    def test_mark_splits_out_and_title_stays_as_the_page(self):
        row = SH._row_dict("财税[2019]13号 关于实施小微企业普惠性税收减免政策的通知[全文失效]",
                           P1, "2019-01-17", "摘要")
        self.assertEqual("全文失效", row["status_mark"])
        self.assertIn("[全文失效]", row["title"], "剥掉标记会让标题与页面不一致")

    def test_unmarked_row_does_not_carry_the_key(self):
        row = SH._row_dict("留抵退税口径", P1, "2026-08-10", "摘要")
        self.assertNotIn("status_mark", row)

    def test_all_five_shipped_values_are_read(self):
        for v in ("条款失效", "全文失效", "条款废止", "全文废止", "条款修订"):
            self.assertEqual(v, SH._row_dict("某办法[%s]" % v, P1, "", "")["status_mark"])

    def test_full_width_brackets_would_still_be_read(self):
        """取样到的带标记标题一律半角；站点改用全角时不至于静默漏读。"""
        self.assertEqual("条款修订",
                         SH._row_dict("某办法〔条款修订〕", P1, "", "")["status_mark"])

    def test_the_word_alone_without_brackets_is_not_a_mark(self):
        """「全文失效」出现在标题正文里（如目录类文章的名目）不算站点标记。"""
        self.assertNotIn("status_mark",
                         SH._row_dict("全文失效和废止部分文件的通知", P1, "", ""))

    def test_result_page_rows_carry_the_mark(self):
        page = ('<div class="xwt2"><div class="xwt2_a">'
                '<a href="https://www.shui5.cn/article/42/101.html" title='
                '"湖南省水资源费改税试点实施办法[条款废止]">可见</a></div>'
                '<div class="xwt2_c"><p class="p1">摘要</p></div>'
                '<div class="xwt2_d"><p class="p1">来源</p></div>'
                '<p class="p3">2019-11-30</p>'
                '<p class="p4"><a href="/e/action/ListInfo/?classid=9">税收法规</a></p></div>')
        rows = SH._search_rows(page)
        self.assertEqual("条款废止", rows[0]["status_mark"])


class TestShui5RepealNote(unittest.TestCase):
    """正文开头的「税屋提示——」批注。批注后面紧跟的就是文件正文，正文里也有文号，
    按整段读会把正文文号混进依据——按「。」切句、只留与时效有关的那几句。
    这里的分句都取 2026-10-18 实测过的真实批注。
    """

    GANSU = ("税屋提示——依据甘人社通[2026]86号 甘肃省人力资源和社会保障厅关于宣布"
             "失效和废止部分文件的通知，自2026年3月5日起本法规全文失效。 "
             "各市州人力资源和社会保障局、财政局： 为深入贯彻党中央、国务院和省委、"
             "省政府稳就业决策部署，根据《关于继续实施失业保险促进就业政策的通知》"
             "（人社部发〔2024〕45号）")
    CAIJIN = ("税屋提示——依据财金[2026]1号 财政部中国人民银行 金融监管总局关于优化实施"
              "个人消费贷款财政贴息政策有关事项的通知，本通知部分条款修订。 "
              "各省、自治区、直辖市、计划单列市财政厅(局)： 为贯彻落实党中央、国务院"
              "关于大力提振消费的决策部署，现印发。")
    ORDER108 = ("税屋提示——依据国家市场监督管理总局令第108号 国家市场监督管理总局关于"
                "修改《个体工商户年度报告办法》等四部规章的决定，自2025年12月25日起，"
                "本法规将第十一条、第十二条、第十三条、第十四条合并，作为第十一条，"
                "修改为：“被列入经营异常名录的企业，符合下列条件之一的，可以依法向其"
                "登记地市场监督管理部门申请移出经营异常名录： “(一)因未按照规定报送"
                "并公示年度报告被列入经营异常名录，已经补报未报年份的年度报告并公示； "
                "“(二)因未按")
    TAIZHOU = ("税屋提示——依据国家税务总局台州市税务局公告2025年第1号 关于公布全文有效、"
               "全文失效废止、部分条款失效废止和部分条款修改的税务规范性文件目录的公告 ，"
               "自2025年8月15日本法规第五条已修订。 为进一步规范全市存量房交易纳税申报行为，"
               "现予以发布，自2025年9月1日起施行。 闽商务规〔2024〕1104号")
    TWO_ITEMS = ("税屋提示—— 1.依据闽商务规[2024]10号 福建省商务厅 福建省发展和改革委员会 "
                 "福建省财政厅关于调整优化消费品以旧换新政策的公告，本法规部分条款修订优化，"
                 "优化详情可查看闽商务规[2024]10号。 2.依据福建省商务厅 福建省发展和改革委员会 "
                 "福建省财政厅关于调整消费品以旧换新部分政策的公告，本法规部分条款修订。 "
                 "各市、县(区)人民政府： 《福建省加力支持消费品以旧换新实施方案》"
                 "（发改环资〔2024〕1104号）")

    def test_single_sentence_with_end_date(self):
        self.assertEqual(
            "依据甘人社通[2026]86号 甘肃省人力资源和社会保障厅关于宣布失效和废止部分文件的"
            "通知，自2026年3月5日起本法规全文失效",
            SH._repeal_note(self.GANSU))

    def test_note_without_an_end_date_is_still_kept(self):
        """不带止期那种（本通知部分条款修订）也要收下，不能因为没有日期就丢。"""
        self.assertEqual(
            "依据财金[2026]1号 财政部中国人民银行 金融监管总局关于优化实施个人消费贷款"
            "财政贴息政策有关事项的通知，本通知部分条款修订",
            SH._repeal_note(self.CAIJIN))

    def test_numbered_items_are_both_kept(self):
        note = SH._repeal_note(self.TWO_ITEMS)
        self.assertTrue(note.startswith("1.依据闽商务规[2024]10号"), note[:40])
        self.assertIn("2.依据福建省商务厅", note)
        self.assertNotIn("各市、县", note)
        self.assertNotIn("实施方案", note.split("2.依据")[1])

    def test_numbered_date_clause_needs_the_head_pattern(self):
        """取样那 11 篇的分句都带「依据」或「本法规/本通知」，这一形不是量出来的，
        钉的是判据本身：只讲「自YYYY年起」又带序号的那一句，靠 `_TIP_KEEP_RE`
        的「序号 + 自YYYY年」那一路留下；后面 `or "本法规" in seg` 那一路顶不上。
        """
        note = SH._repeal_note(
            "税屋提示—— 1.自2026年1月1日起《××办法》第三条废止。 "
            "2.本《办法》附件二同时作废。 各市财政局： 现印发给你们。")
        self.assertEqual("1.自2026年1月1日起《××办法》第三条废止", note)

    def test_body_doc_number_does_not_leak_into_the_basis(self):
        """台州那篇的正文里另有闽商务规〔2024〕1104号，不能算进这一条的依据。"""
        note = SH._repeal_note(self.TAIZHOU)
        self.assertEqual(["2025年第1号"], SH.doc_numbers(SH._to_full_brackets(note)))
        self.assertNotIn("1104", note)

    def test_basis_reading_after_bracket_swap(self):
        """税屋写成半角，tax_terms 认的是六角；不换括号一枚也抽不到。"""
        note = SH._repeal_note(self.GANSU)
        self.assertEqual([], SH.doc_numbers(note), "按原文（半角）抽不到")
        self.assertEqual(["〔2026〕86号"], SH.doc_numbers(SH._to_full_brackets(note)))

    def test_regulation_order_number_yields_no_basis(self):
        """批注引用的是规章令号（令第108号），不在文号形态里：这一段只能交出提醒文字。"""
        self.assertTrue(SH._repeal_note(self.ORDER108))
        self.assertEqual([], SH.doc_numbers(
            SH._to_full_brackets(SH._repeal_note(self.ORDER108))))

    def test_quoted_clause_is_capped_by_the_window(self):
        self.assertLessEqual(len(SH._repeal_note(self.ORDER108)), SH._TIP_MAX)

    def test_no_anchor_and_non_validity_tip_both_return_empty(self):
        self.assertEqual("", SH._repeal_note(
            "各市州人力资源和社会保障局： 根据财税〔2019〕13号文件规定，自2026年1月1日起执行。"))
        self.assertEqual("", SH._repeal_note("税屋提示：本文由用户上传，仅供参考。"))

    def test_parse_article_carries_note_and_basis(self):
        art = SH._parse_article(_article_page(self.GANSU, own_pages=(1,)), P1)
        self.assertTrue(art["repeal_note"].startswith("依据甘人社通"))
        self.assertEqual(["〔2026〕86号"], art["repeal_basis"])

    def test_parse_article_omits_both_keys_without_a_note(self):
        art = SH._parse_article(_article_page("正文第一段，没有批注。", own_pages=(1,)), P1)
        self.assertNotIn("repeal_note", art)
        self.assertNotIn("repeal_basis", art)


# ── ③ L4 中国税网：检索契约、同稿合并、老地址判定与定层不把关 ──────────────
# 这一站的可用面全长在站点自己那一边（参数名、翻页基准、地址分界、注释标记写几遍），
# 所以用例全部离线：假会话按 URL 交出事先搭好的内容，发出去的参数留在会话上回读。
CTAX_SEARCH = CT.SEARCH_ENDPOINTS[0]
CTAX_NEW_URL = "https://www.ctaxnews.com.cn/policy/2023-02/10/content_1016514.html"
CTAX_OLD_URL = "http://www.ctaxnews.com.cn/2020-06/01/content_966206.html"
CTAX_OLD_URLS = "https://www.ctaxnews.com.cn/2020-06/01/content_966206.html"


def _ctax_row_json(title="财政部 税务总局公告2026年第29号", date="2026-10-19",
                   subtitle="财政部 税务总局公告2026年第29号", column="中央税收法规",
                   url=CTAX_NEW_URL, articleid="1016514", **extra):
    """一枚检索行的站点形态（15 枚键里这一层读的那几枚）。"""
    a = {"title": title, "date": date, "subtitle": subtitle, "url": url,
         "articleid": articleid, "nodesearchname": column,
         "introtitle": "财政部 国家税务总局", "sourcename": "中国税务报",
         "author": "2026年10月12日", "enpcontent": "正文起两行……",
         "Abstract": "编辑写的摘要"}
    a.update(extra)
    return a


def _ctax_json(rows, found=None):
    return json.dumps({"foundNum": found if found is not None else len(rows),
                       "article": list(rows)}, ensure_ascii=False)


class _CtaxResp:
    """照 `_http_get` 与 `fetch_ctax` 用得上的那几枚属性搭。
    encoding 按 requests 的规矩给默认值：声明了 charset 用声明的，没声明给 iso-8859-1。"""

    def __init__(self, body, status=200, ctype="application/json;charset=UTF-8"):
        self.text = body
        self.content = body.encode("utf-8")
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        self.encoding = m.group(1) if m else "iso-8859-1"

    def json(self):
        return json.loads(self.text)


class _CtaxSession:
    """按 URL 发内容的假会话；每一次 (url, params) 都记下。
    值是列表的按顺序消费，用完还索要就 IndexError；没准备的地址直接 KeyError。
    Search.do 有两个落点，默认把域名那一路备好的内容同样交给镜像那一路；
    要单独试两路的用例自己给出两个键。"""

    def __init__(self, pages):
        self.pages = dict(pages)
        alt = CT.SEARCH_ENDPOINTS[1]
        if CTAX_SEARCH in self.pages and alt not in self.pages:
            self.pages[alt] = self.pages[CTAX_SEARCH]
        self.requested = []
        self.headers = {}

    def get(self, url, params=None, timeout=None, **kw):
        self.requested.append((url, dict(params or {})))
        p = self.pages[url]
        if isinstance(p, list):
            p = p.pop(0)
        return p

    @property
    def sent_params(self):
        return [q for _, q in self.requested]


def _ctax_article_page(body="<p>正文第一段。</p><p>第二段</p>", props=None, times=2):
    p = props if props is not None else {
        "title": "财政部 税务总局公告2026年第29号",
        "date": "2026-10-19 09:10:00",
        "subtitle": "财政部 税务总局公告2026年第29号",
        "introtitle": "财政部 税务总局",
        "nodename": "中央税收法规", "nodeid": "8215",
        "liability": "全文有效", "tag": "增值税；企业所得税",
        "sourcename": "中国税务报", "author": "2026年10月12日",
        "abstract": "编辑摘要"}
    prop = ("<!--enpproperty"
            + "".join("<%s>%s</%s>" % (k, v, k) for k, v in p.items()) + "-->")
    block = "<!--enpcontent-->" + body + "<!--/enpcontent-->"
    return "<html><body>" + (block + prop) * times + "</body></html>"


class _CtaxOffline(unittest.TestCase):
    """共用：把站点侧的礼节性限速在离线用例里等掉。"""

    def setUp(self):
        p = mock.patch.object(CT.time, "sleep")
        p.start()
        self.addCleanup(p.stop)


class TestCtaxSearchContract(_CtaxOffline):
    """Search.do 的参数形状：翻页只认 pageNo、位置参数只提交一枚、越界值不发出去。"""

    def _one_hit(self, **kw):
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([_ctax_row_json()]))})
        r = CT.search_ctax("增值税", size=1, session=s, **kw)
        return s, r

    def test_default_match_sends_only_q(self):
        s, _ = self._one_hit()
        q = s.sent_params[0]
        self.assertEqual("增值税", q["q"])
        for other in ("title", "content", "keyword", "author"):
            self.assertNotIn(other, q, "多提交一枚就换了匹配域")
        self.assertEqual(1, q["pageNo"])
        self.assertEqual(CT.SEARCH_PAGE_SIZE, q["pageSize"])
        self.assertEqual("date", q["sort"])
        self.assertEqual(CT.SITE_ID, q["siteID"])
        self.assertEqual(CT.CHANNEL_WEB, q["channel"])

    def test_match_title_sends_only_the_title_slot(self):
        """q= 会把位置参数盖掉：同发两枚时站点报的是 q 那一份数，限定等于没生效。"""
        s, _ = self._one_hit(match="title")
        q = s.sent_params[0]
        self.assertEqual("增值税", q["title"])
        self.assertNotIn("q", q)

    def test_page_aliases_are_never_sent(self):
        s, _ = self._one_hit()
        for alias in ("start", "page", "pageNum", "p", "offset", "currentPage"):
            self.assertNotIn(alias, s.sent_params[0],
                             "站点不认这些别名，被忽略后落回第一页")

    def test_channel_zero_omits_the_param(self):
        """站点给 channel=0 回 37 字节空结构；这一层把 0 当"不限"，省掉这一枚取两端并集。"""
        s, _ = self._one_hit(channel=0)
        self.assertNotIn("channel", s.sent_params[0])
        s2, _ = self._one_hit(channel=CT.CHANNEL_TOUCH)
        self.assertEqual(CT.CHANNEL_TOUCH, s2.sent_params[0]["channel"])

    def test_one_sided_date_sends_only_that_side(self):
        s, _ = self._one_hit(date_from="2025-01-01")
        self.assertEqual({"startDate"}, {"startDate", "endDate"} & set(s.sent_params[0]))
        s2, _ = self._one_hit(date_to="2026-10-01")
        self.assertEqual({"endDate"}, {"startDate", "endDate"} & set(s2.sent_params[0]))
        s3, _ = self._one_hit()
        self.assertEqual(set(), {"startDate", "endDate"} & set(s3.sent_params[0]))

    def test_bad_date_is_refused_before_the_request(self):
        """站点这一档越界直接回 HTTP 500，拦在发出之前才有意义。"""
        s = _CtaxSession({})
        r = CT.search_ctax("增值税", date_from="2025/01/01", session=s)
        self.assertEqual([], s.requested)
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
        self.assertIn("yyyy-mm-dd", r["_status"])

    def test_empty_keyword_without_column_is_refused(self):
        s = _CtaxSession({})
        r = CT.search_ctax("", session=s)
        self.assertEqual([], s.requested)
        self.assertIn("空词只在全站范围可用", r["_status"])

    def test_second_page_failure_is_not_rewritten_as_zero_rows(self):
        """第一页成了、第二页挂了：停在已取的条数并把这一句交出去，不许读成"共 0 条"。"""
        s = _CtaxSession({CTAX_SEARCH: [
            _CtaxResp(_ctax_json([_ctax_row_json(articleid="1")], found=500)),
            _CtaxResp("x", status=500, ctype="text/html"),
            _CtaxResp("x", status=500, ctype="text/html")]})
        r = CT.search_ctax("增值税", size=2, session=s)
        self.assertEqual(1, len(r["results"]))
        self.assertIn("第 2 页取不到", r["_status"])
        self.assertIn("停在已取的 1 条", r["_status"])

    def test_mirror_endpoint_is_tried_when_the_domain_fails(self):
        """域名那一路打不通就换镜像落点，换成功了不叫失败。"""
        s = _CtaxSession({CTAX_SEARCH: [_CtaxResp("x", status=500, ctype="text/html"),
                                        _CtaxResp(_ctax_json([_ctax_row_json()]))]})
        r = CT.search_ctax("增值税", size=1, session=s)
        self.assertEqual(2, len(s.requested))
        self.assertEqual(CT.SEARCH_ENDPOINTS[1], s.requested[1][0])
        self.assertEqual(1, len(r["results"]))
        self.assertNotIn("_error", r)

    def test_both_endpoints_failing_is_named_as_a_failure(self):
        """两个落点都试完才算失败；500 那句要带上"不是限流"的判据。"""
        s = _CtaxSession({CTAX_SEARCH: [_CtaxResp("x", status=500, ctype="text/html"),
                                        _CtaxResp("y", status=500, ctype="text/html")]})
        r = CT.search_ctax("增值税", size=1, session=s)
        self.assertEqual(2, len(s.requested))
        self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
        self.assertIn("HTTP 500", r["_status"])
        self.assertIn("不是限流", r["_status"])

    @staticmethod
    def _wide_pages(count):
        """备 count 页、每页 SEARCH_PAGE_SIZE 行且行行不同篇的清单，foundNum 给一份取不完的数。"""
        pages = []
        for p in range(count):
            rows = [_ctax_row_json(title="第%d页第%d行" % (p, i),
                                   articleid=str(300000 + p * 1000 + i), subtitle="")
                    for i in range(CT.SEARCH_PAGE_SIZE)]
            pages.append(_CtaxResp(_ctax_json(rows, found=100000)))
        return pages

    def test_fetch_all_stops_at_max_rows(self):
        """--max-rows 写的是行数上限，翻到底那一档过去只认页数，40 发交回 2000 行。"""
        s = _CtaxSession({CTAX_SEARCH: self._wide_pages(6)})
        r = CT.search_ctax("增值税", fetch_all=True, max_rows=60, session=s)
        self.assertEqual([1, 2], [q["pageNo"] for q in s.sent_params])
        self.assertEqual(60, len(r["results"]))
        self.assertIn("max_rows=60 行的上限", r["_status"])
        self.assertIn("不是这一词只有这些", r["_status"])

    def test_max_rows_only_tightens_and_never_expands_size(self):
        s = _CtaxSession({CTAX_SEARCH: self._wide_pages(6)})
        r = CT.search_ctax("增值税", size=1, max_rows=120, session=s)
        self.assertEqual(1, len(s.requested))
        self.assertEqual(1, len(r["results"]), "max_rows 不能反过来把 size 顶开")

    def test_channel_outside_the_sites_domain_is_refused(self):
        """站点给 3、负数回一份 37 字节空结构，那句读数跟"这一词没命中"长得一样。"""
        for ch in (3, 20, -1):
            s = _CtaxSession({})
            r = CT.search_ctax("增值税", size=1, channel=ch, session=s)
            self.assertEqual([], s.requested, "越界的 channel 不该发出去")
            self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
            self.assertIn("37 字节", r["_status"])

    def test_match_outside_the_five_slots_is_refused(self):
        """拼错的 match 过去会换成 q 发出去，交回的读数是全文那一路的，看着像限定生效了。"""
        for m in ("titel", "Tile", "", "subtitle", "doc-number", "docNumber"):
            s = _CtaxSession({})
            r = CT.search_ctax("增值税", size=1, match=m, session=s)
            self.assertEqual([], s.requested)
            self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
            self.assertIn("六枚", r["_status"])

    def test_doc_number_match_sends_the_subtitle_slot(self):
        """按文号定位只能走 subtitle 这一枚：站点把文号存在检索行的 subtitle 列。

        q= 是全文匹配，会把正文援引了这枚文号的解读文章一起带回来——2026-11-27 实测
        「国家税务总局公告2025年第15号」q= 报 10 条里只有 1 条文号真在列里；
        「财税〔2016〕36号」q= 报 1,210 条，subtitle= 报 1 条就是那份原文。
        """
        s, _ = self._one_hit(match="doc_number")
        q = s.sent_params[0]
        self.assertEqual("增值税", q["subtitle"])
        self.assertNotIn("q", q, "q 会把位置参数盖掉，同发等于窄档没生效")
        for other in ("title", "content", "keyword", "author"):
            self.assertNotIn(other, q)

    def test_doc_number_writing_variants_are_not_normalised(self):
        """站点在 subtitle 这一枚上不挑写法，本层就不替它整形。

        全角〔2016〕与半角[2016] 回逐字节相同的 824 字节；机关名带不带空格回相同的
        3,249 字节。整形反而可能把读者给的原串改坏，所以原样发出去。
        """
        for given in ("财税〔2016〕36号", "财税[2016]36号",
                      "财政部 税务总局公告2026年第29号", "财政部税务总局公告2026年第29号"):
            s2 = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([_ctax_row_json()]))})
            CT.search_ctax(given, size=1, match="doc_number", session=s2)
            self.assertEqual(given, s2.sent_params[0]["subtitle"])

    def test_non_positive_size_is_refused_unless_paging_to_the_end(self):
        s = _CtaxSession({})
        for size in (0, -1):
            r = CT.search_ctax("增值税", size=size, session=s)
            self.assertEqual([], s.requested, "size=0 过去白发一次请求再交回空清单")
            self.assertIn("一篇也不要", r["_status"])
        # 翻到底这一档不看 size：find_by_doc_number 按 size=0 加 max_rows 走
        s2 = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([_ctax_row_json()], found=1))})
        CT.search_ctax("增值税", size=0, fetch_all=True, session=s2)
        self.assertEqual(1, len(s2.requested))

    def test_negative_max_rows_is_refused(self):
        s = _CtaxSession({})
        r = CT.search_ctax("增值税", fetch_all=True, max_rows=-1, session=s)
        self.assertEqual([], s.requested)
        self.assertIn("负数", r["_status"])


class TestCtaxDocNumberLookup(_CtaxOffline):
    """`find_by_doc_number` 这一路先窄后宽：窄档的 0 不能读成「站内没有这份文件」。

    2026-11-27 实测：文号装在检索行的 `subtitle` 列，`q=` 是全文匹配——
    「国家税务总局公告2025年第15号」`q=` 报 10 条而其中只有 1 条文号真在列里，
    「财税〔2016〕36号」`q=` 报 1,210 条、`subtitle=` 报 1 条就是那份原文。
    但 200 行取样里只有 47 行录了 subtitle，所以窄档回 0 必须回落 `q=` 再问一次。
    """

    def _run(self, doc, pages):
        s = _CtaxSession({CTAX_SEARCH: pages})
        return s, CT.find_by_doc_number(doc, session=s)

    def test_the_narrow_slot_is_asked_first_and_stops_there(self):
        """窄档命中就收口：只发一次请求，且发的是 subtitle= 不是 q=。"""
        s, r = self._run("财税〔2016〕36号",
                         [_CtaxResp(_ctax_json([_ctax_row_json(subtitle="财税〔2016〕36号")],
                                               found=1))])
        self.assertEqual(1, len(s.requested), "窄档命中了还往后问，等于白跑一次全文检索")
        self.assertEqual("财税〔2016〕36号", s.sent_params[0]["subtitle"])
        self.assertNotIn("q", s.sent_params[0])
        self.assertEqual(["doc_number=财税〔2016〕36号"], r["_queries_tried"])

    def test_the_fallback_sentence_is_absent_when_the_narrow_slot_hit(self):
        s, r = self._run("财税〔2016〕36号",
                         [_CtaxResp(_ctax_json([_ctax_row_json(subtitle="财税〔2016〕36号")],
                                               found=1))])
        self.assertNotIn("回落", r["_caveat"], "窄档自己命中的，不该说成回落取到的")

    def test_a_zero_from_the_narrow_slot_falls_back_to_fulltext(self):
        """窄档 0 条 ⇒ 回落 q=，并把「这是回落」写进 _caveat。"""
        s, r = self._run("财政部 税务总局公告2026年第29号",
                         [_CtaxResp(_ctax_json([], found=0)),
                          _CtaxResp(_ctax_json([_ctax_row_json()], found=1))])
        self.assertEqual(2, len(s.requested))
        self.assertIn("subtitle", s.sent_params[0])
        self.assertEqual("财政部 税务总局公告2026年第29号", s.sent_params[1]["q"])
        self.assertEqual(["doc_number=财政部 税务总局公告2026年第29号",
                          "q=财政部 税务总局公告2026年第29号"], r["_queries_tried"])
        self.assertIn("这一份是回落全文", r["_caveat"])
        self.assertIn("窄档的 0 不代表站内没有这份文件", r["_caveat"])

    def test_the_space_variant_is_asked_only_when_it_differs(self):
        """去空白那一档只在真去掉东西时才问；写法本就无空白的文号不多发那一次。"""
        s, r = self._run("财税〔2016〕36号",
                         [_CtaxResp(_ctax_json([], found=0)),
                          _CtaxResp(_ctax_json([], found=0))])
        self.assertEqual(["doc_number=财税〔2016〕36号", "q=财税〔2016〕36号"],
                         r["_queries_tried"], "无空白的串不该再多问一遍去空白那一档")
        self.assertEqual(2, len(s.requested))
        s2, r2 = self._run("财政部 税务总局公告2026年第29号",
                           [_CtaxResp(_ctax_json([], found=0)),
                            _CtaxResp(_ctax_json([], found=0)),
                            _CtaxResp(_ctax_json([], found=0))])
        self.assertEqual(3, len(r2["_queries_tried"]))
        self.assertEqual("q=财政部税务总局公告2026年第29号", r2["_queries_tried"][2])
        self.assertTrue(r2["_status"].startswith("0 条"),
                        "三档都空要报成站点回 0，不能报成没走成")

    def test_empty_doc_number_asks_the_site_nothing(self):
        s = _CtaxSession({})
        r = CT.find_by_doc_number("   ", session=s)
        self.assertEqual([], s.requested)
        self.assertIn("没给文号", r["_status"])


class TestCtaxMidPageDropout(_CtaxOffline):
    """翻页中途的空页：站点实测不会在吐满之前给空页，所以那是断供不是尽头。

    判据前提来自现拉读数（.tmp-inspect\\ctax_fullend_control.py）：
    「财政部 税务总局公告2026年第29号」foundNum=4 收到 4 行、「关税税则委员会
    2024」foundNum=6 收到 6 行，两词都在吐满时正常收口、没等到空页；真没命中的
    词首页即空且 foundNum=0。旧写法 `if not rows: break` 把中途空页当列表尽头，
    再落到"已到页数上限 40 页"那支——只翻了 2 页却说成翻到底，且 _error 不给，
    聚合层（tax_aggregator.py:381）就不会把这一源记进 errors。
    """

    def _pages(self, found_first, rows_first, found_second, rows_second):
        return {CTAX_SEARCH: [
            _CtaxResp(_ctax_json([_ctax_row_json(title="A%d" % i)
                                  for i in range(rows_first)], found=found_first)),
            _CtaxResp(_ctax_json([_ctax_row_json(title="B%d" % i)
                                  for i in range(rows_second)], found=found_second)),
        ]}

    def test_dropout_raises_flag_not_silent_end(self):
        """控制组之外：站点报 5 条、第 2 页给空 ⇒ 必须留 _error 且说清不是完整集合。"""
        s = _CtaxSession(self._pages(5, 2, 5, 0))
        r = CT.search_ctax("增值税", fetch_all=True, session=s)
        self.assertEqual(2, len(s.requested))
        self.assertEqual(2, len(r["results"]))
        self.assertEqual(5, r["total"])
        self.assertIn("断供", r["_status"])
        self.assertIn("不是这一词的完整集合", r["_status"])
        self.assertTrue(r.get("_error"), "少了 _error，聚合层会把这一源报成'取到了'")
        self.assertEqual(r["_status"], r["_error"])

    def test_honest_end_of_list_is_not_flagged(self):
        """控制组：吐满即收口（foundNum=2、首页给满）不得报断供。"""
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json(
            [_ctax_row_json(title="A1"), _ctax_row_json(title="A2")], found=2))})
        r = CT.search_ctax("增值税", fetch_all=True, session=s)
        self.assertEqual(1, len(s.requested), "收满后不该再要下一页")
        self.assertEqual(2, len(r["results"]))
        self.assertNotIn("_error", r)
        self.assertNotIn("断供", r["_status"])

    def test_genuine_zero_hit_is_still_zero_hit(self):
        """真 0 命中（首页即空、foundNum=0）照旧报"没有命中"，不许判成故障。"""
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([], found=0))})
        r = CT.search_ctax("增值税", size=5, session=s)
        self.assertEqual([], r["results"])
        self.assertEqual(0, r["total"])
        self.assertIn("没有命中", r["_status"])
        self.assertNotIn("_error", r)

    def test_max_rows_cut_is_not_reported_as_dropout(self):
        """按 max_rows 主动裁掉不是断供：话术仍应是"已到上限，不是这一词只有这些"。"""
        s = _CtaxSession(self._pages(10, 2, 10, 3))
        r = CT.search_ctax("增值税", fetch_all=True, max_rows=3, session=s)
        self.assertEqual(3, len(r["results"]))
        self.assertNotIn("断供", r["_status"])
        self.assertNotIn("_error", r)
        self.assertIn("不是这一词只有这些", r["_status"])


class TestCtaxColumnScope(_CtaxOffline):
    """栏目限定的三种判据：唯一命中、重名、表里没有。后两种都不发出请求。"""

    TABLE = [
        {"nodeid": 24, "name": "政策", "dir": "policy", "foundNum": 0, "parent": True},
        {"nodeid": 8215, "name": "其他税种", "dir": "other", "foundNum": 23},
        {"nodeid": 63, "name": "实务分析", "dir": "sssw", "foundNum": 120},
        {"nodeid": 77, "name": "实务分析", "dir": "news", "foundNum": 90},
    ]

    def setUp(self):
        super().setUp()
        p = mock.patch.object(CT, "load_columns", return_value=self.TABLE)
        p.start()
        self.addCleanup(p.stop)

    def test_three_states_of_the_lookup(self):
        self.assertEqual(("ok", ["8215"]), CT.column_lookup("其他税种"))
        state, cand = CT.column_lookup("实务分析")
        self.assertEqual("ambiguous", state)
        self.assertEqual(2, len(cand))
        self.assertEqual(("missing", []), CT.column_lookup("没有这一栏"))
        self.assertEqual(("missing", []), CT.column_lookup("  "))

    def test_nodeid_of_returns_empty_for_both_non_ok_states(self):
        self.assertEqual("", CT.nodeid_of("实务分析"))
        self.assertEqual("", CT.nodeid_of("没有这一栏"))
        self.assertEqual("8215", CT.nodeid_of("其他税种"))

    def test_ambiguous_name_is_refused_without_a_half_limit(self):
        """站点确实有重名栏目，不替读者挑一条；报错把两行都列出来。"""
        s = _CtaxSession({})
        r = CT.search_ctax("增值税", node="实务分析", session=s)
        self.assertEqual([], s.requested)
        self.assertEqual("ambiguous column", r["_error"])
        self.assertIn("2 行对上", r["_status"])
        self.assertIn("nodeID", r["_status"])

    def test_missing_name_tells_to_rebuild_the_table(self):
        s = _CtaxSession({})
        r = CT.search_ctax("增值税", node="没有这一栏", session=s)
        self.assertEqual([], s.requested)
        self.assertIn("--update-columns", r["_status"])

    def test_parent_column_is_sent_but_flagged(self):
        """父栏目检索按叶节点收，整片回 0 不是"这一类没有文件"，要随读数交出。"""
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([], found=0))})
        r = CT.search_ctax("增值税", node="政策", size=1, session=s)
        self.assertEqual("24", s.sent_params[0]["nodeID"])
        self.assertIn("父栏目", r["_filter_note"])
        self.assertIn("叶节点", r["_filter_note"])

    def test_leaf_column_carries_no_parent_note(self):
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([_ctax_row_json()]))})
        r = CT.search_ctax("增值税", node="其他税种", size=1, session=s)
        self.assertEqual("8215", s.sent_params[0]["nodeID"])
        self.assertNotIn("_filter_note", r)

    def test_numeric_node_skips_the_table(self):
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(_ctax_json([_ctax_row_json()]))})
        CT.search_ctax("增值税", node="63", size=1, session=s)
        self.assertEqual("63", s.sent_params[0]["nodeID"])


class TestCtaxDedupCountsArticles(_CtaxOffline):
    """一稿多发：同一篇挂几栏就出几行，收满与计数都按篇不按行。"""

    @staticmethod
    def _four_columns(title="财政部 税务总局公告2026年第29号", date="2026-10-19",
                      doc="财政部 税务总局公告2026年第29号", aid="1016514"):
        cols = ["中央税收法规", "增值税", "其他税种", "财政部 国家税务总局公告"]
        return [_ctax_row_json(title=title, date=date, subtitle=doc, column=c,
                               articleid=str(int(aid) + i))
                for i, c in enumerate(cols)]

    def test_four_columns_merge_into_one_article(self):
        rows = CT.dedup_rows([CT._row_from_json(a) for a in self._four_columns()])
        self.assertEqual(1, len(rows))
        also = rows[0]["also_in_columns"]
        self.assertEqual(3, len(also))
        self.assertEqual(sorted(also), also, "同一份输入两次重建的顺序要一样")
        self.assertNotIn("中央税收法规", also, "首位那一栏不重复列进同稿")

    def test_merge_key_is_title_date_doc_number(self):
        """四行是四个 articleid，所以判据不用 articleid；文号与发布日期各管一件事。"""
        same = [CT._row_from_json(a) for a in self._four_columns()]
        self.assertEqual(1, len(CT.dedup_rows(same)))
        other_doc = self._four_columns()
        other_doc[2]["subtitle"] = "财政部 税务总局公告2026年第30号"
        merged = CT.dedup_rows([CT._row_from_json(a) for a in other_doc])
        self.assertEqual(2, len(merged), "同号不同件是两份文件，不许合")
        self.assertEqual("其他税种", merged[1]["column"])
        other_date = self._four_columns()
        other_date[1]["date"] = "2026-10-18"
        self.assertEqual(2, len(CT.dedup_rows([CT._row_from_json(a)
                                               for a in other_date])), "同名不同日发布不合")

    def test_size_is_counted_in_articles_not_rows(self):
        """第一页 8 行只合出 2 篇，--size 3 必须再翻一页；按行数收会当已收满。"""
        page1 = (self._four_columns()
                 + self._four_columns(title="国家税务总局公告2026年第15号",
                                      doc="国家税务总局公告2026年第15号", aid="1016520"))
        page2 = self._four_columns(title="增值税法实施条例", date="2026-09-01",
                                   doc="", aid="1016600")
        s = _CtaxSession({CTAX_SEARCH: [
            _CtaxResp(_ctax_json(page1, found=200)),
            _CtaxResp(_ctax_json(page2, found=200)),
            _CtaxResp(_ctax_json([], found=200))]})
        r = CT.search_ctax("公告", size=3, session=s)
        self.assertEqual(2, len(s.requested), "没收满就该翻页")
        self.assertEqual([1, 2], [q["pageNo"] for q in s.sent_params])
        self.assertEqual(3, len(r["results"]))
        self.assertIn("合并同一篇挂多栏的行 9 行", r["_status"])

    def test_small_size_still_pages_when_a_page_merges_too_hard(self):
        """一页 48 行只合出 1 篇：页数上限不拿 --size 去换算行数，否则 --size 2 永远取不到第二篇。"""
        rows = self._four_columns() * 12
        s = _CtaxSession({CTAX_SEARCH: [_CtaxResp(_ctax_json(rows, found=600)),
                                        _CtaxResp(_ctax_json(rows, found=600))]})
        r = CT.search_ctax("公告", size=1, session=s)
        self.assertEqual(1, len(s.requested), "一页就收满 1 篇，不必翻页")
        self.assertEqual(1, len(r["results"]))
        s2 = _CtaxSession({CTAX_SEARCH: [_CtaxResp(_ctax_json(rows, found=600)),
                                         _CtaxResp(_ctax_json(
                                             self._four_columns(
                                                 title="国家税务总局公告2026年第15号",
                                                 date="2026-09-30",
                                                 doc="国家税务总局公告2026年第15号",
                                                 aid="2000000"),
                                             found=600))]})
        r2 = CT.search_ctax("公告", size=2, session=s2)
        self.assertEqual(2, len(s2.requested), "第一页合出的篇数不够，第二页要发出去")
        self.assertEqual(2, len(r2["results"]))


class TestCtaxAddressState(_CtaxOffline):
    """2023-02 改版前的老行只看地址形状就能判，不必先吃一个 500。"""

    def test_three_segment_is_refused_on_both_protocols(self):
        for u in (CTAX_OLD_URL, CTAX_OLD_URLS):
            state = CT._address_state(u)
            self.assertNotEqual("ok", state, u)
            self.assertIn("2023-02", state)

    def test_four_segment_is_ok(self):
        self.assertEqual("ok", CT._address_state(CTAX_NEW_URL))

    def test_missing_url_is_refused(self):
        self.assertEqual("行里没有可用地址", CT._address_state(""))

    def test_fetch_sends_nothing_for_an_old_row(self):
        s = _CtaxSession({})
        art = CT.fetch_ctax(CTAX_OLD_URL, session=s)
        self.assertEqual([], s.requested)
        self.assertIn("2023-02", art["_error"])

    def test_row_carries_the_flag_only_when_unreachable(self):
        bad = CT._row_from_json(_ctax_row_json(url=CTAX_OLD_URL))
        good = CT._row_from_json(_ctax_row_json())
        self.assertIn("_url_state", bad)
        self.assertNotIn("_url_state", good)

    def test_row_field_mapping(self):
        row = CT._row_from_json(_ctax_row_json())
        self.assertEqual("财政部 税务总局公告2026年第29号", row["doc_number"])
        self.assertEqual("财政部 国家税务总局", row["agency"])
        self.assertEqual("中国税务报", row["byline"])
        self.assertEqual("中央税收法规", row["column"])
        self.assertEqual("2026年10月12日", row["draft_date"], "author 段装的是成文日期")
        self.assertEqual("2026-10-19", row["date"], "发布与成文两件事都交出")
        self.assertNotIn("author", row)

    def test_non_date_author_survives_as_author(self):
        row = CT._row_from_json(_ctax_row_json(author="张三"))
        self.assertEqual("张三", row["author"])
        self.assertNotIn("draft_date", row)

    def test_snippet_and_abstract_stay_display_only(self):
        """enpcontent 是正文截断、Abstract 是编辑摘要：两样都不接进抽取。"""
        row = CT._row_from_json(_ctax_row_json())
        self.assertEqual("正文起两行……", row["snippet"])
        self.assertEqual("编辑写的摘要", row["abstract"])
        row2 = CT._row_from_json(_ctax_row_json(enpcontent=""))
        self.assertEqual("编辑写的摘要", row2["snippet"])


class TestCtaxForcedUtf8(unittest.TestCase):
    """正文页回 `Content-Type: text/html` 不带 charset，requests 按 ISO-8859-1 解且不报错。"""

    URL = "https://www.ctaxnews.com.cn/policy/2023-02/10/content_9.html"

    def _get(self, ctype, encoding):
        resp = _CtaxResp("正文", ctype=ctype)
        resp.encoding = encoding
        got = CT._http_get(self.URL, session=_CtaxSession({self.URL: resp}))
        self.assertIs(resp, got)
        return got.encoding

    def test_html_without_charset_is_read_as_utf8(self):
        for enc in ("iso-8859-1", "latin-1", "ISO-8859-1"):
            self.assertEqual("utf-8", self._get("text/html", enc), enc)

    def test_declared_charset_is_left_to_the_site(self):
        self.assertEqual("gbk", self._get("text/html;charset=GBK", "gbk"))

    def test_a_default_that_is_not_latin1_is_not_rewritten(self):
        self.assertEqual("utf-8", self._get("text/html", "utf-8"))


class TestCtaxBodyBlocks(_CtaxOffline):
    """正文与元信息夹在注释标记里；政策页与专题页两对标记各写两遍。"""

    def _fetch(self, page):
        s = _CtaxSession({CTAX_NEW_URL: _CtaxResp(page, ctype="text/html")})
        return CT.fetch_ctax(CTAX_NEW_URL, session=s, fetch_interval=0)

    def test_identical_twins_take_the_first_and_say_so(self):
        art = self._fetch(_ctax_article_page())
        self.assertEqual("正文第一段。\n第二段", art["content"], "两份相同，取一份不是漏读")
        self.assertIn("逐字节相同", art["_note"])

    def test_differing_twins_warn_instead_of_choosing_silently(self):
        page = ("<html><body><!--enpcontent--><p>桌面版</p><!--/enpcontent-->"
                "<!--enpproperty<title>x</title>-->"
                "<!--enpcontent--><p>移动版</p><!--/enpcontent-->"
                "<!--enpproperty<title>x</title>--></body></html>")
        art = self._fetch(page)
        self.assertEqual("桌面版", art["content"])
        self.assertIn("两份不一致", art["_note"])
        self.assertIn("复测", art["_note"])

    def test_single_block_page_gets_no_note(self):
        art = self._fetch(_ctax_article_page(times=1))
        self.assertNotIn("_note", art)
        self.assertEqual("正文第一段。\n第二段", art["content"])

    def test_meta_fields_come_from_the_property_block(self):
        art = self._fetch(_ctax_article_page(times=1))
        self.assertEqual("2026-10-19", art["published"])
        self.assertEqual("财政部 税务总局公告2026年第29号", art["doc_number"])
        self.assertEqual("全文有效", art["liability"])
        self.assertEqual(["增值税", "企业所得税"], art["tags"])
        self.assertEqual("2026年10月12日", art["draft_date"])
        self.assertEqual("8215", art["nodeid"])

    def test_empty_content_is_named_picture_body(self):
        art = self._fetch(_ctax_article_page(body="", times=1))
        self.assertEqual("", art["content"])
        self.assertIn("图片型正文", art["_error"])

    def test_page_without_the_marker_reports_raw_length(self):
        page = "<html><body>无标记</body></html>"
        art = self._fetch(page)
        self.assertIn("enpcontent", art["_error"])
        self.assertEqual(len(page), art["_raw_len"])

    def test_error_page_is_read_as_a_dead_address(self):
        """这一站的错误地址回 500 而不是 404，读成地址不存在、不重试。"""
        s = _CtaxSession({CTAX_NEW_URL: _CtaxResp("x" * 572, status=500,
                                                  ctype="text/html")})
        art = CT.fetch_ctax(CTAX_NEW_URL, session=s, fetch_interval=0)
        self.assertIn("500 而不是 404", art["_error"])
        self.assertIn("不重试", art["_error"])


class TestCtaxReadKeepsUnreachableRows(_CtaxOffline):
    """取正文失败的行留在原位带上原因：丢了行就没人知道这一篇没读到。"""

    def test_old_row_keeps_its_place_with_the_reason(self):
        rows = [CT._row_from_json(_ctax_row_json(articleid="1016514")),
                CT._row_from_json(_ctax_row_json(url=CTAX_OLD_URL, articleid="966206"))]
        s = _CtaxSession({CTAX_NEW_URL: _CtaxResp(_ctax_article_page(times=1),
                                                  ctype="text/html")})
        out = CT.read_articles(rows, limit=2, session=s)
        self.assertEqual(2, len(out))
        self.assertEqual("正文第一段。\n第二段", out[0]["content"])
        self.assertIn("2023-02", out[1]["_error"])
        self.assertIn("2023-02", out[1]["_url_state"], "行上的可达性标注不被正文那一步抹掉")
        self.assertEqual([CTAX_NEW_URL], [u for u, _ in s.requested])


class TestCtaxGradingDoesNotGuardThisRoute(unittest.TestCase):
    """这一路的材料算不算实务层，程序不替读者判：`rank_of` 先按标题形态、
    再按来源兜底，而 `PRACTICE_SOURCES` 里没有这一站——转载件按原文件的位阶计。"""

    SRC = "中国税网 (ctaxnews.com.cn)"

    def test_this_site_is_not_in_the_practice_source_list(self):
        joined = "".join(E.PRACTICE_SOURCES)
        self.assertNotIn("ctaxnews", joined)
        self.assertNotIn("中国税网", joined)

    def test_reprint_is_rated_as_the_original_document(self):
        r = E.rank_of("财政部 税务总局公告2026年第29号", source=self.SRC)
        self.assertEqual("normative", r["rank"], r["by"])
        self.assertIn("标题形态", r["by"])
        self.assertEqual("direct", E.role_of(r["rank"], "effective", True))
        self.assertNotEqual("practice", E.role_of(r["rank"], "effective", True))

    def test_only_an_interpretation_title_reaches_the_practice_tier(self):
        """标题以「解读」收尾才落到实务档；按来源名判不到这一站。"""
        hit = E.rank_of("增值税留抵退税政策的解读", source=self.SRC)
        self.assertIn(hit["rank"], E.PRACTICE_RANKS)
        self.assertEqual("practice", E.role_of(hit["rank"], "effective", True))
        miss = E.rank_of("某省税务局关于征管有关事项的说明", source=self.SRC)
        self.assertEqual("unknown", miss["rank"], miss["by"])
        self.assertEqual("unmatched", E.role_of(miss["rank"], "effective", False))


class TestCtaxColumnPageRows(unittest.TestCase):
    """取行只按地址形状，不认列表容器的类名（站点实测有三枚类名，见 NOTE.md
    「栏目页的行形态」）；切不出本栏标题时整页都算本栏，
    靠目录段与本栏检索集两道过滤扣外来行。"""

    @staticmethod
    def _href(d, ym, dd, aid):
        """站点地址里就带着发布日期：/<目录>/<yyyy-mm>/<dd>/content_<id>.html。"""
        return "https://www.ctaxnews.com.cn/%s/%s/%s/content_%s.html" % (d, ym, dd, aid)

    @classmethod
    def _li(cls, d, ym, dd, aid, text):
        return '<li><a href="%s">%s</a></li>' % (cls._href(d, ym, dd, aid), text)

    def _page(self, own=(), extra=(), header=True):
        """extra 那几行放进 layout-380 里面，是侧栏推荐位；
        own 那几行是本栏列表，其中目录段不对的属于"留在段内的外来行"。
        外壳类名 `tabList` 是合成的：站点这一批 14 份栏目页副本里它 0 处命中
        （见 NOTE.md「栏目页的行形态」），故意挑一枚站点没发过的名字，
        才能验出 `_page_rows` 根本不读类名。"""
        head = '<div class="column-header-1">税案通报</div>' if header else ""
        return ('<html><body>%s<ul class="tabList">%s</ul>'
                '<div class="layout-380">侧栏推荐%s</div></body></html>'
                % (head, "".join(own), "".join(extra)))

    def test_rows_come_from_the_href_shape_not_a_container_class(self):
        """这一页的行包在合成类名 `ul.tabList` 里，没有 div.newsList-item：
        按类名取行的话读出 0 行，按地址形状取照样交回 2 行。"""
        page = self._page(own=[self._li("sswfaj", "2026-06", "22", "111", "某案通报"),
                               self._li("sswfaj", "2026-05", "08", "222", "另一案通报")])
        rows, off_col, sliced, off_set = CT._page_rows(page, "sswfaj", "税案通报")
        self.assertEqual(2, len(rows))
        self.assertEqual("2026-06-22", rows[0]["date"], "发布日期就在地址里")
        self.assertTrue(sliced)
        self.assertEqual((off_col, off_set), (0, 0))

    def test_off_directory_rows_inside_the_region_are_counted(self):
        page = self._page(own=[self._li("sswfaj", "2026-06", "22", "111", "本案"),
                               self._li("policy", "2026-06", "20", "333", "别栏的政策")])
        rows, off_col, sliced, _ = CT._page_rows(page, "sswfaj", "税案通报")
        self.assertEqual(1, len(rows))
        self.assertEqual(1, off_col)
        self.assertTrue(sliced)

    def test_sidebar_rows_are_cut_before_scanning(self):
        """侧栏那块在 layout-380 之后：整段先切掉，所以不占 off_col 那一档。"""
        page = self._page(own=[self._li("sswfaj", "2026-06", "22", "111", "本案")],
                          extra=[self._li("policy", "2026-06", "20", "333", "侧栏推荐")])
        rows, off_col, sliced, _ = CT._page_rows(page, "sswfaj", "税案通报")
        self.assertEqual(1, len(rows))
        self.assertEqual(0, off_col)
        self.assertTrue(sliced)

    def test_unsliced_page_is_judged_by_the_search_set(self):
        """页面没有 column-header-1 时切不出本栏段，行的归属只能由本栏检索集判。
        实测走这一支的三栏：按别的栏铺块的落地页 node_13、
        只铺一块相关文号列表的短页 node_8030、父栏目页 node_24；
        专题页 node_8131 有本栏标题，不在此列。"""
        page = self._page(header=True,
                          own=[self._li("sswfaj", "2026-06", "22", "111", "在册的"),
                               self._li("sswfaj", "2026-06", "21", "222", "不在册的")])
        no_head = self._page(header=False,
                             own=[self._li("sswfaj", "2026-06", "22", "111", "在册的"),
                                  self._li("sswfaj", "2026-06", "21", "222", "不在册的")])
        _, _, sliced, _ = CT._page_rows(page, "sswfaj", "税案通报")
        self.assertTrue(sliced)
        rows, off_col, sliced2, off_set = CT._page_rows(
            no_head, "sswfaj", "税案通报", {"111"})
        self.assertFalse(sliced2)
        self.assertEqual(1, len(rows))
        self.assertEqual((off_col, off_set), (0, 1))
        rows_all, _, _, _ = CT._page_rows(no_head, "sswfaj", "税案通报")
        self.assertEqual(2, len(rows_all), "不给检索集时同目录的行一律收，宁多不漏")

    def test_date_only_line_is_not_glued_into_the_title(self):
        """发布日期与标题在同一枚锚里，中间由 <br> 或块级标签分开：只剔纯日期那一行。"""
        li = ('<li><a href="%s">某逃税案查处情况通报'
              '<br><span class="time">2026.6.22</span></a></li>'
              % self._href("sswfaj", "2026-06", "22", "111"))
        rows, _, _, _ = CT._page_rows(self._page(own=[li]), "sswfaj", "税案通报")
        self.assertEqual("某逃税案查处情况通报", rows[0]["title"])
        # 规则的作用范围：日期与标题之间没有任何分隔时，两者本就是同一行，
        # 这一条判据不动它——留着这一句，免得以后把"整行只有日期"读成"标题里不含日期"。
        glued = ('<li><a href="%s"><span>某逃税案查处情况通报</span>'
                 '<span class="time">2026.6.22</span></a></li>'
                 % self._href("sswfaj", "2026-06", "22", "112"))
        rows2, _, _, _ = CT._page_rows(self._page(own=[glued]), "sswfaj", "税案通报")
        self.assertEqual("某逃税案查处情况通报2026.6.22", rows2[0]["title"])

    def test_two_line_title_keeps_both_lines(self):
        li = ('<li><a href="%s"><p>关于发布</p><p>增值税若干事项的公告</p></a></li>'
              % self._href("sswfaj", "2026-06", "22", "111"))
        rows, _, _, _ = CT._page_rows(self._page(own=[li]), "sswfaj", "税案通报")
        self.assertEqual("关于发布 增值税若干事项的公告", rows[0]["title"])

    def test_image_only_row_is_dropped_not_invented(self):
        li = '<li><a href="%s"><img src="/i/1.jpg"></a></li>' % self._href(
            "sswfaj", "2026-06", "22", "111")
        rows, _, _, _ = CT._page_rows(self._page(own=[li]), "sswfaj", "税案通报")
        self.assertEqual([], rows)

    def test_summary_attaches_to_the_title_row(self):
        href = self._href("sswfaj", "2026-06", "22", "111")
        chunk = ('<div class="newsList-item clearfix">'
                 '<p class="title"><a href="%s">某案通报</a></p>'
                 '<p class="summary"><a href="%s">案情摘要两行</a></p>'
                 '<span class="time">2026.6.22</span></div></div>' % (href, href))
        page = ('<html><body><div class="column-header-1">税案通报</div>%s'
                '<div class="layout-380">侧栏</div></body></html>' % chunk)
        rows, off_col, sliced, _ = CT._page_rows(page, "sswfaj", "税案通报")
        self.assertEqual(1, len(rows))
        self.assertTrue(sliced)
        self.assertEqual("案情摘要两行", rows[0]["snippet"])

    def test_pages_below_one_is_refused_instead_of_reading_one_page(self):
        """--pages 0 与负数过去落到 max(pages, 1)，交回的清单不在请求里。"""
        for pages in (0, -1):
            s = _CtaxSession({})
            r = CT.list_column("63", pages=pages, session=s)
            self.assertEqual([], s.requested)
            self.assertTrue(r["_status"].startswith("没走成"), r["_status"])
            self.assertIn("一页也不要", r["_status"])


class TestCtaxParentColumnExpansion(unittest.TestCase):
    """栏目表重建时，父栏目那一页取不到会静默丢掉整批孙辈，三个自洽计数与落盘行数都看不见。

    判据前提（2026-11-24 真站实测，见 references/source_defects.md 那一行）：
      健康父栏目第一页 10/10 全 HTTP 200；同一栏目第 11 页回 500、572 字节、0 枚 node_ 链接；
      但 node_1269 健康 200 也交出 0 枚子栏链接且页面无错误字样。
    ⇒ 只能认「异常」与「非 200」，「0 链接」不能当失败信号（否则把健康栏目误报成故障）。
    """

    PARENTS = {"24", "36", "8015"}
    LEAVES = {"16", "27", "20"}
    PLACEHOLDER = {"15"}
    CHILD = {"24": ["60", "61", "62", "63", "64"],
             "36": ["70", "71"],
             "8015": ["8030", "8031", "8196"]}

    def _all_children(self):
        return sorted(c for v in self.CHILD.values() for c in v)

    def _link(self, nid):
        return '<a href="/policy/node_%s.html">栏目%s</a>' % (nid, nid)

    def _home(self):
        ids = sorted(self.LEAVES) + sorted(self.PARENTS) + sorted(self.PLACEHOLDER)
        return "<html><body>" + "".join(self._link(n) for n in ids) + "</body></html>"

    def _resp(self, text, status=200):
        return _CtaxResp(text, status=status, ctype="text/html; charset=utf-8")

    def _rebuild(self, break_parent=None, mode="except", max_nodes=120, childless=()):
        """跑一轮 update_columns，交回 (栏目行, 没收全说明, 探测过的 nodeID, stderr)。"""
        all_children = self._all_children()

        def art(nid):
            return {"nodesearchname": "栏" + nid,
                    "url": "https://www.ctaxnews.com.cn/policy/2026-01/01/content_%s.html" % nid,
                    "title": "t", "pubDate": "2026-01-01"}

        pages, envs = [], []

        def fake_get(url, params=None, timeout=None, session=None, **kw):
            path = re.sub(r"^https?://[^/]+", "", url)
            if path in ("", "/"):
                return self._resp(self._home())
            m = re.search(r"node_(\d+)(?:_\d+)?\.html", path)
            if not m:
                return self._resp("<html><body>?</body></html>")
            nid = m.group(1)
            pages.append(nid)
            if break_parent and nid == break_parent:
                if mode == "except":
                    raise TimeoutError("column page read timed out. timeout=30")
                return self._resp("<html><body>服务器错误，请稍后重试</body></html>", 500)
            if nid in childless:
                return self._resp("<html><body>这一栏健康，但没有子栏</body></html>")
            kids = self.CHILD.get(nid)
            if kids:
                return self._resp("<html><body>" + "".join(self._link(c) for c in kids)
                                  + "</body></html>")
            return self._resp("<html><body>没有子栏</body></html>")

        def fake_once(params, session=None):
            nid = str(params.get("nodeID"))
            envs.append(nid)
            if nid in self.PARENTS or nid in self.PLACEHOLDER:
                return {"foundNum": 0, "article": []}, ""
            if nid in self.LEAVES or nid in all_children:
                return {"foundNum": 5, "article": [art(nid)]}, ""
            return None, "这一枚探测没连上"

        with tempfile.TemporaryDirectory() as td:
            err = io.StringIO()
            with mock.patch.object(CT, "_http_get", fake_get), \
                 mock.patch.object(CT, "_search_once", fake_once), \
                 mock.patch.object(CT, "COLUMNS_FILE", Path(td) / "ctax_columns.json"), \
                 mock.patch.object(CT, "SEARCH_MIN_GAP", 0), \
                 mock.patch.object(CT, "READ_INTERVAL", 0), \
                 contextlib.redirect_stderr(err):
                cols, incomplete = CT.update_columns(session=object(),
                                                     max_nodes=max_nodes)
            written = json.loads((Path(td) / "ctax_columns.json")
                                 .read_text(encoding="utf-8"))["columns"]
        return cols, incomplete, envs, err.getvalue(), written

    def test_control_round_is_complete_and_says_nothing(self):
        """前提：全部正常时表完整、说明必须是空串——不许把健康轮次报成有缺。"""
        cols, incomplete, _, _, written = self._rebuild()
        expected = len(self.LEAVES) + len(self.PARENTS) + len(self._all_children())
        self.assertEqual(expected, len(cols))
        self.assertEqual([], self._missing_from(cols))
        self.assertEqual("", incomplete, incomplete)
        self.assertEqual(len(cols), len(written))

    def _missing_from(self, cols):
        got = {str(c["nodeid"]) for c in cols}
        return [c for c in self._all_children() if c not in got]

    def test_parent_page_exception_names_the_dropped_children(self):
        """A：父栏目页抛异常 ⇒ 整批孙辈没进表，且必须逐枚点名，不能响亮说"重建完成"。"""
        cols, incomplete, envs, _, _ = self._rebuild(break_parent="24", mode="except")
        self.assertEqual(["60", "61", "62", "63", "64"], self._missing_from(cols))
        self.assertFalse([x for x in envs if x in self.CHILD["24"]],
                         "这一档根本没为子栏发过探测，说明不该假装探过")
        self.assertIn("24", incomplete)
        self.assertIn("TimeoutError", incomplete)
        self.assertIn("没探测到", incomplete)

    def test_parent_page_http_500_is_not_mistaken_for_a_childless_column(self):
        """B：旧代码从不看状态码，500 的错误页交出 0 枚链接，读起来像"这栏本无子栏"。"""
        cols, incomplete, _, _, _ = self._rebuild(break_parent="24", mode="500")
        self.assertEqual(["60", "61", "62", "63", "64"], self._missing_from(cols))
        self.assertIn("HTTP 500", incomplete)

    def test_healthy_column_without_children_is_not_reported_as_failure(self):
        """E：node_1269 那类——HTTP 200 且 0 枚子栏链接是健康的，不得误判成故障。"""
        cols, incomplete, _, _, _ = self._rebuild(childless=("36",))
        self.assertEqual(["70", "71"], self._missing_from(cols))
        self.assertEqual("", incomplete,
                         "健康但无子栏的父栏目被报成展开失败了：%r" % incomplete)

    def test_probing_cap_reports_which_parents_went_unexpanded(self):
        """D：撞到 max_nodes 而没去展开的父栏目也要点名（同样丢孙辈、同样无痕过）。"""
        cols, incomplete, _, _, _ = self._rebuild(max_nodes=6)
        self.assertTrue(self._missing_from(cols))
        self.assertIn("上限", incomplete)
        for nid in self.PARENTS:
            self.assertIn(nid, incomplete)


class TestCtaxSubSkillDocHooks(unittest.TestCase):
    """子技能文档点名的符号要在发货代码里；探针的逐项请求数与 NOTE.md 那张表对得上账。"""

    DOC_DIR = ROOT / "search_source" / "ctaxnews"

    def test_named_symbols_exist(self):
        named = set()
        for name in ("SKILL.md", "NOTE.md"):
            text = (self.DOC_DIR / name).read_text(encoding="utf-8")
            named |= set(re.findall(r"tax_ctax\.(?!py\b)([A-Za-z_][A-Za-z0-9_]*)", text))
        self.assertTrue(named, "两份文档至少要点名一条判据")
        self.assertEqual([], [n for n in sorted(named) if not hasattr(CT, n)])

    def test_probe_item_costs_match_the_note_table(self):
        src = (self.DOC_DIR / "probe_ctaxnews.py").read_text(encoding="utf-8")
        cost = None
        for node in ast.parse(src).body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "COST"):
                cost = ast.literal_eval(node.value)
        self.assertIsNotNone(cost, "探针里没有 COST 那张表")
        text = (self.DOC_DIR / "NOTE.md").read_text(encoding="utf-8")
        block = text.split("## 探针项与请求数", 1)
        self.assertEqual(2, len(block), "NOTE.md 里没有「探针项与请求数」这一节")
        table = {}
        for ln in block[1].splitlines():
            m = re.match(r"^\|\s*(\d+)\s*\|.*\|\s*(?:约\s*)?(\d+)\s*\|\s*$", ln)
            if m:
                table[int(m.group(1))] = int(m.group(2))
        self.assertEqual(sorted(cost), sorted(table), "表的行与探针的项不成同一集合")
        for n in cost:
            self.assertEqual(cost[n], table[n], "第 %d 项的请求数对不上" % n)
        total, fast = sum(cost.values()), sum(cost.values()) - cost[10]
        self.assertEqual(219, total, "探针的 COST 合计与文档那两个数不等，先核对哪一侧改了")
        self.assertEqual(117, fast, "去掉第 10 项（栏目表重建）之后的合计对不上")
        # 同一对合计复述在六处文字里：NOTE 的复测入口那一行、表下面那一行、单轮耗时那一行，
        # 子技能 SKILL 命令行那两条注释，README 目录树那一行，台账登记那一行。
        # 这六处都在用例够得着的路径上——改了表不改它们，读者按文字发请求就会数错。
        entry = [ln for ln in text.splitlines() if "复测入口" in ln]
        self.assertEqual(1, len(entry), "NOTE.md 里复测入口那一行不唯一")
        self.assertEqual([total, fast],
                         [int(x) for x in re.findall(r"(\d+) 次", entry[0])],
                         "NOTE.md 复测入口那一行的两个数与表不等")
        below = [ln for ln in block[1].splitlines() if ln.startswith("全项")]
        self.assertEqual(1, len(below), "表下面那行合计不唯一")
        self.assertEqual([total, fast],
                         [int(x) for x in re.findall(r"(\d+) 次", below[0])][:2],
                         "表下面那行的两个数与表不等")
        skill = (self.DOC_DIR / "SKILL.md").read_text(encoding="utf-8").splitlines()
        for label, hit, want in (("全项复测", "全项复测", total),
                                 ("--fast", "--fast", fast)):
            ln = [l for l in skill if hit in l and "次" in l]
            self.assertEqual(1, len(ln), "SKILL.md 里 %s 那一行不唯一" % label)
            self.assertEqual(want, int(re.search(r"(\d+) 次", ln[0]).group(1)),
                             "SKILL.md %s 那行的请求数与表不等" % label)
        for rel, phrase in ((self.DOC_DIR / "NOTE.md", "`--fast` 一轮 %d 次请求" % fast),
                            (self.DOC_DIR / "NOTE.md", "全项一轮 %d 次" % total),
                            (ROOT / "README.md",
                             "全项声明 %d 次请求、`--fast` %d 次" % (total, fast)),
                            (ROOT / "references" / "source_defects.md",
                             "（全项 %d、去掉第 10 项后 %d）" % (total, fast))):
            n = rel.read_text(encoding="utf-8").count(phrase)
            self.assertEqual(1, n, "%s 里 %r 要与表相等且只出现一次，实际 %d 次"
                             % (rel.name, phrase, n))

    def test_the_route_is_wired_into_the_aggregator(self):
        """这一路是 ④ 的第 6 源：六处登记一处不缺，日期走服务端而不是本地补筛。

        逐处分开断言——漏一处不会带着别处一起报红：漏 `SOURCE_IMPACT` 时缺口句只剩
        "该源本次没有取到内容"这句兜底，漏 `SOURCE_LABELS` 时缺口行印成裸键 ctax，
        漏 `DATE_SERVER_SOURCES` 时它被本地补筛再过一遍、同一维度算两次。
        """
        for table in ("DEFAULT_SOURCES", "SOURCE_RANK", "SOURCE_LABELS",
                      "SOURCE_IMPACT", "SOURCE_PLAIN", "DATE_SERVER_SOURCES"):
            self.assertIn("ctax", getattr(AGG, table), "接线缺在 %s" % table)
        self.assertNotIn("ctax", AGG.DATE_LOCAL_SOURCES)
        # 四张按源键索引的表与名单必须同集合：只往名单加一枚、表里没登记，
        # 运行时是 KeyError 或 .get 兜底，看输出看不出来。
        keys = {frozenset(AGG.SOURCE_RANK), frozenset(AGG.SOURCE_LABELS),
                frozenset(AGG.SOURCE_IMPACT), frozenset(AGG.SOURCE_PLAIN)}
        self.assertEqual(1, len(keys), "四张源表的键集合不一致")
        self.assertEqual(sorted(AGG.DEFAULT_SOURCES), sorted(keys.pop()))
        # 服务端那一档要逐源登记字段名，否则回显给出"某源由接口自己收窄"却没说收哪一枚
        self.assertEqual(sorted(AGG.DATE_SERVER_SOURCES), sorted(AGG.DATE_SERVER_FIELDS))
        with mock.patch.object(AGG, "search_ctax",
                               return_value={"total": 1, "results": []}) as spy:
            r = AGG.aggregate_search("测试词", size=5, sources=["ctax"],
                                     date_from="2024-01-01", date_to="2026-12-31")
        self.assertEqual("2024-01-01", spy.call_args.kwargs["date_from"])
        self.assertEqual("2026-12-31", spy.call_args.kwargs["date_to"])
        self.assertEqual(["ctax"], r["_date_filter"]["server_side"])
        self.assertEqual({}, r["_date_filter"]["local_window"],
                         "日期已经下推给接口，不该再在窗口内补筛一遍")
        self.assertIn("中国税网收发布日期", r["_date_note"])
        # SKILL 里两处都得各自钉住：只按整篇 assertIn 时，⑪ 那一行能替 ③ L4 那一格
        # 过关，L4 里的接线说明被删掉也不报红，而按 L4 走的调用方读的就是那一格。
        lines = (ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()
        starts = [i for i, ln in enumerate(lines)
                  if ln.startswith("- **L4 实务案例与解读")]
        self.assertEqual(1, len(starts), "③ 的 L4 那一格在 SKILL 里要只有一处")
        block = lines[starts[0]:starts[0] + 40]
        block = block[:next((i for i, ln in enumerate(block) if not ln.strip()),
                            len(block))]
        self.assertTrue(any("源键 `ctax`" in ln for ln in block),
                        "③ L4 那一段要写明这一路在 ④ 的默认名单里")
        rows = [ln for ln in lines if ln.startswith("| 中国税网 ctaxnews.com.cn")]
        self.assertEqual(1, len(rows), "⑪ 数据源表里中国税网那一行要只有一处")
        self.assertIn("源键 `ctax`", rows[0],
                      "⑪ 那一行也要写明它在 ④ 的默认名单里")


# ── 常驻探针自己不能带未定义的名字：一次笔误吃掉整项读数 ──────────────────
PROBE_FILES = sorted((ROOT / "search_source").glob("*/probe_*.py"))


def _unbound_names(src):
    """返回「被读却从没绑定过」的名字。模块级 with/comprehension/except 都算绑定。"""
    tree = ast.parse(src)
    bound = set(dir(builtins))
    used = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            else:
                used.append((node.id, node.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            a = getattr(node, "args", None)
            if a is not None:
                for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
                    bound.add(x.arg)
                if a.vararg:
                    bound.add(a.vararg.arg)
                if a.kwarg:
                    bound.add(a.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                bound.add((al.asname or al.name).split(".")[0])
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for it in node.items:
                if it.optional_vars is not None:
                    for x in ast.walk(it.optional_vars):
                        if isinstance(x, ast.Name):
                            bound.add(x.id)
        elif isinstance(node, ast.comprehension):
            for x in ast.walk(node.target):
                if isinstance(x, ast.Name):
                    bound.add(x.id)
    return sorted({(n, ln) for n, ln in used
                   if n not in bound and not (n.startswith("__") and n.endswith("__"))})


class TestProbeSelfInjury(unittest.TestCase):
    """2026-11-26 那轮 `probe_ctaxnews.py` 第 8 项 14 页全打在
    「取不到：name 'page_note' is not defined」上：`_measure` 的形参叫 `page_no`，
    打印时打成了 `page_note`。15 发请求照样发出去，「实发/声明」对账一片祥和，
    整项读数却一个都没落进汇总——这笔账只能由静态尺来对，不能由请求数来对。
    """

    def test_every_permanent_probe_has_no_unbound_name(self):
        self.assertTrue(PROBE_FILES, "search_source 下应至少有一枚常驻探针")
        for f in PROBE_FILES:
            with self.subTest(probe=str(f.relative_to(ROOT))):
                bad = _unbound_names(f.read_text(encoding="utf-8"))
                self.assertEqual(bad, [], "%s 里有被读却从没绑定的名字：%s" % (f.name, bad))

    def test_a_typo_like_the_one_that_ate_a_probe_item_is_caught(self):
        # 反证：把那次的笔误照原样注回去，尺必须报红（否则上一条绿得没有依据）
        src = (ROOT / "search_source" / "ctaxnews" / "probe_ctaxnews.py").read_text(encoding="utf-8")
        self.assertIn('"" if page_no == "1" else "_%s" % page_no', src)
        broken = src.replace('"" if page_no == "1" else "_%s" % page_no',
                             '"" if page_note == "1" else "_%s" % page_note')
        self.assertNotEqual(broken, src, "注入锚没命中，反证不成立")
        bad = [n for n, _ in _unbound_names(broken)]
        self.assertIn("page_note", bad)


# ── flk 的 total 随参数换值：回显不许把它当命中数或可达页数 ──────────────────
class _NoCache:
    def _key(self, *parts):
        return "|".join(str(p) for p in parts)

    def get(self, key, max_age=0):
        return None

    def set(self, key, value):
        pass


class _FlkResp:
    """`POST /law-search/search/list` 的响应形状：`total` 与 `rows` 都在**根节点**上，
    没有 `data` 那一层（同前缀下的 `enumData` 反倒包在 `data` 里，两条形态相反）。"""

    def __init__(self, total, rows):
        self._payload = {"total": total, "rows": rows, "code": 200, "msg": "查询成功",
                         "searchType": 2, "searchContent": None}
        self.status_code = 200
        self.content = b"{}"
        self.headers = {"Content-Type": "application/json"}
        self.text = "{}"

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestFlkTotalIsNotTheEchoedHitCount(unittest.TestCase):
    """命令行的回显：flk 那一格 `total` 是接口随参数换值的回报，不是命中总数。

    取样口径与逐发读数在 `search_source/npc-flk/NOTE.md` 第二节：同一枚「环境保护」在
    `pageSize=1—5` 回 3,108、6 及以上回 219（2026-10-20 那一次是 3,118 与 224，两档是两份不同的
    集合），`pageSize=10` 翻到第 23 页它又回 3,118 那一档。
    按 `⌈total/pageSize⌉` 报"一共几页"会在一份还能翻的集合上给出一个假的顶。
    """

    def _cli_out(self, total, rows, size):
        buf = io.StringIO()
        argv = ["tax_search.py", "环境保护", "--size", str(size)]
        with mock.patch.object(T, "_request", lambda m, u, **k: _FlkResp(total, rows)), \
                mock.patch.object(T, "_cache", _NoCache()), \
                mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(buf):
            T.main()
        return buf.getvalue()

    def _rows(self, n):
        return [{"bbbs": "id%d" % i, "flfgname": "环境保护法条目%d" % i,
                 "gbrq": "2024-01-01", "sxrq": "2024-02-01", "sxx": 3,
                 "zdjgName": "全国人大常委会", "flxz": "法律"} for i in range(n)]

    def test_rows_read_from_the_root_and_total_is_labelled_as_the_interface_value(self):
        """根节点这一层不包 `data` 也要取到行；`total` 那一格要说成接口回报。"""
        out = self._cli_out(224, self._rows(20), 20)
        self.assertIn("环境保护法条目0", out, "按 data 统一解包会把整批读成空")
        self.assertIn("接口 total 224 条", out)
        self.assertNotIn("共 224 条", out, "这一枚不是命中总数，不许报成「共」")

    def test_no_page_ceiling_derived_from_total(self):
        """224 条按每页 20 行算出的"12 页"不许出现——同一集合按每页 5 行实测翻到 624 页。"""
        out = self._cli_out(224, self._rows(20), 20)
        self.assertIsNone(re.search(r"第 \d+/\d+ 页", out),
                          "回显不许按 total 报可达页数：%s" % out)
        self.assertIn("本屏 20 条", out)


# ── 同一专题的多枚词一轮发：WAF 与正文连读都只付一次 ────────────────────────
class _Shui5BatchOffline(unittest.TestCase):
    """打桩到网络边界（搜狗／站内／正文页），不联网、不开浏览器。

    改前的形状：CLI 只收一枚词，同一专题的三枚词要发三次进程，站内检索与正文
    连读各自过一次 WAF（`read_articles` 的 docstring 记的是浏览器预热 5.9~7.0 秒）。
    主线 ③ 末段要求"在同一条脚本里按词循环"，而脚本没有这一档，纪律落不了地。
    """

    WORDS = ["碳排放权交易", "碳交易", "自愿减排"]
    URLS = {"碳排放权交易": ["https://www.shui5.cn/article/1/101.html",
                             "https://www.shui5.cn/article/2/102.html"],
            "碳交易": ["https://www.shui5.cn/article/2/102.html",
                       "https://www.shui5.cn/article/3/103.html"],
            "自愿减排": ["https://www.shui5.cn/article/4/104.html"]}

    def setUp(self):
        self.waf_calls = []
        self.native_sessions = []
        self.fetch_calls = []
        self.sleeps = []
        self.session = mock.MagicMock(name="waf-session")
        self.sogou_ok = False
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(SH, "_pass_waf", side_effect=self._waf).start()
        mock.patch.object(SH, "sogou_search", side_effect=self._sogou).start()
        mock.patch.object(SH, "search_native", side_effect=self._native).start()
        mock.patch.object(SH, "fetch_shui5", side_effect=self._fetch).start()
        mock.patch.object(SH.time, "sleep",
                          side_effect=lambda s: self.sleeps.append(s)).start()

    def _waf(self, warm_url=""):
        self.waf_calls.append(warm_url)
        return self.session, "打桩过 WAF"

    def _sogou(self, keyword, site=None, size=5):
        if not self.sogou_ok:
            return {"results": [], "_error": "打桩：搜狗这一路没取到", "_blocked": True}
        return {"results": [{"title": keyword + "（搜狗）",
                             "url": self.URLS[keyword][0], "date": "2026-01-01",
                             "snippet": "摘要"}],
                "searched_at": "2026-11-10 00:00:00", "_from_cache": False}

    def _native(self, keyword, size=5, session=None, **kw):
        self.native_sessions.append(session)
        if session is None:
            # 真 search_native 在没有外部会话时自己过一次 WAF，桩要照做，
            # 否则"首词退回站内付了几次预热"这一格量的是桩而不是代码。
            session, _ = self._waf()
        urls = self.URLS[keyword][:size]
        return {"results": [{"title": keyword + "-" + u.rsplit("/", 1)[-1],
                             "url": u, "date": "2026-01-02", "snippet": "摘要",
                             "column": "实务解读"} for u in urls],
                "total": len(urls), "_status": f"命中 {len(urls)} 条"}

    def _fetch(self, url, session=None, page_interval=None):
        self.fetch_calls.append((url, session))
        return {"url": url, "content": "正文-" + url.rsplit("/", 1)[-1],
                "title": "", "date": "", "pages": 1}

    def _run(self, **kw):
        args = dict(size=5, read_body=True, channel="native")
        args.update(kw)
        return SH.search_many(self.WORDS, **args)


class TestShui5BatchOneWafPass(_Shui5BatchOffline):

    def test_three_words_pass_waf_once(self):
        self._run()
        self.assertEqual(1, len(self.waf_calls),
                         "三枚词各过一次 WAF 就是把 6 秒乘以词数：%s" % self.waf_calls)

    def test_every_search_reuses_the_same_session(self):
        self._run()
        self.assertEqual([self.session] * 3, self.native_sessions)

    def test_bodies_are_read_once_per_unique_url(self):
        got = self._run()
        self.assertEqual(4, len(self.fetch_calls),
                         "两枚词共有的那一篇被读了两次：%s" % self.fetch_calls)
        self.assertEqual(4, len(got["results"]))
        self.assertTrue(all(r.get("content") for r in got["results"]))

    def test_shared_url_records_both_keywords(self):
        got = self._run()
        row = next(r for r in got["results"] if r["url"].endswith("/102.html"))
        self.assertEqual(["碳排放权交易", "碳交易"], row["matched_keywords"])

    def test_site_declared_search_gap_is_kept_between_words(self):
        self._run()
        self.assertEqual(2, self.sleeps.count(SH.SEARCH_MIN_GAP),
                         "三枚词之间要留两次站点声明的检索间隔：%s" % self.sleeps)

    def test_per_keyword_attribution_survives_the_merge(self):
        got = self._run()
        self.assertEqual(self.WORDS, [p["keyword"] for p in got["_per_keyword"]])
        self.assertEqual([2, 2, 1], [p["total"] for p in got["_per_keyword"]])
        self.assertEqual(4, got["total"], "total 是去重后的篇数，不是各词命中数之和")

    def test_session_it_passed_is_closed_once(self):
        self._run()
        self.assertEqual(1, self.session.close.call_count)

    def test_empty_word_list_is_refused(self):
        for words in ([], ["", "  "], None):
            with self.assertRaises(ValueError):
                SH.search_many(words)

    def test_duplicate_and_blank_words_are_folded_before_searching(self):
        got = SH.search_many(["碳交易", " 碳交易 ", "", "自愿减排"],
                             size=5, read_body=False, channel="native")
        self.assertEqual(["碳交易", "自愿减排"], got["keywords"])
        self.assertEqual(1, len(self.waf_calls))


class TestShui5BatchChannelCost(_Shui5BatchOffline):

    def test_sogou_success_without_bodies_does_not_pay_for_waf(self):
        self.sogou_ok = True
        self._run(channel="auto", read_body=False)
        self.assertEqual([], self.waf_calls,
                         "搜狗这一路不要凭据，没必要为它过一次浏览器 WAF")

    def test_auto_fallback_to_native_shares_one_waf_for_the_rest(self):
        """首词退回站内时它自己已经过一次 WAF，那份会话不外传；剩下的词共用一份。

        三枚词从三次降到两次。要一次就得让 search_shui5 把内部建的会话交回来，
        那是另一处契约改动，不在这一档里。
        """
        self._run(channel="auto", read_body=False)
        self.assertEqual(2, len(self.waf_calls))
        self.assertEqual([None, self.session, self.session], self.native_sessions)

    def test_bodies_need_waf_even_when_sogou_supplied_the_list(self):
        self.sogou_ok = True
        got = self._run(channel="auto", read_body=True)
        self.assertEqual(1, len(self.waf_calls))
        self.assertEqual(3, len(self.fetch_calls))
        self.assertTrue(all(r.get("content") for r in got["results"]))

    def test_read_articles_does_not_close_a_borrowed_session(self):
        borrowed = mock.MagicMock(name="borrowed")
        SH.read_articles(["https://www.shui5.cn/article/1/101.html"], session=borrowed)
        self.assertEqual(0, borrowed.close.call_count)
        self.assertEqual([], self.waf_calls)
        self.assertIs(borrowed, self.fetch_calls[0][1])

    def test_read_articles_still_passes_and_closes_its_own_session(self):
        SH.read_articles(["https://www.shui5.cn/article/1/101.html"])
        self.assertEqual(1, len(self.waf_calls))
        self.assertEqual(1, self.session.close.call_count)


class TestShui5BatchCli(_Shui5BatchOffline):
    """命令行真收得下多枚词：纪律写在文档里不够，得能照着发。"""

    def _cli(self, argv):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["tax_shui5.py"] + argv):
            with contextlib.redirect_stdout(buf):
                SH.main()
        return buf.getvalue()

    def test_multiple_positionals_take_the_batch_path(self):
        out = self._cli(self.WORDS + ["--size", "5", "--read", "--channel", "native"])
        self.assertEqual(1, len(self.waf_calls))
        self.assertEqual(4, len(self.fetch_calls))
        for w in self.WORDS:
            self.assertIn(w, out)

    def test_single_positional_keeps_the_existing_path(self):
        with mock.patch.object(SH, "search_many",
                               side_effect=AssertionError("单词不该走批量")) as many:
            self._cli(["碳交易", "--size", "5", "--read", "--channel", "native"])
        self.assertEqual(0, many.call_count)
        self.assertEqual(2, len(self.fetch_calls))
        # 单词那条路保持原样：站内检索与正文连读各过一次 WAF。这正是多词那一档
        # 要省掉的开销，不该顺手改掉单词路的既有行为。
        self.assertEqual(2, len(self.waf_calls))

    def test_batch_json_carries_per_keyword_blocks(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["tax_shui5.py"] + self.WORDS + ["--channel", "native", "--json"]):
            with contextlib.redirect_stdout(buf):
                SH.main()
        got = json.loads(buf.getvalue())
        self.assertEqual(self.WORDS, got["keywords"])
        self.assertEqual(3, len(got["_per_keyword"]))


# ── search5 空格多词是任一词命中：把这一轮被谁主导当场说出来 ────────────────
class _Search5Resp:
    """search5 的响应形状：清单与总数都在 searchResultAll 下。"""

    def __init__(self, titles, total):
        self.status_code = 200
        self._payload = {"searchResultAll": {
            "total": total,
            "searchTotal": [{"title": t, "url": f"https://fgk.chinatax.gov.cn/{i}.html",
                             "content": "摘要", "pubDate": "2023-01-01",
                             "pubName": "财政部 税务总局"}
                            for i, t in enumerate(titles)]}}

    def json(self):
        return self._payload


class TestSearch5MultiTermNote(unittest.TestCase):
    """2026-11-10 本机实测（search_chinatax，size=10，FILE_LABELS 默认档）：

        检索词              收窄                命中    首屏标题含「碳排放」
        碳排放权 增值税     无                  1911    0/10
        碳排放权 增值税     wordPlace=1          909    0/10
        碳排放权 增值税     participleRule=5      73    0/10
        碳排放权            无                     1    0/1（正文命中）

    四发的首屏标题里都数不出专题词。空格不是 AND，专题词被税种词顶掉；仅标题匹配
    也救不回来。但 `participleRule=5` 那一发把单独发「碳排放权」命中的那一份
    （`c100013/c5194808`，标题里两枚词都不含、命中在正文）升到了首屏第 3 位——
    所以"标题里 0 条"不能写成"首屏里没有这一份"。这一格不多发请求，
    只用已经取回的那一页把成因说清楚。
    """

    TITLES = ["财政部 税务总局关于增值税小规模纳税人减免增值税政策的公告",
              "财政部 税务总局关于对增值税小规模纳税人免征增值税的公告",
              "财政部 税务总局关于明确增值税小规模纳税人免征增值税政策的公告"] * 3 + [
              "财政部 税务总局关于明确增值税小规模纳税人减免增值税等政策的公告"]

    def setUp(self):
        self.calls = []
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(WS.tax_http, "attempt", side_effect=self._attempt).start()
        mock.patch.object(WS.tax_http, "new_log", return_value=[]).start()

    def _attempt(self, fn, url, log, **kw):
        self.calls.append(url)
        return self.resp, "", False

    def _search(self, keyword, titles=None, total=1911, **kw):
        self.resp = _Search5Resp(self.TITLES if titles is None else titles, total)
        return WS.search_chinatax(keyword, size=10, **kw)

    def test_absent_topic_word_is_named_with_its_zero_count(self):
        got = self._search("碳排放权 增值税")
        note = got.get("_keyword_note", "")
        self.assertTrue(note, "首屏 0/10 含专题词却不吭声，读者只能自己逐条看标题")
        self.assertIn("碳排放权", note)
        self.assertIn("0 条", note)
        self.assertIn("1911", note)
        self.assertIn("任一词命中", note)
        self.assertIn("--precise", note)

    def test_absent_word_is_scoped_to_titles_not_to_the_whole_first_screen(self):
        """计数只看标题，结论也只能说到标题这一层。

        2026-11-10 实测：加 `participleRule=5` 后首屏第 3 位就是单独发「碳排放权」
        命中的那一份（`fgk.chinatax.gov.cn/zcfgk/c100013/c5194808/content.html`），
        而它的标题里既不含「碳排放权」也不含「增值税」——命中在正文。写成
        「在首屏没有条目」就把一份已经在首屏里的文件说成了不在。
        """
        titles = self.TITLES[:9] + ["国家发展改革委关于创新和完善促进绿色发展价格机制的意见"]
        got = self._search("碳排放权 增值税", titles=titles, total=73)
        note = got["_keyword_note"]
        self.assertNotIn("在首屏没有条目", note,
                         "标题里 0 命中不等于首屏里没有这一份：正文命中的那一份就在第 10 位")
        self.assertIn("首屏标题里没有条目", note)

    def test_note_says_title_match_does_not_change_the_semantics(self):
        got = self._search("碳排放权 增值税")
        self.assertIn("--in-title", got["_keyword_note"])
        self.assertIn("不改任一词命中", got["_keyword_note"])

    def test_it_costs_no_extra_request(self):
        self._search("碳排放权 增值税")
        self.assertEqual(1, len(self.calls), "诊断只用已取回的那一页，不许再发一轮")

    def test_single_term_gets_no_note(self):
        self.assertNotIn("_keyword_note", self._search("增值税"))

    def test_all_terms_present_gets_no_note(self):
        titles = ["碳排放权交易的增值税处理", "碳排放权增值税口径"]
        self.assertNotIn("_keyword_note", self._search("碳排放权 增值税", titles=titles))

    def test_genuine_zero_hits_get_no_note(self):
        self.assertNotIn("_keyword_note",
                         self._search("碳排放权 增值税", titles=[], total=0))

    def test_no_term_in_any_title_is_reported_as_such_not_as_a_dominant_word(self):
        titles = ["财政部 税务总局公告2023年第19号"] * 10
        note = self._search("碳排放权 增值税", titles=titles)["_keyword_note"]
        self.assertIn("正文", note)
        self.assertNotIn("主导", note)

    def test_terms_split_on_any_whitespace_and_drop_blanks(self):
        self.assertEqual(["碳排放权", "增值税"], WS.keyword_terms(" 碳排放权\t增值税\n"))
        self.assertEqual(["增值税"], WS.keyword_terms("增值税"))
        self.assertEqual([], WS.keyword_terms("   "))

    def test_cli_prints_the_note(self):
        self.resp = _Search5Resp(self.TITLES, 1911)
        buf = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["tax_web_search.py", "碳排放权 增值税", "--size", "10"]):
            with contextlib.redirect_stdout(buf):
                WS.main()
        self.assertIn("任一词命中", buf.getvalue())

    def test_json_carries_the_note(self):
        got = self._search("碳排放权 增值税")
        self.assertIn("_keyword_note", json.loads(json.dumps(got, ensure_ascii=False)))


# ── NPC 正文日期与版本沿革：一趟取回，别再多下一遍 ─────────────────────────
# 下面五份题注与施行句都是 2026-11-10 从 flk 下载的 docx 里逐字取的原文。
_CARBON_CAPTION = ("（2024年1月25日中华人民共和国国务院令第775号公布\u3000"
                   "根据2026年8月8日《国务院关于修改和废止部分行政法规的决定》修订）")
_CARBON_EFFECTIVE = "第三十三条\u3000本条例自2024年5月1日起施行。"
_VAT_CAPTION = "（2024年12月25日第十四届全国人民代表大会常务委员会第十三次会议通过）"
_VAT_EFFECTIVE = ("第三十八条\u3000本法自2026年1月1日起施行。"
                  "《中华人民共和国增值税暂行条例》同时废止。")
_COLLECTION_CAPTION = (
    "（1992年9月4日第七届全国人民代表大会常务委员会第二十七次会议通过\u3000"
    "根据1995年2月28日第八届全国人民代表大会常务委员会第十二次会议"
    "《关于修改〈中华人民共和国税收征收管理法〉的决定》第一次修正\u3000"
    "2001年4月28日第九届全国人民代表大会常务委员会第二十一次会议修订\u3000"
    "根据2013年6月29日第十二届全国人民代表大会常务委员会第三次会议"
    "《关于修改〈中华人民共和国文物保护法〉等十二部法律的决定》第二次修正\u3000"
    "根据2015年4月24日第十二届全国人民代表大会常务委员会第十四次会议"
    "《关于修改〈中华人民共和国港口法〉等七部法律的决定》第三次修正）")
_RULES_CAPTION = (
    "(2002年9月7日中华人民共和国国务院令第362号公布\u3000"
    "根据2012年11月9日《国务院关于修改和废止部分行政法规的决定》第一次修订\u3000"
    "根据2013年7月18日《国务院关于废止和修改部分行政法规的决定》第二次修订\u3000"
    "根据2016年2月6日《国务院关于修改部分行政法规的决定》第三次修订)")
_RULES_EFFECTIVE = ("第一百一十三条\u3000本细则自2002年10月15日起施行。"
                    "1993年8月4日国务院发布的《中华人民共和国税收征收管理法实施细则》同时废止。")


class TestNpcDateLineage(unittest.TestCase):
    """题注与末条施行句要能被读出来，并且不许把版本沿革判成元数据错。"""

    def _body(self, title, caption, effective):
        ps = [title]
        if caption:
            ps.append(caption)
        ps += ["第一章\u3000总\u3000\u3000则", "第一条\u3000为了测试，制定本法。"]
        if effective:
            ps.append(effective)
        return ps

    def _carbon(self, **kw):
        return DT.law_date_lineage(
            self._body("碳排放权交易管理暂行条例", _CARBON_CAPTION, _CARBON_EFFECTIVE),
            **kw)

    def test_carbon_original_publish_date_comes_from_the_caption(self):
        got = self._carbon(publish_date="2026-08-08", effective_date="2026-08-15")
        self.assertEqual("2024-01-25", got["original_publish_date"])
        self.assertEqual(_CARBON_CAPTION, got["caption"])

    def test_carbon_amendment_is_read_with_its_date_and_document(self):
        got = self._carbon(publish_date="2026-08-08", effective_date="2026-08-15")
        self.assertEqual([{"date": "2026-08-08", "kind": "修订",
                           "document": "国务院关于修改和废止部分行政法规的决定"}],
                         got["amendments"])

    def test_carbon_effective_clause_date_is_the_original_one(self):
        got = self._carbon(publish_date="2026-08-08", effective_date="2026-08-15")
        self.assertEqual("2024-05-01", got["effective_clause_date"])
        self.assertEqual(_CARBON_EFFECTIVE, got["effective_clause"])

    def test_amended_law_is_not_reported_as_a_metadata_conflict(self):
        """录入项 2026-08-08 与正文 2024-05-01 都对，指的是不同版次。"""
        note = self._carbon(publish_date="2026-08-08",
                            effective_date="2026-08-15")["date_note"]
        self.assertIn("2026-08-08", note)
        self.assertIn("2024-05-01", note)
        self.assertIn("不是同一次", note)
        self.assertNotIn("不一致", note)

    def test_explained_version_split_does_not_also_ask_to_verify_it(self):
        """题注已经把差异解释清楚了，就不该再追加一句"核对是否指同一次施行"。"""
        note = self._carbon(publish_date="2026-08-08",
                            effective_date="2026-08-15")["date_note"]
        self.assertNotIn("是否指同一次施行", note)

    def test_all_five_amendments_of_the_collection_law_are_read_in_order(self):
        got = DT.law_date_lineage(
            self._body("中华人民共和国税收征收管理法", _COLLECTION_CAPTION,
                       "第九十四条\u3000本法自2001年5月1日起施行。"),
            publish_date="2015-04-24", effective_date="2015-04-24")
        self.assertEqual("1992-09-04", got["original_publish_date"])
        self.assertEqual(["1995-02-28", "2001-04-28", "2013-06-29", "2015-04-24"],
                         [a["date"] for a in got["amendments"]])
        self.assertEqual(["修正", "修订", "修正", "修正"],
                         [a["kind"] for a in got["amendments"]])
        self.assertEqual("", got["amendments"][1]["document"],
                         "2001 年那次修订题注里没写文件名，不许从别处补一个")

    def test_latest_amendment_not_the_first_is_the_one_compared(self):
        note = DT.law_date_lineage(
            self._body("中华人民共和国税收征收管理法", _COLLECTION_CAPTION,
                       "第九十四条\u3000本法自2001年5月1日起施行。"),
            publish_date="2015-04-24", effective_date="2015-04-24")["date_note"]
        self.assertIn("2015-04-24", note)
        self.assertIn("2001-05-01", note)
        self.assertNotIn("不一致", note)

    def test_ascii_parentheses_and_ordinal_amendments_are_accepted(self):
        got = DT.law_date_lineage(
            self._body("中华人民共和国税收征收管理法实施细则", _RULES_CAPTION,
                       _RULES_EFFECTIVE),
            publish_date="2016-02-06", effective_date="")
        self.assertEqual("2002-09-07", got["original_publish_date"])
        self.assertEqual(["2012-11-09", "2013-07-18", "2016-02-06"],
                         [a["date"] for a in got["amendments"]])
        self.assertEqual("2002-10-15", got["effective_clause_date"])

    def test_body_supplies_the_effective_date_the_record_left_blank(self):
        note = DT.law_date_lineage(
            self._body("中华人民共和国税收征收管理法实施细则", _RULES_CAPTION,
                       _RULES_EFFECTIVE),
            publish_date="2016-02-06", effective_date="")["date_note"]
        self.assertIn("2002-10-15", note)
        self.assertIn("录入项未录", note)

    def test_missing_caption_is_declared_not_guessed(self):
        got = DT.law_date_lineage(
            self._body("中华人民共和国增值税法实施条例", "",
                       "第五十四条\u3000本条例自2026年1月1日起施行。"),
            publish_date="2025-12-25", effective_date="2026-01-01")
        self.assertEqual("", got["caption"])
        self.assertEqual([], got["amendments"])
        self.assertIn("未附题注", got["date_note"])
        self.assertNotIn("不一致", got["date_note"])

    def test_matching_dates_without_amendment_produce_no_conflict_claim(self):
        note = DT.law_date_lineage(
            self._body("中华人民共和国增值税法", _VAT_CAPTION, _VAT_EFFECTIVE),
            publish_date="2024-12-25", effective_date="2026-01-01")["date_note"]
        self.assertNotIn("不是同一次", note)
        self.assertNotIn("不一致", note)

    def test_repealed_law_date_in_the_same_clause_is_not_the_effective_date(self):
        got = DT.law_date_lineage(
            self._body("中华人民共和国增值税法", _VAT_CAPTION, _VAT_EFFECTIVE),
            publish_date="2024-12-25", effective_date="2026-01-01")
        self.assertEqual("2026-01-01", got["effective_clause_date"])

    def test_differing_effective_dates_without_amendment_ask_for_a_check(self):
        got = DT.law_date_lineage(
            self._body("某法", _VAT_CAPTION, "第三十八条\u3000本法自2025年1月1日起施行。"),
            publish_date="2024-12-25", effective_date="2026-01-01")
        self.assertIn("核对", got["date_note"])
        self.assertIn("2025-01-01", got["date_note"])
        self.assertIn("2026-01-01", got["date_note"])

    def test_unreadable_body_says_so_instead_of_claiming_no_caption(self):
        got = DT.law_date_lineage([], publish_date="2026-08-08",
                                  effective_date="2026-08-15")
        self.assertEqual("", got["caption"])
        self.assertEqual("", got["effective_clause_date"])
        self.assertIn("没取到", got["date_note"])
        self.assertNotIn("未附题注", got["date_note"])


class TestNpcPreviewOneRound(unittest.TestCase):
    """--preview 已经下过正文，日期沿革就该在这一趟里带出来。"""

    def setUp(self):
        self.detail = {"id": "x", "title": "碳排放权交易管理暂行条例",
                       "category": "行政法规", "status": "现行有效",
                       "issuing_authority": "国务院",
                       "publish_date": "2026-08-08", "effective_date": "2026-08-15",
                       "content_tree": [], "_from_cache": False}
        self.paras = ["碳排放权交易管理暂行条例", _CARBON_CAPTION,
                      "第一条\u3000为了规范碳排放权交易，制定本条例。",
                      "第二条\u3000本条例适用于全国碳排放权交易市场。",
                      _CARBON_EFFECTIVE]
        self.downloads = []

        def _bytes(bbbs_id, fmt="docx"):
            self.downloads.append((bbbs_id, fmt))
            return b"stub"

        for name, val in (("fetch_detail", lambda bid: dict(self.detail)),
                          ("download_bytes", _bytes),
                          ("_parse_docx_from_bytes", lambda b: list(self.paras)),
                          ("download_file", mock.Mock(
                              side_effect=AssertionError("preview 不该再落盘一遍")))):
            patcher = mock.patch.object(DT, name, val)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_preview_downloads_exactly_once_and_never_writes_a_file(self):
        DT.preview_law("x")
        self.assertEqual([("x", "docx")], self.downloads)

    def test_preview_carries_the_date_lineage(self):
        got = DT.preview_law("x")
        lin = got["date_lineage"]
        self.assertEqual("2024-01-25", lin["original_publish_date"])
        self.assertEqual("2024-05-01", lin["effective_clause_date"])
        self.assertEqual("2026-08-08", lin["amendments"][-1]["date"])
        self.assertIn("不是同一次", got["date_note"])

    def test_article_count_and_numbering_are_unchanged(self):
        got = DT.preview_law("x")
        self.assertEqual(3, got["article_count"])
        self.assertEqual("chinese", got["numbering_pattern"])
        self.assertEqual(3, len(got["first_articles"]))

    def test_download_failure_is_reported_not_disguised_as_a_missing_caption(self):
        with mock.patch.object(DT, "download_bytes",
                               side_effect=RuntimeError("HTTP 429")):
            got = DT.preview_law("x")
        self.assertEqual(0, got["article_count"])
        self.assertEqual("", got["date_lineage"]["caption"])
        self.assertIn("HTTP 429", got["date_note"])
        self.assertNotIn("未附题注", got["date_note"])

    def test_cli_preview_prints_the_lineage_and_the_note(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["tax_detail.py", "--preview", "x"]):
            with contextlib.redirect_stdout(buf):
                DT.main()
        out = buf.getvalue()
        self.assertIn("2024-05-01", out)
        self.assertIn("2026-08-08", out)
        self.assertIn("不是同一次", out)

    def test_cli_info_points_at_preview_for_the_body_lineage(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["tax_detail.py", "--info", "x"]):
            with contextlib.redirect_stdout(buf):
                DT.main()
        self.assertIn("--preview", buf.getvalue())


# ── ⑬ 统一出口标记契约：0 条与没取到，从此各有一枚键 ────────────────────────
class TestUnifiedExitMarkerContract(unittest.TestCase):
    """3.62.26 起六个源的出口必须带这两枚键之一，消费面不再拿 `_error` 文本猜。

    契约本身在 `tax_http`：`_zero_hit`＝请求跑成了、答案是 0 条；`_fetch_failed`＝
    请求层面没取到。判据 `is_fetch_failure` 先看 `_zero_hit`（短路成 False），
    再看 `_fetch_failed`，最后才拿 `_error` 兜底。没打键的老信封按失败处理是
    有意选的：多报一次失败看得见、会去补，少报一次是静默——正是红线⑦那一族。

    这一组用例逐源钉两向（合法空档 / 真失败），是因为本仓反复栽在"只改了
    一个源"：`_doc_number_in_library` 那一路早就认标记，检索层却还认文本，
    同一个 fgk 信封在两处读出两种性质。
    """

    RESULT_URL = SH.SEARCH_RESULT + "?page=0&searchid=12345"
    # 判「站内没货」只认站点自己的空结果文案（报告 §5.3）：结果容器不算证据——
    # 它同时也是客户端渲染骨架页的组成部分。夹具把这句一起带上，真页面上两者同现。
    WX_ZERO_HTML = ('<html><body><div class="js-results">'
                    '<p class="p3">没有找到相关的微信公众号文章。</p>'
                    '<p>抱歉，没有找到相关网页</p></div></body></html>')
    WX_BROKEN_HTML = "<html><body> totally restructured, no blocks, no marker </body></html>"

    class _Shui5Session:
        """search_native 只用 post 与 get 两件事。"""

        def __init__(self, posts, landing):
            self.posts, self.landing = list(posts), landing

        def post(self, url, **kw):
            return _Resp(self.posts.pop(0), url=self.landing)

        def get(self, url, **kw):
            return _Resp("")

    def _fgk_scan(self, total, pages, errors=None):
        calls = []
        errors = errors or {}

        def fake_search(keyword, page=1, size=10, filters=None, **opts):
            calls.append(page)
            out = {"total": total, "results": _fgk_hit(pages.get(page, 0), "p%d" % page)}
            if page in errors:
                out["_error"] = errors[page]
                out["results"] = []
            return out

        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search):
            return FGK._scan_list("契约词", size=99,
                                  max_pages=(max(pages) + 3 if pages else 4),
                                  adaptive=False)

    def _npc(self, payload, keyword):
        old = T._request
        try:
            T._request = lambda method, url, **kw: _NpcResp(payload)
            return T.search_tax(keyword, scope="title", search_type=2, size=5)
        finally:
            T._request = old

    def _shui5(self, posts, landing, keyword="契约词", **kw):
        return SH.search_native(keyword, size=5, session=self._Shui5Session(posts, landing),
                                gap=0, **kw)

    def _chinatax(self, titles, total, keyword="契约词", **kw):
        resp = _Search5Resp(titles, total)
        with mock.patch.object(WS.tax_http, "attempt", return_value=(resp, "", False)), \
             mock.patch.object(WS.tax_http, "new_log", return_value=[]):
            return WS.search_chinatax(keyword, size=10, **kw)

    def _chinatax_failed(self, err, keyword="契约词"):
        with mock.patch.object(WS.tax_http, "attempt", return_value=(None, err, False)), \
             mock.patch.object(WS.tax_http, "new_log", return_value=[]):
            return WS.search_chinatax(keyword, size=10)

    def _wechat(self, html, keyword="契约词"):
        """契约族这一枚钉的是 GET 兜底页型 ⇒ 主路两发 POST 必须回熔断形。

        2026-11-27：只替 `_yuanbao_get` 的旧桩会让 POST 真的打出去（报告 §7「不 hermetic」），
        于是这一族名义离线、实际吃网络与频控。
        """
        fake = _WxSession(_WxResp(html, ISEARCH_URL, 200))
        old = (W._yuanbao_get, W._yuanbao_post, W.DEAD_COOLDOWN)
        try:
            W._yuanbao_get = lambda sess, u, **kw: fake.get(u)
            W._yuanbao_post = lambda sess, u, **kw: _WxResp(_dead_shape(), NEXT_PAGE_URL)
            W.DEAD_COOLDOWN = 0.0
            return W.search_wechat(keyword, size=3)
        finally:
            W._yuanbao_get, W._yuanbao_post, W.DEAD_COOLDOWN = old

    def _sogou(self, html, err="", blocked=False, keyword="契约词"):
        with mock.patch.object(SOG, "_cache", tax_cache.CacheManager(enabled=False)), \
             mock.patch.object(SOG, "_STATE_PATH",
                               Path(tempfile.mkdtemp()) / "state.json"), \
             mock.patch.object(SOG, "SEARCH_MIN_GAP", 0), \
             mock.patch.object(SOG, "_fetch",
                               return_value=(html, "https://www.sogou.com/web?query=x",
                                             err, blocked)):
            return SOG.sogou_search(keyword, site="shui5.cn", size=5)

    def _ctax(self, resp, keyword="契约词", **kw):
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp(resp)})
        with mock.patch.object(CT.time, "sleep"):
            return CT.search_ctax(keyword, size=5, session=s, **kw)

    def _ctax_http500(self, keyword="契约词"):
        s = _CtaxSession({CTAX_SEARCH: _CtaxResp("{}", status=500)})
        with mock.patch.object(CT.time, "sleep"):
            return CT.search_ctax(keyword, size=5, session=s)

    def _agg(self, *, sogou=None, shui5=None, wechat=None):
        ok = lambda n: {"total": n, "results": [{"title": "财税〔2025〕1号",
                                                 "url": "https://x.test/a"}] if n else []}
        with mock.patch.object(AGG, "search_tax", return_value=ok(1)), \
             mock.patch.object(AGG, "search_chinatax", return_value=ok(1)), \
             mock.patch.object(AGG, "sogou_search",
                               return_value=sogou if sogou is not None else ok(1)), \
             mock.patch.object(AGG, "search_shui5",
                               return_value=shui5 if shui5 is not None else ok(0)), \
             mock.patch.object(AGG, "search_wechat",
                               return_value=wechat if wechat is not None else ok(0)), \
             mock.patch.object(AGG, "search_ctax", return_value=ok(1)):
            return AGG.aggregate_search("契约词", size=5)

    def _gapped(self, r):
        return {g["source"] for g in r["gaps"]}

    # ── 逐源：合法空档 ──────────────────────────────────────────────
    def test_fgk_legal_zero_hit_carries_the_key(self):
        r = self._fgk_scan(0, {})
        self.assertTrue(r.get("_zero_hit"),
                        "翻完未筛出是扫描结论，不带这一枚就被读成取数失败")
        self.assertTrue(r.get("_error"), "那句成因仍要交出去：翻了几页、站点共几条命中")
        self.assertFalse(tax_http.is_fetch_failure(r))
        self.assertIn("未筛出法规库条目", tax_http.empty_note(r))

    def test_npc_legal_zero_hit_carries_the_key(self):
        r = self._npc('{"total":0,"rows":[],"code":200,"msg":"查询成功"}', "契约零命中甲")
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"),
                        "NPC 原来回的是裸 total=0，消费面分不清它与接口异常")
        self.assertFalse(tax_http.is_fetch_failure(r))

    def test_shui5_legal_zero_hit_carries_the_key(self):
        r = self._shui5(["<div>%s</div>" % SH.NO_RESULT_MARK], self.RESULT_URL)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"),
                        "站点明说没搜到＝一轮跑成、答案 0 条；_status 那句两种成因说的是参数档位")
        self.assertFalse(tax_http.is_fetch_failure(r))

    def test_chinatax_legal_zero_hit_carries_the_key(self):
        r = self._chinatax([], 0)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"))
        self.assertFalse(tax_http.is_fetch_failure(r))

    def test_chinatax_page_beyond_the_last_page_is_a_legal_empty(self):
        r = self._chinatax([], 3, page=9)
        self.assertTrue(r.get("_zero_hit"), "翻过末页是正常收尾")
        self.assertIn("已翻过末页", tax_http.empty_note(r))

    def test_chinatax_empty_page_inside_the_last_page_is_not_a_legal_empty(self):
        """接口报了命中数却没给清单：既不是失败也不算跑成，别打 _zero_hit。"""
        r = self._chinatax([], 3, page=1)
        self.assertFalse(r.get("_zero_hit"))
        self.assertIn("不能据此说库里没有", r["_empty_reason"])

    def test_wechat_legal_zero_hit_carries_the_key(self):
        r = self._wechat(self.WX_ZERO_HTML)
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"))
        self.assertFalse(tax_http.is_fetch_failure(r))

    def test_sogou_legal_zero_hit_carries_the_key(self):
        r = self._sogou("<html><body><p>没有找到相关内容</p></body></html>")
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"))
        self.assertFalse(tax_http.is_fetch_failure(r))

    def test_ctax_legal_zero_hit_carries_the_key_and_still_no_error(self):
        r = self._ctax(_ctax_json([], found=0))
        self.assertEqual(0, r["total"])
        self.assertTrue(r.get("_zero_hit"))
        self.assertNotIn("_error", r, "这一档老钉（:3987）不许带 _error，只补键")
        self.assertFalse(tax_http.is_fetch_failure(r))

    # ── 逐源：真失败 ────────────────────────────────────────────────
    def test_fgk_request_failure_is_still_a_failure(self):
        r = self._fgk_scan(62, {1: 10}, errors={2: "HTTP 500"})
        self.assertTrue(r.get("_fetch_failed"))
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_npc_failure_is_an_exception_not_an_envelope(self):
        """NPC 的失败走 raise，契约不为此新增第三种形状——这条钉住边界。"""
        with self.assertRaises(RuntimeError):
            self._npc('{"msg":"系统异常","code":500}', "契约失败甲")

    def test_shui5_landing_without_searchid_is_a_failure(self):
        r = self._shui5(["<html><body>既没有提示也没有结果区</body></html>"], SH.SEARCH_FORM)
        self.assertTrue(r.get("_fetch_failed"),
                        "落点里没有 searchid＝这一轮没取到，原来只有一句 _status")
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_shui5_waf_page_is_a_failure(self):
        page = ('<textarea id="renderData">{"arg1":"%s"}</textarea>' % ("A" * 40))
        r = self._shui5([page], self.RESULT_URL)
        self.assertTrue(r.get("_fetch_failed"),
                        "WAF 那一支也要带键，否则判据只能退回去认 _status 前缀")
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_shui5_unknown_column_is_a_failure(self):
        r = self._shui5([], self.RESULT_URL, classid="这一栏不在表里")
        self.assertTrue(r.get("_fetch_failed"), "参数在发出前就被拦掉也是没取到")
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_shui5_request_exception_is_a_failure(self):
        class Boom:
            def post(self, url, **kw):
                raise SH.requests.RequestException("连接被重置")

        r = SH.search_native("契约词", size=5, session=Boom(), gap=0)
        self.assertTrue(r.get("_fetch_failed"))
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_chinatax_transport_error_is_a_failure(self):
        r = self._chinatax_failed("SSLError: 连接重置")
        self.assertTrue(r.get("_fetch_failed"))
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_wechat_restructured_page_is_a_failure(self):
        r = self._wechat(self.WX_BROKEN_HTML)
        self.assertTrue(r.get("_fetch_failed"),
                        "既没结果块也没无结果提示＝页面改版，不能读成库里没有")
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_sogou_breaker_is_a_failure(self):
        r = self._sogou("", err="搜狗熔断中：约 600 秒后到期")
        self.assertTrue(r.get("_fetch_failed"))
        self.assertTrue(tax_http.is_fetch_failure(r))

    def test_ctax_http_500_on_the_first_page_is_a_failure(self):
        r = self._ctax_http500()
        self.assertTrue(r.get("_fetch_failed"))
        self.assertTrue(tax_http.is_fetch_failure(r))

    # ── 消费面：判据换掉之后两种 0 条走两条路 ──────────────────────────
    def test_rows_and_error_hands_a_legal_empty_back_as_an_empty_round(self):
        rows, err, partial = ANS._rows_and_error(
            {"results": [], "total": 0, "_zero_hit": True,
             "_error": "翻完前 1 页总局检索结果（共 4822 条命中）未筛出法规库条目"})
        self.assertEqual(([], "", ""), (rows, err, partial),
                         "第二枚非空就会被 gather 记进 errors 与 rounds_done[].failed")

    def test_rows_and_error_still_voids_a_real_failure(self):
        rows, err, partial = ANS._rows_and_error(
            {"results": [], "total": None, "_error": "HTTP 500", "_fetch_failed": True})
        self.assertEqual(([], "HTTP 500", ""), (rows, err, partial))

    def test_rows_and_error_keeps_the_old_fallback_for_unmarked_envelopes(self):
        rows, err, _ = ANS._rows_and_error({"results": [], "_error": "连接超时"})
        self.assertEqual(([], "连接超时", ""), (rows, err, ""),
                         "没打键的信封按失败兜底：宁可多报一次，不静默")

    def test_aggregator_does_not_gap_a_legal_empty(self):
        r = self._agg(sogou={"results": [], "total": 0, "_zero_hit": True,
                             "_error": "翻完未筛出法规库条目"})
        self.assertNotIn("sogou", self._gapped(r),
                         "把「没有」记成「缺了这一层」，读者会去放宽检索而不是接受空答")

    def test_aggregator_still_gaps_a_real_failure(self):
        r = self._agg(sogou={"results": [], "total": None, "_error": "HTTP 500",
                             "_fetch_failed": True})
        self.assertIn("sogou", self._gapped(r))

    # ── 两枚键互斥：并列时判据必须取失败那一侧 ────────────────────────────
    def test_both_keys_on_one_envelope_read_as_failure(self):
        """同时挂两枚键说明源侧写错了；判据不许因此把接口挂了答成库里没有。

        2026-11-25 首版判据先看 `_zero_hit` 短路，`tax_sogou._empty` 恰好经
        `_payload` 打了 `_zero_hit` 再叠 `_fetch_failed`，熔断那轮被读成合法
        空档——用例 `test_sogou_breaker_is_a_failure` 撞出来的。源侧修掉了碰撞，
        这一枚把判据本身的退化方向钉住，否则次序改回去也没人报警。
        """
        self.assertTrue(tax_http.is_fetch_failure({"_zero_hit": True,
                                                   "_fetch_failed": True}),
                        "并列时取失败侧：多报一次看得见，少报一次是静默")
        self.assertFalse(tax_http.is_fetch_failure({"_zero_hit": True}))
        self.assertTrue(tax_http.is_fetch_failure({"_fetch_failed": True}))

    def test_no_source_envelope_carries_both_keys(self):
        """逐源实测：同一只信封上不许两枚键并存（契约的互斥面）。"""
        both = []
        empties = [
            ("fgk", lambda: self._fgk_scan(0, {})),
            ("npc", lambda: self._npc('{"total":0,"rows":[],"code":200,"msg":"查询成功"}',
                                      "契约零命中甲")),
            ("shui5", lambda: self._shui5(["<div>%s</div>" % SH.NO_RESULT_MARK],
                                          self.RESULT_URL)),
            ("chinatax", lambda: self._chinatax([], 0)),
            ("wechat", lambda: self._wechat(self.WX_ZERO_HTML)),
            ("sogou", lambda: self._sogou("<html><body><p>没有找到相关内容</p></body></html>")),
            ("ctax", lambda: self._ctax(_ctax_json([], found=0))),
        ]
        failures = [
            ("fgk", lambda: self._fgk_scan(62, {1: 10}, errors={2: "HTTP 500"})),
            ("shui5", lambda: self._shui5(["<html><body>既没有提示也没有结果区</body></html>"],
                                          SH.SEARCH_FORM)),
            ("chinatax", lambda: self._chinatax_failed("SSLError: 连接重置")),
            ("wechat", lambda: self._wechat(self.WX_BROKEN_HTML)),
            ("sogou", lambda: self._sogou("", err="搜狗熔断中：约 600 秒后到期")),
            ("ctax", lambda: self._ctax_http500()),
        ]
        for name, make in empties + failures:
            r = make()
            if "_zero_hit" in r and "_fetch_failed" in r:
                both.append(name)
        self.assertEqual([], both, "两枚键并存时判据只能赌先后次序，源侧必须只挂一枚")

    # ── 点名定位那一层：档位词必须跟着键走 ────────────────────────────────
    def _locate(self, env):
        """把一只预制信封喂给 locate_cited_document，带回 state（第三枚）。"""
        real = ANS.FGK.search_fgk
        try:
            ANS.FGK.search_fgk = lambda kw, size=6, **kw2: dict(env)
            return ANS.locate_cited_document("税收征管法")[2]
        finally:
            ANS.FGK.search_fgk = real

    def test_locate_calls_a_legal_empty_no_hit_not_channel_failed(self):
        """3.62.27 收的那条：通道跑成了、答案是 0 条，不许写成"没连上"。

        fgk 的合法零命中带一句 `_error`（翻完前 N 页未筛出法规库条目）。locate
        老写法读 `_error` 非空即失败，于是 state=channel-failed，compose 写出
        「检索通道没取成…不是库里没有这一份：按 ⑦ 不能把没连上写成没有」——
        红线⑦的反向假陈述，读者会去重跑那一轮，重跑一百次还是 0 条。
        2026-11-25 探针 probe27b.py 实测到 state 与 cited_note 原文。
        """
        env = self._fgk_scan(0, {})
        self.assertTrue(env.get("_zero_hit"), "前提：这一档是合法空档")
        self.assertTrue(env.get("_error"), "前提：这一档带一句扫描结论")
        state = self._locate(env)
        self.assertTrue(state.startswith("no-hit"), state)
        self.assertIn("未筛出法规库条目", state,
                      "成因句要跟着进 no-hit 那一档，否则只剩"
                      "「关键词：未注明」")

    def test_locate_still_calls_a_real_failure_channel_failed(self):
        """反向钉：真失败仍走失败档，别把这次改动读成放松判据。

        两档分开钉：一枚条目都没取回 → channel-failed；取回过条目又有失败
        → partial（`tax_answer.py` 折档的优先级：有条目时不算"这一轮没捞着"，
        只补一句"这一轮不完整"）。断供那一档在真实 fgk 里必然带着已收的条目，
        所以它落 partial 而不是 channel-failed——这是既有形状，本轮没动它。
        """
        pure = {"results": [], "total_hits": 62, "_error": "search5 HTTP 500",
                "_fetch_failed": True}
        self.assertTrue(tax_http.is_fetch_failure(pure))
        state = self._locate(pure)
        self.assertTrue(state.startswith("channel-failed"), state)
        self.assertIn("HTTP 500", state)

        with_rows = self._fgk_scan(62, {1: 10}, errors={2: "HTTP 500"})
        self.assertTrue(tax_http.is_fetch_failure(with_rows))
        state = self._locate(with_rows)
        self.assertTrue(state.startswith("partial"), state)
        self.assertIn("HTTP 500", state)

    def test_library_lookup_keeps_its_own_criterion_on_purpose(self):
        """文号核对那一层有意不换成 is_fetch_failure，这一枚把理由钉住。

        `_doc_number_in_library` 判的是"能不能据此说库里没有这份文件"：清单没给全
        （`_empty_reason`）时那一轮不足以否定存在性，所以它回一句失败说明——而契约
        判据把只带 `_empty_reason` 的信封读成非失败。两层的判据本来就该不同（检索层
        判这一轮计不计入底稿，本层判能不能下"没有"的结论），改动必须先读
        :1970-1988 那两枚老钉，不许顺手统一成一把尺。
        """
        legal = {"results": [], "total_hits": 0, "_zero_hit": True,
                 "_error": "翻完前 1 页未筛出法规库条目"}
        self.assertFalse(tax_http.is_fetch_failure(legal), "前提：契约读它为非失败")
        row, why, hits = ANS._doc_number_in_library("财税〔1999〕43号",
                                                    want="财税〔1999〕43号",
                                                    lookup=lambda t: dict(legal))
        self.assertIsNone(row)
        self.assertEqual("", why, "合法空档不许回失败说明，否则上层写 lookup_failed")
        self.assertEqual(0, hits, "命中数要带出去给 tax_evidence 的零命中句用")

        partial = {"results": [], "total_hits": 48, "_empty_reason": "接口没给清单"}
        self.assertFalse(tax_http.is_fetch_failure(partial), "前提：契约读它为非失败")
        row, why, hits = ANS._doc_number_in_library("财税〔1999〕43号",
                                                    want="财税〔1999〕43号",
                                                    lookup=lambda t: dict(partial))
        self.assertIsNone(row)
        self.assertTrue(why, "清单没给全不足以否定存在性，这一轮不能当「库里没有」用")
        self.assertIsNone(hits)


# ── 用例自身的能力自检：规则不能永远绿 ─────────────────────────────────────
class TestRulesCanActuallyFail(unittest.TestCase):
    """把规则作用在构造的反例上，确认它真的拦得住。"""

    def test_degraded_note_is_empty_only_without_gaps(self):
        self.assertEqual("", AGG._degraded_note(["npc"], [], {"npc": 3}))
        note = AGG._degraded_note(["npc"], [{"source": "npc", "label": "NPC"}],
                                  {"npc": 3})
        self.assertTrue(note)

    def test_reliability_marker_normalizes_only_known_levels(self):
        """认不出的取值一律当"没有标记"，免得凭空多出一条提醒。"""
        self.assertEqual("", E._reliability_of({"_reliability": "HIGH"}))
        self.assertEqual("low", E._reliability_of({"_reliability": " LOW "}))
        self.assertEqual("", E._reliability_of({}))


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    r = unittest.main(verbosity=2, exit=False)
    print("\n结果：%d/%d 通过" % (r.result.testsRun - len(r.result.failures)
                                - len(r.result.errors), r.result.testsRun))
    sys.exit(0 if r.result.wasSuccessful() else 1)
