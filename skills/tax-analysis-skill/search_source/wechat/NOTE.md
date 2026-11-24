# 微信公众号检索的形状与实测读数

本文件只记实测到的形状。工作流在 `search_source/wechat/SKILL.md`。

## 一、三段流程（每段都经实测确认）

1. **检索**：`GET https://weixin.sogou.com/weixin?type=2&query=<关键词>`。`type=2` 检索文章；`type=1` 检索公众号，实测返回 0 条，不用。
2. **还原真实地址**：搜狗交回的是 `weixin.sogou.com/link?url=…` 跳转链接。**带 Referer 请求该链接，回的是 200 的 JS 片段页而不是 302**——真实地址被拆成 `url += '…'` 的若干段，拼完还要去掉 `@`。不带 Referer 会被重定向到 `/antispider/` 反爬页。
3. **取正文**：`GET mp.weixin.qq.com/s?…`，手机版 UA + `Referer: https://mp.weixin.qq.com/`，正文容器是 `id="js_content"`。

## 二、判据、节奏与阈值

- **零命中判据**：`noresult_part1_container` 这枚 id。2026-11-24 实测：`blocks=0` 时必现、`blocks=10` 时必不现。它只用于判"这页确实没结果"，不能代替反爬判据——两者形状不同，一个有结果块缺失、一个是跳转或验证页。
- **还原篇数上限** `MAX_RESTORE = 5`，每次还原之间 `RESTORE_INTERVAL = 1.2` 秒；正文逐篇取、`READ_INTERVAL = 2.0` 秒。搜狗对高频请求敏感，这两个上限是保护，不是性能参数，不要为了多拿正文往上改。
- **检索与链接还原必须共用同一个 Session**：还原要靠检索那一次的会话 cookie，两个进程各查一次等于各持一份会话互相搅。所以这一路整体进 `tax_http.SerialGate`（锁文件 `tax-analysis-skill-sogou.lock`，`TAX_SOGOU_LOCK_TIMEOUT` 默认 180 秒），闸内再加 `_SOGOU_MIN_INTERVAL` 1.0 秒。
- 闸只保证同一时刻一个请求，保证不了别发太快，所以两者都要有；"并发加压会触发反爬"这句话光写在文档里全靠人记，进了闸就不必记了。
- **`mp.weixin.qq.com` 的正文读取没测到同样的阈值**，所以那一路只按 `READ_INTERVAL` 拉开间隔、不入闸。台账里那行的"最近实测日期"写的是「从未取过阈值」——它是边界声明，不是"限流已消失"，也不是"可以给正文读取补一把闸"的依据。

## 三、复测入口

- 检索阈值：`python tests/probe_rate_limit.py --target sogou`（探针抓生产路径那一枚请求重放，并跳过串行闸——它要量的就是并行）。
- 正文那一路要复测得先在探针的 `TARGETS` 里加一条，**不要在台账里写没量过的数字**。
- 逐日读数与闸的存废判定统一看 `references/source_defects.md` 的「限流记录的实测台账」三字段（最近实测日期 / 实测方法 / 当时结果）。
