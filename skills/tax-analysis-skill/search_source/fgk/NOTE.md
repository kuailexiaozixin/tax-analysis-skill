# fgk 法规库站点形状与实测读数

本文件只记实测到的形状。工作流与命令口径在 `search_source/fgk/SKILL.md`。

每条断言后面都跟着量它的那一天；没有日期的句子等于没量过，不要照着办事。
2026-11-26 这一轮把全篇没有日期的那些「实测」重新量了一遍（`.tmp-inspect\
probe34a-run.txt`、`probe34b-run.txt`、`probe34c-run.txt`、`probe34d-run.txt`、
`probe34e-run.txt`），量到的都写在下文，与旧记录不同的地方把两个数一起留着。

## 一、清单页与正文的形态

- 站点：`fgk.chinatax.gov.cn`，与总局站内检索同域不同路。清单接口交回的每条带标题、发文字号、日期、正文地址与 `articleId`。
- **正文不在"看起来的容器"里，问题出在编码不在渲染。** 详情页的 HTML 不声明 charset（2026-11-26 实测两份详情页的 `Content-Type` 都是光秃秃的 `text/html`，requests 于是按 HTTP 头默认的 ISO-8859-1 解码），于是中文全成乱码，读起来像"正文没在 HTML 里"（检索词在原文里 0 次命中）。把字节流显式按 UTF-8 解就拿到完整正文。
  - 2026-11-26 的对照控件：取「特别纳税调整实施办法」与「研发费用加计扣除」各一条详情页，用**每条自己的标题前 8 字**当探针词（标题一定在页面里，才不会把"词不在文里"误读成"编码坏了"）。两发的 `r.encoding` 都是 `ISO-8859-1`、默认解码查自己的标题都是 False、按 UTF-8 解都是 True。前一版这里写的"检索词 0 次命中"是拿一条文件去查另一个词，控件用错，读数作废过重（`probe34b-run.txt`）。
- 正文容器两枚：注释类页面在 `<div class="zscont">`，法规正文在 `<div class="arc_cont">`。正文内的法规名带 `<a href>` 指向关联文件。
  - 2026-11-26 量到两枚容器**不是每页都有**：那份通知里 zscont 开标签在 @15621、arc_cont 在 @16501，两枚都在；「研发费用加计扣除项目鉴定案例」那页**只有 arc_cont、没有 zscont**。所以"注释在 zscont"是"注释类页面才有"，不是"每页两枚都找"。生产按这个形状分两路（`tax_fgk.fetch_fgk_body` 的 zscont/arc_cont 两支，只有 arc_cont 时走后者），两份详情页交回的 `body_status` 都是 `ok`、正文长度 22238 与 3520，都命中自己的标题。
- 页面头部 meta 带 `ArticleTitle`、`PubDate`、`ContentSource`、`articleId`；`articleId` 是关联文件接口 `queryManuscriptAssociation` 的入参。
  - 2026-11-26 那份通知的 meta 里 `articleId='5194010'`，与 URL 末段 `c5194010` 只差一个 c 前缀。**接口吃的是不带 c 的纯数字**：发 `5194010` 回 146976 字节、`policyDocument` 7 条；发 `c5194010` 回 56 字节空壳。生产的 `article_id_from_url` 用 `/c(\d+)/content\.html` 抠捕获组，交出来就是纯数字，形状对（`test_article_id_from_url_forms`）。

## 二、翻页基准与 pageSize 上限

- 接口把 `pageSize` 卡在 10：实测传 20/60/100 一律只回 10 条，所以只能按页取。
  - 2026-11-26 复核：「研发费用加计扣除」发 size=10/20/60/100 四回，交回条数恒 10、`total` 恒 62；另用原始 `pageSize=100` 直打 search5，`searchTotal` 数组仍是 10 行。这一条成立，不是生产自己截断的。
- **两本翻页基准，别混用。** 本模块（`scripts/tax_fgk.py`）的 `page` 从 **1** 起算；总局站内 search5（`scripts/tax_web_search.py`，见 `search_source/chinatax/SKILL.md`）的 `pageNum` 从 **0** 起算。
- 基准用错时的实测很隐蔽：检索「特别纳税调整实施办法」，按 1 起算发出去取回的是真实的第二屏，目标文件落在第 5 屏；按 0 起算后它就是第一屏的首条。清单不为空、看起来一切正常，只是少了一屏——这类错不会报错，只会让"没找到"变成结论。
  - 2026-11-26 复核这一维的三枚数（`probe34c-run.txt`）：原始 `pageNum=0` 与 `pageNum=1` 各回 10 与 6 行、两屏 url 交集 **0** 枚；生产 `page=1` 交回的 10 条与原始 `pageNum=0` 那屏交集 **10/10**——减 1 这一步是对的。目标文件「特别纳税调整实施办法（试行）」就在第 0 屏首条，文号 `国税发〔2009〕2号`。旧句"按 1 起算取回的是真实的第二屏"这一轮没重造（要故意发错基准才能看到，本轮没发错的那一档）。
- 自适应收尾：连续 `IDLE_PAGE_LIMIT`(3) 页没捞到新的法规库条目就停。范围已经是文件类标签，还连着几页空手，剩下的只是沾词的别的文件。给 `--pages N` 则关掉自适应严格翻满。
  - 2026-11-26 复核：`_scan_list("转让定价", 30, 8, adaptive=True, file_only=False)` 交回 results=0、total_hits=186、pages_scanned=3、`stopped_early=True`，并带那句写明"翻完前 3 页未筛出法规库条目"的 `_error`；同一词 `file_only=True` 交回 results=18、pages_scanned=3、`stopped_early=False`。停在第 3 页正是 `IDLE_PAGE_LIMIT` 的值。

## 三、收窄维度：文件类标签与缓存键

- 检索范围默认锁在文件类标签（`tax_web_search.FILE_LABELS`），不是全站。这一维决定翻页窗口里装的是什么：
  - 「转让定价」按全站取，前 3 屏一条法规库条目都没有（全是新闻与各地动态，自适应就此收尾，得 0 条）；收窄到文件类标签后 18 条命中全部取回。2026-11-26 复核：全站 `total=186`、前三屏 30 条里法规库 **0** 条；收窄 `total=18`，两屏 10+8 全取回。**全站总数 186 这一枚旧记录没写**，本轮补上。
  - 「小微企业」全站 4822 条、首屏十条无一条是文件；收窄后 184 条。2026-11-26 复核：全站 `total=4831`（与旧记录的 4822 差 9 条——这一维是站点的计数，会随录入漂移，不是当时量错）、首屏 10 条 `source_label` 全是「税务总局」（无一条法规库）；收窄 `total=184`、首屏 10 条全是「税务总局法规库」。
- 代价写明白：会漏掉标在「视频政策解读」「图片政策解读」上的法规库条目——那些页面回的是 `media_only` 空正文，本来就引不了条文。要连它们一起搜，命令行给 `--all-labels`。
- 缓存键分两维：`filters_token` 收收窄维度（分号分隔、按字典序，避开 `CacheManager._key` 里 join 用的竖线，也保证写入顺序不影响键值）；`scope_token` 收非默认范围（`labels=all`、`order=` 段），默认范围回 `LIST_KEY_REV` 那一条键，只有偏离默认才另立键。理由：白名单关掉之后同一检索词回的是另一个集合的排序，两种清单绝不能共用一条缓存。
- 只缓存清单（标题/文号/日期/URL），**正文永不缓存**。条文必须每次现拉，避免把已废止或被修订的旧条文当现行有效引用。`--cache` 开清单缓存（TTL 1h，`CACHE_TTL=3600`），`--cache-stats` / `--cache-clear` 查看与清空。2026-11-26 复核：`_cache` 默认 `enabled=False`，取数只在 `search_fgk` 里读写清单，`fetch_fgk_body` 与 `fetch_associations` 两处压根不碰缓存。

## 四、关联接口那一层（2026-11-26 首次逐档量过）

- `POST /queryManuscriptAssociation`（表单 `id=` 纯数字 articleId）**只在 www 域回 200**：同一 id 打 fgk 域回 404/49825 字节的 HTML（`probe34c-run.txt`）。它交回的 `/zcfgk/…` 相对链接反过来要拼 fgk 域，拼 www 回 404。两条域名分工相反，这件事在 `search_source/chinatax/NOTE.md` 也记了一份。
- 分组的形状：`results` 是一个数组，`[0]` 是文章本体，关联分组在带 `policyDocument` 键的那一段（实测是 `[1]`），四组键名见 `tax_fgk._ASSOC_GROUPS`。
- **「没有关联」与「id 没被认」是两种响应，别混：**
  | 发出去的 id | 站点回的 | 生产读数 |
  | --- | --- | --- |
  | `5194010`（详情页 meta 真值） | 200 / 146976 字节 / 两段 / policyDocument 7 条 | files=7，`_error` 空 |
  | `5248633`（鉴定案例，真无关联） | 200 / 41879 字节 / 两段 / policyDocument 空数组 | 四组全 0，`_error` **空** |
  | `c5194010`、`9999999`、`5194010x` | 200 / **56 字节** / `{"code":200,"results":{"data":{"total":0,"results":[]}}}` | 报"这个 id 没被接口认下" |
  | 空串 | 200 / 17 字节 / `text/plain` 的「缺少参数id！」 | 压根不发请求，报"URL 里取不到 articleId" |
  - 关键一条：**"这份文件真没有关联"根本不会走到报错那一支**——接口照样回完整结构。旧话术「接口结构变了或该文件无关联」把一条走不到的成因列了进去，读的人会用"查无关联"去解释自己发错的入参。3.62.34 起这一支按段数分两句：零段＝id 未被认；有段却没有 `policyDocument` 键＝结构真的变了（句里带段数）。盯它的是 `test_zero_segment_shell_blames_the_id_not_the_structure`、`test_genuine_no_association_is_not_an_error`、`test_assoc_groups_present_but_unnamed_is_called_structure_change`。

## 五、复测入口

- 单条清单与正文：`python scripts/tax_fgk.py "研发费用" --size 10` / `python scripts/tax_fgk.py "资产评估减值" --size 1 --body`。
- 严格翻页：`python scripts/tax_fgk.py "转让定价" --size 3 --pages 8`。
- 全站范围对照（看收窄代价）：给 `--all-labels` 再跑一次同一检索词，比对条数与文件占比。
- 关联那一层要三档一起看（真值／带 c 前缀／不存在的号），照第四节那张表；一次性脚本的形状见 `.tmp-inspect\probe34e.py`。
- 限流与闸的复测走 `python tests/probe_rate_limit.py --target fgk-list`；台账见 `references/source_defects.md` 的「限流记录的实测台账」。
