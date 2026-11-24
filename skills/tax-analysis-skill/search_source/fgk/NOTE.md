# fgk 法规库站点形状与实测读数

本文件只记实测到的形状。工作流与命令口径在 `search_source/fgk/SKILL.md`。

## 一、清单页与正文的形态

- 站点：`fgk.chinatax.gov.cn`，与总局站内检索同域不同路。清单接口交回的每条带标题、发文字号、日期、正文地址与 `articleId`。
- **正文不在"看起来的容器"里，问题出在编码不在渲染。** 详情页的 HTML 不声明 charset，requests 按 HTTP 头的 ISO-8859-1 解码，于是中文全成乱码，读起来像"正文没在 HTML 里"（检索词在原文里 0 次命中）。把字节流显式按 UTF-8 解就拿到完整正文。
- 正文容器两枚：注释类页面在 `<div class="zscont">`，法规正文在 `<div class="arc_cont">`。正文内的法规名带 `<a href>` 指向关联文件。
- 页面头部 meta 带 `ArticleTitle`、`PubDate`、`ContentSource`、`articleId`；`articleId` 是关联文件接口 `queryManuscriptAssociation` 的入参。

## 二、翻页基准与 pageSize 上限

- 接口把 `pageSize` 卡在 10：实测传 20/60/100 一律只回 10 条，所以只能按页取。
- **两本翻页基准，别混用。** 本模块（`scripts/tax_fgk.py`）的 `page` 从 **1** 起算；总局站内 search5（`scripts/tax_web_search.py`，见 `search_source/chinatax/SKILL.md`）的 `pageNum` 从 **0** 起算。
- 基准用错时的实测很隐蔽：检索「特别纳税调整实施办法」，按 1 起算发出去取回的是真实的第二屏，目标文件落在第 5 屏；按 0 起算后它就是第一屏的首条。清单不为空、看起来一切正常，只是少了一屏——这类错不会报错，只会让"没找到"变成结论。
- 自适应收尾：连续 `IDLE_PAGE_LIMIT`(3) 页没捞到新的法规库条目就停。范围已经是文件类标签，还连着几页空手，剩下的只是沾词的别的文件。给 `--pages N` 则关掉自适应严格翻满。

## 三、收窄维度：文件类标签与缓存键

- 检索范围默认锁在文件类标签（`tax_web_search.FILE_LABELS`），不是全站。这一维决定翻页窗口里装的是什么：
  - 「转让定价」按全站取，前 3 屏一条法规库条目都没有（全是新闻与各地动态，自适应就此收尾，得 0 条）；收窄到文件类标签后 18 条命中全部取回。
  - 「小微企业」全站 4822 条、首屏十条无一条是文件；收窄后 184 条。
- 代价写明白：会漏掉标在「视频政策解读」「图片政策解读」上的法规库条目——那些页面回的是 `media_only` 空正文，本来就引不了条文。要连它们一起搜，命令行给 `--all-labels`。
- 缓存键分两维：`filters_token` 收收窄维度（分号分隔、按字典序，避开 `CacheManager._key` 里 join 用的竖线，也保证写入顺序不影响键值）；`scope_token` 收非默认范围（`labels=all`、`order=` 段），默认范围回 `LIST_KEY_REV` 那一条键，只有偏离默认才另立键。理由：白名单关掉之后同一检索词回的是另一个集合的排序，两种清单绝不能共用一条缓存。
- 只缓存清单（标题/文号/日期/URL），**正文永不缓存**。条文必须每次现拉，避免把已废止或被修订的旧条文当现行有效引用。`--cache` 开清单缓存（TTL 1h），`--cache-stats` / `--cache-clear` 查看与清空。

## 四、复测入口

- 单条清单与正文：`python scripts/tax_fgk.py "研发费用" --size 10` / `python scripts/tax_fgk.py "资产评估减值" --size 1 --body`。
- 严格翻页：`python scripts/tax_fgk.py "转让定价" --size 3 --pages 8`。
- 全站范围对照（看收窄代价）：给 `--all-labels` 再跑一次同一检索词，比对条数与文件占比。
- 限流与闸的复测走 `python tests/probe_rate_limit.py --target fgk-list`；台账见 `references/source_defects.md` 的「限流记录的实测台账」。
