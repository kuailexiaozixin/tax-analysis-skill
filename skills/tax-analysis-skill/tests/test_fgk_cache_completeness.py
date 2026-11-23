#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3.62.17：清单残缺的那一轮绝不写盘缓存。

判据前提实测（2026-11-24，`.tmp-inspect\\fgk_exit_marks_probe.py` 与
`fgk_direct_marks_probe.py`，七条出口）：
  ① 取全（自然尽头）         标记 = []
  ② 合法 0 条（无 marker）    标记 = [_error]
  ③ 接口空清单              标记 = [_error, _empty_reason]
  ④ 首页请求失败            标记 = [_error, _fetch_failed]
  ⑤ 失败改直达且取到条目     标记 = [_error, _search_failed, direct_from_ids]
  ⑤b 失败改直达也没取到      标记 = [_error, _fetch_failed, _search_failed]
  ⑥ 中途空页断供            标记 = [_error, _empty_reason]

所以 `"_error" in result` **不能**当"别缓存"的判据——②那一支是"翻完 N 页未筛出
法规库条目"，是一个完整可信的答案，值得缓存；而 ③④⑤⑥ 清单不完整，缓存一小时
等于把一次抖动钉住一小时（之后每轮 _from_cache=True 回放残缺、连重试都没有）。
分界正好落在 `_fetch_failed` / `_empty_reason` / `_search_failed` 这三枚键上：
①② 全无、③④⑤⑤b⑥ 至少有一枚。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import tax_cache                       # noqa: E402
import tax_fgk as FGK                  # noqa: E402
from tax_web_search import FGK_MARKER  # noqa: E402


def _hits(n, tag):
    return [{"title": f"财税文件{tag}-{i}",
             "url": f"https://fgk.chinatax.gov.cn/{FGK_MARKER}/{tag}{i}.htm",
             "date": "2025-01-01",
             "document_number": f"财税〔2025〕{tag}{i}号",
             "publisher": "财政部"} for i in range(n)]


class _DiskCache(tax_cache.CacheManager):
    """缓存目录换到临时目录，其余行为照旧（不碰用户真实 ~/.cache）。"""

    def __init__(self, tmp):
        super().__init__(enabled=True, namespace="fgk")
        self.dir = Path(tmp)

    def written(self):
        """盘上真实的清单 payload 列表（读不了的临时件不算）。"""
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8"))["payload"])
            except Exception:
                pass
        return out


class TestFgkIncompleteListNotCached(unittest.TestCase):
    """失败轮 / 断供轮 / 直达轮都不许落盘；健康轮与合法空轮照旧落盘。"""

    def _scan_env(self, pages, total, errors=None):
        """跑 `_scan_list`（不发请求），交回那一轮的信封。"""
        errors = errors or {}

        def fake_search(kw, page=1, size=10, filters=None, **opts):
            out = {"total": total, "results": _hits(pages.get(page, 0), "p%d" % page)}
            if page in errors:
                out["_error"] = errors[page]
                out["results"] = []
            return out

        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search), \
             mock.patch.object(FGK.time, "sleep", lambda *a, **k: None):
            return FGK._scan_list("测试词", size=20, max_pages=6, adaptive=False)

    def _wire(self, env, cache, keyword="测试词", pages=None):
        """把 `_scan_list` 换成预制信封，走真实的 search_fgk 缓存路径。

        pages 给出时 search_chinatax 按页供数（模拟通道恢复），否则一律回 env。
        """
        if pages is None:
            scan = lambda *a, **k: dict(env)
        else:
            def scan(*a, **k):
                return {"total": sum(len(v) for v in pages.values()),
                        "total_hits": sum(len(v) for v in pages.values()),
                        "results": [it for v in pages.values() for it in v]}
        with mock.patch.object(FGK, "_cache", cache), \
             mock.patch.object(FGK, "_scan_list", side_effect=scan), \
             mock.patch.object(FGK.time, "sleep", lambda *a, **k: None):
            return FGK.search_fgk(keyword, size=20, max_pages=6, adaptive=False)

    # ── 控制组：取全了的那一轮必须照旧落盘 ────────────────────────────────
    def test_control_round_is_still_cached(self):
        env = self._scan_env({1: 10, 2: 2}, 12)
        self.assertNotIn("_error", env, "前提：这一轮没有残缺点")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            first = self._wire(env, cache)
            self.assertEqual(1, len(cache.written()), "健康轮不落盘就是缓存白丢")
            self.assertFalse(first["_from_cache"])
            second = self._wire(env, cache)
            self.assertTrue(second["_from_cache"], "第二次应当吃到盘上那份")

    # ── ② 合法空结果：完整可信的答案，必须落盘 ───────────────────────────
    def test_legal_zero_result_is_cached(self):
        """少了这条，守卫就会被写成 `if "_error" in r`，把合法空结果一并排除。"""
        env = {"total": 0, "total_hits": 4822, "results": [],
               "_error": "翻完前 1 页总局检索结果（共 4822 条命中）未筛出法规库条目"}
        self.assertNotIn("_empty_reason", env, "前提：合法空档只有 _error")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            self._wire(env, cache, keyword="小微企业")
            self.assertEqual(1, len(cache.written()),
                             "合法空结果是可信结论，不缓存等于每次白抓")

    # ── ④ 请求失败轮 ─────────────────────────────────────────────────────
    def test_request_failure_round_is_not_cached(self):
        env = self._scan_env({}, 0, errors={1: "search5 检索失败：HTTP 500"})
        self.assertTrue(env.get("_fetch_failed"), "前提：这一轮是取数失败")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            self._wire(env, cache)
            self.assertEqual([], cache.written(), "取数失败的那一轮不许落盘")
            back = self._wire(env, cache, pages={1: _hits(10, "p1"), 2: _hits(2, "p2")})
            self.assertFalse(back.get("_from_cache"), "没落盘，恢复后才会真去重试")

    # ── ⑥ 中途断供轮 ─────────────────────────────────────────────────────
    def test_dropout_round_is_not_cached(self):
        env = self._scan_env({1: 10}, 62)
        self.assertIn("断供", env["_error"], "前提：这一轮判成断供")
        self.assertEqual(10, env["total"], "已取回的条目照旧交回，不是清零")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            self._wire(env, cache)
            self.assertEqual([], cache.written(), "半截清单不能被当完整存档钉住一小时")

    # ── ③ 接口报命中数却没给清单 ──────────────────────────────────────────
    def test_empty_list_reason_round_is_not_cached(self):
        env = self._scan_env({}, 62, errors={})
        # 直接构造第三档：接口 total>0 而首屏 items 空，_scan_list 会走 empty_reason
        def fake_search(kw, page=1, size=10, filters=None, **opts):
            return {"total": 62, "results": [],
                    "_empty_reason": "接口报告命中 62 条，第 1 页却没给条目清单"}
        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search), \
             mock.patch.object(FGK.time, "sleep", lambda *a, **k: None):
            env = FGK._scan_list("测试词", size=20, max_pages=3, adaptive=False)
        self.assertIn("_empty_reason", env, "前提：这一轮走的是接口空清单那档")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            self._wire(env, cache)
            self.assertEqual([], cache.written())

    # ── ⑤ 检索失败改按标识直达、取到了条目 ───────────────────────────────
    def test_direct_fallback_round_is_not_cached(self):
        direct = ([{"title": "直达条目",
                    "url": f"https://fgk.chinatax.gov.cn/{FGK_MARKER}/c52.htm",
                    "body_status": "ok"}], [], [])

        def fake_search(kw, page=1, size=10, filters=None, **opts):
            return {"total": 0, "results": [], "_error": "search5 检索失败：HTTP 500"}

        with mock.patch.object(FGK, "search_chinatax", side_effect=fake_search), \
             mock.patch.object(FGK, "detail_ids_from_text", lambda t: ["c100024/c52"]), \
             mock.patch.object(FGK, "_direct_entries", lambda t: direct), \
             mock.patch.object(FGK.time, "sleep", lambda *a, **k: None):
            env = FGK._scan_list("c100024/c52", size=20, max_pages=3, adaptive=False)
        self.assertTrue(env.get("direct_from_ids"), "前提：这一臂是直达成功档")
        self.assertIn("_search_failed", env, "前提：清单那一路的失败记在 _search_failed")
        self.assertNotIn("_fetch_failed", env, "前提：有条目在手，_fetch_failed 已被清掉")
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            self._wire(env, cache, keyword="c100024/c52")
            self.assertEqual([], cache.written(),
                             "直达那几条不是这一词的清单，不能当清单存档")

    # ── 三枚键里任一出现即不落盘（把判据本身钉住，防以后有人"简化"成真值判）──
    def test_guard_reads_keys_not_truthiness(self):
        """只带这三枚键之一也必须不落盘；只带 _error 必须落盘。"""
        for marks, should_cache in (
                ({"_fetch_failed": True}, False),
                ({"_empty_reason": "接口没给清单"}, False),
                ({"_search_failed": True}, False),
                ({"_error": "翻完未筛出法规库条目"}, True),
                ({}, True)):
            env = {"total": 0, "total_hits": 0, "results": [], **marks}
            with self.subTest(marks=sorted(marks)), tempfile.TemporaryDirectory() as tmp:
                cache = _DiskCache(tmp)
                self._wire(env, cache)
                self.assertEqual(should_cache, len(cache.written()) == 1,
                                 "%s 应当%s落盘" % (sorted(marks),
                                                    "" if should_cache else "不"))

    # ── 读侧：旧版本写进盘上的失败存档不得被回放 ──────────────────────────
    def test_poisoned_entry_on_disk_is_not_replayed(self):
        """守卫是 3.62.17 才加的，之前落的失败存档还在用户盘上。

        这一条只 patch `_scan_list`，**写盘那一路照旧走真实代码**；键按生产算法
        现算（默认参数不追加 filters/scope 键段），对不对由"这一轮取全后落盘份
        覆盖在同一键上"自证。
        """
        keyword = "测试词"
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            key = cache._key("fgk", FGK.LIST_KEY_REV, keyword, "20", "6", "False")
            poisoned = {"total": 0, "total_hits": 62, "results": [],
                        "_error": "search5 检索失败：HTTP 500",
                        "_fetch_failed": True}
            cache.set(key, poisoned)
            self.assertEqual(1, len(cache.written()), "前提：盘上确有那份残缺")

            env = self._scan_env({1: 10, 2: 2}, 12)
            got = self._wire(env, cache, keyword=keyword)
            self.assertFalse(got.get("_from_cache"),
                             "残缺存档绝不能被回放成这一轮的结论")
            self.assertEqual(12, got["total"], "交回的应是这一轮真取到的清单")
            written = cache.written()
            self.assertEqual([env], written,
                             "同一键上，这一轮的完整清单把那份残缺覆盖掉")
            self.assertNotIn("_fetch_failed", written[0])

    def test_poisoned_entry_is_not_replayed_even_when_this_round_fails_again(self):
        """这一轮也没取全时，那份残缺同样不能被当成答案回放。"""
        with tempfile.TemporaryDirectory() as tmp:
            cache = _DiskCache(tmp)
            key = cache._key("fgk", FGK.LIST_KEY_REV, "测试词", "20", "6", "False")
            cache.set(key, {"total": 0, "total_hits": 62, "results": [],
                            "_error": "search5 检索失败：HTTP 500",
                            "_fetch_failed": True})
            second = self._wire(self._scan_env({}, 0,
                                               errors={1: "search5 检索失败：HTTP 500"}),
                                cache)
            self.assertFalse(second.get("_from_cache"),
                             "两次都失败也不许把上一次的残缺当结论")
            self.assertTrue(second.get("_fetch_failed"))


if __name__ == "__main__":
    unittest.main()
