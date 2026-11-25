"""人民法院案例库墙位复测（3.62.30 档案用）：匿名逐发，输出 JSON 到 stdout。

用法：
    python probe_rmfyalk_wall.py            # 全部十发
    python probe_rmfyalk_wall.py --quick    # 只发四枚核心接口

照 NOTE.md 第二节逐发间隔 2.6 秒（一发一停），不并发、不重试。
只有 recordSearchLog 用真 401，其余匿名一律 200 + {"msg":"未登录","code":401}；
形状变了（不再是这一句）就说明墙变了，更新台账与本目录。
"""
import io
import json
import sys
import time
from urllib import parse

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://rmfyalk.court.gov.cn"
GAP = 2.6

SEARCH_BODY = {
    "page": 1,
    "size": 10,
    "lib": "qb",
    "searchParams": {
        "userSearchType": 1,
        "isAdvSearch": "0",
        "selectValue": "qw",
        "lib": "cpwsAl_qb",
        "sort_field": "",
    },
}


def shot(label, method, url, body=None, headers=None):
    if method == "POST":
        r = requests.post(url, json=body, headers=headers or {}, timeout=20)
    else:
        r = requests.get(url, headers=headers or {}, timeout=20)
    text = r.text.strip()
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = None
    print(json.dumps({
        "label": label,
        "status": r.status_code,
        "bytes": len(r.content),
        "ct": r.headers.get("Content-Type", ""),
        "body": (text[:120] if payload is None else payload),
    }, ensure_ascii=False))
    time.sleep(GAP)


def main():
    quick = "--quick" in sys.argv
    shot("search 默认", "POST", BASE + "/cpws_al_api/api/cpwsAl/search", dict(SEARCH_BODY))
    body = dict(SEARCH_BODY)
    body["searchParams"] = dict(body["searchParams"], keyTitle=["增值税"], selectValue=["qw"])
    shot("search 增值税", "POST", BASE + "/cpws_al_api/api/cpwsAl/search", body)
    if quick:
        return
    shot("searchTop10", "POST", BASE + "/cpws_al_api/api/cpwsAl/searchTop10",
         {"keyword": "增值税", "size": 10})
    shot("getGroupDatas tjb", "POST", BASE + "/cpws_al_api/api/cpwsAl/getGroupDatas",
         {"flag": "tjb"})
    shot("recordSearchLog", "POST", BASE + "/cpws_al_api/api/user/recordSearchLog",
         {"keyword": "增值税"})
    shot("getGdLoginUrl", "POST", BASE + "/cpws_al_api/api/user/getGdLoginUrl", {})
    shot("getUserInfo", "POST", BASE + "/cpws_al_api/api/user/getUserInfo", {})
    shot("首页", "GET", BASE + "/")
    shot("列表页", "GET", BASE + "/view/list.html")
    print(json.dumps({"query": parse.urlparse(BASE).netloc, "gap": GAP},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
