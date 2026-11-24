# -*- coding: utf-8 -*-
"""3.62.22 常驻测试第一版：下载路的三档报错与白名单。

钉四件事（3.62.22 起）：
1. fmt 白名单：库函数直调传 zip 必须报 ValueError——实测站点对白名单外的
   format 静默回 docx 地址，二分式 ext 又会把 docx 字节挂上 .pdf 的名字。
2. 缺地址三档分开报：库里没有这条 bbbs ≠ 这份文件没有这个格式 ≠ 探测本身
   失败。旧文案 `No download URL returned for <id>` 把三者混成一句（红线⑦族）。
3. 判据走 fetch_detail 的 oss_files（缓存 TTL 内，不多打一次站）；
   探测失败时必须退回"原因未能确认"，不许拿失败的探测断言文件不存在。
4. 闸与复用契约不变：download_bytes 仍在 npc_gate 内取字节；
   _missing_attachment_reason 复用 fetch_detail（同一模块函数名，桩换它就能观测）。

全部离线：桩 _request 与 fetch_detail，缓存走 TAX_CACHE_DIR（conftest 已设）。
"""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import tax_detail as DT  # noqa: E402


class _NpcEnvelope:
    """HTTP 200 的 NPC 信封替身，业务状态只活在 JSON 里。"""

    def __init__(self, payload):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.text = payload
        self.content = payload.encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)


_DL_OK_DOCX = '{"msg":"操作成功","code":200,"data":{"url":"https://flkoss.obs/1.docx"}}'
_DL_NONE = '{"msg":"操作成功","code":200,"data":{}}'

_TITLE = "碳排放权交易管理暂行条例"


class TestDownloadFormatWhitelist(unittest.TestCase):
    """库函数直调也要挡住白名单外的 format。"""

    def test_zip_is_refused_at_the_url_layer(self):
        with mock.patch.object(DT, "_request",
                               side_effect=AssertionError("白名单外不该发出请求")):
            with self.assertRaises(ValueError) as cm:
                DT.get_download_url("x", "zip")
        self.assertIn("docx/pdf", str(cm.exception))

    def test_empty_format_is_refused_too(self):
        with mock.patch.object(DT, "_request",
                               side_effect=AssertionError("空串也不该发出请求")):
            with self.assertRaises(ValueError):
                DT.get_download_url("x", "")

    def test_docx_and_pdf_still_go_through(self):
        """控制组：白名单内两个值照常工作。"""
        with mock.patch.object(DT, "_request",
                               return_value=_NpcEnvelope(_DL_OK_DOCX)):
            self.assertEqual("https://flkoss.obs/1.docx",
                             DT.get_download_url("x", "docx"))
            self.assertEqual("https://flkoss.obs/1.docx",
                             DT.get_download_url("x", "pdf"))

    def test_download_file_stops_before_touching_disk(self):
        """白名单外不许落到盘上——这是 3.62.22 事故的本体。

        站点在 fmt="zip" 时吐的是 docx 字节，而 `ext = "docx" if fmt == "docx"
        else "pdf"` 会把它挂成 .pdf：内容与扩展名一起说谎，任何阅读器打开都报错。
        现在这条路在取地址那一步就断，压根走不到 open()。
        """
        import tempfile
        tmp = tempfile.mkdtemp(prefix="tax-dl22-")
        path = os.path.join(tmp, "out.bin")
        with mock.patch.object(DT, "_request",
                               side_effect=AssertionError("不该发请求")):
            with self.assertRaises(ValueError):
                DT.download_file("SHARED-DL22", "zip", output_path=path)
        self.assertFalse(os.path.exists(path), "报错之前已经把文件落盘了")


class TestMissingDownloadReason(unittest.TestCase):
    """取不到地址时分三档报，不许再混成一句 `No download URL`。"""

    def _run_bytes(self, detail_or_exc):
        """download_bytes 撞上"无地址"信封时的异常文案。"""
        old = DT._request
        old_detail = DT.fetch_detail
        try:
            DT._request = lambda url, **kw: _NpcEnvelope(_DL_NONE)
            if isinstance(detail_or_exc, Exception):
                def _boom(bid):
                    raise detail_or_exc
                DT.fetch_detail = _boom
            else:
                DT.fetch_detail = lambda bid: detail_or_exc
            with self.assertRaises(ValueError) as cm:
                DT.download_bytes("SHARED-DL22", "pdf")
            return str(cm.exception)
        finally:
            DT._request = old
            DT.fetch_detail = old_detail

    def test_record_absent_says_so(self):
        got = self._run_bytes({"title": "", "oss_files": {"docx": "", "pdf": ""}})
        self.assertIn("查不到这条 bbbs", got, "没把库里没有这件事说出口：" + got)
        self.assertIn("pdf", got, "没说是哪个格式")

    def test_record_present_without_this_format_says_so(self):
        got = self._run_bytes({"title": _TITLE, "oss_files": {"docx": "a.docx", "pdf": ""}})
        self.assertIn(_TITLE, got)
        self.assertIn("没有 pdf", got, "这份没这个格式没说出来：" + got)
        self.assertIn("docx", got, "没说现有的格式是什么")

    def test_probe_failure_never_claims_absence(self):
        got = self._run_bytes(RuntimeError("网络抖动"))
        self.assertIn("原因未能确认", got, f"拿失败的探测断言了文件不存在：{got}")
        self.assertIn("网络抖动", got, "没把探测失败的原因带出来")
        self.assertNotIn("查不到", got)

    def test_reason_mentions_which_format_was_asked(self):
        got = self._run_bytes({"title": _TITLE, "oss_files": {"docx": "a.docx", "pdf": ""}})
        self.assertIn("pdf", got)

    def test_both_ends_agree_never_claimed_absent(self):
        """兜底档：详情写着有这个附件、下载端点却没给地址——两端读数相左。

        这一档既不能说"这份没这个格式"（详情不同意），也不能说"库里没这条"
        （标题明明取回来了）。它存在的意义是把矛盾摆在明面上，而不是替站点
        挑一个说法。
        """
        got = self._run_bytes({"title": _TITLE, "oss_files": {"docx": "a.docx", "pdf": "a.pdf"}})
        self.assertIn(_TITLE, got)
        self.assertIn("相左", got, "没有承认两端读数对不上：" + got)
        self.assertNotIn("查不到", got)
        self.assertNotIn("没有 pdf 附件", got)

    def test_record_with_no_attachment_at_all_says_so(self):
        """记录在、两种附件都空——得说"两种附件都没有"，别只报一个空列表。"""
        got = self._run_bytes({"title": _TITLE, "oss_files": {"docx": "", "pdf": ""}})
        self.assertIn(_TITLE, got)
        self.assertIn("两种附件都没有", got, got)
        self.assertNotIn("查不到", got)


class TestReasonReusesDetailCache(unittest.TestCase):
    """判据必须复用 fetch_detail（TTL 内的缓存），不许另开一条详情路。"""

    def test_reason_layer_is_only_fetch_detail(self):
        src = (SCRIPTS_DIR / "tax_detail.py").read_text(encoding="utf-8")
        body = src[src.index("def _missing_attachment_reason"):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("fetch_detail(", body, "三档判据没有走 fetch_detail")
        self.assertNotIn("law-search/", body, "判据层自己拼了详情地址")


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
