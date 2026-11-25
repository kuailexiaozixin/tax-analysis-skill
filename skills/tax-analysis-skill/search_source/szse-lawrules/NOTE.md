# szse-lawrules 子技能：来源、实测取证与硬约束

本目录收录的是**本项目自行编写**的查询式子技能（对标 `maodocs/`、`chenyiwei-bbs/`、
`税屋`）。上游只有一个人工维护的抓取脚本（`D:\CPAHelperForExcel\…\szse-lawrules\
scripts\szse_lawrules_scraper.py`，playwright+openpyxl 全站爬成 Excel），本项目**不改
那份原技能**，只把"深交所法律规则"这一信息源按查询式重做成仓库原生子技能。

用来给母技能的「专业口径缺口」那一层（在 L1–L4 之外）补上**证券交易场所自律规则**这一格——六个税收源、
MaoDocs、chenyiwei-bbs 都不收交易所自己的业务规则。

## 收录来源

| 项 | 值 |
|---|---|
| 站点 | `http://www.szse.cn/www/lawrules/`（深交所官网，公开匿名可访，无 token） |
| 左侧导航通道 | 49 个 `index.html` 叶子页（2026-11-26 再枚举仍是 49）；其中被 `szse.CATEGORIES` 表覆盖 **18 枚**、表外 31 枚 ⇒ `build` 默认只吃表里那 18 枚 |
| 本目录文件 | `SKILL.md`（技能说明）、`szse.py`（build/query/fetch/categories） |
| `szse.py` SHA-256 | `e8880f876c12dc2479d01dd1c4d2eb46771d3e6f7669e94e973f705d8abee05c`（2026-11-26 拦未渲染占位锚那一改后的值；2026-09-29 那版是 `a9b6fd15…`） |
| 索引产物 | `szse_index.json`（`build` 生成，随技能分发不含，已在 `.gitignore` 内） |
| 依赖 | 标准库直连；浏览器通道复用母技能 `scripts/tax_browser.py`（**不新增依赖**） |
| 模型额度 | **不调用任何模型，不消费任何额度** |
| 抓取时间 | 2026-09-29（盘上 `szse_index.json` 的 built_at 就是这一版）；2026-11-26 复量一轮站点面，见文末那节 |

## 站点渲染的两种形态（决定了 build 的默认范围）

| 形态 | 通道 | 取法 | 当日实测 |
|---|---|---|---|
| **内联 SSR** | 法律 / 行政法规 / 司法解释 / 证监会规章 / 适用指引 / 规范性文件 / 废止公告 | 纯 urllib：每条是 `<li>` 里 `var curHref`/`var curTitle` + `<span class="time">`；翻页 `index.html→index_N.html` | 7 通道 **602** 条（2026-11-26 逐通道复核盘上索引：45+84+79+71+38+269+16），`build` 默认覆盖 |
| **运行时模板** | 11 类“本所业务规则”（`szse.CATEGORIES` 里 render=browser 的那 11 枚：通用/股票/发行上市/审核/持续监管/债券/基金/衍生品/REITs/会员/交易通则） | 直连只返回 EJS 模板（`_.each(data,…)`；2026-11-26 实测页内**没有** `<template>` 标签，`articleList.js` 两枚候选 URL 仍 404）；须 `tax_browser.BrowserSession.read_html()` 渲染出 `a.art-list-link` 锚点后解析。模板分支里躺着未渲染占位锚 `<%=replaceTitle(item.doctitle)%>`／`<%=item.docpuburl%>`，`szse._parse_rendered` 把 title 或 url 含 `<%` 的锚判掉（2026-11-26 改前 `rule/stock/trade/index.html` 直连解出 2 条假条目、改后 0 条；`general`/`bond` 同形） | `build --browser --channel stock` 2026-09-29 实测 14 条（Edge，无模型）；2026-11-26 未重跑浏览器通道 |
| **落地页快照** | `lawrules/index.html` | 内联混排约 122 条最新业务规则，stdlib 直取 | `build --snapshot` 2026-09-29 实测 122 条；2026-11-26 直连一发 `szse._parse_static_page` 仍 122 条 |

默认 `build`（不加 `--browser`）产出 **724 条 = 602 业务通道 + 122 落地页快照**（2026-11-26 逐通道求和核对）。旧版这里写「724（582 + 122）」——582 与 724 自己就对不上，少的 20 条在 `csrc_file` 那一格（269 条，旧记 249）。确定性好、不开浏览器。交易所自律规则若快照不够，再 `--browser` 补对应通道。

## 实测校正（以本机当日返回值为准）

| 现象 | 实测证据 | 对主线的影响 |
|---|---|---|
| **URL 的 t 编号不表版次** | `…/t20250327_612564.html` 标题"（2023年修订）"、列表日期 2023-12-15，t20250327 只是 CMS 生成序号 | 引用写"规则名＋（修订年份）"，别拿 URL 编号或文号当版本依据（与 chenyiwei `docNo`、MaoDocs 文号陷阱同源） |
| **列表日期≠施行日** | 详情页正文写"自发布之日起施行"并另列废止旧文号，与列表 `class="time"` 日期口径不同 | 本技能只给目录与定位；生效时点按正文自述，不接进 `tax_evidence.judge_validity` |
| **正文附件常是 PDF/DOC** | 规范性文件/司法解释多为 `P….pdf`/`.doc`，`fetch` 对非 `.html` 只回链接 | 要逐条原文得下载附件另行解析；`fetch` 回显会明确标 `type:pdf` |
| **业务规则页 502 抖动** | `rule/stock/trade/index.html` 直连偶发 HTTP 502，重试即通 | `_get_retry` 带退避重试；一次 502 不算通道失败 |
| **浏览器通道依赖本机浏览器** | 2026-09-29 当日仅探到 `edge` 可启动、playwright 不在 ⇒ `build --browser` 跳过该通道并记原因；**2026-11-26 本机 `importlib.util.find_spec('playwright')` 已能命中**，那句「playwright 未安装」在本机不再成立 | 分发到他机时业务规则通道可用性取决于本机是否装了 Edge/Chrome 与 playwright |
| **Git Bash 路径改写** | `fetch "/lawrules/…"` 里以 `/` 开头参数被 MSYS 改写成 `D:/Git/…` | 传完整 URL；脚本对 `http` 开头不拼接 |

## 与其他专业口径子技能的分工

三者并排在「专业口径缺口」那一层，取的东西不同：

- **szse-lawrules**：证券**交易所自律规则**与规章/规范性文件的**目录＋原文定位**（先建索引、离线查）。
- **maodocs**：会计/审计/内控/评估/证券监管**规范逐条原文全文**（静态站直连）。
- **chenyiwei-bbs**：陈版主**实务答疑**、处罚案例、准则衍生问答。

同一份证监会文件，MaoDocs `garr` 与深交所 `csrc_*` 都可能收到；**要目录与官网链接走
szse，要逐条原文走 MaoDocs**。三者都不进六源、不进母技能的依据定级，触发条件与在答案里的位置
都写在母技能 `SKILL.md` 层级下挖那一层的末尾与 `references/out_of_library_layers.md`。

**本技能不自行决定何时调它。**

## 2026-11-26 复测记录（一次性探针，判据全走 `szse.py` 自己的函数）

- 盘上 `szse_index.json`（built_at 2026-09-29 23:43:46）八键逐枚 45/84/79/71/38/269/16/122；
  七枚业务通道求和 **602**、加快照 **724**。上面表格与那句算式按这组数改口。
- 当日一发 `rules/law/index.html`：行内 20 条、首条与索引首条同一 URL
  （`2026-01-01 中华人民共和国网络安全法（2025年修正）`）⇒ 索引没漂。
- 当日一发 `rule/stock/trade/index.html`（直连 30674 字节）：这是本轮唯一落到代码的改动。
  改前 `_parse_rendered` 解出 2 条 `<%=replaceTitle(item.doctitle)%>`；改后 0 条。
  病因不是注释残留（注释那一枚 `_strip_comments` 挡得住），是 **EJS 模板分支里的占位锚**：
  浏览器起了但页面 JS 没跑完时 `_enumerate_browser` 拿到模板本身、items 非空 ⇒
  既不报错也不收尾，占位串会随翻页写进 `szse_index.json` 并随索引对外分发。
  整页存档 `.tmp-inspect/szse-stock-direct.html`，常驻用例照它做桩。
- 左侧导航 `index.html` 叶子仍 49 枚、`CATEGORIES` 覆盖 18 枚（表外 31）⇒ 见「收录来源」那行。
