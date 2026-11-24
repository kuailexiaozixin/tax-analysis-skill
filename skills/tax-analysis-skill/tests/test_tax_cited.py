#!/usr/bin/env python3
"""tax_cited（官方域判据 + 文号链接缓存）与其在 locate_cited_document 里接线的离线用例。

不联网。缓存指到临时文件，不碰真实 ~/.cache。桩打在检索入口 AN.FGK.search_fgk。

钉住三件事（B 的验收标准）：
  A) 域名判据 is_official：chinatax.gov.cn 及任意子域为真；把官方域塞进路径 /
     后缀拼假的站、商业站一律假。put_cited_link 据此拒收非官方链接。
  B) 缓存闭环：冷启动检索 → 命中官方链接落缓存；再查同文号 → _from_cache=True
     且**不打检索**；检索到的条目 URL 非官方域 → 不落缓存（下次仍走检索）。
  C) 3.62.20 起：命中缓存之前必须拿**缓存里存着的标题**现判同一性。旧判据
     title_identity(title, title) 是恒真式——一枚文号能从两类标题里抽出来，
     于是"种着 A 的链接、点名引用 A 的 B"会零网络交回 A 的地址并称"字面同一"。
     所以缓存值带 title（旧裸字符串值判不了 ⇒ 不采信），写侧要把它落下去。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import tax_answer as AN          # noqa: E402
import tax_cited as CITED        # noqa: E402
import tax_terms as TT           # noqa: E402

OFFICIAL = "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5207148/content.html"


class TestIsOfficial(unittest.TestCase):
    def test_real_official_hosts(self):
        for url in [
            "https://chinatax.gov.cn/",
            "https://www.chinatax.gov.cn/chinatax/n810346/index.html",
            OFFICIAL,
            "https://shanghai.chinatax.gov.cn/zcfw/zcfgk/zzs/201210/t400596.html",
        ]:
            self.assertTrue(CITED.is_official(url), url)

    def test_lookalike_hosts_rejected(self):
        for url in [
            "https://example.com/chinatax.gov.cn",           # 官方域在路径里
            "http://evil-chinatax.gov.cn/x",                 # 连字符前缀，不是子域
            "https://chinatax.gov.cn.attacker.net/x",        # 官方域只是中间标签
            "https://notchinatax.gov.cn/x",
            "https://shanghai.chinatax.gov.cn.evil.com/x",
        ]:
            self.assertFalse(CITED.is_official(url), url)


class TestPutGet(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "cited_links.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_put_accepts_official_rejects_other(self):
        dn = "财税〔2012〕75号"
        self.assertTrue(CITED.put_cited_link(dn, OFFICIAL, self.path))
        self.assertEqual(OFFICIAL, CITED.get_cited_link(dn, self.path))
        self.assertFalse(CITED.put_cited_link("国税发〔2001〕110号",
                                              "https://example.com/x", self.path))
        self.assertEqual("", CITED.get_cited_link("国税发〔2001〕110号", self.path))

    def test_empty_doc_number_no_op(self):
        self.assertFalse(CITED.put_cited_link("", OFFICIAL, self.path))


class TestLocateIntegration(unittest.TestCase):
    def setUp(self):
        self._saved_get = AN.FGK.search_fgk
        self._saved_path = AN.CITED_CACHE_PATH
        self._tmp = tempfile.TemporaryDirectory()
        AN.CITED_CACHE_PATH = Path(self._tmp.name) / "cited_links.json"
        self.calls = []

        def stub(keyword, size=6, **kw):
            self.calls.append(keyword)
            # 返回的就是被点名的那一份（标题与 title 字面相同 → identity="same"），
            # 这样才会触发"定位成功 + 官方域 → 落缓存"这一路径。
            return {"results": [{"title": keyword,
                                 "url": OFFICIAL,
                                 "document_number": "财税〔2012〕75号"}]}
        AN.FGK.search_fgk = stub

    def tearDown(self):
        AN.FGK.search_fgk = self._saved_get
        AN.CITED_CACHE_PATH = self._saved_path
        self._tmp.cleanup()

    def _title(self):
        # 标题字面即点名文件：doc_number_of 能从标题尾部抽出文号
        return "财税〔2012〕75号 鲜活肉蛋产品免征增值税"

    def test_cold_then_hot_cache_skips_search(self):
        title = self._title()
        dn = TT.doc_number_of(title)
        self.assertTrue(dn, "用例标题应能被 doc_number_of 归出文号")

        rows1, _, state1 = AN.locate_cited_document(title)
        self.assertTrue(rows1 and rows1[0].get("_cited_identity") == "same", rows1)
        self.assertEqual("", state1, "检索取成时不该报任何档位")
        self.assertFalse(rows1[0].get("_from_cache"))
        first_call_count = len(self.calls)
        self.assertGreater(first_call_count, 0, "冷启动却没打检索")

        # 现在缓存里应有这枚文号 → 官方链接
        self.assertEqual(OFFICIAL, CITED.get_cited_link(dn, AN.CITED_CACHE_PATH))

        rows2, tried2, state2 = AN.locate_cited_document(title)
        self.assertEqual("", state2, "缓存命中档应交回空状态")
        self.assertEqual(len(self.calls), first_call_count, "命中缓存仍打了检索")
        self.assertTrue(rows2[0]["_from_cache"])
        self.assertEqual(OFFICIAL, rows2[0]["url"])
        self.assertEqual([dn], tried2)

    def test_non_official_result_not_cached(self):
        # 让检索回一条非官方域：定位成功但不落缓存，下次仍走检索
        def stub(keyword, size=6, **kw):
            self.calls.append(keyword)
            return {"results": [{"title": "鲜活肉蛋产品免征增值税",
                                 "url": "https://example.com/x",
                                 "document_number": "财税〔2012〕75号"}]}
        AN.FGK.search_fgk = stub
        title = self._title()
        rows, _, _state = AN.locate_cited_document(title)
        self.assertTrue(rows)   # 定位本身不受域名影响
        dn = TT.doc_number_of(title)
        self.assertEqual("", CITED.get_cited_link(dn, AN.CITED_CACHE_PATH),
                         "非官方域链接竟被写进了缓存")


class TestCacheIdentityGate(unittest.TestCase):
    """3.62.20：缓存命中前必须拿**存着的标题**现判同一性，不能自封"字面同一"。

    事故形状（2026-11-24 实测复现）：旧判据是 `title_identity(title, title)`——
    拿用户点名的标题和**它自己**比，恒为 "same"，等于从来没判过。于是缓存里种着
    A 的链接时，点名"引用了 A 的 B"会零网络交回 **A 的地址**，还顶着
    `_cited_identity="same"`，compose 那句直接写成"用户点名的文件本身"。
    一枚文号能从两类完全不同的标题里抽出来（被点名的那份 / 在标题里引用它的另一份），
    因为 doc_number_of 取的是**第一个**文号，而引用式标题的第一个恰恰是别人家的。
    """

    DN_A = "财税〔2012〕75号"
    URL_A = "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5207148/content.html"
    URL_OTHER = "https://fgk.chinatax.gov.cn/zcfgk/c100013/c5100000/content.html"
    # A 这份文件在站点上的标题。故意**不带文号**：实测离线清单 1892 条带文号键的
    # 记录里，题面能抽出文号的是 0 条（文号单独存在「发文字号」字段）。
    A_SITE_TITLE = "财政部 国家税务总局关于免征鲜活肉蛋产品流通环节增值税的通知"
    # 引用式标题：题面第一枚文号是 A 的，自己另有那枚
    B_CITING = ("财政部 税务总局关于继续对鲜活肉蛋产品免征增值税的通知"
                "（财税〔2012〕75号）财政部 税务总局公告2023年第12号")
    C_SITE_TITLE = "增值税专用发票验旧供新管理办法（试行）"

    def setUp(self):
        self._saved_search = AN.FGK.search_fgk
        self._saved_path = AN.CITED_CACHE_PATH
        self._tmp = tempfile.TemporaryDirectory()
        AN.CITED_CACHE_PATH = Path(self._tmp.name) / "cited_links.json"
        self.calls = []

        def stub(keyword, size=6, **kw):
            self.calls.append(keyword)
            return {"results": [{"title": keyword, "url": self.URL_OTHER,
                                 "document_number": TT.doc_number_of(keyword)}]}
        AN.FGK.search_fgk = stub

    def tearDown(self):
        AN.FGK.search_fgk = self._saved_search
        AN.CITED_CACHE_PATH = self._saved_path
        self._tmp.cleanup()

    def test_control_empty_cache_still_searches(self):
        """控制组：缓存空时必须照常检索——否则下面几条的"退回检索"是白给的。"""
        rows, tried, state = AN.locate_cited_document(
            self.DN_A + " " + self.A_SITE_TITLE)
        self.assertGreater(len(self.calls), 0, "缓存空却没打检索")
        self.assertEqual(self.URL_OTHER, rows[0]["url"])
        self.assertFalse(rows[0].get("_from_cache"))
        self.assertEqual("", state)

    def test_seeded_clean_title_hits_cache_with_zero_network(self):
        """离线预热闭环：种着同一份文件的站点标题（题面不带文号）必须零网络命中。

        这条同时钉住一个**反向**事故：判据若写成 `cached_dn == dn`（要求缓存标题
        自己抽得出同一枚文号），这里就会全军覆没——站点标题普遍不带文号，预热
        白种、每次点名都退回走网络。
        """
        CITED.put_cited_link(self.DN_A, self.URL_A, AN.CITED_CACHE_PATH,
                             title=self.A_SITE_TITLE)
        rows, tried, state = AN.locate_cited_document(
            self.DN_A + " " + self.A_SITE_TITLE)
        self.assertEqual(0, len(self.calls), "命中缓存仍打了检索")
        self.assertEqual([self.DN_A], tried)
        self.assertEqual("", state)
        self.assertEqual(self.URL_A, rows[0]["url"])
        self.assertTrue(rows[0]["_from_cache"])
        self.assertTrue(rows[0]["_cited_identity"],
                        "缓存命中必须带上现判出的同一性，下游只认这一枚")

    def test_title_naming_another_doc_number_is_not_trusted(self):
        """缓存标题抽出的是**别的**文号 ⇒ 这条地址是从引用式标题身上核下来的。"""
        CITED.put_cited_link(self.DN_A, self.URL_A, AN.CITED_CACHE_PATH,
                             title="2013年第25号 " + self.C_SITE_TITLE)
        rows, _, _ = AN.locate_cited_document(self.DN_A + " " + self.A_SITE_TITLE)
        self.assertGreater(len(self.calls), 0, "缓存标题指向别的文号仍被采信")
        self.assertNotEqual(self.URL_A, rows[0]["url"])
        self.assertFalse(rows[0].get("_from_cache"))

    def test_title_of_an_other_document_is_not_trusted(self):
        """缓存标题属于另一份文件（不带文号）⇒ 只能靠 title_identity 拒。

        这就是旧恒真判据出事的那一臂：改之前这里零网络交回 A 的地址 + "same"。
        """
        CITED.put_cited_link(self.DN_A, self.URL_A, AN.CITED_CACHE_PATH,
                             title=self.C_SITE_TITLE)
        rows, _, _ = AN.locate_cited_document(self.B_CITING)
        self.assertGreater(len(self.calls), 0,
                           "旧事故复活：缓存里另一份文件的地址被当成点名目标交回")
        self.assertNotEqual(self.URL_A, rows[0]["url"],
                            "交回的是被引用那份 A 的地址，不是点名的 B")
        self.assertFalse(rows[0].get("_from_cache"))

    def test_legacy_bare_string_entry_is_not_trusted_but_link_still_readable(self):
        """旧形状（裸 URL 字符串、没有标题）：定位路不采信，取链接路照常工作。

        get_cited_link 的返回形状不能改——tax_gov_list 的待补清单与 tax-preference
        都在用它，那两路要的是"有没有地址"，不是"地址属不属于这一份"。
        """
        AN.CITED_CACHE_PATH.write_text(
            json.dumps({self.DN_A: self.URL_A}, ensure_ascii=False),
            encoding="utf-8")
        self.assertEqual(self.URL_A, CITED.get_cited_link(self.DN_A,
                                                          AN.CITED_CACHE_PATH))
        entry = CITED.get_cited_entry(self.DN_A, AN.CITED_CACHE_PATH)
        self.assertEqual({"url": self.URL_A, "title": ""}, entry)
        rows, _, _ = AN.locate_cited_document(self.DN_A + " " + self.A_SITE_TITLE)
        self.assertGreater(len(self.calls), 0, "判不了同一性的旧条目被直接采信了")
        self.assertFalse(rows[0].get("_from_cache"))

    def test_writer_records_the_title_so_next_round_can_judge(self):
        """写侧必须把标题一起落下：否则读侧永远判不了，缓存形同虚设。"""
        title = self.DN_A + " " + self.A_SITE_TITLE
        AN.locate_cited_document(title)          # 冷启动 → 检索 → 落缓存
        entry = CITED.get_cited_entry(TT.doc_number_of(title), AN.CITED_CACHE_PATH)
        self.assertTrue(entry["title"], "写侧没带标题，下次命中仍判不了同一性")
        calls_before = len(self.calls)
        rows, _, _ = AN.locate_cited_document(title)   # 第二轮：应零网络
        self.assertEqual(calls_before, len(self.calls), "带标题的条目没被复用")
        self.assertTrue(rows[0]["_from_cache"])

    def test_search_path_strips_numbers_for_two_writes_of_one_file(self):
        """检索路的同一性同样要先摘文号（注入第 4 路抓的就是这条）。

        出事形状是**同一份文件的两种写法**：用户按"文号+标题"点名，站点记录的
        标题把文号挂在括注后缀。实测 `title_identity` 裸判给 ''（core_of_title
        不摘文号，两串核心不等位），摘完文号给 'same'。丢掉这步，真目标就没了
        `_cited_identity`——排序看着还对（sim 高），下游却不再打点名标记。
        """
        AN.CITED_CACHE_PATH.write_text("{}", encoding="utf-8")   # 关掉缓存路
        site = self.A_SITE_TITLE + "（" + self.DN_A + "）"
        asked = self.DN_A + " " + self.A_SITE_TITLE

        def stub(keyword, size=6, **kw):
            self.calls.append(keyword)
            return {"results": [{"title": self.C_SITE_TITLE,
                                 "url": self.URL_OTHER, "document_number": ""},
                                {"title": site, "url": self.URL_A,
                                 "document_number": self.DN_A}]}
        AN.FGK.search_fgk = stub
        rows, _tried, _state = AN.locate_cited_document(asked)
        self.assertGreater(len(self.calls), 0, "这条本该走检索")
        self.assertEqual(self.URL_A, rows[0]["url"], "真目标没排到第一")
        self.assertEqual("same", rows[0]["_cited_identity"],
                         "检索路没摘文号：同一份文件的两种写法被判成两份")

    def test_gov_list_seed_produces_a_trustable_entry(self):
        """预热写者必须把 title 一起种：没标题的条目在定位路上等于没写。

        注入第 5 路抓的就是这条——seed 退回不带 title 的旧写法后，本文件其余
        用例仍全绿（它们不经 seed_cited_cache），只有这一条会红。
        """
        import tax_gov_list as GL
        dn19 = "2026年第19号"
        index = {"记录": [{
            "发文字号": "国家税务总局公告2026年第19号",
            "title": self.A_SITE_TITLE,        # 清单题面实况：不带文号
            "url": self.URL_A,
        }]}
        stat = GL.seed_cited_cache(AN.CITED_CACHE_PATH, index=index)
        self.assertEqual(1, stat["写入"])
        entry = CITED.get_cited_entry(dn19, AN.CITED_CACHE_PATH)
        self.assertEqual(self.A_SITE_TITLE, entry["title"],
                         "seed 没把标题种进缓存，预热闭环白做")
        calls_before = len(self.calls)
        rows, _, _ = AN.locate_cited_document("国家税务总局公告2026年第19号 "
                                              + self.A_SITE_TITLE)
        self.assertEqual(calls_before, len(self.calls),
                         "种好了却仍打检索——读侧没认这条预热条目")
        self.assertTrue(rows[0]["_from_cache"])
        self.assertEqual(self.URL_A, rows[0]["url"])

    def test_garbage_entry_shape_never_raises(self):
        """盘上被手工改坏的形状（数字/列表）不许把定位整条路炸掉。"""
        AN.CITED_CACHE_PATH.write_text(
            json.dumps({self.DN_A: 12345}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual({"url": "", "title": ""},
                         CITED.get_cited_entry(self.DN_A, AN.CITED_CACHE_PATH))
        self.assertEqual("", CITED.get_cited_link(self.DN_A, AN.CITED_CACHE_PATH))
        rows, _, _ = AN.locate_cited_document(self.DN_A + " " + self.A_SITE_TITLE)
        self.assertGreater(len(self.calls), 0, "坏形状没能退回检索")
        self.assertTrue(rows)


class TestStripDocNumbers(unittest.TestCase):
    """tax_terms.strip_doc_numbers：判同一性前先把文号摘干净。

    实测选型（三档尺对照，10 组用例）：裸判错 3 组、自造正则错 4 组（留残字
    「财」「（）」）、只比 core 互含错 3 组；逐枚 doc_numbers replace 只错 1 组，
    而那组的代价是多跑一次检索。只摘第一枚也不够——引用式标题带着两枚文号。
    """

    def test_removes_every_document_number_not_just_the_first(self):
        citing = ("财政部 税务总局关于继续对鲜活肉蛋产品免征增值税的通知"
                  "（财税〔2012〕75号）财政部 税务总局公告2023年第12号")
        out = TT.strip_doc_numbers(citing)
        self.assertNotIn("财税", out)
        self.assertNotIn("2012", out)
        self.assertNotIn("2023", out)
        self.assertNotIn("〔", out)
        self.assertNotIn("〕", out)
        self.assertIn("继续对鲜活肉蛋产品免征增值税", out)

    def test_leaves_a_title_without_document_number_untouched(self):
        t = "财政部 国家税务总局关于免征鲜活肉蛋产品流通环节增值税的通知"
        self.assertEqual(t.replace(" ", ""), TT.strip_doc_numbers(t))

    def test_empty_and_none_are_safe(self):
        self.assertEqual("", TT.strip_doc_numbers(""))
        self.assertEqual("", TT.strip_doc_numbers(None))

    def test_identity_needs_it_when_the_user_writes_the_number_in(self):
        """用户点名带文号、站点标题不带 ⇒ 裸判认不出同一份，摘完就认得出。"""
        site = "财政部 国家税务总局关于免征鲜活肉蛋产品流通环节增值税的通知"
        asked = "财税〔2012〕75号 " + site
        self.assertEqual("same",
                         TT.title_identity(TT.strip_doc_numbers(asked),
                                           TT.strip_doc_numbers(site)))


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(unittest.main(verbosity=2))
