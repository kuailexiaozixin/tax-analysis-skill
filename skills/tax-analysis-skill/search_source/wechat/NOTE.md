# 元宝公众号搜索的形状与实测读数

本文件只记现行入口、判据与实测边界。工作流在 `search_source/wechat/SKILL.md`。

## 一、现行入口与业务契约

- 入口：`GET https://so.qq.com/isearch?tab=weixin_article&query=<URL编码词>`。返回服务端渲染 HTML，结果直接含 `mp.weixin.qq.com/s` 文章直链，不再经过搜狗 `/link` 跳转还原。
- 严格直链白名单：只允许 http/https；主机精确等于 `mp.weixin.qq.com`；无端口；无用户信息。查询参数可以保留，但主机、端口与用户信息任一不符即弃。
- 业务契约不变：`search_wechat()`、聚合源键 `wechat`、单条 `source=微信公众号`、`source_label=实务解读`；顶层来源名为“微信公众号 (元宝搜索)”。`read_article()` 继续读 `mp.weixin.qq.com` 正文。
- 元宝无翻页；税务侧 `size` 只截取当页，不承诺取全，也不据当页条数替站点声明总数。

## 二、页型分诊与出口标记

| 页型 | 判读 | 出口 |
| --- | --- | --- |
| 结果页 | 先解析出有效结果与严格白名单内的微信直链 | 正常返回 |
| 登录墙 | 页面结构表明要登录，不能当作零命中 | `_fetch_failed` |
| 验证码/拦截页 | 由 `/antispider/`、`antispider.min.js`、`anti.min.css` 等结构锚认定 | `_fetch_failed` |
| 合法零命中 | 页面明确给出空结果结构 | `_zero_hit` |
| 空响应 | 请求返回但正文为 0 字节 | `_fetch_failed` |
| HTTP 失败 | 请求层失败或状态码表明未取成 | `_fetch_failed` |
| 结构改版 | 有内容但认不出结果或空结果结构 | `_fetch_failed` |
| 全部无效链接 | 候选链接全部未通过严格直链白名单 | `_fetch_failed` |

- **先解析结果，再判拦截**：正常摘要里出现“验证码”字样不能误伤；`antispiderToken` 本身也不是拦截，只认结构锚。
- `_fetch_failed` 与 `_zero_hit` 互斥；只有明确空结果页是 `_zero_hit`，其余失败、改版与全部无效链接都是 `_fetch_failed`。

## 三、保护、会话与读取边界

- 串行闸：`tax_wechat.yuanbao_gate`，类型 `tax_http.SerialGate`；锁文件 `tax-engine-yuanbao.lock`；`TAX_YUANBAO_LOCK_TIMEOUT` 默认 180 秒；闸内最小间隔 `YUANBAO_MIN_INTERVAL=1.5` 秒。
- 检索每次使用新 Session；无 API Key、无硬编码 Cookie，不读取浏览器登录态。超时 25 秒，响应上限 4MB；403、429、5xx 不重试。
- 日期可能是相对时间，条目标 `date_approx=True`；只能当近似线索，不能当精确发布时间。
- 正文读取仍按 `READ_INTERVAL=2.0` 秒拉开间隔、不入闸。`mp.weixin.qq.com/s` 仍可能落到 `appmsgcaptcha` 验证码门；这时只报正文取不到，不改写成“文章不存在”。
- 复测入口：检索阈值用 `python tests/probe_rate_limit.py --target yuanbao`；正文阈值用 `python tests/probe_rate_limit.py --target wechat-read`，它先由元宝取得有效直链。搜狗手机网页另用 `--target sogou-mobile`。

## 四、2026-11-26 实测与阈值边界

2026-11-26 做过低频功能实调，检索词均为“研发费用加计扣除”：公众号技能解析 30 条，前 3 条均有有效微信直链；税务侧 CLI 于 20:59 交付 1 条有效直链。同日早些时候另一发回归曾返回 0 条，未留存响应页，不能判定其页型，也不记为合法零命中。这些只作当日可用性与波动证据，不能证明稳定，更不能证明限流阈值；功能实调不是并发或限流测量。

限流台账元宝行因此写为：

- 最近实测日期：**从未取过阈值**。
- 实测方法：2026-11-26 低频功能实调“研发费用加计扣除”，不是并发／限流测量，未运行阈值探针。
- 当时结果：**没有阈值数据**。公众号技能解析 30 条、前 3 条有有效直链；税务 CLI 交付 1 条有效直链；另一次回归返回 0 条且未留页，原因未定。成功与空结果都不能替限流阈值作保。

## 五、历史停用入口：搜狗微信（非活跃）

旧 `weixin.sogou.com` 公众号检索已停用。2026-11-25 与 2026-11-26 曾连续测到该入口返回 HTTP 200 / 0 字节 / `text/plain`，多档会话与代理对照同形；这些只是历史故障读数，不能证明今天的元宝入口状态，也不能用于拆掉元宝的闸。

旧的 `type=2`、`/link` JS 还原、检索与还原共用 Session、`NO_RESULT_MARK`、旧搜狗锁与 `--target sogou` 均只属于该历史入口，**不是现行操作指引**。现行公众号检索只按本文件前四节执行；`m.sogou.com` 手机网页通道仍活跃，判据与保护另见 `search_source/sogou/`。
