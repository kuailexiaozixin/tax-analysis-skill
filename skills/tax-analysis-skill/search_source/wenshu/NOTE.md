# 中国裁判文书网（wenshu）实测档案

> 本文件记 2026-11-25 首次实测的全部读数。此前本机对这个站**一次请求都没发过**。
> 墙的形状量清了；这一层仍**没有接入**，本仓库没有任何代码路径向它取数。

## 一、页面层：匿名可达，不下发 cookie

- 首页 `GET https://wenshu.court.gov.cn/` ⇒ **200 / 22309 字节**（`charset=utf-8`），
  无 `Set-Cookie`、无 WAF 挑战页；正文里只有 `function login(url)` 与 `diy:lawyee`
  这类登录入口字样。响应头带 `WZWS-RAY: 1129-…`、`X-Frame-Options: SAMEORIGIN`，
  以及一枚**畸形 CSP**：`Content-Security-Policy: : default-src 'self'`（冒号前空着）。
- 检索页 `GET /website/wenshu/181217BMTKHNT2W0/index.html` ⇒ **200 / 14179 字节**，
  标题「文书列表」，页面上没有任何挑战字样。首页还挂 12 枚脚本、31 个 `html/aspx` 链接
  （含 `?s8=01…11` 的案件类型入口、登录/注册页、四种少数民族语言页）。
- `POST /website/wenshu/181107ANFZ0BXSK4/index.html?docId=` ⇒ **200 / 10418 字节**，
  但回的是「文书全文」那个 **HTML 页面本身**，不是数据接口。

⇒ 页面层不是墙。别把"能打开列表页"当成"能拿到数据"。

## 二、接口层：匿名一律不给数据，三种形状

一发一停 2.6 秒（脚本 `probe_wenshu_wall.py`）：

| 接口 | 方法 | 状态 | 字节 | 响应 |
| --- | --- | --- | --- | --- |
| `/website/parse/rest.q4w`（空 body） | POST | 200 | 76 | `{"code":9,"description":null,"secretKey":null,"result":null,"success":false}` |
| 同上（只带 construct/pageId/WebSite） | POST | 200 | 76 | 同上，**一字不差** |
| 同上（带明文假 ciphertext + 真 queryCondition） | POST | 200 | 76 | 同上 |
| 同上 | GET | **405** | 696 | Tomcat 8.5.91 中文错误页，`Allow: POST` |
| `/api/fp/ah` | POST | 200 | **0** | 空响应，无 `Content-Type` |
| `/api/fp/cprq` | POST | 200 | **0** | 同上 |
| `/api/fp/gjjsClick` | POST | 200 | **0** | 同上 |
| `/down/isDown` | POST | 200 | 53 | `{"msg":"文书解码失败，无法下载!","code":1}` |

三条结论：

1. **失败用 HTTP 200 装着**，`code=9` + `success:false`；带不带参数完全同形，
   所以"参数对不对"在这一层根本看不出来。
2. **另有空响应一族**：三枚 `/api/fp/*` 回 200/0 字节。判 `json.loads` 之前要先判
   字节数，否则 `JSONDecodeError` 会被当成解析 bug 去查。
3. CORS 头开得很宽（`Access-Control-Allow-Credentials: true`、
   `Allow-Methods: POST, GET`），但**这不表示匿名能取到数据**——实测就是取不到。

## 三、检索参数要前端现算（这是它比案例库难的地方）

`181217BMTKHNT2W0/index.js?v=1.6`（200 / 189986 字节）里 `loadData1545184311000`：

```js
var ciphertext = cipher();
$.WebSite.refreshModule($mid, {
  sortFields: "s50:desc", ciphertext: ciphertext,
  pageNum: pageNum, pageSize: pageSize,
  queryCondition: JSON.stringify(postData)
});
```

`strToBinary.js`（842 字节）全文很短：

```js
function cipher() {
  var date = new Date();
  var timestamp = date.getTime();
  var salt = $.WebSite.random(24);
  var iv = date.getFullYear() + 补零(date.getMonth() + 1) + 补零(date.getDate());
  var enc = DES3.encrypt(timestamp, salt, iv).toString();
  return strTobinary(salt + iv + enc);
}
```

`strTobinary` 是逐字符 `charCodeAt().toString(2)` 拼接。站点配置 `$website` 里还带
`enCode`（一枚 32 位串）、`dataParsePath:"/website/parse/rest.q4w"`、`loggedFlag:true`、
`name:"裁判文书二期"`。列表字段字典在 `wenshulist1.js`（221375 字节）：s1 案件名称、
s2 法院名称、s5 文书ID、s7 案号、s8 案件类型、s9 审判程序、s11 案由……

⇒ **本仓库不重造这套 DES3**：它依赖当日 iv 与站方 `enCode`，一旦站点轮换就变成
"看起来像反爬的静默失败"，正是最难查的那一类。要接这一层，先接的是浏览器路径
（`scripts/tax_browser.BrowserSession` 那一套），不是自己算参数。

## 四、判据与用例

`tax_http.court_business_error`／`tax_http.require_court_ok` 认 `code=0` 为成功、
`success is False` 先报失败，报错句里点名「裁判文书网的检索参数要前端 DES3 现算」。
与 NPC 那把 `tax_http.npc_business_error`（认 `code=200`）**不许合并**。
常驻用例在 `tests/test_source_defects.py::TestCourtSharedBusinessGuard`，
其中 `test_the_two_guards_are_not_one_ruler` 钉住两把尺的分歧。

## 五、为什么判据先备好而源不接

同 `search_source/rmfyalk/NOTE.md` 第五节：这六只原始信封喂 `tax_http.is_fetch_failure`
全 False、喂 `tax_answer._rows_and_error` 全部读成「rows=0 且无错」——照现状接进来，
墙后的空响应会被答成「库里没有这份文书」。将来接入时客户端必须自己打 `_fetch_failed`。