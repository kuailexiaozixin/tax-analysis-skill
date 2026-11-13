#!/usr/bin/env python3
"""有界复测 fgk 详情端点（fgk.chinatax.gov.cn/.../content.html）的并发容忍度。

只读、查询式复测，不是压测：串行 4 次 + 4 线程并发 4 次，共约 8 次 GET。
用生产路径 tax_fgk.fetch_fgk_body 本身发请求（含 attempt 重试与 TLS 熔断），
按 body_status 与 _attempts 逐项计数，回吐台账三字段所需的形态计数。
"""
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import tax_http  # noqa: E402
import tax_fgk as F  # noqa: E402

# 台账与 source_defects 里实测出现过的详情页标识对（栏目段/文章段）。
PAIRS = [("c100009", "c5193055"), ("c100024", "c5245218"),
         ("c100009", "c5193058"), ("c100009", "c5237365")]
URLS = [F.fgk_detail_url(c, a) for c, a in PAIRS]


def one(url):
    t0 = time.monotonic()
    out = F.fetch_fgk_body(url)
    dt = (time.monotonic() - t0) * 1000
    return {"url": url, "body_status": out.get("body_status"),
            "bytes": len(out.get("content", "") or ""),
            "attempts": len(out.get("_attempts") or []),
            "error": out.get("_error", ""), "ms": round(dt, 1)}


def reset_tls():
    tax_http._tls_blocked.clear()
    tax_http._tls_streak.clear()


def summarize(label, rows):
    shapes = Counter(r["body_status"] for r in rows)
    total_attempts = sum(r["attempts"] for r in rows)
    print(f"\n[{label}] body_status 形态计数：" +
          "、".join(f"{k}×{v}" for k, v in sorted(shapes.items())))
    print(f"  共发请求 {total_attempts} 次（含重试）；逐条：")
    for r in rows:
        print(f"    {r['body_status']:7} bytes={r['bytes']:6} "
              f"attempts={r['attempts']} ms={r['ms']:7} {r['url']}")
        if r["error"]:
            print(f"      error: {r['error']}")
    return shapes


print("目标主机：fgk.chinatax.gov.cn（详情页 GET，生产路径 fetch_fgk_body）")
print(f"请求预算：串行 {len(URLS)} + 并发 {len(URLS)}（4 线程）≈ {2*len(URLS)} 次 GET")

reset_tls()
t0 = time.monotonic()
serial = [one(u) for u in URLS]
serial_secs = time.monotonic() - t0
s_shapes = summarize("串行 4 次", serial)
print(f"  串行墙钟 {serial_secs:.2f}s")

reset_tls()
t0 = time.monotonic()
with ThreadPoolExecutor(max_workers=4) as ex:
    concurrent = list(ex.map(one, URLS))
conc_secs = time.monotonic() - t0
c_shapes = summarize("4 线程并发 4 次", concurrent)
print(f"  并发墙钟 {conc_secs:.2f}s")

print("\n=== 判读 ===")
print(f"串行形态 {dict(s_shapes)}；并发形态 {dict(c_shapes)}")
bad = {"error"}
conc_bad = sum(v for k, v in c_shapes.items() if k in bad)
ser_bad = sum(v for k, v in s_shapes.items() if k in bad)
print(f"error 计数：串行 {ser_bad}、并发 {conc_bad}")
if conc_bad > ser_bad:
    print("结论：并发比串行多出取失败 → 疑似限流，保持串行，登记边界。")
elif conc_secs < serial_secs * 0.7 and conc_bad == 0:
    print("结论：并发无新增失败且墙钟明显下降 → tolerates 并发，可改有界并发。")
else:
    print("结论：并发未显著提速或网络不可用 → 据实登记，不盲改。")