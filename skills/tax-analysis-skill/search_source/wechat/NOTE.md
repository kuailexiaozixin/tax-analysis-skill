# 元宝公众号搜索的形状与实测读数

本文件只记现行入口、判据与实测边界。工作流在 `search_source/wechat/SKILL.md`。
3.62.49 起主路换成了取数接口，本文件同时记下被推翻的旧判据，免得下一轮照着旧句改回去。

## 一、现行入口与业务契约

- **主路是 POST**：`https://so.qq.com/searchweb/api/search/next-page`，体 `{"query":词,"page":1,"sp":{"tab":"weixin_vertical"}}`，头 `Content-Type: application/json` 之外**必须再带** `x-original-uri: /iweixin?tab=weixin_article&query=<URL编码词>`——两枚缺一不可，只带 `sp.tab` 不带 `x-original-uri` 时站点不给公众号档。返回 JSON，卡片在 `data.cards[].data.vm`，`item.jsonData` 里另有 `pub_time`/`doc_from`。
- **旧的 GET 不是主路了**：`GET https://so.qq.com/isearch?tab=weixin_article&query=<词>` 现在只作第三档兜底。它是 SSR 骨架页（60,751 字节那份实测：`result-card` 0 次、`js-results` 0 次、`mp.weixin` 0 次，结果全靠客户端再发 POST），所以拿 GET 判「元宝改版」会误判。
- 三档阶梯，逐档降级并在 `_caveat` 写明：垂直档（`sp.tab=weixin_vertical`）→ 综合档（`sp={}`，卡片形 `card-common/card30010608`，直链在 `h5Url`）→ GET 兜底。上一档没货就下一档，任何一档出货即止。
- 严格直链白名单：只允许 http/https；主机精确等于 `mp.weixin.qq.com`；无端口；无用户信息。查询参数可以保留。**垂直档只认 `vm.jumpUrl`，不回落 `vm.host`**——host 是频道首页，能过白名单却点不进任何一篇文章（2026-11-27 离线自测暴露）。
- 业务契约不变：`search_wechat(keyword, size=5, read_body=False, time_filter="")`、聚合源键 `wechat`、单条 `source=微信公众号`、`source_label=实务解读`；顶层来源名为“微信公众号 (元宝搜索)”。`read_article()` 继续读 `mp.weixin.qq.com` 正文。
- `--time-filter` 只认 `1d`/`1w`/`1m`/`1y`（`all` 等于不筛），越界在发请求**之前**拒。**`sp.timeFilter` 垂直档不执行**：2026-11-27 三组真网对照（同词带与不带各两发）回的是**同一批卡、同一顺序**（25 张与 28 张两个词都如此），其中落进近 30 天的只有 4 张；把参数塞进 `x-original-uri` 查询串会让整批发空（112 字节熔断形），放 body 顶层则换了一批候选池但窗口内仍是 4/26。所以这一档的筛选**由本地按发布日期做**：`_apply_time_filter()` 三档都接（垂直档 `site_ignored=True`，综合档与 GET 兜底只说「本地复核」，因为综合档站点自己可能筛——probe58tf 那组成立、yb77tf2 那轮没复现，不能当保证）。生效时在 `_caveat` 写明「已按发布日期本地筛近 %d 天：%d 张里留 %d 张」，一张没滤掉就不写（免得「2 张里留 2 张」这种噪声）。**全被窗清空时报 `_zero_hit` 并把「%d 张相关条目都不在所选时间窗内」写进 `_caveat`**——这既不是通道故障，也不能落成「站内没这个词」。

## 二、通道形状与出口标记

同一个接口返回的是同一份信封，差别在字段值，所以判据不能看大小：

| 形状 | 读数 | 出口 |
| --- | --- | --- |
| 满档 | 17-23 万字节，`cards` 二十余张，`timings.search` 七百至一千一百毫秒 | 正常返回 |
| 熔断短接 | 309 或 112 字节，`ok=true`、`cards=[]`、`hasMore=false`，`timings.search` 十几至几十毫秒（**112 字节那形连 `search` 键都可能没有**） | `_fetch_failed`，报「通道短接」，**绝不报零命中** |
| 活批空卡 | `cards=[]` 而 `timings.search` 过阈值 | `_fetch_failed`（没货不等于站内没词，不作证据） |
| 推词兜底 | 整批卡片没有一张含检索词的任一分词 | `_zero_hit` 并在 `_caveat` 写明是兜底批 |
| 限流页 | HTML 侧出现「请登录后继续查看内容」 | `_fetch_failed`，报限流，**不报账号墙** |
| 验证码/拦截 | 结构锚 `/antispider/`、`antispider.min.js`、`anti.min.css`，或落地 `antip=web_hd`/`wap_hd`/`new_hd` | `_fetch_failed` |
| 站点空结果 | GET 那页有 `<h2>抱歉，没有找到相关网页</h2>` | `_zero_hit` |
| 全部无效链接 | 候选链接全未过严格白名单 | `_fetch_failed` |

- **`timings.search` 是这轮的命门**：熔断形看着像“站点说没这个词”（`ok=true`、`cards=[]`、HTTP 200），只有 `timings.search` 能把它和真零命中分开。阈值 `SEARCH_ALIVE_MS=120` 毫秒；实测活批 744/745/749/764/787/807/1156，熔断侧 19/22/23/25/68。取值一律过 `_alive_ms`，非数值当 0（宁可落短接，不可落零命中）。
- 短接是可恢复的频控窗口，不是账号问题：冷却 180 秒后连打两发都满；8 秒间隔三连发会翻空，25 秒间隔三连发不翻空。所以短接后先 `DEAD_COOLDOWN=12.0` 秒重发一次垂直档，仍短接才降档。
- `approve`／`uigs` 握手**不是通道开关**（实测握手 `ret=OK` 时照样能翻成空档），补握手只是为了不欠站点一个回执。
- 先解析结果，再判拦截：正常摘要里出现“验证码”字样不能误伤；`antispiderToken` 本身不是拦截，只认结构锚。
- `_fetch_failed` 与 `_zero_hit` 互斥；只有站点自己的空结果文案或整批推词兜底是 `_zero_hit`。有结果容器（`js-results`/`result-card`）**不是**空结果证据——那只是壳。

## 三、卡片字段与文本脏源

- 垂直档卡片：`vm.jumpUrl`（直链）、`vm.title`、`vm.authorName`、`vm.summary`、`vm.publishTime`，`item.jsonData.pub_time` 是 epoch 秒（补 `timestamp`，并在缺日期时换算）。
- 综合档卡片（`card30010608`）：`vm.h5Url`、`vm.title`、`vm.author`、`vm.publishTime`、`vm.content`；`vm.showname` 恒为“微信公众平台”，**账号只认 `author`**，取值顺序错了就把交付账号写成站点名。外部站点那形 `card-pc/card_normal_result` 才有 `url`/`date`/`sourcename`，主机不是 mp，会被白名单挡掉——这是对的。
- **JSON 通道的标题与摘要里直接插私有区高亮符 U+E40A/U+E40B**（真响应 25 张里 23 张带）。GET 那一路是 HTML，标签被 `TAG_RX` 吃掉；JSON 这一路必须显式剥（`HL_RX`），否则私有区脏字符直接交付下游。
- 相关性口径：剥高亮符后，`title + summary` 含检索词的**任一分词**即留。真词批留 19/25，整批推词兜底那批留 0/26——这把尺能把两批分开。`doc_from` 在真批与兜底批同值（全是 `q2q`），**不能当判据**。
- 日期可能是相对时间（GET 那一路），条目标 `date_approx=True`，只能当近似线索。

## 四、保护、会话与读取边界

- 串行闸：`tax_wechat.yuanbao_gate`，类型 `tax_http.SerialGate`；锁文件 `tax-engine-yuanbao.lock`；`TAX_YUANBAO_LOCK_TIMEOUT` 默认 180 秒。**闸等待超时会转成 `_fetch_failed` 信封**（句里写明“串行闸”），不再把 `TimeoutError` 抛给调用方。
- 最小间隔 `YUANBAO_MIN_INTERVAL=1.5` 秒，**检查在闸内做**，且时间戳同时记在内存与盘上（`tax-engine-yuanbao-pace.json`）——旧写法把 sleep 放在闸外、时间戳只在本进程，两个进程实测间隔能压到 0.002 秒。
- 一轮检索最多五次 HTTP（两档 POST + 握手 + GET 兜底），全程一把闸、一份频次账。每轮新建 Session，退出必 `close()`；响应读完也 `close()`。无 API Key、无硬编码 Cookie，不读取浏览器登录态。超时 25 秒，响应上限 4MB（末块跨界也置 `truncated`），被截断的响应整批拒收；403、429、5xx 不重试。
- `read_article()`：先过严格白名单（含端口、用户信息、`127.0.0.1` 一律**发请求前**拒），再 `allow_redirects=False` 自己跟跳——**只连同主机的跳**（微信会把 `http://` 版 301 升级到同路径 `https://`，一律拒跳等于把正文路全断），落到非微信主机或跳超过 `MAX_REDIRECT_HOPS=2` 次即拒。正文容器 `js_content`，只提 `<p>` 段落（表格型、图片型正文会漏，属已知边界）。仍按 `READ_INTERVAL=2.0` 秒拉开间隔。`appmsgcaptcha` 只报“正文取不到（验证码门）”，不改写成“文章不存在”。

## 五、2026-11-27 实测读数

同一检索词“研发费用加计扣除”，端到端三发各隔 25 秒：A 垂直档满档 25 张，滤掉 6 张无关后交付 3 条，全直链、私有区残留 0，耗时 1.6 秒；B 带 `--time-filter 1m` 走垂直档交付 3 条；C 词“资源税 计税依据 特殊规定”30 张里滤 1 张。B 那发的三条日期是 2024-09-19／2025-03-10／2025-03-14，**不在近一个月内**——后来三组对照量清了：垂直档根本不执行 `sp.timeFilter`，所以这一枚改成由本地按发布日期筛（第一节末条）。取正文三枚 323／3544／2284 字符，`error` 全空。越界自检 `http://127.0.0.1/private` 零出网。

本地筛落码后的真网复验（同词、`--time-filter 1m`、`size=5`）：交付 **4 条，日期 2026-11-20／11-23／11-24／11-26 全部落进近 30 天**，`_caveat`＝「垂直档不执行站点时间筛（实测带与不带 `timeFilter` 回同一批卡），已按发布日期本地筛近 30 天：26 张里留 4 张；公众号垂直档只出一页…」，`error` 空，18.6 秒（含闸等待）。这一发是本地筛生效的直接证据，不是 `timeFilter` 生效的证据。

2026-11-26 那轮（GET 主路时代）的读数保留作历史：公众号技能解析 30 条、前 3 条有有效直链，税务侧 CLI 于 20:59 交付 1 条；同日另一发回归返回 0 条且未留页，不能判定其页型。功能实调不是并发或限流测量。

限流台账元宝行因此写为：

- 最近实测日期：**从未取过阈值**。
- 实测方法：2026-11-27 起探针改量 POST 取数主路（`--target yuanbao`，形状＝垂直档 POST + `x-original-uri`），本轮只做了低频功能实调与 8 秒／25 秒两种间隔的节奏观察，**未运行阈值探针**。
- 当时结果：**没有阈值数据**。已量到的是“短接窗口可恢复”这一定性结论（约 3 分钟冷却后复满、握手与否无关），不是第几次请求翻脸的那个数字；功能实调成功不能冒充阈值。

## 六、未保证的边界（别写成已解决）

- 本地时间筛靠的是卡片自带的发布日期（`item.jsonData.pub_time`，回落 `vm.publishTime`）：**读不出日期的条目一律不计入结果**并单独记一笔，所以「近一月」这种窗在日期字段改版时会静默变短——这不是「站点筛过了」。窗口的起点按**本地时区**的日历天算，跨时区读数会差一天。
- 综合档加时间筛后微信卡更稀（一次实测 17 张里 0 张带 mp 直链），“综合档补直链”不能承诺一定有货。
- 整批推词兜底的频率没有量过；`SEARCH_ALIVE_MS=120` 这枚阈值只在两批样本上分得开，长期稳定性未知。
- 多进程下闸超时的实际频率未知（只在离线用例里造过）。
- 表格型、图片型正文漏读率未量。
- 三通道（NPC／搜狗／元宝／正文）的限流阈值都仍**从未取过**；本轮改动不等于量过阈值。
- 浏览器里点击这条链路的回归未做。

## 七、历史停用入口与已推翻的旧判据

旧 `weixin.sogou.com` 公众号检索已停用；2026-11-25/26 连续测到该入口 HTTP 200 / 0 字节 / `text/plain`，只是历史故障读数，不能证明今天的元宝状态，也不能用于拆掉元宝的闸。旧的 `type=2`、`/link` JS 还原、检索与还原共用 Session、`NO_RESULT_MARK`、旧搜狗锁与 `--target sogou` 均只属于该历史入口；`m.sogou.com` 手机网页通道仍活跃，判据另见 `search_source/sogou/`。

本轮明确推翻、不要再写回文档的三条：

1. **“入口是 GET isearch，返回 HTML 含直链”**——GET 是第三档兜底，主路是 POST 取数接口（第一节）。
2. **“页型分登录墙”**——`请登录后继续查看内容` 是站点 `getRateLimitTitle` 的 `case"429_outer"` 限流标题，前端渲染器 `WebLoginRequiredPlaceholder` 只在 `allowLogin:"429_outer"===code` 时才给登录入口；`429_user` 是“请求过于频繁，请过会儿再尝试～”，`429_inner` 是“当前请求量较大，请稍后再试。”。这是限流，不是账号墙（第二节）。
3. **“元宝无翻页”**——准确说法是垂直档 `hasMore=false`、只出一页，`page=2` 那一发实测回空信封；不是“站点没有翻页参数”。
