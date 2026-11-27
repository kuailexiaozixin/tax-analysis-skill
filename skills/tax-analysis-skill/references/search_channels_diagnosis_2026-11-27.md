# 搜狗、元宝与微信检索通道诊断报告

- 诊断日期：2026-11-27
- 诊断对象：`tax-analysis-skill`
- 诊断范围：搜狗手机网页检索、元宝公众号检索、微信公众号正文读取
- 诊断性质：只读检查、离线复现和低频受控实测；不修复代码，不提交，不推送
- 报告基线：母技能工作树中未提交的 `scripts/tax_wechat.py`，SHA-256 为 `fae6e19fe3169c0de5181b28988bcad1bebbce9cbb451dd5022ebc14ab3ed461`

> 本报告是诊断时点快照。诊断期间 `scripts/tax_wechat.py` 存在并发未提交改写，因此本文以函数名、类名和常量名定位代码，不依赖容易漂移的行号。若后续代码继续变化，应重新核对本文结论。

## 一、结论摘要

本次低频受控实测中，三条通道都能取得结果：

1. 搜狗手机网页检索返回 HTTP 200，并交付 3 条真实结果。
2. 元宝公众号检索首发出现“通道短接”，冷却重发后取得 24 张卡，滤掉 5 张无关卡，交付 3 条有效微信直链。
3. 微信正文读取返回 HTTP 200，取得一篇正文样本，共 2668 字。

因此，本次不能把问题概括为“三个通道全部失效”。当前主要问题分为四类：

- **结果语义错误**：把取数失败、无效链接或推荐内容误报为合法零命中。
- **安全边界缺失**：正文读取函数没有复用微信直链白名单，可请求任意 URL。
- **保护机制不完整**：元宝握手绕闸，最小间隔不是跨进程保证，锁超时异常会穿透公共函数。
- **工程一致性漂移**：测试仍按旧 GET-only 实现编写且会发真实请求，文档仍为 3.62.48，三个适配器运行时副本与母技能不一致。

建议在发布或扩大使用前，优先修复结果语义和正文 URL 边界，再修复筛选传递与保护闸，最后重建离线测试并同步文档和运行时快照。

## 二、范围、方法与证据等级

### 2.1 检查范围

| 通道 | 生产入口 | 本文检查内容 |
|---|---|---|
| 搜狗手机网页 | `tax_sogou.sogou_search()` | HTML 解析、JSON 数据岛、`site:` 限定、零命中、反爬、预算、熔断、缓存、锁超时 |
| 元宝公众号检索 | `tax_wechat.search_wechat()` | 垂直档 POST、综合档 POST、旧 GET 回退、相关性过滤、时间筛选、短接重试、串行闸 |
| 微信正文读取 | `tax_wechat.read_article()` | URL 边界、验证码门、正文容器、段落提取、响应上限、资源释放 |

旧 `weixin.sogou.com` 公众号入口已经停用，不属于本次现行通道；其历史故障只作为背景，不用于判断当前元宝或搜狗手机入口。

### 2.2 方法

1. 静态阅读生产脚本、测试、探针、技能文档和运行时副本。
2. 用合成 HTML、JSON 和 HTTP 替身进行离线复现，不访问真实站点。
3. 以单线程、低频方式对三个通道做受控真实探测，不绕过验证码或登录墙。
4. 运行现有相关测试，检查其是否仍能作为离线门禁。
5. 比对母技能与 API、CLI、MCP 三个适配器的运行时文件哈希。

### 2.3 证据等级

| 等级 | 含义 | 本文用法 |
|---|---|---|
| A | 低频真实探测 | 证明诊断当日该样本可用，不证明限流阈值或长期稳定性 |
| B | 离线可复现 | 用确定性输入证明代码存在某种错误行为 |
| C | 静态代码确认 | 从控制流和数据结构确认风险，未单独构造运行样本 |
| D | 文档或哈希比对 | 证明版本、说明或运行时快照不一致 |

本文严格区分“已复现缺陷”“代码风险”和“未定项”。查不到的材料不写成不存在，功能成功也不写成阈值已经测到。

## 三、诊断基线

### 3.1 工作树状态

诊断开始及报告撰写前，Git 工作树只有以下既有修改：

```text
 M .gitignore
 M scripts/tax_wechat.py
```

- 当前分支：`master`
- 当前发布提交：`0f65f2e`
- `SKILL.md` 版本：`3.62.48`
- 工作树 `scripts/tax_wechat.py` 已在文件说明中标注“3.62.49 起”
- 除本报告外，本轮未修改生产代码、测试或既有文档

### 3.2 文件哈希

| 文件 | SHA-256 |
|---|---|
| 母技能 `scripts/tax_wechat.py` | `fae6e19fe3169c0de5181b28988bcad1bebbce9cbb451dd5022ebc14ab3ed461` |
| 母技能 `scripts/tax_sogou.py` | `3025c6a3840b9a4bcd2bdee45caf64e6e3f8c13b3d7e0dde73e54ede8b594c73` |
| API `tax_wechat.py` | `a6063fe5088a796d31aa7ee8d96d4d233cdae97c55338a030f3415cd62587075` |
| CLI `tax_wechat.py` | `a6063fe5088a796d31aa7ee8d96d4d233cdae97c55338a030f3415cd62587075` |
| MCP `tax_wechat.py` | `a6063fe5088a796d31aa7ee8d96d4d233cdae97c55338a030f3415cd62587075` |

三个适配器副本彼此一致，但都与母技能工作树版本不同。

## 四、当前通道状态

### 4.1 搜狗手机网页：本次可用

受控请求：

```text
GET https://m.sogou.com/web/searchList.jsp?keyword=研发费用加计扣除
HTTP 200
```

公开调用 `sogou_search("研发费用加计扣除", size=3)` 的返回摘要：

```text
total=3
_from_cache=false
_error=无
_fetch_failed=无
_zero_hit=无
_blocked=无
```

样本标题：

1. `一文了解:研发费用加计扣除政策_国家税务总局`
2. `国家税务总局辽宁省税务局 资料下载 税费政策可视答疑第十九期热点问题`
3. `研发费用税前加计扣除新政指引_解读_中国政府网`

结论：本次样本证明手机入口可用；不能据此证明数据岛分类、`site:` 零命中或限流阈值没有问题。

### 4.2 元宝公众号检索：本次可用，但首发可能短接

受控请求序列：

```text
POST /searchweb/api/search/next-page
HTTP 200，309 字节，cards=0，timings.search=68ms，hasMore=false

冷却 12 秒后重发：
POST /searchweb/api/search/next-page
HTTP 200，171994 字节，cards=24，timings.search=1156ms，hasMore=false

GET /newanti/approve
HTTP 200
```

公开调用 `search_wechat("研发费用加计扣除", size=3)` 的返回摘要：

```text
total=3
有效微信直链=3
24 张卡中滤掉 5 张无关卡
_error=无
_fetch_failed=无
_zero_hit=无
```

结论：三档阶梯本次能交付结果；首发短接后的冷却重试本次有效，但 `timings.search < 120ms` 阈值的长期稳定性尚未测得。

### 4.3 微信正文：本次样本可用

受控调用：

```text
search_wechat("研发费用加计扣除", size=1, read_body=True)
```

请求序列：

- 元宝 POST 两次；
- `/newanti/approve` 一次；
- `GET https://mp.weixin.qq.com/s` 一次，HTTP 200。

返回摘要：

```text
total=1
有效直链=1
正文字数=2668
正文错误=无
_partial_error=无
```

结论：一篇正常 `<p>` 型正文样本读取成功；不能据此证明表格型、图片型或非 `<p>` 正文的覆盖率。

## 五、已复现缺陷

### 5.1 P0：正文读取没有复用微信直链白名单

**位置**：`scripts/tax_wechat.py` 的 `read_article()`、`_safe_mp_link()`

**证据等级**：B

`_safe_mp_link()` 已经实现严格白名单：

- 只允许 HTTP/HTTPS；
- 主机必须精确等于 `mp.weixin.qq.com`；
- 不允许端口；
- 不允许用户信息。

但 `read_article()` 没有调用它，而是直接把入参交给 `requests.get()`。

离线 HTTP 替身复现：

```python
W.read_article("http://127.0.0.1/private")
```

观察结果：

```json
{
  "requested": "http://127.0.0.1/private",
  "body": "private",
  "error": ""
}
```

**影响**：

- 公共函数失去 SSRF 边界；
- 若未来把正文读取暴露给外部输入，可能访问内网、本地服务或其他非微信主机；
- 当前正常检索链路会先过滤微信直链，因此本次没有实际访问内网，但函数本身缺少最后一道防线。

**建议**：

1. 在 `read_article()` 入口先调用 `_safe_mp_link()`，不合格立即返回错误，不发请求。
2. 重定向后的最终 URL 也要复核主机，或禁用自动重定向并逐跳校验。
3. 使用上下文管理器关闭响应，并按 4MB 上限流式读取。

**验收标准**：

- `read_article("http://127.0.0.1/private")` 返回明确错误，HTTP 调用次数为 0。
- `mp.weixin.qq.com.evil.test`、带端口、带用户信息的 URL 同样在发请求前被拒绝。
- 合法微信 URL 的正常正文读取不受影响。

### 5.2 P0：无效链接可能先被相关性过滤，最终误报零命中

**位置**：`scripts/tax_wechat.py` 的 `_parse_vertical_cards()`、`_relevant_only()`、`search_wechat()`

**证据等级**：B

当前顺序是：

1. 解析卡片；
2. 按 title+summary 做相关性过滤；
3. 对保留结果进入 `_finalize()`；
4. 最后才统计有效微信直链。

合成垂直卡：

```json
{
  "title": "题名",
  "jumpUrl": "https://example.test/a",
  "summary": "摘要"
}
```

检索词：`某词`

观察结果：

```json
{
  "total": 0,
  "zero_hit": true,
  "fetch_failed": null,
  "caveat": "垂直档 1 张卡没有一张含检索词的分词"
}
```

**影响**：站点确实返回了卡片，但卡片没有有效微信直链；当前却告诉调用方“站内没有结果”。这违反 `_zero_hit` 与 `_fetch_failed` 互斥契约。

**建议**：

- 先识别“是否存在候选卡片”，再检查链接有效性，最后做相关性过滤。
- 全部候选链接无效时走 `_fetch_failed`，不能进入零命中分支。
- 明确区分 `no_cards`、`invalid_links`、`irrelevant_cards`、`site_empty` 四种状态。

**验收标准**：

- 上述合成卡必须返回 `_fetch_failed=True`、`_zero_hit` 不存在。
- 错误文案必须包含“没有一条有效的微信文章直链”。
- 相关且有效的卡片仍正常交付。

### 5.3 P0：GET 回退把结果容器误当作空结果证据

**位置**：`scripts/tax_wechat.py` 的 `ZERO_RESULT_MARKS`、`_get_fallback()`

**证据等级**：B

当前 `ZERO_RESULT_MARKS = ("js-results", "result-card")`。只要页面出现其中一个类名，且没有解析出卡片，就归类为 `site-empty`。

合成输入：

```html
<div class="js-results"><script>client-render</script></div>
```

观察结果：

```text
kind="site-empty"
note="GET 回退有结果容器但一张卡都没解析出来"
```

公开语义会变成 `_zero_hit=True`。

**影响**：客户端渲染壳、脚本占位或结构改版都会被误报为合法零命中。

**建议**：

- 只有站点明确空结果文案，例如 `SITE_EMPTY_MARK`，才能判 `site-empty`。
- 有结果容器但无卡片时，应判 `_fetch_failed`，文案写明“容器存在但未解析出结果”。
- 不要把通用类名当作空结果锚。

**验收标准**：

- 上述客户端壳必须返回 `_fetch_failed=True`。
- 明确空结果页仍返回 `_zero_hit=True`。
- 两种页面不得输出相同状态。

### 5.4 P0：垂直档 0 卡叠加后两档失败，仍可能误报零命中

**位置**：`scripts/tax_wechat.py` 的 `search_wechat()`、`site_empty_note`

**证据等级**：B

离线替身构造：

```text
垂直档：payload={"cards": [], "timings": {"search": 500}}
综合档：失败
GET 回退：失败
```

观察结果：

```json
{
  "total": 0,
  "zero_hit": true,
  "fetch_failed": null,
  "caveat": "垂直档回 0 张卡"
}
```

**影响**：第一档的“0 卡”被当作正面空结果证据；后两档都失败后，调用方仍收到零命中，而不是“三档均未成功取得结果”。

**建议**：

- “0 卡”不能单独作为 `site_empty` 的充分条件。
- 只有明确空结果锚，或经过确认的推词空批，才能保留零命中证据。
- 三档均失败时，即使某档回 0 卡，也应返回 `_fetch_failed`。

**验收标准**：

- 上述组合必须返回 `_fetch_failed=True`。
- 任意一档明确空结果页且其他档失败时，才可以保留 `_zero_hit`。

### 5.5 P0：搜狗推荐数据岛可造成假命中或假零命中

**位置**：`scripts/tax_sogou.py` 的 `_island_rows()`、`_parse()`、`sogou_search()`

**证据等级**：B，另有 C

`_island_rows()` 只检查 JSON 岛顶层是否有 `url+title`，不验证该岛属于当前查询结果区，也不检查标题、摘要与检索词的关系。

合成页：

```html
<div class=vrResult><h3>客户端渲染壳</h3></div>
<script type="application/json">
{"url":"https://example.com/recommend","title":"无关推荐","content":"推荐"}
</script>
```

观察结果：

```json
{
  "all_titles": ["无关推荐"],
  "site_total": 0,
  "site_zero_hit": true,
  "site_fetch_failed": null
}
```

**影响**：

- 无 `site:` 时可能把相关推荐当命中；
- 有 `site:` 时，推荐直链被过滤后可能制造假零命中；
- `sogou_search()` 末尾“有直链但都被 site 过滤掉”的分支会直接判零命中。

**建议**：

- 给数据岛增加结果区归属或明确卡片类型约束。
- 对数据岛条目执行查询相关性检查。
- 如果只能确认“存在推荐岛、无法确认结果岛”，应返回 `_fetch_failed`，不能判零命中。
- `site:` 过滤后为零时，优先要求站点明确零结果锚。

**验收标准**：

- 合成推荐岛不得进入 `results`。
- 推荐岛被 `site:` 过滤后不得输出 `_zero_hit`。
- 真实结果岛 fixture 仍正常解析。

### 5.6 P1：`time_filter` 在 Fallback 路径静默丢失

**位置**：`scripts/tax_wechat.py` 的 `_vertical_search()`、`_plain_search()`、`_get_fallback()`、`search_wechat()`

**证据等级**：B

`time_filter` 只传给垂直档。综合档和 GET 回退没有接收或应用该参数。

离线构造：

```text
垂直档失败
综合档返回一条研发费用结果
调用：search_wechat("研发费用", size=1, time_filter="1m")
```

观察结果：

```json
{
  "total": 1,
  "caveat": "垂直档失败；改用综合档取到 1 条微信直链"
}
```

**影响**：调用方要求最近一个月，实际可能收到任意时间的文章；当前返回没有 `filter_acknowledged` 字段，也没有其他明确说明筛选已丢失的标记。

**建议**：

- 将 `time_filter` 传递到所有支持该参数的档位。
- 不支持筛选的 Fallback 要么不返回结果，要么在顶层明确返回 `filter_acknowledged=False` 和说明。
- 不得静默交付未筛选结果。

**验收标准**：

- `time_filter="1m"` 时，最终结果必须满足筛选，或明确返回筛选未生效。
- 未筛选调用不受影响。

### 5.7 P1：`_finalize()` 在检查有效链接前截断

**位置**：`scripts/tax_wechat.py` 的 `_finalize()`

**证据等级**：B

当前先执行 `results = results[:size]`，再统计 `lost_link`。

合成输入：

```text
第 1 条：无有效链接
第 2 条：有效微信链接
size=1
```

观察结果：

```json
{
  "total": 0,
  "fetch_failed": true,
  "error": "元宝给出 1 条结果，但没有一条有效的微信文章直链"
}
```

**影响**：后面存在可用文章，但调用方收到整轮失败。

**建议**：

- 先过滤无效链接，再按 `size` 截断。
- 若生产源一次返回数量有限，可适当过取，再用有效结果补齐。
- 部分无效链接仍按 `_partial_error` 记录，但不能让第一条无效链接遮蔽后续有效结果。

**验收标准**：

- 上述输入应交付第 2 条有效文章。
- 全部无效时仍返回 `_fetch_failed`。

### 5.8 P1：元宝握手请求绕开串行闸

**位置**：`scripts/tax_wechat.py` 的 `_approve_handshake()`、`_yuanbao_get()`、`_yuanbao_post()`

**证据等级**：B

`_approve_handshake()` 直接调用：

```python
sess.get(YUANBAO_APPROVE, params=params, timeout=TIMEOUT, verify=False)
```

离线记录：

```json
{
  "direct_get_calls": 1,
  "payload_returned": true,
  "response_closed": false
}
```

**影响**：每次拿到卡片后的握手不受 `yuanbao_gate` 和 `YUANBAO_MIN_INTERVAL` 控制，形成额外请求峰值。

**建议**：

- 握手请求统一经过 `_yuanbao_get()` 或等价的受闸封装。
- 握手响应显式关闭。
- 如果确认握手不是通道必需，应记录证据后移除，而不是保留绕闸请求。

**验收标准**：

- 所有元宝请求的最大并发数为 1。
- 握手与检索请求共同遵守最小间隔。

### 5.9 P1：最小间隔不是跨进程保证，且并发线程可能绕过

**位置**：`scripts/tax_wechat.py` 的 `_last_yuanbao_at`、`_yuanbao_get()`、`_yuanbao_post()`

**证据等级**：B

`_last_yuanbao_at` 是进程内全局变量。文件锁只保证同一时刻一个请求，不保证跨进程间隔。

两个独立进程离线探针：

```json
{
  "configured": 1.0,
  "observed": 0.0019359,
  "enforced": false,
  "request_count": 2
}
```

同一进程两个线程同步发起调用，配置间隔 0.25 秒：

```json
{
  "configured": 0.25,
  "observed_gap": 0.0007792
}
```

**原因**：

- 跨进程不共享 `_last_yuanbao_at`；
- 间隔等待发生在进入串行闸之前，两个线程可能都先等待，再依次进入闸内，进入后没有再次检查间隔。

**影响**：多进程或多线程使用时，实际请求频率可能高于配置值。

**建议**：

- 把“检查间隔、等待、更新时间戳”放进同一个串行闸临界区。
- 跨进程最后请求时间写入锁文件或状态文件。
- 获得锁后再次计算等待时间。

**验收标准**：

- 两个独立进程的请求间隔不小于配置值。
- 两个并发线程的请求间隔不小于配置值。
- 串行并发峰值仍为 1。

### 5.10 P1：两个通道的锁超时异常会穿透公共函数

**位置**：`scripts/tax_http.py` 的 `SerialGate.__enter__()`；`scripts/tax_wechat.py` 的 `_yuanbao_get()`、`_yuanbao_post()`；`scripts/tax_sogou.py` 的 `_fetch()`

**证据等级**：B

`SerialGate` 等待超时时抛 `TimeoutError`。元宝请求封装只捕获 `requests.RequestException`；搜狗 `_fetch()` 只捕获 `_Unavailable` 和 `requests.RequestException`。

闸替身抛 `TimeoutError("lock timeout")` 的离线结果：

```json
{
  "yuanbao_lock_timeout": "TimeoutError: lock timeout",
  "sogou_lock_timeout": "TimeoutError: lock timeout"
}
```

**影响**：

- 直接调用 `search_wechat()` 或 `sogou_search()` 时可能整体抛异常。
- 聚合层 `tax_aggregator.aggregate_search()` 会在线程异常处记录源错误，因此聚合路径不会让整个聚合崩溃，但源错误不是统一的结构化 `_fetch_failed`。
- CLI 直接调用公共函数时可能出现未处理异常。

**建议**：

- 在两个通道的公共入口捕获 `TimeoutError`，转成 `_fetch_failed=True`。
- 错误文案保留“等待串行闸超时”和可操作建议。
- 不要把锁超时误报为 `_zero_hit` 或 `_blocked`。

**验收标准**：

- 闸超时后公共函数返回结构化错误，不抛异常。
- 聚合层仍能继续其他源。

### 5.11 P2：响应上限跨在最后一个 chunk 时可能漏报截断

**位置**：`scripts/tax_wechat.py` 的 `_read_capped()`

**证据等级**：B

`_read_capped()` 只在下一轮循环开始时检查 `total >= MAX_BODY_BYTES`。如果最后一个 chunk 使总量跨过上限，且之后没有下一个 chunk，`truncated` 可能仍为 `False`。

离线输入：

```text
MAX_BODY_BYTES=4194304
第 1 个 chunk=4194294 字节
第 2 个 chunk=20 字节
```

观察结果：

```json
{
  "returned_bytes": 4194304,
  "truncated": false
}
```

**影响**：GET 回退可能把截断响应当作完整响应继续解析；POST 分支当前还忽略了 `_truncated`。

**建议**：

- 当 `total + len(chunk) > MAX_BODY_BYTES` 时立即设置 `truncated=True`。
- POST 分支检查截断标记，明确返回读取失败并进入下一档。

**验收标准**：

- 上述输入必须返回 `truncated=True`。
- 正好等于上限且未超限的响应仍返回 `False`。

## 六、代码结构确认的风险

以下问题已从代码确认，但未在本轮单独构造完整复现样本。

### 6.1 P2：相关性判据过弱

**位置**：`scripts/tax_wechat.py` 的 `_query_tokens()`、`_relevant_only()`

当前规则：

- 检索词按空白切 token；
- title+summary 命中任一 token 即保留；
- 整批零 token 命中即视为推词空批。

风险：

- 多词查询可能混入只共享“国家税务总局”等公共词的无关卡；
- 同义表达但无字面 token 的真实结果可能被误杀；
- “整批零命中”被直接当作站内无结果，证据强度不足。

建议引入更明确的相关性阈值，并区分“无字面命中”“确实无关”“站点推荐空批”。不得只靠 `doc_from=q2q`，当前代码注释也明确说明该字段不能单独作为判据。

### 6.2 P2：Session 和响应资源未完整释放

**位置**：`scripts/tax_wechat.py` 的 `search_wechat()`、`_vertical_search()`、`_plain_search()`、`_approve_handshake()`、`read_article()`

- `search_wechat()` 创建 Session 后没有 `close()`。
- POST 响应没有显式关闭。
- 握手响应没有显式关闭。
- `read_article()` 响应没有显式关闭。

离线记录：

```json
{"session_closed": false}
```

建议使用 `with requests.Session() as sess:` 和 `with response:`，确保所有返回路径都释放资源。

### 6.3 P2：正文只提取 `<p>`，复杂正文覆盖率未知

**位置**：`scripts/tax_wechat.py` 的 `read_article()`

当前只从 `js_content` 中提取 `<p>`。表格、图片型正文、非段落文本可能漏读。本轮只验证一篇正常段落型文章，不能证明复杂文章覆盖率。

建议保留正文容器结构，至少识别表格和图片型正文；无法完整提取时返回明确标记，不把部分文本当作完整正文。

### 6.4 P2：公共参数和外部 JSON 类型校验不足

**位置**：`scripts/tax_wechat.py` 的 `search_wechat()`、`_vertical_search()`、`_plain_search()`

已离线复现：

```text
size=1.5   -> TypeError
size="10"  -> TypeError
size=True  -> 被接受
timings.search="19" -> TypeError
```

建议：

- `size` 必须是正整数，并显式拒绝 `bool`。
- 外部 JSON 字段先做类型检查，异常值进入 `_fetch_failed`，不穿透。
- 公共入口对 `keyword`、`time_filter`、`read_body` 做边界校验。

### 6.5 P2：POST 分支忽略响应截断标记

**位置**：`scripts/tax_wechat.py` 的 `_vertical_search()`、`_plain_search()`

两个分支都接收 `_read_capped()` 的 `_truncated`，但没有使用。若 JSON 被截断，可能进入解析失败并 Fallback；错误原因不够明确。

建议把截断作为独立的响应读取失败返回。

## 七、现有测试问题

### 7.1 测试结果

执行命令：

```text
python -m pytest tests/test_source_defects.py -k "Sogou or Wechat or Yuanbao" -q
```

结果：

```text
9 failed, 81 passed, 345 deselected, 40 subtests passed
266.02s
```

失败用例：

1. `TestPartialRoundLoss.test_wechat_lost_body_is_counted_apart_from_lost_link`
2. `TestPartialRoundLoss.test_wechat_partial_link_loss_names_the_loss`
3. `TestWechatYuanbaoGate.test_yuanbao_requests_go_through_the_gate`
4. `TestWechatSearchZeroHit.test_all_invalid_links_are_failure_not_a_delivered_zero_hit`
5. `TestWechatSearchZeroHit.test_login_wall_is_a_fetch_failure_not_zero_hit`
6. `TestWechatSearchZeroHit.test_result_page_wins_over_keywords_and_antispider_token`
7. `TestWechatSearchZeroHit.test_structurally_broken_page_still_reports_error`
8. `TestWechatEmptyBodyIsItsOwnShape.test_a_nonempty_marker_free_page_still_reports_relayout`
9. `TestWechatEmptyBodyIsItsOwnShape.test_three_shapes_are_three_sentences`

### 7.2 根本原因：测试替身仍按旧 GET-only 实现编写

**位置**：`tests/test_source_defects.py` 的 `_WxSession`、`TestWechatSearchZeroHit._search_with()`、`TestPartialRoundLoss._wechat_round_trip()`

`_WxSession` 只实现 `headers.update` 和 `get()`，测试只替换 `_yuanbao_get`。当前 `search_wechat()` 会先创建真实 `requests.Session()` 并调用 `_vertical_search()` 和 `_plain_search()`，因此这些测试会向元宝发送真实 POST。

影响：

- 测试不再 hermetic；
- 测试结果受当日站点状态影响；
- 运行耗时 266 秒；
- 真实 URL 不含测试桩期待的 `k=`，导致 `fake_read()` 抛 `IndexError`；
- 当前测试不能作为离线门禁。

### 7.3 失败分类

| 失败类型 | 代表用例 | 判断 |
|---|---|---|
| 测试未跟随三档实现 | `test_yuanbao_requests_go_through_the_gate`、两个 `PartialRoundLoss` 用例 | 测试结构失真 |
| 错误文案断言过期 | 登录墙、结构改版、三段式错误文案用例 | 测试断言失真 |
| fixture 与相关性规则不匹配 | `test_result_page_wins_over_keywords_and_antispider_token` |  fixture 标题不含检索词 |
| 暴露真实语义缺陷 | `test_all_invalid_links_are_failure_not_a_delivered_zero_hit` | 无效链接先被过滤成零命中 |

### 7.4 建议

1. 用同时实现 `get()`、`post()`、`close()` 的 Session 替身，或直接替换三个档位函数。
2. 所有元宝契约测试禁止真实网络请求。
3. 为垂直档、综合档、GET 回退分别建立 fixture。
4. 更新错误文案断言，避免测试绑定易变措辞。
5. 增加本文第五节的确定性复现用例。
6. 新用例逐项做变异验证，确认判据真正能失败。

## 八、文档、版本与运行时快照漂移

### 8.1 文档仍描述旧 GET-only 入口

| 文件 | 当前内容 | 问题 |
|---|---|---|
| `SKILL.md` | 版本 `3.62.48`；元宝入口写为 GET SSR | 与工作树 3.62.49 三档实现不一致 |
| `README.md` | 元宝入口写为 GET SSR | 未同步 |
| `search_source/wechat/SKILL.md` | 工作流仍以 GET `/isearch` 为入口 | 未同步 |
| `search_source/wechat/NOTE.md` | 仍把 GET 当现行入口 | 未同步 |
| `references/source_defects.md` | 页型、限流台账仍按旧 GET 描述 | 未同步 |
| `references/commands.md` | 仍写 GET `/isearch` | 未同步 |
| `tests/probe_rate_limit.py` | `_yuanbao_shape()` 仍解析旧 GET HTML | 未覆盖 POST、握手、时间筛选 Fallback |

### 8.2 三个适配器快照不同步

母技能与三个适配器的 `tax_wechat.py` 哈希不同。三个适配器内置的是旧副本，不能获得工作树中的三档 POST 改写。

建议：

1. 先完成生产代码修复和测试稳定，再同步快照。
2. 同步后逐个比对 SHA-256，要求完全一致。
3. 分别运行 API、CLI、MCP 的测试和隔离目录真实调用。
4. 更新版本、CHANGELOG、README、子技能文档和探针。
5. 发布动作仍需本轮明确授权。

## 九、站点侧限制与未定项

以下内容目前没有足够证据下结论：

1. 搜狗数据岛在更多关键词下混入推荐岛的实际频率。
2. 元宝 `timings.search < 120ms` 短接阈值的长期稳定性。
3. 真实多进程并发下锁超时和频率失控的发生频率。
4. 微信表格型、图片型正文的实际漏读率。
5. 三个通道的限流阈值。当前所有功能实调都不是阈值测量。
6. 公众号入口的可点击浏览器回归。内置 Browser viewport 尚未附着，本轮未完成。

不得把上述“未测到”写成“不存在”，也不得把一次成功写成稳定保证。

## 十、修复建议与优先级

### 10.1 第一批：结果语义与安全边界

1. `read_article()` 入口复用 `_safe_mp_link()`，并校验重定向最终主机。
2. 元宝候选处理顺序改为：识别卡片 → 校验链接 → 相关性过滤 → 明确零命中判断。
3. GET 回退移除通用容器类名作为零命中证据。
4. 垂直档 0 卡不再单独构成零命中证据。
5. 搜狗数据岛增加结果区归属和相关性约束。
6. `_finalize()` 先过滤有效链接，再按 `size` 截断。

### 10.2 第二批：筛选传递与保护闸

1. `time_filter` 传递到所有支持档位；不支持时明确返回筛选未生效。
2. 握手请求纳入统一串行闸。
3. 最小间隔检查移入闸内，并跨进程保存最后请求时间。
4. 两个通道捕获 `TimeoutError`，返回结构化 `_fetch_failed`。
5. POST 分支处理响应截断标记。

### 10.3 第三批：资源、类型与正文完整性

1. 使用上下文管理器关闭 Session 和响应。
2. 校验 `size` 和外部 JSON 字段类型。
3. 修正 `_read_capped()` 的末 chunk 截断标记。
4. 改进正文提取，识别表格和图片型正文。

### 10.4 第四批：测试、文档与快照

1. 重建元宝离线测试，禁止真实 POST。
2. 为所有已复现缺陷增加可证伪用例并做变异验证。
3. 更新探针，使其覆盖三档 POST 和握手。
4. 同步版本、CHANGELOG、README、子技能文档和来源缺陷台账。
5. 同步三个适配器快照并核对哈希。
6. 完成浏览器可点击回归后再考虑发布。

## 十一、建议验收用例

| 验收项 | 输入 | 预期 |
|---|---|---|
| 正文 URL 白名单 | `http://127.0.0.1/private` | 发请求前拒绝，HTTP 调用 0 次 |
| 重定向边界 | 微信 URL 跳转到非微信主机 | 拒绝读取最终页面 |
| 无效链接优先于相关性 | 不相关且非微信直链的卡片 | `_fetch_failed=True`，不是 `_zero_hit` |
| 客户端壳 | 只有 `js-results` 容器 | `_fetch_failed=True` |
| 空卡叠加全档失败 | 垂直档 0 卡，后两档失败 | `_fetch_failed=True` |
| 搜狗推荐岛 | 合成推荐 JSON 岛 | 不交付，不判零命中 |
| 时间筛选 Fallback | `time_filter="1m"`，垂直档失败 | 结果满足筛选或明确筛选未生效 |
| 提前截断 | 第一条无效、第二条有效，`size=1` | 交付第二条有效文章 |
| 握手闸 | payload 含 `uuid` | 所有请求并发峰值 1 |
| 跨进程间隔 | 两个进程同步请求 | 实际间隔不小于配置值 |
| 线程间隔 | 两个线程同步请求 | 实际间隔不小于配置值 |
| 锁超时 | 闸替身抛 `TimeoutError` | 公共函数返回 `_fetch_failed` |
| 响应截断 | 最后 chunk 跨过 4MB | `truncated=True` |
| 类型边界 | `size=True`、`size="10"`、`timings.search="19"` | 明确参数错误或 `_fetch_failed`，不抛未处理异常 |
| 测试隔离 | 运行元宝契约测试 | 真实网络请求数 0 |

## 十二、复现命令与记录

### 12.1 相关契约测试

```text
python -m pytest tests/test_source_defects.py -k "Sogou or Wechat or Yuanbao" -q
```

记录：

```text
9 failed, 81 passed, 345 deselected, 40 subtests passed
266.02s
```

### 12.2 哈希核对

```text
sha256sum scripts/tax_wechat.py scripts/tax_sogou.py \
  ../tax-analysis-api/src/tax_engine_api/runtime/scripts/tax_wechat.py \
  ../tax-analysis-cli/src/tax_engine_cli/runtime/scripts/tax_wechat.py \
  ../tax-analysis-mcp/src/tax_engine_mcp/runtime/scripts/tax_wechat.py
```

记录见本文 3.2 节。

### 12.3 真实探测原则

- 单线程；
- 低频；
- 不读取浏览器登录态；
- 不硬编码 Cookie 或 API Key；
- 不打印凭证值；
- 不绕过验证码；
- 403、429、5xx 不重试；
- 功能实调不标记为阈值测量。

## 十三、最终建议

当前三个通道在诊断当日均能取得样本结果，但工作树中的元宝实现尚未完成测试、文档和适配器同步，且存在多项会改变结果语义的确定性问题。

建议按“结果语义与安全边界 → 筛选与保护闸 → 资源与正文完整性 → 测试与发布同步”的顺序处理。修复完成后，先运行零真实网络请求的离线契约测试，再做一次低频三通道受控实测，最后核对三个适配器哈希和文档版本。

本报告不构成修复完成或发布授权。本轮未修改生产代码、未提交、未推送。
