---
name: netpaper
description: 中国税务报网络报（数字报，www.ctaxnews.net.cn）按日期取版与关键词扫版。这一站没有站内检索接口，只能逐日扫版面；版面号、栏目漂移、图片稿、与中国税网同稿异题这些形状都在这里。要找报纸口径的税案报道或某天的整版内容时用。
---

# 中国税务报网络报（scripts/tax_paper.py）

站点形状与全部实测读数在 `search_source/netpaper/NOTE.md`：第一节地址形状与出版日历，第二节抽取（正文、标题、图片稿），第三节讲为什么只能扫版面，第四节与中国税网的重叠裁定，第五节复测入口。

## 工作流

1. **取整版**：`python scripts/tax_paper.py --date 2026-11-24 --edition 6`。交回那一版当天的全部文章（标题、地址、日期、正文）。
2. **关键词扫版**：`python scripts/tax_paper.py "虚开" --days 10 --editions 6,7`。**这不是站内检索**——它逐日取版面、在本地比文，所以成本随天数与版面数线性涨；默认只扫第 6 版，要全报传 `--editions 1,2,3,4,5,6,7,8`。
3. **先看哪些天出报**：`python scripts/tax_paper.py --list-days --from 2026-11-16 --to 2026-11-24`，只回真正有报的日子，省掉白扫。
4. **读到空命中时**：输出里固定带扫了哪几天、哪些天没出报、哪些天取数失败。**没命中不等于报上没有**，那三行读数决定这句"没有"值多少。

## 这一层负责什么、不负责什么

- 负责：按日期取版、按关键词扫版、图片稿标记、正文与图注分开交回。
- **不参与多源聚合**（不在 `DEFAULT_SOURCES` 六源里）。理由不是性能：同一篇稿在本报与中国税网常用两副标题（全题与半题），而聚合层按标题字符相似度去重，进了聚合就会把两条不同地址的稿子错并成一条。实测读数在 `search_source/netpaper/NOTE.md` 第四节。
- 报纸是媒体口径，不是依据。报道里提到的政策要回到 NPC 或税务总局原文再定级（`references/evidence_grading.md`）。

## 命令依赖

- `python scripts/tax_paper.py --help`
- 服务入口：`POST /api/paper`（`date` 与 `keyword` 二选一）；三仓侧 `tax-doc papers` / MCP 工具 `read_tax_paper`。
