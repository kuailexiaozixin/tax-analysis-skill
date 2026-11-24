"""离线守卫：号称离线的用例，一次真实连接都不许发生。

起因（2026-11-24 实测）。审计工具 `.tmp-inspect/netblock_plugin.py` 第一版只在
异常**冒泡到用例层**时记违规，而本项目生产代码普遍把网络异常吞成 `_error`
字符串——那正是被测行为。于是它报 `total-offline-violations=0`，可同一枚用例
不带插件跑时 urllib3 明明白白抛出
`InsecureRequestWarning: Unverified HTTPS request is being made to host
'www.chinatax.gov.cn'`，耗时 2.51s；掐断后同一用例涨到 14.32s、18 次 connect
尝试（重试退避）。**"零违规"是探测器的盲点，不是测试真的离线。**

漏出来的那处缺陷也顺带量到了根：`TestRoundFailureIsNotSilent
.test_draft_round_uses_draft_term_not_short_term` 的题面点了《税收征管法》的名，
`gather` 在轮次循环**之前**先走点名定位（`locate_cited_document →
FGK.search_fgk → tax_web_search.search_chinatax → requests.get`），这条路
不经过 `_FETCHERS`。所以只 patch 六个取数函数的桩法挡不住它。同文件 L2208
那处（`_跑一趟`）本来就是 `_FETCHERS` + `FGK.search_fgk` 双打的，这一处漏了半边。

本文件把探测器修好的那半件事固化进门禁：记账点移到 `socket.connect` 那一刻，
且**抛出之前先记数**（生产代码吞异常也不能把尝试吞没）。全部用例只用回环地址，
守卫自身不需要联网，也不会因为外网抖动而假失败。
"""

import os
import socket
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class OffNetworkAttempt(BaseException):
    """本应离线的代码段里发生了真实连接/DNS 解析。

    故意派生自 `BaseException` 而**不是** `Exception`：项目里每一层取数都是
    `except Exception`（把网络故障收成 `_error` 字符串，那正是被测行为），
    从钩子里抛出的 `Exception` 会被源层吞掉、然后走完它自己的重试退避——
    实测 12 次 DNS × 1.5s ≈ 18 秒白等，而 `sleep=time.sleep` 是 `attempt()`
    的**默认实参**、导入时就绑死了函数对象，事后 patch 模块属性根本拦不住。
    抛 `BaseException` 则在第一次拨号尝试处当场断开：记数照样先做，
    控制层吞不掉它，也就不会替它把退避睡完。
    """


@contextmanager
def assert_offline():
    """这一段代码不许拨号：任何 socket.connect / getaddrinfo 先记账再断开。

    与"只拦不记"的区别是关键：源层普遍 `except Exception` 把网络异常收成
    一句 `_error`，若只在抛出时判类型、事后看有没有冒泡，被吞掉的那次尝试
    就消失了——这正是上一版探测器的盲点（它报 violations=0，同一用例却真连了
    www.chinatax.gov.cn 18 次）。

    yield 出记录列表，供调用方在段内自查；退出时列表非空是第二道兜底
    （万一哪层真把 BaseException 也吞了，仍然在这里翻脸）。
    """
    real_connect = socket.socket.connect
    real_create = getattr(socket, "create_connection", None)
    real_getaddr = socket.getaddrinfo
    tried = []

    def blocked(sock, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) and address else address
        tried.append(str(host))
        raise OffNetworkAttempt("offline section tried to connect to %r" % (host,))

    def blocked_create(address, *a, **kw):
        blocked(None, address, *a, **kw)

    def blocked_getaddr(host, *a, **kw):
        # DNS 解析同样是网络副作用：真站域名在这段里一概不许查
        # （回环数字地址不经这条路，所以控制组不受影响）
        tried.append("dns:%s" % (host,))
        raise OffNetworkAttempt("offline section tried to resolve %r" % (host,))

    socket.socket.connect = blocked
    if real_create is not None:
        socket.create_connection = blocked_create
    socket.getaddrinfo = blocked_getaddr
    try:
        yield tried
    finally:
        socket.socket.connect = real_connect
        if real_create is not None:
            socket.create_connection = real_create
        socket.getaddrinfo = real_getaddr
        if tried:
            raise OffNetworkAttempt(
                "这一段本应离线，却尝试了 %d 次真实连接：%s"
                % (len(tried), sorted(set(tried))))


class TestGuardMechanism(unittest.TestCase):
    """控制组：先证明这道闸真的拦得住、也真的会还原，否则后面的守卫是假绿。"""

    def test_loopback_connect_is_caught(self):
        # 守卫段内拨号（哪怕是回环）必须被抓住：验的是"拦得住"，不是"连不连得上"
        with self.assertRaises(OffNetworkAttempt):
            with assert_offline():
                socket.create_connection(("127.0.0.1", 1), 0.2)

    def test_swallowed_exception_is_still_counted(self):
        """生产代码那种 `except Exception: pass` 不许把尝试吞没。

        这是本文件存在的理由：上一版探测器就是死在这一条上。
        """
        import requests
        with self.assertRaises(OffNetworkAttempt) as cm:
            with assert_offline():
                try:
                    requests.get("https://127.0.0.1:1/", timeout=0.2)
                except Exception:
                    pass  # 源层的标准做法——正因为如此才看不见它打过网络
        self.assertIn("127.0.0.1", str(cm.exception))

    def test_guard_restores_socket_on_exit(self):
        real = socket.socket.connect
        with self.assertRaises(OffNetworkAttempt):
            with assert_offline():
                socket.create_connection(("127.0.0.1", 1), 0.2)
        self.assertIs(socket.socket.connect, real)
        with assert_offline() as tried:      # 空段必须干净通过
            pass
        self.assertEqual([], tried)

    def test_dns_lookup_is_caught_before_it_leaves(self):
        """解析域名也是外连：闸门得拦在 getaddrinfo 上。

        只拦 `socket.connect` 的话，域名要先真查一次 DNS 才走到那一步——
        上一版就是这么漏的：18 次尝试全部记成 `dns:www.chinatax.gov.cn`，
        一次 connect 都没发生，探测器却报零违规。
        """
        with self.assertRaises(OffNetworkAttempt) as cm:
            with assert_offline() as tried:
                socket.getaddrinfo("example.invalid", 443)
        self.assertIn("dns:example.invalid", tried)
        self.assertIn("dns:example.invalid", str(cm.exception))

    def test_guard_exception_cannot_be_swallowed(self):
        """`OffNetworkAttempt` 必须避开 `except Exception`。

        派生自 `Exception` 时它会被源层那句标准吞法吃掉、接着把重试退避睡完：
        `tax_http.attempt(..., sleep=time.sleep)` 的 sleep 是**默认实参**、导入时
        就绑死了函数对象，事后 patch 拦不住，实测白等 18 秒才在同一处翻脸。
        拦副作用要断在副作用发生的那一刻，不是断在事后清点。
        """
        self.assertFalse(issubclass(OffNetworkAttempt, Exception),
                         "守卫异常会被 except Exception 吞掉")
        self.assertTrue(issubclass(OffNetworkAttempt, BaseException))


class TestGatherStaysOffline(unittest.TestCase):
    """按文档桩法跑 gather，全程零 connect。桩少打半边，这里就红。"""

    Q = "请解读《税收征管法》修订草案，已提请全国人大常委会审议"

    def _fetchers(self, seen=None):
        def make(src):
            def fn(term, size):
                if seen is not None:
                    seen.setdefault(src, []).append(term)
                return [], "", ""
            return fn
        # 六枚键都要覆盖：`_FETCHERS` 少一枚，gather 就拿真函数去拨号
        return {s: make(s) for s in ("npc", "fgk", "whole_site",
                                     "shui5", "wechat", "legis")}

    def test_documented_stub_set_is_genuinely_offline(self):
        import tax_answer as AN
        import tax_fgk as FGK
        seen = {}
        with mock.patch.dict(AN._FETCHERS, self._fetchers(seen)), \
                mock.patch.object(FGK, "search_fgk",
                                  lambda kw, size=6, **kw2: {"results": []}), \
                assert_offline():
            AN.gather(self.Q, at="2026-09-29", check_citations=False)
        self.assertTrue(seen.get("shui5"), "桩没被调用，这条路测不到东西")

    def test_cited_locate_path_needs_its_own_stub(self):
        """反向钉住教训：不桩 `FGK.search_fgk`，点名定位路一定拨号。

        这条路在 `gather` 的轮次循环之前，`_FETCHERS` 全桩上也挡不住——
        2026-11-24 那枚用例就是这么漏出 18 次真连的。哪天点名定位改成走
        `_FETCHERS` 或 gather 有了默认离线开关，这一条会因为抓不到连接而红：
        那时该改的是桩清单（以及上一条），别把这条删掉。
        """
        import tax_answer as AN
        # 直接测漏网那一路（`gather` 里它排在轮次循环之前，走的是同一个
        # `locate_cited_document`）。跑整趟 gather 会把六个源的重试退避全走一遍——
        # 注意 `attempt(..., sleep=time.sleep)` 的 sleep 是**默认实参**，导入时就
        # 绑死了函数对象，事后 patch 模块属性拦不住它，实测白等 14 秒。
        with self.assertRaises(OffNetworkAttempt) as cm:
            with assert_offline() as tried:
                try:
                    AN.locate_cited_document("中华人民共和国税收征收管理法")
                except Exception:
                    pass
        self.assertTrue(tried, "没抓到连接：点名定位路已不再外连，"
                               "桩清单与本条断言都要同步改")
        self.assertIn("次真实连接", str(cm.exception))


TESTS = [
    ("守卫自身可用", TestGuardMechanism),
    ("gather 桩法离线", TestGatherStaysOffline),
]


def main():
    ok = total = 0
    for name, case in TESTS:
        r = unittest.TextTestRunner(verbosity=1).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(case))
        total += r.testsRun
        ok += r.testsRun - len(r.failures) - len(r.errors)
    print("结果：%d/%d 通过" % (ok, total))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
