---
name: fgk
description: 国家税务总局政策法规库（fgk.chinatax.gov.cn）检索清单与取正文。翻页基准、文件类标签收窄、正文编码这三个坑都在这里。当用户要现行有效的规章/公告/办法原文，或要按发文字号回库核实某个文件时用。
---

# fgk 法规库（scripts/tax_fgk.py）

站点形状与实测读数在 `search_source/fgk/NOTE.md`：第一节讲清单与正文的形态，第二节讲翻页基准，第三节讲收窄维度，第四节是复测入口。

## 工作流

1. **检索清单**：`python scripts/tax_fgk.py "关键词" --size 10`。交回清单（标题/文号/日期/URL），默认只在文件类标签里搜（第三节）。
2. **取正文**：加 `--body` 现拉。正文**永不缓存**——条文必须每次现拉，避免把已废止或被修订的旧条文当现行有效引用。这一条是本模块与其它检索模块最大的口径差。
3. **翻页**：默认自适应——连续 3 页没捞到新的法规库条目就收尾；要严格翻满给 `--pages N`（关掉自适应）。
4. **收窄维度**：`--effect`（效力位阶）等按 `add_filter_args` 的清单发。范围键由 `filters_token` 与 `scope_token` 收进缓存键：白名单关掉（`--all-labels`）之后同一检索词回的是另一个集合的排序，两种清单绝不共用一条缓存。

## 这一层负责什么、不负责什么

- 负责：法规库清单、单篇正文、按 `articleId` 查关联文件（`queryManuscriptAssociation`）。
- 不负责：时效性与权威性判定。正文里写的"有效"只是站点字段，定级口径走 `references/evidence_grading.md`。
- 与 `search_source/chinatax` 的分工：那本子技能管总局站内 search5（`scripts/tax_web_search.py`，pageNum 从 0 起算）；本模块的 page 从 1 起算。两本基准混过一次，实测读数记在 `search_source/fgk/NOTE.md` 第二节。

## 命令依赖

- `python scripts/tax_fgk.py --help`
- 文号到官方链接的那枚缓存（`scripts/tax_cited.py`）默认把本库当回库目标；命中前先拿缓存里存着的标题现判同一性，判不过就丢弃缓存照常检索。
