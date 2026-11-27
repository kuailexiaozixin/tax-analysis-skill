---
name: wechat
description: 微信公众号文章检索与取正文（元宝 so.qq.com 的 POST 取数接口 + mp.weixin.qq.com 正文）。当用户要找实务口径、官方解读、或只有公众号发过全文的那类内容时用。三档阶梯、通道形状判据、严格直链白名单与保护配置都在这里。
---

# 微信公众号（scripts/tax_wechat.py）

站点形状与实测读数在 `search_source/wechat/NOTE.md`：第一节现行入口与契约，第二节通道形状与出口标记，第三节卡片字段与文本脏源，第四节保护与读取边界，第五节实测台账，第六节未保证的边界，第七节历史停用入口与已推翻的旧判据。

## 工作流

1. **检索**：`python scripts/tax_wechat.py "研发费用加计扣除" --size 5`。主路是 POST `https://so.qq.com/searchweb/api/search/next-page`，`sp.tab=weixin_vertical` 与 `x-original-uri` 两枚缺一不可；拿不到货自动降综合档（`sp={}`，直链在 `h5Url`），再降 GET 兜底——`GET /isearch` 那一发只是第三档，它本身是 SSR 骨架页。要限时间加 `--time-filter 1m`（只认 `1d`/`1w`/`1m`/`1y`，越界在发请求前拒）——但**站点的 `sp.timeFilter` 在垂直档不生效**（带与不带回同一批卡），筛选由本地按发布日期完成，生效与否都写在 `_caveat` 里；全被窗清空是 `_zero_hit` 带成因，不是失败也不是站内没货。
2. **取正文**：加 `--read`（可配 `--json`）。直链只允许 http/https、主机精确等于 `mp.weixin.qq.com`、无端口、无用户信息；不合规的链接在**发请求之前**就拒，不进网络。跟跳只连同主机（微信会把 `http://` 升到 `https://`），落到非微信主机即拒。
3. **判空与判失败**：先看 `timings.search`——HTTP 200 + `ok=true` + `cards=[]` + 十几毫秒是**熔断短接**，报 `_fetch_failed`，绝不报零命中；整批卡片没有一张含检索词分词才是推词兜底（`_zero_hit`）；站点自己写「抱歉，没有找到相关网页」才是站内确实没货。「请登录后继续查看内容」是 `429_outer` 限流标题，不是账号墙。`_fetch_failed` 与 `_zero_hit` 互斥。
4. **保护与复测**：一轮检索最多五次 HTTP，全程一把 `tax_wechat.yuanbao_gate` 闸、一份跨进程盘上频次账（闸内 1.5 秒最小间隔）；超时 25 秒、响应上限 4MB、被截断整批拒收；403/429/5xx 不重试。复测 target 是 `yuanbao`（3.62.49 起量 POST 主路）与 `wechat-read`（先由元宝取有效直链）。

## 这一层负责什么、不负责什么

- 业务契约不变：`search_wechat()`、聚合源键 `wechat`、单条 `source=微信公众号`、`source_label=实务解读`；顶层来源名为“微信公众号 (元宝搜索)”。
- **本源是"实务解读"层，权威性低于 NPC 法规与税务总局原文。** 公众号里的说法不能当作现行依据交回；引它只能作为线索，找到原文那一路再定级（`references/evidence_grading.md`）。
- 与 `search_source/sogou` 的分工：那本子技能管 `m.sogou.com` 手机网页检索；本模块管元宝公众号检索。`tax_wechat.yuanbao_gate` 与 `tax_sogou._sogou_gate` 是两把不同的闸，读数也不通用。
- 交付的条数不等于站点总数：垂直档 `hasMore=false` 只出一页，`size` 只在这批里截。当页条数不能替站点声明总数。
- 本地时间筛不保证日期字段本身：读不出发布日期的条目一律不计入（并在 `_caveat` 单独记账），窗口起点按本地时区日历天算。字段改版会让窗口静默变短，这不能读成「站点筛过了」。

## 命令依赖

- `python scripts/tax_wechat.py --help`
- `python tests/probe_rate_limit.py --target yuanbao`
- `python tests/probe_rate_limit.py --target wechat-read`
- 限流与闸的存废判定读 `references/source_defects.md` 的「限流记录的实测台账」；元宝与正文阈值都尚未取到，功能实调不能冒充阈值测量。
