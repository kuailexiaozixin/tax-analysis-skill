# chenyiwei-bbs 子技能：收录说明与实测校正

本目录收录的是**外部编写的子技能文档**，用来补齐主线的一个取证缺口：税法条文
大量以会计确认为前提（"确认收入""计提减值""权益法核算""纳入合并范围"），
而五个税收数据源里没有任何一处写会计准则怎么规定。

每条断言后面都跟着量它的那一天；没有日期的句子等于没量过。本节里 2026-11-26 的
读数出自常驻探针 `probe_mirror.py`（本目录内，14 发 HTTP、零模型调用），一次性
对照出自 `.tmp-inspect/probe37a–37f-run.txt`。

## 收录来源

| 项 | 值 |
|---|---|
| 文件 | `SKILL.md`（**与上游已分叉**，见下面「与上游的分叉」那节；2026-11-26 之前这里写的是"与上游字节一致，未作任何改写"，那句话从来没被量过） |
| 上游地址 | `https://bbs.auditdog.cn/chenyiwei-skill/SKILL.md` |
| 抓取时间 | 2026-09-29（盘上这份的来路日期） |
| SHA-256 | `0ba6ef6a1481f0875da924e2fc86deb7f794993bec40f51d348f609346497c5a`（盘上现算 == 本行声明，`tests/test_subskill_selfcontained.py::TestDeclaredFileHashes` 钉这一层；它只保证"盘上这份还是声明那一份"，**不保证它等于上游**） |
| 上游今日那份 | 2026-11-26 量到 HTTP 200、`text/markdown; charset=UTF-8`、10,529 字节 / 265 行、sha256 `73e4b7a203e1c0462b9a4e5eac5d6adf784ef385f33a386826a861c3ec3b0f43` |
| 服务基址 | `https://bbs.auditdog.cn`，匿名可访问；**上游今天的文档另有一档可选 API Key**（`X-API-Key: <key>`，限流从 30 req/min/IP 提到 120 req/min/key，且不受共享出口 IP 的封禁连带）——盘上这份没有这一档，本项目实测的两个 IP 段都没撞上 429，所以没申请 |
| 依赖 | 只需 HTTPS 出站；不调用任何模型，不消费任何模型额度 |

**同步方式（2026-11-26 改口，旧写法有害）**：先
`python search_source/chenyiwei-bbs/probe_mirror.py` 看 [1] 段那份逐字节比对与端点集合差，
**再决定取不取**；禁止照旧写法 `curl -o …` 直接覆盖。理由见下面那节：今天照旧写法覆盖，
会把 13 枚端点压成 7 枚、丢掉引用溯源/准则原文/监管处罚三节，换来一份更旧的文档。

**为什么不改编上游文件**：它同时是可以被 Claude Code / Codex / Cursor 直接安装的独立
技能，改一个字就会让"与上游 diff"失去意义。本项目的补充说明只写在这个文件里。
分叉之后这条理由要读成两层：盘上这份仍然**不改写**，但它已经不是上游的副本，
所以"与上游 diff"只能用来发现上游改了，不能用来证明我们这份是对的。

## 与上游的分叉（2026-11-26 首次量）

探针 [1] 段读数：盘上 15,886 字节 / 349 行，上游 10,529 字节 / 265 行，逐行不同 **305 行**；
接口表端点数**上游 7 枚、盘上 13 枚**。

- 盘上有而上游没有的六枚：`/api/public/related`、`/api/public/references`、
  `/api/public/ref-posts`、`/api/public/ref/{slug}`、`/api/learn/search`、`/api/public/penalties`。
- 上游有而盘上没有的：**无**（上游那 7 枚全在盘上表里）。
- 上游另有一句盘上没有的：搜索被描述成「关键词搜索（同义词扩展）」，盘上写「关键词 + 语义搜索」——
  盘上这句与今天返回里 `semantic_triggered`/`semantic_affected` 两枚键对得上。
- 十枚候选路径里，上游只有两处有内容：`/chenyiwei-skill/SKILL.md`（那份 10,529 字节的）与
  `/chenyiwei-skill/`（45,153 字节的 HTML 介绍页，接口表 8 枚、比 SKILL.md 多一枚 `related`）。
  小写 `skill.md`、`index.md`、`README.md`、根下 `SKILL.md`、`/api/public/skill`、
  `/api/chenyiwei-skill/SKILL.md`、`/chenyiwei-skill.zip` 全回同一份 14,186 字节 404 页；
  `/api/public/skills` 回 HTTP 522、0 字节。**盘上那份在上游已无处可取，它是唯一副本。**
- ⇒ 所以这不是"我们落后了"也不是"我们更新了"，是**分叉**：盘上这份多出六枚端点的用法，
  上游那份多出 API Key 那一档；两边各自有对方没有的东西。

## 实测校正（以本机当日返回值为准）

上游文档写的是接口应有的样子，下面是实际打出来的差异。**引用准则前先看这一节。**

| 现象 | 实测证据 | 对主线的影响 |
|---|---|---|
| **`/api/public/related` 已经是一条死接口** | 2026-11-26 探针回 **HTTP 410**、123 字节，逐字 `{"error":"相关帖推荐端点已于 2026-11-20 下线（remove-related-recommendation），请改用 /api/public/search"}`；`tid` 与 `link` 两种入参都是 410，响应头没有 Deprecation/Sunset 标记 | **盘上那份 `SKILL.md` 的接口表与「还有哪些相关的讨论？」那一节教的就是这条**；上游删得对，我们这份留着死接口。本子技能不改写上游文件，所以纠正只落在这一行：要"相关讨论"就用 `search`（按关键词）或 `references?tid=`（按引用关系），**不要再调 related** |
| **准则实体的 `docNo` 不表示条文版次** | `/api/public/ref/cas-33` 返回 `docNo=财会〔2006〕3号`、`doc.officialUrl` 指向 2008 年的财政部页面，而第二条正文已是"拥有对被投资方的权力"并出现"结构化主体"——这是 2014 年修订后的措辞；`/api/public/ref/cas-2` 同样报 `财会〔2006〕3号`，第二条已是"以及对其合营企业的权益性投资"（共同控制在 2014 修订后归《合营安排》准则）。2026-11-26 复量：`cas-33` 仍 200 / 211,462 字节 / `docNo=财会〔2006〕3号` / `status=current` / `supersededBy=null`，`cas-2` 仍 200 / 119,971 字节 / 同 `docNo` / units=26 | 把 `docNo` 当"这是 2006 版条文"会引错版本；当"这就是现行版"又没有证据。**版次只能由条文措辞自证**，引用时写准则名＋条款 heading，不写 `docNo` 当版本依据 |
| **`status` 没有可判版次的取值** | 2026-11-26 取到的两枚准则条目 `status` 均为 `current`，`supersededBy` 均为 `null`；仍未取到非 `current` 的样本 | 不能凭 `status=current` 说"这就是最新版"。主线的时效判定（`tax_evidence.judge_validity`）不接管这一栏，会计口径的在效结论要另找证据 |
| **`slug` 拼不出来，必须从检索里取** | `/api/public/ref/cas-14`、`cas-2-2014`、`cas-99-9999` 2026-11-26 三发全 **HTTP 404 / 30 字节 / `{"error": "未找到该准则"}`**（旧记录只写了返回文案，今天补上状态码），而 `cas-14-2017`（200 / 275,464 字节）、`cas-2`、`cas-33` 有内容——年份后缀时有时无 | 每次取准则原文都要先 `/api/learn/search` 或 `/api/public/references` 拿 `slug`，再调 `/api/public/ref/{slug}`；不得由编号自己拼 slug |
| **`recent` 可以整天空；上游那句"数据每天更新"按实测不成立** | 2026-11-26 探针 `days=3` 一发仍是 82 字节 / 200 / `total=0` `count=0` `hasMore=false`（`total/page/pageSize/count` 今天全是 int）；此前 2026-10-18 连取 `days=1/2/3` 三份回包除回显的 `days` 外逐字段相同、都是 82 字节空 `results`，同一时刻 `tags` 回 3,253 字节、`search?q=收入确认` 回 8,537 字节条目齐全，所以空窗口不是服务故障。按时间取两枚帖数最多的标签各第 1 页 20 条（`by-tag?name=合并报表&sort=time`、`name=收入确认`）：2026-11-26 合并报表 20 条落 5 个日期（10-25/10-31/11-01/11-02/11-06）、收入确认 20 条落 12 个日期（08-28→11-06），两栏日期簇重合五枚，看着是按批进库 | 空窗口只说明这几天没有新帖，不代表服务故障，也不代表陈版主没答过这个主题；这时改用 `search` 或 `by-tag?sort=time`。给用户的说法写"最近一批"，不要写"今日更新""每天更新"。上游 `SKILL.md` 的「不要做」小节里那句"数据每天更新"照上游留着（本子技能不改写上游文件），以本行读数为准；"不要高频轮询"那半句照做 |
| **`penalties` 的分页字段今天已是整数——旧校正在 2026-11-26 作废** | 旧记录（2026-09-29）写 `/api/public/penalties?year=2025` 的 `total`/`page`/`pageSize` 是字符串（`"203"`、`"1"`、`"20"`）。2026-11-26 四档参数各一发：`year=2025` → `total=203`、`year=2025&page=2` → `page=2`、`book=pen-csrc&year=2024` → `total=152`、`authority=深圳证监局` → `total=67`，**三枚分页字段全是 `int`**；`search` 侧同样全 `int` | 这一行原本是"两个接口的分页字段不能共用一句取出来比大小"的依据，今天两接口同型，**不必再先转一遍**；但引用前仍要看当天探针的 `type_of_counts` 读数——这条就是那条"没人复算就一直成立"的字段类型，上游改了不会通知 |
| **返回里有上游文档没写的字段** | 2026-11-26 `search` 顶层实测 `count,fallback,hasMore,highlight_terms,keyword,page,pageSize,results,scope,semantic_affected,semantic_triggered`——`fallback`/`highlight_terms` 是旧记录已有的，**`semantic_affected`/`semantic_triggered` 是 NOTE 之前没记的两枚**；三发（`收入确认`、`合并报表 内部交易`、一枚不存在的词）这两枚都是 `false`、`highlight_terms` 原样回吐检索词，所以它们是状态位但当天都没触发；`tags` 接口仍报 `count=64`；`ref/{slug}` 顶层另有 `guide`、`doc`、`cardsByUnit`、`unitCiteCount`、`fallbackTids` | `tags` 可直接用来把检索词换成论坛在用的标签（`by-tag`），比自由词命中稳；`semantic_*` 两枚**别当命中质量**——今天没触发就没验证过它们为 `true` 时长什么样 |
| **`latest_time` 两种格式** | 2026-11-26 复量：`search` 条目是 ISO 串（`2026-06-10T11:28:01.000Z`），`ref-posts` 条目是日期（`2026-08-24`）；`by-tag`/`topic` 条目是 ISO 串 | 转成"三天前"这类人话时两条路径都要走，别按一种格式解析 |
| **`topics` 的元素键不是 `name`/`count`** | 2026-11-26 `topics` 回 11,537 字节 / `count=12`，首枚键 `key_points_count,post_count,slug,summary,title`；`topic?slug=hebing-baobiao&page=1` 回 17,214 字节，顶层 `count,hasMore,key_points,page,pageSize,post_count,reading_order,results,slug,sort,summary,title`，`post_count=12943`、`reading_order` 10 枚、`key_points` 5 枚 | 按 `name`/`count` 取会取到 `undefined`；专题这一层的入口是 `slug` |
| **`references` 要用真 `tid`** | 2026-11-26 用旧样本 `tid=5497367` 回 200 / 27 字节 / `refs=[]`；改用 `ref-posts?slug=cas-33` 首条的真 `tid=5498231` 回 200 / 439 字节 / `refs` 3 枚，首枚 `{"slug":"cas-33","name":"企业会计准则第33号——合并财务报表","type":"cas","status":"current","doc_no":"财会〔2006〕3号"}` | 引用溯源可用，但**空 `refs` 与 `tid` 不存在同形**（都是 200 + 空数组），别把空数组读成"这条帖没引用任何准则"以外的事实 |

## 主线里的唯一入口

**本技能不自行决定何时调它。** 触发条件、在答案里的位置、禁止事项都写在母技能
`SKILL.md` 层级下挖那一层的末尾与 `references/out_of_library_layers.md`
「专业口径缺口：准则那一层不在 L1–L4 之内」；本节只登记来源与实测差异。

## 复测入口

```bash
# 14 发（1 发上游镜像件 + 13 枚端点各一发），零模型；台账与上面那张表据此更新
python search_source/chenyiwei-bbs/probe_mirror.py

# 只列计划、不发请求；这一档的输出不能用来更新台账
python search_source/chenyiwei-bbs/probe_mirror.py --dry-run
```

探针 [1] 段管"上游改了没有、两份是分叉还是新旧"，[2] 段逐枚给状态码、顶层键、
分页字段类型与条数，[3] 段汇总今天非 2xx 的端点（2026-11-26 只有 `related` 一枚 410）。
端点入参用的是 2026-11-26 从真返回里取出的样本（`tid=5498231`、`slug=cas-33`、
`slug=hebing-baobiao`），换样本时 `ENDPOINT_PROBES` 要一起换，否则 `references` 那发
会退化成空数组、读不出"没引用"还是"tid 不存在"。
