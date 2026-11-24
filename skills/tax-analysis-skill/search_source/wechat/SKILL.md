---
name: wechat
description: 微信公众号文章检索与取正文（weixin.sogou.com 检索 + mp.weixin.qq.com 正文）。当用户要找实务口径、官方解读、或只有公众号发过全文的那类内容时用。跳转链还原、反爬与限流形状都在这里。
---

# 微信公众号（scripts/tax_wechat.py）

站点形状与实测读数在 `search_source/wechat/NOTE.md`：第一节三段流程，第二节判据与阈值，第三节复测入口。

## 工作流

1. **检索**：`python scripts/tax_wechat.py "研发费用加计扣除" --size 5`。只要候选清单时用这一步。
2. **取正文**：加 `--read`（可配 `--json`）。这一步会额外发若干请求（还原直链 + 逐篇取正文），单批还原的篇数有上限，见第二节。
3. **判空**：返回的 `error` 与命中数要一起看。"零命中"与"被反爬"在页面上是两种形状，本源分开报，读到「没有」之前先看有没有报反爬。

## 这一层负责什么、不负责什么

- 负责：公众号文章的候选清单、真实地址还原、正文抽取。
- **本源是"实务解读"层，权威性低于 NPC 法规与税务总局原文。** 公众号里的说法不能当作现行依据交回；引它只能作为线索，找到原文那一路再定级（`references/evidence_grading.md`）。
- 与 `search_source/sogou` 的分工：那本子技能管 `m.sogou.com` 网页检索；本模块管 `weixin.sogou.com` 公众号检索。两把闸是分开的，读数也不通用。

## 命令依赖

- `python scripts/tax_wechat.py --help`
- 限流与闸的存废判定读 `references/source_defects.md` 的「限流记录的实测台账」——微信正文那一路至今没有阈值读数，那行记录本身就是边界声明。
