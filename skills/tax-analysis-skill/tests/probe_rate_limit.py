#!/usr/bin/env python3
"""限流实测探针 —— 给 `references/source_defects.md` 的「限流记录实测台账」产出证据。

为什么要这么查：串行闸与退避都是照"某年某月并行被限流过"建的，而站点风控是
随时间变化的活物。记录过期之后，闸就成了没人敢拆、也没人证明它还有必要的保守。
这个脚本把一条记录当场重量一遍，回吐台账要的三字段：

    最近实测日期 / 实测方法（连发 N 次 + M 线程 × 每线程 K 次）/ 当时结果

`当时结果` 按失败形态逐项计数（挑战页、429、5xx、断连、反爬跳转各几次），所以
"没复现"与"复现了"读到的是同一张表；真被限的那天，形态、状态码、字节数也留在
同一份回显里，直接抄进台账，不必再凭记忆补写。

用法：
    python tests/probe_rate_limit.py --target npc --burst 15 --threads 8 --per-thread 2
    python tests/probe_rate_limit.py --target fgk-list --dry-run   # 只看要发的请求，一个不发
    python tests/probe_rate_limit.py --target sogou-mobile --burst 6 --threads 2 --per-thread 2
    python tests/probe_rate_limit.py --target yuanbao --dry-run
    python tests/probe_rate_limit.py --target yuanbao --burst 4 --threads 2 --per-thread 1

`yuanbao` 量的是 POST 取数主路（`searchweb/api/search/next-page` 的
`sp.tab=weixin_vertical`）。GET `/isearch` 是阶梯的第三档兜底，SSR 那一路连结果
都不渲染，量它没有意义。这一枚要小水量：2026-11-27 实测 8 秒间隔连打到第三、四发
就整批回空（112 字节 0 卡、`timings.search` 只剩十几毫秒），25 秒间隔三连发不翻空
——那是冷却窗口，不是账号问题，形态里的「200-通道短接」就是它。

元宝公众号检索（`yuanbao`）、搜狗手机网页检索（`sogou-mobile`）与公众号正文读取
（`wechat-read`）分别量。
手机那枚的量法有个坑必须写死：
生产 `_get` 是 `allow_redirects=False`，反爬信号在 302 的 Location 里；探针若跟随
重定向，302 就变成 200，那道墙当场看不见了——量出来的「不限流」是假的。所以
`sogou-mobile` 的形状判据直接调生产的 `tax_sogou._is_antispider_location` 与
`_looks_like_verify_page`，探针不自立一套，也不跟随跳转。

请求总量被 `MAX_REQUESTS` 卡住：这是查询式访问的复测，不是压测。想刷量级就调
这个常量，不调它脚本会直接拒绝并说明为什么拒——不给"顺手多跑几轮"留口子。
更高量级的阈值本脚本不探测，台账里也就不得写成"已探到上限"。
"""

import argparse
import itertools
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import requests  # noqa: E402
import urllib3  # noqa: E402

import tax_http  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

#: 单次运行的请求总量上限。超过就拒绝执行，见模块文档那句"不是压测"。
MAX_REQUESTS = 60


# ── 取"生产路径真实要发的那一次请求"───────────────────────────────────────
class _Stub:
    """让被拦住的调用正常走完，返回值只求形状对，内容一律当空清单。"""

    status_code = 200
    headers = {"Content-Type": "application/json"}
    url = ""

    def __init__(self, text='{"results":{"data":{"total":0,"results":[]}}}', content=None):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass


def capture_request(build):
    """执行 build()，截住其中第一次 tax_http.request，返回 (method, url, kwargs)。

    为什么不手写一份请求副本：NPC 的 payload 有十几个字段、search5 的 filters 还在
    长，手写副本在源模块改版之后会照发一份过时的请求，然后被"对方给了 5xx"当成
    限流形态记进台账。从生产路径抓就永远与真实取数同一形状。
    """
    real, box = tax_http.request, {}

    def spy(method, url, **kw):
        box.setdefault("call", (method, url, kw))
        return _Stub()

    tax_http.request = spy
    try:
        build()
    finally:
        tax_http.request = real
    if "call" not in box:
        raise RuntimeError("这条生产路径没有经过 tax_http.request，探针取不到请求形状")
    return box["call"]


# ── 三个入口：记录原话、请求形状、失败形态判据 ──────────────────────────────
def _npc_call():
    import tax_search
    return capture_request(lambda: tax_search.search_tax("增值税", size=5))


def _fgk_call():
    import tax_gov_list
    return capture_request(lambda: tax_gov_list.make_fetch_page() (1))


def _yuanbao_call():
    """取数主路那一发（3.62.49 起是 POST next-page 的垂直档）。

    为什么不再量 GET：GET `/isearch` 现在是三档阶梯的第三档兜底，而 SSR 那一路
    根本不渲染结果——量它等于量一条不常用的路。真正在挨限流的是垂直档 POST。
    形状逐字照 `_vertical_search`：同一个接口、`sp.tab=weixin_vertical`、
    `x-original-uri` 头、`data` 是 `ensure_ascii=False` 编出的 UTF-8 字节。这四样
    少任何一样，量到的就不是生产那条路（实测 sp 多给一枚键就整批清空成 112 字节）。
    """
    import tax_wechat
    keyword = "研发费用加计扣除"
    body = {"query": keyword, "page": 1, "sp": {"tab": tax_wechat.VERTICAL_TAB}}
    headers = dict(tax_wechat.HEADERS_YUANBAO)
    headers.update({
        "Content-Type": "application/json",
        "x-original-uri": "%s?tab=weixin_article&query=%s" % (
            tax_wechat.IWEIXIN_PREFIX, quote(keyword, safe="")),
    })
    return ("POST", tax_wechat.YUANBAO_NEXT_PAGE,
            {"headers": headers, "timeout": tax_wechat.TIMEOUT, "verify": False,
             "data": json.dumps(body, ensure_ascii=False).encode("utf-8")})


def _sogou_mobile_call():
    """手机网页检索：照生产 `_fetch` 那一次请求的形状，含不跟随跳转。

    为什么不复用 capture_request：`tax_sogou._get` 在闸内直接调 `sess.get`，
    不经 `tax_http.request`，抓不到（capture_request 会抛那句"没有经过
    tax_http.request"）。所以这里按生产逐字重述：同一个 SEARCH_URL 模板、同一份
    HEADERS、同一个 `allow_redirects=False`。这四样任何一样写错，量到的都不是
    生产那条路。
    """
    import tax_sogou
    url = tax_sogou.SEARCH_URL % quote("增值税 留抵退税")
    return ("GET", url, {"headers": dict(tax_sogou.HEADERS), "timeout": tax_sogou.TIMEOUT,
                         "verify": False, "allow_redirects": False})


def _wechat_read_call():
    """公众号正文读取：先经元宝取到有效直链，再照 `read_article` 逐枚发那一发。

    返回的是**一串**入口（每枚 URL 一发），`run` 轮转使用；每枚只发一次，正文
    取数失败与元宝检索失败分开记。前置检索不计入形态计数，只在报告前单独说明，
    免得读的人把检索段的反爬当成正文段的。
    """
    import tax_wechat
    out = tax_wechat.search_wechat("增值税", size=5)
    urls = [i.get("url") for i in out.get("results", []) if i.get("url")]
    if not urls:
        raise SystemExit(
            "元宝检索没给出任何有效的微信正文直链，正文这一路无从量起。"
            f"顶层说明：{out.get('_error') or out.get('_partial_error') or '（无）'}；"
            "这本身就是台账要记的一条：入口不通，正文阈值就取不到。")
    print(f"前置元宝检索：取到 {len(urls)} 枚有效微信正文直链（每枚只发一次），"
          "正文判据与生产一致（落地 URL 里找 appmsgcaptcha）。")
    # allow_redirects=False 与生产同形（3.62.49 起 `read_article` 不跟随跳转）：
    # 签名地址被 302 送到非微信主机时，探针跟着跳就会把「落地不是那篇文章」读成
    # 「正常拿到 200」。
    return [("GET", u, {"headers": dict(tax_wechat.HEADERS_WX),
                        "timeout": tax_wechat.TIMEOUT, "verify": False,
                        "allow_redirects": False}) for u in urls]


def _json_shape(r):
    """200 且 Content-Type 是 JSON 才算正常；其余按"多少字节的非 JSON 正文"记形态。"""
    ctype = (r.headers.get("Content-Type") or "").lower()
    if r.status_code == 200 and "json" in ctype:
        return "200-JSON"
    if r.status_code == 200:
        return f"200-非JSON正文({len(r.content)}字节)"
    return f"HTTP {r.status_code}"


def _npc_shape(r):
    """NPC 的限流形态判据直接用生产那一份，探针不自立一套。

    生产判据是 tax_search._is_challenge_page：HTTP 200 但正文是带
    `<noscript>` 与混淆 JS 的挑战页。探针另写一份就会两处演化，台账里
    "复现"与"没复现"量的就不是同一件事。
    """
    import tax_search
    if tax_search._is_challenge_page(r):
        return f"200-挑战页({len(r.content)}字节)"
    return _json_shape(r)


def _yuanbao_shape(r):
    """元宝取数的形态判据：JSON 优先，判据全部复用生产那三份。

    复用而不是另写：`_parse_vertical_cards`（含微信直链白名单）、`_alive_ms` 与
    `SEARCH_ALIVE_MS`（熔断短接）。探针自立一套，台账里「复现」与「没复现」量的
    就不是同一件事。

    非 JSON 的回显仍按 HTML 分形，因为兜底档与拦截页都在那里落。两处旧标签被拆掉：
    「请登录后继续查看内容」在前端 chunk 里是 `getRateLimitTitle("429_outer")`
    的文案——那是**限流**，不是账号墙（旧标签「200-登录墙」把限流记成了墙，台账
    因此一直以为这两路需要登录态）；`login_page` 那枚锚才是真需要登录。
    """
    import tax_wechat
    landed = r.url or ""
    if ("/antispider/" in landed or "antip=web_hd" in landed
            or "antip=wap_hd" in landed or "antip=new_hd" in landed):
        return "跳转-antispider"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if not r.content:
        return "200-空响应(0字节)"
    try:
        payload = json.loads(r.text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        cards = payload.get("cards") or []
        if cards:
            rows, bad = tax_wechat._parse_vertical_cards(payload)
            if rows:
                return f"200-结果卡({len(rows)}张,白名单挡掉{bad})"
            return f"200-结果卡无有效直链({len(cards)}张)"
        alive = tax_wechat._alive_ms(payload)
        if alive < tax_wechat.SEARCH_ALIVE_MS:
            return f"200-通道短接(search={alive}ms)"
        return f"200-空批次(search={alive}ms)"
    if "请登录后继续查看内容" in r.text:
        return "200-限流页(429_outer)"
    if "linkid&quot;:&quot;login_page" in r.text:
        return "200-需登录"
    if tax_wechat._blocked_reason(r.text):
        return "200-验证或拦截页"
    if any(marker in r.text for marker in tax_wechat.ZERO_RESULT_MARKS):
        return "200-无结果提示"
    return f"200-既无结果卡也无提示({len(r.content)}字节)"


def _sogou_mobile_shape(r):
    """手机网页：判据逐字用生产的两把，探针不另立。

    生产把失败分成三层（`sogou_search` 里 `site-vr-none`／`_NO_RESULT_MARK`／
    「raw==0 且有结果区」那三支，3.62.43 起岛层读不出才落到最后一支）：
    302 跳反爬、200 验证页、200 有结果区但取不到直链。三层在阈值上是三件事，
    合成一层就看不出是哪一种先出现。这里不写行号——本文件与生产都在长，
    写死一次就过期（旧句那句「L487-505」到 3.62.43 已失真四十余行）。
    """
    import tax_sogou
    if tax_sogou._is_antispider_location(r):
        return f"{r.status_code}-跳转反爬"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if not r.content:
        # 空响应与"页面里没有结果区"是两件事：前者站点根本没给东西，后者给了
        # 页面但解析不出。混成一格，台账就看不出这一发到底回没回东西。
        return "200-空响应(0字节)"
    if tax_sogou._looks_like_verify_page(r.text):
        return "200-验证页"
    rows, raw, has_vrwrap = tax_sogou._parse(r.text, size=10)
    if rows:
        return f"200-结果区({len(rows)}条)"
    if has_vrwrap:
        return f"200-有结果块无直链(raw={raw})"
    return "200-无结果区无提示"


def _wechat_read_shape(r):
    """正文读取：生产判据是落地 URL（`read_article` L274），状态码全程 200。

    2026-11-23 的实测教训写在那段注释里：正文关键词判不出这道门，所以这里也只认
    落地 URL 与 `js_content`，不拿"环境异常/验证"这类文案当主判据。
    """
    if "appmsgcaptcha" in (r.url or ""):
        return f"{r.status_code}-验证码门"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if 'id="js_content"' in r.text:
        return "200-有正文容器"
    return f"200-无正文容器({len(r.content)}字节)"


TARGETS = {
    # 每条都带 record：台账里那句"记录原话"，探针回显时照抄，免得两处各写一份。
    "npc": {
        "record": "NPC 限流，并行必现",
        "endpoint": "POST https://flk.npc.gov.cn/law-search/search/list",
        "build_call": _npc_call,
        "shape": _npc_shape,
        "good": "200-JSON",
    },
    "fgk-list": {
        "record": "总局清单接口连发不限流（建闸时未取阈值）",
        "endpoint": "POST https://www.chinatax.gov.cn/getFileListByCodeId",
        "build_call": _fgk_call,
        "shape": _json_shape,
        "good": "200-JSON",
    },
    "yuanbao": {
        "record": "元宝公众号检索的限流阈值尚未量过（3.62.49 起量 POST 取数主路）",
        "endpoint": "POST https://so.qq.com/searchweb/api/search/next-page",
        "build_call": _yuanbao_call,
        "shape": _yuanbao_shape,
        "good": lambda label: label.startswith("200-结果卡("),
    },
    "sogou-mobile": {
        "record": "手机网页检索曾观察过验证页，但阈值从未量过（3.62.31 首次实测）",
        "endpoint": "GET https://m.sogou.com/web/searchList.jsp?keyword=",
        "build_call": _sogou_mobile_call,
        "shape": _sogou_mobile_shape,
        # 「正常」在这里不是一个固定串：结果条数写在标签里。good 允许是判函数，
        # 否则这一枚入口只能把形态压成"200"，台账就看不出量到了几条。
        "good": lambda label: label.startswith("200-结果区"),
    },
    "wechat-read": {
        "record": "公众号正文读取从未取过阈值（3.62.31 首次实测）",
        "endpoint": "GET https://mp.weixin.qq.com/s?...",
        "build_call": _wechat_read_call,
        "shape": _wechat_read_shape,
        "good": "200-有正文容器",
        # dry-run 不构造入口：构造就得真发一次检索（签名地址只能现场取），
        # 那就违背了「一个请求都不发」这句承诺。改为打印一份形状说明。
        "dry_run_safe": False,
        "dry_shape": ("GET", "https://mp.weixin.qq.com/s?<元宝检索现场给出的签名地址>",
                      {"headers": "tax_wechat.HEADERS_WX（手机版 UA + Referer）",
                       "timeout": 20, "verify": False}),
    },
}


def _is_good(target, label) -> bool:
    """形态是否算"放行"。good 可以是字符串，也可以是判函数。

    为什么允许判函数：手机网页那一枚的正常形态带着条数（`200-结果区(7条)`），
    写成字面量就得把条数从标签里抹掉——而台账要的恰恰是形态计数。
    """
    good = target["good"]
    return bool(good(label)) if callable(good) else label == good


def classify(target, method, url, kwargs, details):
    """发一次，把回显归成一个形态标签；异常也算一种形态，不吞。

    `details` 按标签留一份原文（首次出现时），台账要的"特征词、状态码、形态"
    就从这里抄——只留计数会把被限那天的证据压成一个词。
    """
    try:
        r = tax_http.request(method, url, **kwargs)
    except requests.RequestException as e:
        label = type(e).__name__
        details.setdefault(label, tax_http.short_reason(e))
        return label
    except Exception as e:                       # 闸超时之类的本地故障也要留名
        return f"本地-{type(e).__name__}"
    label = target["shape"](r)
    if not _is_good(target, label):
        details.setdefault(label, f"HTTP {r.status_code}，"
                                 f"{len(r.content)} 字节，"
                                 f"Content-Type {r.headers.get('Content-Type')}，"
                                 f"正文首 120 字 {r.text[:120]!r}")
    return label


def run(target, call, burst, threads, per_thread):
    # call 可以是一发，也可以是一串：正文那一路每发要用不同的签名 URL（同一枚反复取
    # 会先过期而不是先被限，两种失败不能混）。串按序号轮转，第 N 发用第 N % len 枚。
    plan = call if isinstance(call, list) else [call]
    idx = itertools.count()

    def one_call():
        return plan[next(idx) % len(plan)]

    method, url, kwargs = plan[0]
    total = burst + threads * per_thread
    if total > MAX_REQUESTS:
        raise SystemExit(
            f"请求总量 {total}（连发 {burst} + {threads} 线程 × 每线程 {per_thread}）"
            f"超过上限 {MAX_REQUESTS}。这个探针只做查询式访问的复测，不是压测；"
            f"要探更高量级请先改 MAX_REQUESTS，并在台账里写明探测到的边界。")
    print(f"数据源：{url}")
    if len(plan) > 1:
        print(f"本轮用 {len(plan)} 枚不同入口轮转，共 {total} 发")
    print("请求形状（从生产路径抓取）："
          f"{method} body={str(kwargs.get('json') or kwargs.get('data') or '')[:160]}")
    if os.getenv("TAX_SEARCH_VERIFY_SSL", "0") == "1":
        print("注：TAX_SEARCH_VERIFY_SSL=1，证书链在本机不完整，这一趟可能是连不上而不是被限。")

    details = {}
    serial = Counter()
    for _ in range(burst):
        m, u, kw = one_call()
        serial[classify(target, m, u, kw, details)] += 1

    concurrent = Counter()
    lock = threading.Lock()

    def one(_):
        m, u, kw = one_call()
        s = classify(target, m, u, kw, details)
        with lock:
            concurrent[s] += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        list(ex.map(one, range(threads * per_thread)))

    return total, serial, concurrent, details, time.time() - t0


def report(target, key, burst, threads, per_thread, serial, concurrent, details, secs):
    all_counts = serial + concurrent
    hit = sum(v for k, v in all_counts.items() if not _is_good(target, k))
    print("\n=== 台账三字段（照抄进 references/source_defects.md 的对应行）===")
    print(f"记录：{target['record']}")
    print(f"入口：{target['endpoint']}")
    print(f"最近实测日期：{date.today().isoformat()}")
    print(f"实测方法：连发 {burst} 次（0 间隔）+ {threads} 线程 × 每线程 "
          f"{per_thread} 次（共 {burst + threads * per_thread} 次，耗时 {secs:.1f} 秒）")
    print(f"当时结果：{' / '.join(f'{k}×{v}' for k, v in sorted(all_counts.items()))}"
          f"；{'未复现' if hit == 0 else f'复现 {hit} 次'}")
    print(f"      分项：串行段 {' / '.join(f'{k}×{v}' for k, v in sorted(serial.items()))}"
          f"，并发段 {' / '.join(f'{k}×{v}' for k, v in sorted(concurrent.items()))}")
    for label, detail in details.items():
        if not _is_good(target, label):
            print(f"      形态留证 {label}：{detail}")
    print(f"      复跑命令：python tests/probe_rate_limit.py --target {key} "
          f"--burst {burst} --threads {threads} --per-thread {per_thread}")
    return {"record": target["record"], "hit": hit,
            "date": date.today().isoformat(),
            "method": f"连发 {burst} 次 + {threads} 线程 × 每线程 {per_thread} 次",
            "result": " / ".join(f"{k}×{v}" for k, v in sorted(all_counts.items()))}


def main():
    ap = argparse.ArgumentParser(description="限流记录实测探针")
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    ap.add_argument("--burst", type=int, default=15, help="串行连发次数（0 间隔）")
    ap.add_argument("--threads", type=int, default=8, help="并发线程数")
    ap.add_argument("--per-thread", type=int, default=2, help="每线程请求数")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印抓到的请求形状，一个请求都不发")
    a = ap.parse_args()

    target = TARGETS[a.target]
    if a.dry_run:
        # 有的入口（正文那一路）必须先真检索一次才拿得到签名地址。dry-run 的承诺是
        # 「一个请求都不发」，所以这类入口改打印声明的形状，不去构造。
        if not target.get("dry_run_safe", True):
            method, url, kwargs = target["dry_shape"]
            print(f"[dry-run] 这一枚入口要现场检索才有地址，dry-run 不发检索。声明形状：")
            print(f"[dry-run] 将发 {method} {url}")
            print(f"[dry-run] kwargs={ {k: str(v)[:200] for k, v in kwargs.items()} }")
        else:
            plan = target["build_call"]()
            plan = plan if isinstance(plan, list) else [plan]
            for method, url, kwargs in plan:
                print(f"[dry-run] 将发 {method} {url}")
                print(f"[dry-run] kwargs={ {k: str(v)[:200] for k, v in kwargs.items()} }")
            print(f"[dry-run] 可用入口 {len(plan)} 枚轮转")
        print(f"[dry-run] 计划请求数：连发 {a.burst} + {a.threads} 线程 × {a.per_thread} "
              f"= {a.burst + a.threads * a.per_thread}（上限 {MAX_REQUESTS}）")
        return 0
    call = target["build_call"]()
    total, serial, concurrent, details, secs = run(target, call, a.burst, a.threads, a.per_thread)
    return 1 if report(target, a.target, a.burst, a.threads, a.per_thread,
                       serial, concurrent, details, secs)["hit"] else 0


if __name__ == "__main__":
    sys.exit(main())
