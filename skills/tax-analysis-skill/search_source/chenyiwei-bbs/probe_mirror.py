#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chenyiwei-bbs 子技能的复测探针：镜像声明与端点可用性。不联网的用例不碰这个文件。

为什么要有这一枚：这个目录里没有生产脚本，它的全部价值就是那份从上游取来的
`SKILL.md` 加 `NOTE.md` 的实测校正。2026-11-26 之前，NOTE 里那句「与上游字节一致」
从来没有被任何可复跑的东西量过——`tests/test_subskill_selfcontained.py` 的哈希守卫
只核对「盘上这份 == NOTE 声明的那串」，管不到上游今天还回不回同一份字节。结果就是
NOTE 教的同步动作（`curl -o` 直接覆盖）会把一份**更全**的文档换成一份**更旧**的。

本探针干两件事：
  1. 取上游那份，与盘上这份逐字节比，报出行数/字节/哈希与差异行数；
  2. 把两份文档接口表里出现的每一枚端点各发一发，记下今天的状态码与顶层键。

请求数固定 1 + len(ENDPOINT_PROBES)，上限 MAX_REQUESTS；超出直接拒跑。
读数写进 stdout，NOTE.md 的「实测校正」引用的是本文件某一次的输出。
"""
import sys
import time
import json
import hashlib
import pathlib
import argparse

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
MIRROR = HERE / "SKILL.md"
BASE = "https://bbs.auditdog.cn"
UPSTREAM_PATH = "/chenyiwei-skill/SKILL.md"
MAX_REQUESTS = 20
GAP = 1.5
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "*/*"}

# 每一枚端点配一发具体入参——入参是 2026-11-26 那轮从真返回里取出来的（tid 5498231
# 来自 ref-posts?slug=cas-33 的首条），不是编的。换 slug/tid 时这里要一起换。
ENDPOINT_PROBES = [
    ("/api/public/recent", {"days": 3}),
    ("/api/public/search", {"q": "收入确认"}),
    ("/api/public/detail", {"link": "https://bbs.esnai.cn/thread-5498231-1-1.html"}),
    ("/api/public/related", {"tid": "5498231"}),
    ("/api/public/tags", {}),
    ("/api/public/by-tag", {"name": "合并报表", "sort": "time"}),
    ("/api/public/references", {"tid": "5498231"}),
    ("/api/public/ref-posts", {"slug": "cas-33", "page": 1}),
    ("/api/public/topics", {}),
    ("/api/public/topic", {"slug": "hebing-baobiao", "page": 1}),
    ("/api/learn/search", {"q": "长期股权投资的处置"}),
    ("/api/public/ref/cas-33", {}),
    ("/api/public/penalties", {"year": 2025}),
]


def get(path, params=None):
    t0 = time.time()
    try:
        r = requests.get(BASE + path, params=params or None, headers=HDRS, timeout=25)
    except Exception as e:  # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}
    out = {"status": r.status_code, "bytes": len(r.content), "content": r.content,
           "ctype": r.headers.get("Content-Type"), "secs": round(time.time() - t0, 1)}
    try:
        out["json"] = r.json()
    except Exception:  # noqa: BLE001
        out["text"] = r.text[:160]
    return out


def top_keys(j):
    return ",".join(sorted(j.keys())) if isinstance(j, dict) else "(非对象)"


def type_of_counts(j):
    """分页字段的实际类型——NOTE 里那条「penalties 的分页字段是字符串」就靠这里复算。"""
    if not isinstance(j, dict):
        return ""
    bits = []
    for k in ("total", "page", "pageSize", "count"):
        if k in j:
            bits.append("%s=%r(%s)" % (k, j[k], type(j[k]).__name__))
    return " ".join(bits)


def declared_in(text):
    """文档接口表里出现过的端点路径集合（`| /api/... |` 那种行）。"""
    out = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and "/api/" in s:
            for tok in s.split("|")[1:]:
                t = tok.strip().strip("`")
                if t.startswith("/api/"):
                    out.add(t.split("{")[0].rstrip("/") or t)
    return out


def main(dry=False):
    disk = MIRROR.read_bytes()
    disk_text = disk.decode("utf-8", "replace")
    total = 1 + len(ENDPOINT_PROBES)
    print("取样日期：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("方法：上游 %s%s 一发 + 端点逐枚各一发，共 %d 发（上限 %d），间隔 %.1f 秒；"
          "全部只发 HTTP，零模型调用。" % (BASE, UPSTREAM_PATH, total, MAX_REQUESTS, GAP))
    if dry:
        print("（--dry-run：只列计划，不发请求，台账不得据此更新）")
        for p, params in ENDPOINT_PROBES:
            print("  GET %s%s %s" % (BASE, p, json.dumps(params, ensure_ascii=False)))
        return 0
    if total > MAX_REQUESTS:
        print("计划 %d 发超过上限 %d，先改 MAX_REQUESTS 并同步 NOTE.md 的请求数。" % (total, MAX_REQUESTS))
        return 2

    print("\n== [1] 上游那份与盘上这份")
    print("  盘上 %d 字节 %d 行 sha256=%s"
          % (len(disk), len(disk_text.splitlines()), hashlib.sha256(disk).hexdigest()))
    d = get(UPSTREAM_PATH)
    if "err" in d:
        print("  上游取不到：%s —— 这一发失败，[1] 的比对没有读数" % d["err"])
        up_text = None
    else:
        ub = d["content"]
        up_text = ub.decode("utf-8", "replace")
        print("  上游 HTTP %s %d 字节 %.1fs ctype=%s"
              % (d["status"], len(ub), d["secs"], d["ctype"]))
        ul = up_text.splitlines()
        print("  上游 %d 字节 %d 行 sha256=%s" % (len(ub), len(ul), hashlib.sha256(ub).hexdigest()))
        print("  与盘上逐字节相同? %s" % (ub == disk))
        dl = disk_text.splitlines()
        diff = sum(1 for i in range(max(len(ul), len(dl)))
                   if (ul[i] if i < len(ul) else None) != (dl[i] if i < len(dl) else None))
        print("  逐行不同的行数=%d（行数 %d vs %d）" % (diff, len(ul), len(dl)))
        de, dd = declared_in(up_text), declared_in(disk_text)
        print("  接口表端点数 上游=%d 盘上=%d" % (len(de), len(dd)))
        print("  盘上有而上游没有的：%s" % (",".join(sorted(dd - de)) or "无"))
        print("  上游有而盘上没有的：%s" % (",".join(sorted(de - dd)) or "无"))
    time.sleep(GAP)

    print("\n== [2] 端点逐枚可用性（今天还认不认）")
    rows = []
    for p, params in ENDPOINT_PROBES:
        r = get(p, params)
        if "err" in r:
            print("  %-26s 请求失败 %s" % (p, r["err"]))
            rows.append((p, "err", r["err"]))
            time.sleep(GAP)
            continue
        j = r.get("json")
        err = j.get("error") if isinstance(j, dict) else None
        print("  %-26s HTTP %s %6d 字节 %5.1fs 顶层=%s%s"
              % (p, r["status"], r["bytes"], r["secs"], top_keys(j),
                 ("  error=%r" % err) if err else ""))
        tc = type_of_counts(j)
        if tc:
            print("      %s" % tc)
        if isinstance(j, dict):
            res = j.get("results") or j.get("items") or j.get("refs") or j.get("topics") or j.get("groups")
            if isinstance(res, list):
                print("      条数=%d%s" % (len(res),
                      ("  首条键=" + ",".join(sorted(res[0].keys()))) if res and isinstance(res[0], dict) else ""))
        rows.append((p, r["status"], top_keys(j)))
        time.sleep(GAP)

    print("\n== [3] 汇总")
    dead = [p for p, st, _ in rows if isinstance(st, int) and st >= 400]
    print("  今天非 2xx 的端点：%s" % (",".join(dead) or "无"))
    print("  盘上接口表共 %d 枚端点，本轮逐枚量过 %d 枚"
          % (len(declared_in(disk_text)), len(ENDPOINT_PROBES)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="chenyiwei-bbs 镜像与端点复测")
    ap.add_argument("--dry-run", action="store_true", help="只列计划，不发请求")
    sys.exit(main(dry=ap.parse_args().dry_run))
