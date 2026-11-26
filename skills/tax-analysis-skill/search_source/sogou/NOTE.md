# 搜狗手机端网页检索的形状与限流读数

本文件只记实测到的形状与台账口径。工作流在 `search_source/sogou/SKILL.md`。

## 一、入口与请求形状

- 入口：`https://m.sogou.com/web/searchList.jsp?keyword=<词>`（`tax_sogou.SEARCH_URL`），手机端 UA（Android 13 + Chrome 131 Mobile）+ `Referer: https://m.sogou.com/`。
- 结果块认 `<div class="vrwrap">`；标题在 `<h3 class="vr-title">`，直链在 `data-url="https://…"`，摘要在 `class="fz-mid space-txt"`，来源站在 `class="citeLinkClass"`，日期按正文里的 `YYYY-MM-DD`。
- **上面那把 HTML 锚在 2026-11-26 的页面上已经不够用了**：这一天量到的形状是结果卡片整体搬进 `<script type="application/json">` 数据岛，HTML 侧只剩壳——`data-url` 0 处，`class` 含 `resultLink` 的 `<a>` 只剩百科卡一枚（目标 `baike.sogou.com`，被自家域判据正确拒掉）。3.62.43 起 `_parse` 在「按 HTML 读到 0 枚直链」之后回落 `_island_rows`，从岛上的顶层 `url`+`title` 取结果；岛上的 `showSiteAndDate.time` **不当发布日用**（同一页里两枚卡片标的是抓取当天），所以岛层那几枚的 date 一律留空——宁可少给一个字段，不把猜测印进答案。
- 续页形状是地址里的 `$N` 段（正则 `\$\d+(?=\.html)`），不是查询参数。
- 重定向码单独列出 `(301,302,303,307,308)`：`_is_antispider_location` 只在重定向族里看 `Location`，其它状态码一律不按反爬判。

## 二、反爬与验证页的判据

- **反爬页是 200**（跟随跳转以后），所以判据看 `Location` 与最终地址，不看状态码。标记三枚：`/antispider/`、`antip=web_hd`、`antip=wap_hd`。
- 不跟随反爬跳转：跟随本身就是再一次请求，而且会把 302 变成 200，读起来像成功。发现跳转指向反爬就直接落熔断。
- **反爬不重试**（`MAX_RETRIES=2` 只给网络异常与 5xx 用）：重发只会把封禁时间拖长。
- 200 的验证码页另判：`_looks_like_verify_page` 先看有没有结果块（`vrwrap`，或 `vrResult` 解析后有真结果），有结果就不按验证码判；再看前 6000 字节里 `antispider` / `seccodeImage` / （`验证码` 且不含零结果标记）。摘要里出现"验证码"三个字不能当判据。
- 零结果标记 `没有找到`（站内文案「没有找到能和"…"匹配的内容」）：**有结果块时不按它判**，免得摘要里出现同一句话被误读成 0 条。0 命中与"被反爬"在页面上长得像，是这一路最容易读反的地方。
- 手机入口的 `site:` 限定另有第二种无结果形状（2026-11-26 量到）：那一档的文案是「抱歉，未找到“<站点>”站内包含“<词>”的内容」——**说的是「未找到」，不是上面那枚「没有找到」**，且挂在一枚 `class="vrResult site-vr-none"` 的 div 上。旧判据认不出它，把这一档落进了「结构可能改版」（`_fetch_failed`），语义正好写反：那是站点明确告诉你 0 条，不是取数失败。3.62.40 起 `_SITE_NONE_CLASS = "site-vr-none"` 走 `HTMLParser` 的 class 词元判（类名出现在脚本字符串里不算，同 `vrResult` 那一枚理由），判成真 0 条并进缓存。
- 同一批页里另一档**仍然是改版**：`<div class=vrResult>`（无引号写法）里只有一枚表头「以下是网页“shui5.cn”中包含“研发费用加计扣除”的结果」，条目区是空的——`.results` 容器内 33,950 字符只有 11 枚标签（表头 + 3 枚 script + 4 枚广告位 + 1 枚 script），站点承诺了站内结果却一条都没落下。这一档照旧报「结构可能改版」，不能被上一条判据一并吞掉。
- 数 class 时严格锚与宽松解法会差一枚（2026-11-26 就是这么发现矛盾的）：正则 `<div class="vrResult` 数到 0，`HTMLParser` 报 `has_results=True`——差的那枚写的是 `class=vrResult`（不带引号）。生产解析器一直按 `.split()` 比词元，所以它对；**手打的属性正则才是不可信的那一方**。

## 三、闸、预算与熔断

- 跨进程串行闸 `tax_http.SerialGate`（锁文件 `tax-analysis-sogou-web.lock`，超时 `TAX_SOGOU_WEB_LOCK_TIMEOUT` 默认 180 秒）。闸只保证同一时刻一个请求，保证不了"别发太快"，所以另加最小间隔。
- 状态文件 `tax-analysis-sogou-web-state.json` 存 `last_request_at` / `recent` / `blocked_until`。**写不进去就继续跑**——状态盘只影响保护强度，不能因为它就中断检索。
- 三道保护（`_reserve_slot`，全在闸内判）：熔断期内直接抛 `_Unavailable(blocked=True)`；10 分钟窗口内满 4 次抛"预算已用尽，本轮没有发请求"；不足 `SEARCH_MIN_GAP` 3 秒就补足等待。抛出的话都写明白是"没发请求"，不是"发了没查到"。
- 熔断时长 `BLOCK_SECONDS` 600 秒，取 max 不缩短（多条请求先后触发时以最后那次为准）。
- 整页结果元数据缓存 30 分钟（`CACHE_TTL=1800`，`TAX_SOGOU=0` 可关）；键不含 size，size 只截输出。

## 四、复测入口

- 联网阈值：`python tests/probe_rate_limit.py --target sogou-mobile`（手机当前入口）。微信公众号检索另用 `--target yuanbao`，正文阈值用 `--target wechat-read`；旧 `--target sogou` 只对应已停用的搜狗微信入口，不是现行复测入口。**3.62.43 把该探针注释里那句「生产把失败分成三层（`sogou_search` L487-505）」的行号校正为真身位置**（原行号已随文件增长失真）。
- 数据岛这一刀的回放入口：`python -m pytest tests/test_source_defects.py -k SogouMobileDataIsland -q`（离线读 `tests/fixtures/msogou_dataisland_20261126.html`，零请求）。
- **2026-11-25 首次实测的形状**：连发 6 + 2 线程×2 共 10 发，`200-有结果块无直链(raw=0)`×9、`ConnectionError`×1——阈值没触发，量到的是改版形态（52–56 万字节 React 页，老的 `vrwrap` 与 `data-url` 两把锚零命中；页面里那 8 枚 `application/json` 结果岛不跟 `site:` 走，是「相关推荐」不是命中清单）。生产报 `_fetch_failed`「页面结构可能改版」是对的，这一路的判据没有坏。
- **2026-11-26 再复量（离线回放当天存的三页，零请求）**：页型又换了——三页 178,778 / 156,364 / 283,176 字节（11-25 那批是 52–56 万），`vrwrap`、`data-url` 两把老锚仍全零命中；三页 `div.vrResult` 各 1 / 1 / 11 枚，`class` 含 `resultLink` 的 `<a>` 各 0 / 0 / **1** 枚（唯一那枚是「研发费用加计扣除 - 搜狗百科」，目标 `baike.sogou.com` 被 `_matches_site(target,"sogou.com")` 正确拒掉）；`site:` 两页里那些 `./id=<uuid>/…/tc?…` 相对跳转址（13 与 31 枚）逐个解 `url=`/`pcurl=` 后 **44/44 全指 sogou 自家**（提示词跳板 `s_from=uphintTag`），不带 site 那页外站直链只剩 8 枚去重（chinatax／gov.cn／cnfin 一类），全在 React 推荐岛、**不跟 `site:` 走**，无一枚 shui5。⇒ 改版是持续状态不是单日抖动；当天两档 `site:` 页里 `shui5.cn` 字样（48 与 84 处）全在 `window.oldQuery` 回显与 keyword 段，不在结果里。判据分流见第二节末尾那三条。
- 同一天真浏览器（带自己的 cookie）打开同址被 302 到 `/captcha/?m=1&antip=wap_hd` 图形验证码页——requests 那路拿到壳页、浏览器那路被跳验证页，两件事都记在台账那一行里，读的时候别只挑一件。
- **2026-11-26 同日第三轮（这一轮把「改版」那档翻案了）**：另存的一页 320,043 字节（脱敏后进 `tests/fixtures/msogou_dataisland_20261126.html`，318,013 字节）里有 **9 块 `<script type="application/json">` 数据岛**，其中**六块是结果卡片**——顶层对象带 `url`+`title`（另有 `content` 摘要、`showSiteAndDate`），六枚直链落在 chinatax.gov.cn（含带 `:8443` 端口那枚）、www.gov.cn、liaoning/hainan/hunan.chinatax 上，全是真命中。⇒ 上一段那句「改版」判得没错（HTML 锚确实取不出直链），但**结论不该停在「取不出」**：站点把结果换了容器，不是没给结果。这一页离线喂旧解析器读数 `rows=0 raw=0 has_results=True`、完整信封 `_error='搜狗返回了结果区，但没有解析出可用直链：页面结构可能改版'` + `_fetch_failed=True`。
- 3.62.43 的修复与边界：新增 `_ISLAND_JSON_RE`（只认带 `type="application/json"` 的容器，裸 `<script>` 里出现 url/title 字样不算）与 `_island_rows()`，挂在 `_parse` 的手机支后面——**HTML 读到 0 枚直链才回落岛层，岛层也读不出仍报「结构可能改版」**（「有结果区但一条直链都取不出」这个语义保留，不加成静默 0 条）。岛层只认顶层 `url`+`title` 这一对键，所以配置块、只有标题的新闻聚合、带翻页 URL 的导航块自动筛掉。**注意别拿 script 的 `id` 当锚**：那是 `data-<会话 uuid>`，每轮都换。固化用例见 `tests/test_source_defects.py::TestSogouMobileDataIsland`（十枚）。
- 外部诊断报告（`搜狗通道故障诊断汇报_2026-11-26.md`）里关于 **weixin.sogou.com 那一路持续 200/0 字节**的三条主张，本轮独立复现通过：微信主机活着（首页 200/66,627B `text/html`），而 `/weixin?type=2&query=…` 回 200/0B、`text/plain`、`Server: stgw`、`Content-Length: 0`、正文 sha256 `e3b0c44298fc1c14…`（空正文的哈希）。**该入口现已停用，公众号检索已迁移到元宝**；这里只保留历史故障读数，不构成现行操作指引。`m.sogou.com` 手机网页通道仍活跃，其反爬、预算、熔断、数据岛与两档无结果判据照旧适用。
- 台账两行分开读：桌面历史入口（`www.sogou.com/web?query=`）2026-10-23 有当次读数——1 线程连发 6 词全落 `200-反爬页`（5422–5458 字节、`blocks=0 rows=0`）；手机当前入口 2026-11-25 起有实测行（日期格 ISO），但**首次实测没有量到阈值**。桌面读数不得移作手机证据，保护配置也不是站点放行承诺。
- 判闸的存废按 `references/source_defects.md` 那张限流台账的日期与三字段，不按这一段的转述。
