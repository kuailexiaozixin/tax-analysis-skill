# -*- coding: utf-8 -*-
"""NPC（flk）分页与 total 换值的常驻复测探针。

为什么要有这一枚（2026-11-26）：NOTE 第三节原话「这一层没有固定探针脚本，
复测按逐枚重发走」——那轮复量把 NOTE 自认的两处空档补掉了：
  1. 「6—9 那一档没取」⇒ 实测分界落在 5 与 6 之间（1—5 一档、6 及以上一档）；
  2. 换值不只是 total 数字变：**整个结果集换**（低档首屏全「法律」、高档混入
     行政法规与地方法规，两档首屏交集只有 1/5），且生产 `search_tax` 的
     加宽第二发（pageSize=max(size*3,20)）落在高档那份集合上、而报出去的
     total 取的是主发那一档。
本探针把这两层按固定档位重发，供下一轮比对「两边都换数就是上游动了索引」。

纪律：
- 一律经生产 `tax_search._request`（同一把串行闸、0.6 秒最小间隔、退避重试），
  每发之间再睡 `GAP` 秒；`MAX_REQUESTS` 超了直接退出并返回 2。
- `--dry-run` 只列计划不发请求，输出里声明「台账不得据此更新」。
- 运行结果只是当日读数：要写进 NOTE/台账，就整段贴回显并带当日日期，
  不要只抄本探针的分组结论。
"""
import argparse
import json
import sys
import time
import pathlib

try:  # 本机 pwsh 是 GBK：中文与 ⇒ 这类符号必须先转 UTF-8 才打得出来
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
import tax_search          # noqa: E402
import tax_http            # noqa: E402

WORD = "环境保护"
GAP = 15.0
MAX_REQUESTS = 20
# 十二档梯子 + 精确两档 + 单字两档 = 16 发
LADDER = [1, 2, 3, 4, 5, 6, 10, 20, 30, 40, 50, 100]
EXTRA_SHOTS = [("精确", 1, WORD, 5), ("精确", 1, WORD, 10),
               ("单字模糊", 2, "税", 5), ("单字精确", 1, "税", 5)]


def payload(content, stype, size):
    return {"searchRange": 1, "searchType": stype, "searchContent": content,
            "pageNum": 1, "pageSize": size, "orderByParam": {},
            "flfgCodeId": [], "zdjgCodeId": [], "sxx": [3], "gbrq": [],
            "sxrq": [], "gbrqYear": [], "xgzlSearch": False}


def shot(content, stype, size):
    r = tax_search._request("POST", tax_search.BASE_URL + "/law-search/search/list",
                            json=payload(content, stype, size))
    d = r.json()
    tax_http.require_npc_ok(d)
    outer = d.get("data", d)
    rows = outer.get("rows") or []
    return {"http": r.status_code, "bytes": len(r.content),
            "total": outer.get("total"), "rows": len(rows),
            "echo_st": outer.get("searchType"),
            "keys0": sorted(rows[0].keys()) if rows else [],
            "kinds": [x.get("flxz") for x in rows],
            "bbbs": [x.get("bbbs") for x in rows]}


def main(dry=False):
    plan = [("模糊", 2, WORD, s) for s in LADDER] + EXTRA_SHOTS
    print("取样口径：检索词「%s」×现行有效，逐键照 NOTE 第二节那串；"
          "经生产 tax_search._request，每发间隔 %g 秒。" % (WORD, GAP))
    print("计划 %d 发 = 梯子 %d 档 %s + 对照 %d 发；MAX_REQUESTS=%d"
          % (len(plan), len(LADDER), LADDER[:3] + ["…"], len(EXTRA_SHOTS), MAX_REQUESTS))
    if dry:
        print("--dry-run：以上只是计划，台账不得据此更新。")
        return 0
    if len(plan) > MAX_REQUESTS:
        print("计划 %d 发超过 MAX_REQUESTS=%d，拒绝执行。" % (len(plan), MAX_REQUESTS))
        return 2

    shots = []
    for i, (sname, stype, content, size) in enumerate(plan):
        if i:
            time.sleep(GAP)
        d = shot(content, stype, size)
        shots.append({"name": sname, "stype": stype, "content": content,
                      "size": size, **d})
        print("[%02d] %-6s searchType=%d pageSize=%-3d total=%-6s rows=%-3d "
              "bytes=%-6d" % (i + 1, sname, stype, size, d["total"], d["rows"],
                              d["bytes"]))

    print("\n[A] 按 total 分组（只对模糊梯子）")
    groups = {}
    for s in shots:
        if s["stype"] == 2 and s["content"] == WORD:
            groups.setdefault(s["total"], []).append(s["size"])
    for total, sizes in sorted(groups.items()):
        print("   total=%s ← pageSize %s" % (total, sorted(sizes)))

    low = shots[0]
    print("\n[B] rows[0] 的键（第一发）：%s" % low["keys0"])
    print("   「flfgname」在不在：%s" % ("flfgname" in low["keys0"]))

    print("\n[C] 门类构成（低档第一发 vs 高档第一发）")
    print("   ps=1 门类=%s" % low["kinds"])
    high = next(s for s in shots if s["stype"] == 2 and s["size"] == 6)
    print("   ps=6 门类=%s" % high["kinds"])
    inter = set(low["bbbs"]) & set(high["bbbs"])
    print("   两档首屏交集 %d/%d" % (len(inter), len(low["bbbs"])))

    print("\n[D] 精确对照与单字对照（回显 searchType 一并打印）")
    for s in shots[-4:]:
        print("   %-6s 「%s」ps=%d ⇒ total=%s 回显searchType=%s"
              % (s["name"], s["content"], s["size"], s["total"], s["echo_st"]))

    print("\nJSON: " + json.dumps(
        {"groups": {str(k): v for k, v in groups.items()},
         "keys0": low["keys0"], "flfgname_present": "flfgname" in low["keys0"],
         "inter": len(inter)},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只列计划，不发请求；输出声明台账不得据此更新")
    raise SystemExit(main(ap.parse_args().dry_run))
