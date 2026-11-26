# 微信公众号检索的形状与实测读数

本文件只记实测到的形状。工作流在 `search_source/wechat/SKILL.md`。

## 一、三段流程（每段都经实测确认）

1. **检索**：`GET https://weixin.sogou.com/weixin?type=2&query=<关键词>`。`type=2` 检索文章；`type=1` 检索公众号，实测返回 0 条，不用。
2. **还原真实地址**：搜狗交回的是 `weixin.sogou.com/link?url=…` 跳转链接。**带 Referer 请求该链接，回的是 200 的 JS 片段页而不是 302**——真实地址被拆成 `url += '…'` 的若干段，拼完还要去掉 `@`。不带 Referer 会被重定向到 `/antispider/` 反爬页。
3. **取正文**：`GET mp.weixin.qq.com/s?…`，手机版 UA + `Referer: https://mp.weixin.qq.com/`，正文容器是 `id="js_content"`。

## 二、判据、节奏与阈值

- **零命中判据**：`noresult_part1_container` 这枚 id（常量 `tax_wechat.NO_RESULT_MARK`）。2026-11-24 实测：`blocks=0` 时必现、`blocks=10` 时必不现。它只用于判"这页确实没结果"，不能代替反爬判据——两者形状不同，一个有结果块缺失、一个是跳转或验证页。
- **`if not blocks:` 现在分三支**（3.62.33 起）：先判正文是否为空——HTTP 200 且 0 字节回「这一路当天没给页面」；再看 `NO_RESULT_MARK`，命中就回干净的 0（`_error` 空串）；有内容却既无块又无标记才报「页面有内容，但既没有结果块也没有无结果提示：可能改版或落在验证页」。**为什么要把 0 字节单列**：2026-11-25 与 11-26 两轮实测里这一路对任何检索词都回 200 / 0 字节 / `text/plain`，旧话术把三种成因压成一句，会带读者去查改版与验证页，而这两条当天一条都不成立（改版至少回一份 HTML，验证页会跳 `/antispider/` 或带验证字样）。钉在 `tests/test_source_defects.py` 的 `TestWechatEmptyBodyIsItsOwnShape` 四条。
- **还原篇数上限** `MAX_RESTORE = 5`，每次还原之间 `RESTORE_INTERVAL = 1.2` 秒；正文逐篇取、`READ_INTERVAL = 2.0` 秒。搜狗对高频请求敏感，这两个上限是保护，不是性能参数，不要为了多拿正文往上改。
- **检索与链接还原必须共用同一个 Session**：还原要靠检索那一次的会话 cookie，两个进程各查一次等于各持一份会话互相搅。所以这一路整体进 `tax_http.SerialGate`（锁文件 `tax-analysis-skill-sogou.lock`，`TAX_SOGOU_LOCK_TIMEOUT` 默认 180 秒），闸内再加 `_SOGOU_MIN_INTERVAL` 1.0 秒。
- 闸只保证同一时刻一个请求，保证不了别发太快，所以两者都要有；"并发加压会触发反爬"这句话光写在文档里全靠人记，进了闸就不必记了。
- **`mp.weixin.qq.com` 的正文读取没测到同样的阈值**，所以那一路只按 `READ_INTERVAL` 拉开间隔、不入闸。台账里那行的"最近实测日期"写的是「从未取过阈值」——它是边界声明，不是"限流已消失"，也不是"可以给正文读取补一把闸"的依据。

## 三、复测入口

- 检索阈值：`python tests/probe_rate_limit.py --target sogou`（探针抓生产路径那一枚请求重放，并跳过串行闸——它要量的就是并行）。
- 正文阈值：`python tests/probe_rate_limit.py --target wechat-read`（3.62.31 起收录）。签名地址只能现场从检索还原，所以这一枚会先打一次检索、拿到几枚就轮转几枚；检索一枚都不给时探针直接停下来说明「入口不通，正文阈值就取不到」，不会编数字。
- **2026-11-25 那一轮的形状**：检索入口连发 6 + 2 线程×2 共 10 发全是 `200-空响应(0字节)`（`Content-Type: text/plain`），四档对照（新会话手机 UA、先取首页拿 cookie、桌面 UA、补 Referer+X-Requested-With）与真浏览器同址全同形——不是 UA 被区别对待、也不是缺会话，是这一路当天不给页面。旧探针把这种响应记成「200-正常页」，台账当场会写成「未复现限流」，与生产同一发的报错（「既没有结果块也没有无结果提示」）对不上；3.62.31 已把形态分成四层并钉住（`tests/test_rate_limit_ledger.py` 的 `TestProbeShapeLabels`）。**这一行不等于限流已消失，也不等于可以拆闸**——入口通了要重测。
- **2026-11-26 复量第二轮，同形照旧**：同址三发 + 五枚检索词各一发（含 2026-11-24 实测 `blocks=10` 的两枚词与真 0 命中那枚）全回 HTTP 200 / 0 字节 / `text/plain`，真浏览器同址仍是空白页。⇒ 连续两天这一路断供：`NO_RESULT_MARK` 那一支这两天走不到，正文阈值（`--target wechat-read`）也因此第二次无从量起——**不是这一栏查不到，也不是页面结构变了，那两种都至少回一份 HTML**。
- **2026-11-26 第三轮 + 排除本机代理嫌疑**（`probe42b.py`，同一枚 URL、同一份头打三臂）：A 臂照现状走环境代理、B 臂 `trust_env=False`、C 臂 `proxies={"http":None,"https":None}` ⇒ **三臂全 200 / 0 字节 / `text/plain`**。本机环境代理现读为 `{'http':'http://127.0.0.1:7897', 'https':…, 'ftp':…}`，三臂同形说明**那 0 字节不是代理截走或改写**，断供确实发生在站点侧。三天三轮、约二十发，这一路没给出过一份 HTML。
- 逐日读数与闸的存废判定统一看 `references/source_defects.md` 的「限流记录的实测台账」三字段（最近实测日期 / 实测方法 / 当时结果）。

## 四、第二条通道（元宝 `so.qq.com`）的实测形状，以及本源为什么不接它

weixin.sogou 断供之后，本机另有公众号检索通道 `https://so.qq.com/isearch?tab=weixin_article&query=<词>`（腾讯元宝的公众号频道，返回体里带 `mp.weixin.qq.com` 永久直链，不需要还原跳转链）。2026-11-26 对它做了完整取证，形状记在这里；**它的解析器、判据与常驻用例都在用户技能 `wechat-article` 那一侧（脚本名 `yuanbao_search.py`，5.21.2 已修复并推送），本仓库里没有这一份**。

当天一个小时内，同一个入口、同一个词轮换出三种形状（每形都存了真页）：

| 形状 | 字节 | 判读 | 特征 |
| --- | --- | --- | --- |
| 结果页 | 349,173 / 351,224 | 正常出数 | 30 枚 `linkid:title` 锚，30 条全带 mp.weixin 直链；`Set-Cookie` 一枚 |
| 登录墙 | 60,751 | **要登录** | 飞行数据带 `"linkid":"login_page"`、可见区「请登录后继续查看内容」；**不报 403、不带验证码字样** |
| 验证码墙 | 4,395 | **拦截** | `search.sogoucdn.com/anticaptcha/anti-captcha-…/` 资源、`form id="seccodeForm"` + tcaptcha，页面明写本机 IP 与访问时间 |

三条取证结论：

1. **紧跟着成功响应的那一发就是登录墙**（同词同头，第一发 349,173 字节出 30 卡、六秒后第二发 60,751 字节要登录、不带 cookie jar 的会话直接落 4,395 字节验证码页）⇒ 这一通道**当天起对未登录会话开始收口**，形状与登录态、会话强弱相关，不与检索词相关。
2. 结果页的 Next.js 飞行数据里每个请求都带参数名 `"antispiderToken":"…"`。拿 `antispider` 做**全文裸子串**比对会把出满 30 条的好页判成"命中反爬拦截"（这正是 `wechat-article` 5.21.2 修掉的自伤缺陷；同源共性问题在搜狗那份 `search_wechat.py` 里同款，一并收紧为两层判据：文案层 + `/antispider/`、`antispider.min.js`、`anti.min.css` 结构锚层）。**本仓库没有这个病**——`tax_wechat.py` 只看 `"/antispider/" in r.url`（L128、L253）与落地 URL 里的 `wappoc_appmsgcaptcha`（L286），`tax_sogou.py` 的 `_ANTISPIDER_MARKS`（L57）也只看 Location/final_url，都不做全文子串比对。这一条按"共性问题一并查"的要求核过，结论是**无需动 tax 侧**。
3. **本源不接它，是读数决定的，不是偷懒**：一条匿名即可用、且能稳定出清单的路径才有资格进 `tax_wechat.py` 的自动链路。当天量到的形状是「一次成功之后就要登录 / 要验证码」，接进来会造出最难查的那类失败——**静默换源**：查不到时说不清是词没有结果、还是第二通道掉了登录态。要接的前提是浏览器登录态，那属于 `scripts/tax_browser.py` 那条路径的工作面，与 `search_source/wenshu`、`search_source/rmfyalk` 记的是同一件事（判据与形状先备好，接入再谈）。
4. 本轮改口只落在**答句的归因**上：微信这一路取不到时，报的是「站点侧断供（三轮十九发同形、本机代理已排除）」，不能报「改版/验证页」，也不许顺手答成「公众号里没有这篇文章」。
