"""中国裁判文书网墙位复测（3.62.30 档案用）：匿名逐发，输出 JSON 到 stdout。

用法：
    python probe_wenshu_wall.py            # 全部八发
    python probe_wenshu_wall.py --quick    # 只发 rest.q4w 那一族

照 NOTE.md 第二节逐发间隔 2.6 秒。匿名读数应当是：
  - rest.q4w 一律 200 / 76 字节 {"code":9,…,"success":false}（带不带参数同形）；
  - 三枚 /api/fp/* 一律 200 / **0 字节**（空响应，不是 JSON）；
  - /down/isDown 200 / 53 字节 code:1。
一旦 rest.q4w 开始回 code=0 或字节数变了，说明墙或参数族变了，更新台账与本目录。
"""
import io
import json
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://wenshu.court.gov.cn"
GAP = 2.6
PARSE_URL = BASE + "/website/parse/rest.q4w"


def shot(label, method, url, data=None):
    if method == "POST":
        r = requests.post(url, data=data, timeout=20)
    else:
        r = requests.get(url, timeout=20)
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
    shot("rest.q4w 空 body", "POST", PARSE_URL, "")
    shot("rest.q4w 只带 construct", "POST", PARSE_URL,
         "construct=271a5cfb&WebSiteID=181107ANFZ0BXSK4&type=search")
    shot("rest.q4w 带明文假 ciphertext", "POST", PARSE_URL,
         "construct=271a5cfb&ciphertext=01000110&queryCondition={\"s1\":\"增值税\"}"
         "&pageNum=1&pageSize=10&sortFields=s50:desc")
    if not quick:
        shot("rest.q4w GET", "GET", PARSE_URL)
        for name in ("ah", "cprq", "gjjsClick"):
            shot("/api/fp/%s" % name, "POST", BASE + "/api/fp/%s" % name, "keyword=增值税")
        shot("/down/isDown", "POST", BASE + "/down/isDown", "docId=")
        shot("检索页", "GET", BASE + "/website/wenshu/181217BMTKHNT2W0/index.html")


if __name__ == "__main__":
    main()
