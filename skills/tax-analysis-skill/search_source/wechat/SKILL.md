---
name: wechat
description: 微信公众号文章检索与取正文（元宝 so.qq.com 检索 + mp.weixin.qq.com 正文）。当用户要找实务口径、官方解读、或只有公众号发过全文的那类内容时用。页型分诊、严格直链白名单与保护配置都在这里。
---

# 微信公众号（scripts/tax_wechat.py）

站点形状与实测读数在 `search_source/wechat/NOTE.md`：第一节现行入口与契约，第二节页型分诊，第三节保护与读取边界，第四节实测台账，第五节历史停用入口。

## 工作流

1. **检索**：`python scripts/tax_wechat.py "研发费用加计扣除" --size 5`。入口是元宝 `GET https://so.qq.com/isearch?tab=weixin_article&query=<URL编码词>`，返回服务端渲染 HTML；结果直接含 `mp.weixin.qq.com/s` 文章直链，不再经过搜狗 `/link` 还原。
2. **取正文**：加 `--read`（可配 `--json`）。`read_article()` 继续读 `mp.weixin.qq.com` 正文；元宝只负责先取得有效直链。直链只允许 http/https、主机精确等于 `mp.weixin.qq.com`、无端口、无用户信息。
3. **判空与判失败**：先解析有效结果，再区分结果页、登录墙、验证码/拦截页、合法零命中、空响应、HTTP 失败、结构改版、全部无效链接。只有明确空结果页打 `_zero_hit`，其余失败打 `_fetch_failed`，两键互斥。`antispiderToken` 本身不是拦截，只认 `/antispider/`、`antispider.min.js`、`anti.min.css` 等结构锚。
4. **保护与复测**：元宝无翻页，`size` 只截当页；相对日期标 `date_approx=True`，不能当精确发布时间。检索每次新 Session，无 API Key、无硬编码 Cookie、不读取浏览器登录态；超时 25 秒、响应上限 4MB，403/429/5xx 不重试。串行保护用 `tax_wechat.yuanbao_gate`，复测 target 为 `yuanbao`；`wechat-read` 先由元宝取得有效直链。

## 这一层负责什么、不负责什么

- 业务契约不变：`search_wechat()`、聚合源键 `wechat`、单条 `source=微信公众号`、`source_label=实务解读`；顶层来源名为“微信公众号 (元宝搜索)”。
- **本源是"实务解读"层，权威性低于 NPC 法规与税务总局原文。** 公众号里的说法不能当作现行依据交回；引它只能作为线索，找到原文那一路再定级（`references/evidence_grading.md`）。
- 与 `search_source/sogou` 的分工：那本子技能管 `m.sogou.com` 手机网页检索；本模块管元宝公众号检索。`tax_wechat.yuanbao_gate` 与 `tax_sogou._sogou_gate` 是两把不同的闸，读数也不通用。

## 命令依赖

- `python scripts/tax_wechat.py --help`
- `python tests/probe_rate_limit.py --target yuanbao`
- `python tests/probe_rate_limit.py --target wechat-read`
- 限流与闸的存废判定读 `references/source_defects.md` 的「限流记录的实测台账」；元宝与正文阈值都尚未取到，功能实调不能冒充阈值测量。
