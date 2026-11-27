#!/usr/bin/env python3
"""限流记录实测台账的契约用例。不联网，只读文档与源码。

台账要解决的事：闸与退避是照"某年并行被限流过"建的，而站点风控会变。记录一旦
没有再量的日期，读的人分不清它说的是今天的站点还是当时的站点。所以这里钉三件事：

1. 台账每条限流记录都带齐三字段——最近实测日期、实测方法（连发几次 + 几线程）、
   当时结果（按形态逐项计数）。缺任一格，这条记录就没有证据。
2. 没复测的行必须明写"没有当次数据"，不许留空、也不许用旧句子冒充今天的结论。
3. 代码里每把串行闸所保护的站点，台账都要有一行——防止"先装闸、证据以后再补"，
   那正是本仓库要避免的那种事。

日期值域写成常量而不是"看起来像日期就行"：`从未取过阈值` 这类说法是这条记录的
内容本身（从没量过），不是过期数据，所以它必须在值域里被明写出来才通过。
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
REFERENCES_DIR = ROOT / "references"
LEDGER_DOC = REFERENCES_DIR / "source_defects.md"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SECTION = "## 限流记录的实测台账"

#: 「最近实测日期」这一格允许的写法。ISO 日期之外的两种是"这条记录没有再量过"的
#: 明确表述，其余任何说法（"最近"、"上次"、"以前"）都不算填了这一格。
MEASURED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_RECHECKED = {"未复测"}
NEVER_MEASURED = {"从未取过阈值"}

#: 没有实测日期的行，「当时结果」必须携带这句话，读者才知道这一格不是数据。
NO_DATA_SENTENCE = "没有当次数据"

#: 有实测日期的行，方法格里必须同时给出连发次数与线程数——只写"并行跑了一次"
#: 无法复查，也无法判断下一次要跑到什么量级才算复现过。
BURST_RE = re.compile(r"连发\s*\d+")
THREAD_RE = re.compile(r"(\d+)\s*线程|整栏分页|天然串行")


def _ledger_rows(md: str):
    """取出台账表格的数据行，返回 [列列表]；不含表头与分隔行。"""
    start = md.index(SECTION)
    rest = md[start + len(SECTION):]
    stop = rest.find("\n## ")          # 台账只到自己那一节结束
    body = rest[:stop] if stop >= 0 else rest
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        if cells[0].startswith("记录原话") or set(cells[0]) <= {"-", " ", ":"}:
            continue
        rows.append(cells)
    return rows


def _gated_hosts():
    """代码里每把串行闸所保护的站点主机名。

    认"实例化 SerialGate 的那个模块"而不是认锁文件名：闸与站点是同模块绑定的
    （`NpcSerialGate` 打在 tax_search、`yuanbao_gate` 打在 tax_wechat），模块顶部的
    站点常量就是这把闸保护的对象。tax_http 是闸的本体，跳过。
    """
    hosts = set()
    for p in sorted(SCRIPTS_DIR.glob("*.py")):
        if p.name == "tax_http.py":
            continue
        src = p.read_text(encoding="utf-8")
        if "SerialGate" not in src:
            continue
        # 只取模块级字符串常量里的 URL，注释与 docstring 里的示例站不算保护对象
        for m in re.finditer(r'^([A-Z_]+)\s*=\s*"(https?://[^"]+)"', src, re.M):
            host = re.sub(r"^https?://", "", m.group(2)).split("/")[0]
            hosts.add(host)
    return hosts


class TestLedgerRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.md = LEDGER_DOC.read_text(encoding="utf-8")
        cls.rows = _ledger_rows(cls.md)

    def test_section_exists_with_rows(self):
        self.assertIn(SECTION, self.md, "台账这一节被删掉了")
        self.assertGreaterEqual(len(self.rows), 3,
                                f"台账只剩 {len(self.rows)} 行，限流记录不止这几条")

    def test_columns_are_named_in_order(self):
        head = [ln for ln in self.md.splitlines()
                if ln.strip().startswith("| 记录原话")]
        self.assertEqual(len(head), 1, "台账表头丢了或重复了")
        cols = [c.strip() for c in head[0].strip("|").split("|")]
        self.assertEqual(cols, ["记录原话", "入口", "现在由什么挡着",
                                "最近实测日期", "实测方法", "当时结果"])

    def test_every_row_has_a_date_or_says_it_was_not_rechecked(self):
        for row in self.rows:
            date_cell = row[3]
            if MEASURED_RE.match(date_cell):
                continue
            self.assertIn(date_cell, NOT_RECHECKED | NEVER_MEASURED,
                          f"「{row[0][:20]}…」的日期格写的是 {date_cell!r}，"
                          f"既不是 ISO 日期，也不在'{NOT_RECHECKED | NEVER_MEASURED}'里")
            self.assertIn(NO_DATA_SENTENCE, row[5],
                          f"「{row[0][:20]}…」没有实测日期，"
                          f"「当时结果」却没写'{NO_DATA_SENTENCE}'，会被读成有数据")

    def test_measured_rows_name_both_burst_and_concurrency(self):
        for row in self.rows:
            if not MEASURED_RE.match(row[3]):
                continue
            self.assertTrue(BURST_RE.search(row[4]),
                            f"「{row[0][:20]}…」有实测日期，方法格却没写连发几次：{row[4]!r}")
            self.assertTrue(THREAD_RE.search(row[4]),
                            f"「{row[0][:20]}…」有实测日期，方法格却没写并发/线程量：{row[4]!r}")

    def test_measured_rows_count_by_shape_not_by_opinion(self):
        """「当时结果」必须是形态×次数的计数，否则下次复现时看不出是不是同一种形态。"""
        for row in self.rows:
            if not MEASURED_RE.match(row[3]):
                continue
            self.assertRegex(row[5], r"[×x]\s*\d+",
                             f"「{row[0][:20]}…」的当时结果没有按形态计数：{row[5]!r}")

    def test_no_empty_cell(self):
        for row in self.rows:
            for i, cell in enumerate(row):
                self.assertTrue(cell, f"台账第 {i + 1} 列是空的：{row[0][:20]}…")


class TestGatesHaveLedgerRows(unittest.TestCase):
    def test_every_gated_host_appears_in_the_ledger(self):
        rows = _ledger_rows(LEDGER_DOC.read_text(encoding="utf-8"))
        listed = " ".join(r[1] for r in rows)
        missing = [h for h in sorted(_gated_hosts()) if h not in listed]
        self.assertFalse(
            missing,
            f"这些站点上装了串行闸，台账里却没有对应的限流记录行：{missing}。"
            f"要么补一行（可以写'未复测'），要么把闸撤掉——"
            f"没有证据的闸正是本台账要治的东西。")

    def test_the_two_known_gates_are_covered(self):
        """值域自检：闸真在的时候这一条才有效，闸被删了要在这里报，而不是静默变绿。"""
        hosts = _gated_hosts()
        self.assertIn("flk.npc.gov.cn", hosts, "NPC 那把闸在代码里找不到了")
        self.assertIn("so.qq.com", hosts, "元宝那把闸在代码里找不到了")


class _Resp:
    """探针形态判据要的最小响应面：状态码、原始字节、文本、落地地址。"""

    def __init__(self, status=200, body="",
                 url="https://so.qq.com/isearch?tab=weixin_article&query=x"):
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.text = body if isinstance(body, str) else body.decode("utf-8", "replace")
        self.url = url
        self.headers = {"Content-Type": "text/html"}


class TestProbeShapeLabels(unittest.TestCase):
    """探针形态必须与元宝生产判据同族，手机搜狗仍单独判。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        spec = importlib.util.spec_from_file_location(
            "probe_rate_limit", ROOT / "tests" / "probe_rate_limit.py")
        cls.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probe)

    def test_yuanbao_request_shape_matches_production(self):
        """探针那一发必须与生产的垂直档 POST 同形——量错路径等于没量。

        逐枚对照 `_vertical_search`：接口、`sp.tab`、`page`、`x-original-uri`、
        编码方式、超时、verify。旧断言钉的是 GET `/isearch`，3.62.49 起那是兜底档。
        """
        import tax_wechat
        method, url, kwargs = self.probe._yuanbao_call()
        self.assertEqual("POST", method)
        self.assertEqual(tax_wechat.YUANBAO_NEXT_PAGE, url)
        self.assertEqual(tax_wechat.TIMEOUT, kwargs["timeout"])
        self.assertFalse(kwargs["verify"])
        sent = json.loads(kwargs["data"].decode("utf-8"))
        self.assertEqual({"tab": tax_wechat.VERTICAL_TAB}, sent["sp"])
        self.assertEqual(1, sent["page"])
        self.assertEqual("研发费用加计扣除", sent["query"])
        self.assertIsInstance(kwargs["data"], bytes)
        headers = kwargs["headers"]
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertTrue(headers["x-original-uri"].startswith(
            tax_wechat.IWEIXIN_PREFIX + "?tab=weixin_article&query="))
        for key, value in tax_wechat.HEADERS_YUANBAO.items():
            self.assertEqual(value, headers[key], f"会话头 {key} 没带上")

    def test_empty_page_is_not_recorded_as_a_normal_page(self):
        label = self.probe._yuanbao_shape(_Resp(status=200, body=""))
        self.assertFalse(self.probe._is_good(self.probe.TARGETS["yuanbao"], label))
        self.assertIn("空响应", label)

    def test_json_shapes_are_separated_from_each_other(self):
        """JSON 四形各占一格：有货／有货但链形不对／短接／活着的空批。

        熔断形与「站内真没这个词」在阈值上是两件事，压成一格就看不出这一发是被
        频控了还是站点给了空清单（真响应读数：满档 `timings.search` 744+ms，
        熔断只剩十几毫秒且 `cards` 为空）。
        """
        card = {"data": {"vm": {"title": "题名",
                                "jumpUrl": "https://mp.weixin.qq.com/s?k=1"},
                         "item": {"jsonData": {"pub_time": 1764000000}}}}
        junk = {"data": {"vm": {"title": "题名", "jumpUrl": "https://evil.test/a"}}}
        alive = json.dumps({"cards": [card], "timings": {"search": 744}},
                           ensure_ascii=False)
        self.assertTrue(self.probe._yuanbao_shape(_Resp(body=alive)).startswith(
            "200-结果卡("), alive)
        badlink = json.dumps({"cards": [junk], "timings": {"search": 744}},
                             ensure_ascii=False)
        self.assertIn("无有效直链", self.probe._yuanbao_shape(_Resp(body=badlink)))
        dead = json.dumps({"cards": [], "timings": {"antispider": 23}},
                          ensure_ascii=False)
        self.assertIn("通道短接", self.probe._yuanbao_shape(_Resp(body=dead)))
        empty = json.dumps({"cards": [], "timings": {"search": 744}},
                           ensure_ascii=False)
        self.assertIn("空批次", self.probe._yuanbao_shape(_Resp(body=empty)))

    def test_html_fallback_pages_keep_their_own_labels(self):
        """非 JSON 的回显仍按 HTML 分形：无结果提示、改版壳页。"""
        self.assertEqual(self.probe._yuanbao_shape(
            _Resp(body='<div class="js-results">没有结果</div>')), "200-无结果提示")
        self.assertIn("既无结果卡也无提示",
                      self.probe._yuanbao_shape(_Resp(body="<html>壳页</html>")))

    def test_rate_limit_page_is_not_recorded_as_a_login_wall(self):
        """「请登录后继续查看内容」记成限流，`login_page` 才记成需登录。

        前端 chunk 逐字：`case"429_outer":return"请登录后继续查看内容"`，渲染器
        `WebLoginRequiredPlaceholder` 按 `allowLogin:"429_outer"===code` 才给登录
        入口。旧标签把前者记成「登录墙」，台账于是以为这两路需要登录态，掩盖了它
        其实是频次问题（真网那两枚红的真身就是它）。
        """
        self.assertEqual(self.probe._yuanbao_shape(
            _Resp(body="<div>请登录后继续查看内容</div>")), "200-限流页(429_outer)")
        self.assertEqual(self.probe._yuanbao_shape(
            _Resp(body='<a data-x="linkid&quot;:&quot;login_page&quot;">登录</a>')),
            "200-需登录")
        self.assertEqual(self.probe._yuanbao_shape(
            _Resp(body='<script src="/static/antispider.min.js"></script>环境异常')),
            "200-验证或拦截页")

    def test_result_cards_win_over_summary_keywords(self):
        """摘要里带「验证码」不改变形态：先认卡，再认拦截锚。"""
        card = {"data": {"vm": {"title": "题名", "summary": "摘要提到验证码",
                                "jumpUrl": "https://mp.weixin.qq.com/s?k=1"}}}
        body = json.dumps({"cards": [card], "timings": {"search": 744}},
                          ensure_ascii=False)
        self.assertTrue(self.probe._yuanbao_shape(_Resp(body=body)).startswith(
            "200-结果卡("), body)

    def test_antispider_redirect_still_wins_over_the_body_checks(self):
        for marker in ("antip=web_hd", "antip=wap_hd", "antip=new_hd"):
            self.assertEqual(
                self.probe._yuanbao_shape(_Resp(
                    body='{"cards":[],"timings":{"search":744}}',
                    url="https://so.qq.com/x?" + marker)), "跳转-antispider", marker)
        self.assertEqual(
            self.probe._yuanbao_shape(_Resp(
                body="", url="https://so.qq.com/antispider/?x")), "跳转-antispider")

    def test_the_mobile_probe_separates_an_empty_body_too(self):
        self.assertIn("空响应",
                      self.probe._sogou_mobile_shape(_Resp(
                          body="", url="https://m.sogou.com/web/searchList.jsp")))

    def test_good_labels_are_predicates_not_one_fixed_string(self):
        for key in ("yuanbao", "sogou-mobile"):
            good = self.probe.TARGETS[key]["good"]
            self.assertTrue(callable(good),
                            f"{key} 的 good 又不是判函数了，形态会被压平")
        self.assertTrue(self.probe._is_good(
            self.probe.TARGETS["yuanbao"], "200-结果卡(10张,白名单挡掉0)"))
        self.assertFalse(self.probe._is_good(
            self.probe.TARGETS["yuanbao"], "200-通道短接(search=22ms)"))
        self.assertFalse(self.probe._is_good(
            self.probe.TARGETS["yuanbao"], "200-限流页(429_outer)"))
        self.assertFalse(self.probe._is_good(
            self.probe.TARGETS["yuanbao"], "200-空响应(0字节)"))
        self.assertFalse(self.probe._is_good(
            self.probe.TARGETS["sogou-mobile"], "200-有结果块无直链(raw=0)"))

    def test_read_probe_declares_no_redirect_following(self):
        """正文入口探针与 `read_article` 同形：不跟随跳转（零出网断言）。

        `_wechat_read_call` 要先真检索一次才有签名地址，离线用例不能调它，
        所以这里钉源码：那枚 `allow_redirects` 必须在。
        """
        src = (ROOT / "tests" / "probe_rate_limit.py").read_text(encoding="utf-8")
        body = src[src.index("def _wechat_read_call"):src.index("def _json_shape")]
        self.assertIn('"allow_redirects": False', body,
                      "_wechat_read_call 跟随跳转，落地非微信主机也会被记成正常")

    def test_the_probe_covers_all_active_entries(self):
        self.assertIn("yuanbao", self.probe.TARGETS)
        self.assertIn("sogou-mobile", self.probe.TARGETS)
        self.assertIn("wechat-read", self.probe.TARGETS)
        self.assertNotIn("sogou", self.probe.TARGETS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
