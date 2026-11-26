# 人民法院案例库（rmfyalk）实测档案

> 本文件记 2026-11-25 首次实测与 2026-11-26 复量两轮的全部读数。此前本机对这个站
> **一次请求都没发过**，所以 `references/source_defects.md` 里原先只写"未实现、
> 没有量过就没有记录"。
> 现在墙的形状有了，但仍**没有接入**：本仓库没有任何代码路径向这座站取数。

## 一、页面层：匿名可达

- 首页 `GET https://rmfyalk.court.gov.cn/` ⇒ **200 / 8555 字节**，正文是
  「首页 - 人民法院案例库」。
- **它不下发 `Content-Type` 的 charset**（只有 `text/html`），`requests` 因此回落
  ISO-8859-1，正文成乱码；按 utf-8 解才对。判据是 `r.apparent_encoding`，
  不是 `r.encoding`。这一条与取数无关，但会骗人：乱码看起来像反爬，其实是编码。
- 列表页 `GET /view/list.html` ⇒ **200 / 11261 字节**，标题「法院案例 - 人民法院案例库」，
  挂八枚脚本（jquery、layer、zTree、`/faxin/console.js`、`/faxin/faxin.js`、
  `/asset/js/base.min.js`、`/asset/js/list.js`）。
- 响应头带 `Wzws-Ray: 1129-…-w-waf03yzm`（站方 WAF 的标记头），但**页面照给**，
  没有挑战页、不要求 cookie。⇒ 页面层不是墙。

## 二、接口层：HTTP 200 装业务失败

匿名实测（一发一停 2.6 秒，脚本见本目录 `probe_rmfyalk_wall.py`）：

| 接口 | 方法 | 状态 | 字节 | 响应体逐字 |
| --- | --- | --- | --- | --- |
| `/cpws_al_api/api/cpwsAl/search`（默认参数） | POST | 200 | 30 | `{"msg":"未登录","code":401}` |
| 同上 + 关键词「增值税」 | POST | 200 | 30 | 同上 |
| 同上 + 关键词「税务」+ size=50 | POST | 200 | 30 | 同上 |
| 同上 + UA/Referer/X-Requested-With 全带 | POST | 200 | 30 | 同上 |
| `/cpws_al_api/api/cpwsAl/searchTop10` | POST | 200 | 30 | 同上 |
| `/cpws_al_api/api/cpwsAl/getGroupDatas` `{flag:"tjb"}` | POST | 200 | 30 | 同上 |
| 两枚左侧聚类接口 | POST | 200 | 30 | 同上 |
| `/cpws_al_api/api/user/recordSearchLog` | POST | **401** | 39 | `{"msg":"用户未登录！","code":401}` |
| `/cpws_al_api/api/user/getGdLoginUrl` | POST | 200 | 384 | `{"code":0,…data:"http://…"}` |
| `/cpws_al_api/api/user/getUserInfo` | POST | 200 | — | `{"code":401,…}` |

三条结论：

1. **墙在接口层，不在页面层**；`getGdLoginUrl` 是唯一不认登录态的接口（它给的是授权
   地址，前端 `.replace('http:','https:')` 之后跳走）。
2. **失败用 HTTP 200 装着**，只有 `recordSearchLog` 用真 401。所以判据只能是业务码，
   `status_code == 200` 什么也证明不了。
3. **补浏览器头不松墙**——UA、Referer、X-Requested-With 都加上，读数一字不差。

### 2026-11-26 复量（十发，同脚本 `probe_rmfyalk_wall.py`，一发一停 2.6 秒）

结论：**墙没有动，读数与 11-25 逐字节同形**——search 四档 / searchTop10 /
getGroupDatas / getUserInfo 仍是 200 / 30 字节 / `{"msg":"未登录","code":401}`；
`recordSearchLog` 仍是 **真 401** / 39 字节 / `{"msg":"用户未登录！","code":401}`；
首页 200 / 8555 字节、列表页 200 / 11261 字节不变。唯一差异是
`getGdLoginUrl` 那发从 384 字节变成 392 字节——它回的是带 `signature`/`state`
的授权地址，这两枚本来就是动态串，形状没变。

复量真正量出来的是**自家判据的一句假话**（本轮改口点）：
`tax_http.court_business_error` 旧句子开口就是「法院站回 HTTP 200 但业务失败」，
可这个函数**收不到 status**——把 `recordSearchLog` 那封真 401 的响应体喂进去，
它照样回一句「回 HTTP 200」。判据分支本身全对（该报的报、该放的放、非 dict
不炸），错在句子替状态码作了保，而这句是要进日志、进答句的。3.62.42 起句子改成
「法院站这封响应是业务失败（code=…）」，「多数失败用 200 装着」这句统计陈述
留在本文档与函数注释里，不再进运行时句子。常驻用例
`tests/test_source_defects.py::TestCourtSharedBusinessGuard::test_the_court_sentence_does_not_vouch_for_a_status_code`
用这两封真读数钉住它。

## 三、前端调用原文（将来接入时照这个发）

`list.js` 里一般检索的参数形状：

```js
{page: 1, size: 10, lib: "qb",
 searchParams: {userSearchType: 1, isAdvSearch: "0", selectValue: "qw",
                lib: "cpwsAl_qb", sort_field: ""}}
```

`_handlerList()` 的调用：`$.ajax({type:"post", contentType:"application/json;charset=UTF-8",
url:"/cpws_al_api/api/cpwsAl/search", data: JSON.stringify(param), dataType:"json"})`，
成功判据写在回调里：`response.code == "0" && data.datas && data.totalCount`。
`base.min.js` 里 `code=="401"` 分支的注释是「拿到验证码，去获取用户信息」，
登录走 `account.court.gov.cn` 的 OAuth，退出 iframe 是
`https://account.court.gov.cn/oauth/logout`。

**健康响应的形状**（按 JS 推断，本机没有登录态没取到真样本）：
`{"msg":…,"code":0,"data":{"datas":[…],"totalCount":N}}`。判据函数
`tax_http.court_business_error` 就是按这个形状写的；零条命中（`totalCount:0`）
必须继续是合法答案，不许被拦成失败。

## 四、与 NPC 那族同病不同值（判据不能合并）

NPC 的接口认 `code=200` 为成功（`tax_http.npc_business_error` 按此写），本库认
`code=0`。实测把本库的正常响应 `{"code":0,"msg":"获取成功！"}` 喂给
`npc_business_error`，它会回一句「NPC 回 HTTP 200 但业务失败（code=0…）」——
**把成功当失败**。所以两族各一把尺：`tax_http.court_business_error` /
`tax_http.require_court_ok`。

## 五、为什么判据先备好而源不接

探针把六只**原始**信封（本库未登录、未登录带空 data、文书网 code:9、本库健康对照、
健康零条对照、NPC code:500）喂现有消费面，实测：

- `tax_http.is_fetch_failure` 六只全 False（原始接口信封不带契约键 `_fetch_failed`）；
- `tax_answer._rows_and_error` 六只全部读成「rows=0 且无错」——也就是说，**照现状接进来，
  墙后的空清单会被答成「库里没有」**，正是这条技能反复栽的那件事。

所以顺序是：判据先落地并有常驻用例
（`tests/test_source_defects.py::TestCourtSharedBusinessGuard`），接入这条链再谈；
将来接入时客户端必须自己打 `_fetch_failed`，别指望接口会替你说。