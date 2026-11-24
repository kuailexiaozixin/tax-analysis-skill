# 中国税务报网络报（数字报）的形状与实测读数

本文件只记实测到的形状，全部读数来自 2026-11-24 那八轮只读探针（脚本与原始输出留在 `D:\DeepSeek Harness WorkSpace\.tmp-inspect\netpaper-probe23*.txt`）。工作流在 `search_source/netpaper/SKILL.md`。

## 一、地址形状与出版日历

- **这一站与第六源是两台主机。** `www.ctaxnews.net.cn` 是中国税务报的报纸电子阅览版（方正数字报）；`www.ctaxnews.com.cn` 是中国税网（见 `search_source/ctaxnews/`）。两边模板不共用：`.com.cn` 的正文在 `<article>` / `article-main`，`founder-content` 与 `newsdetatext` 全不存在；数字报反过来——`founder-content`、`newsdetatext` 在，`<article>` 不在。抽取器绝不能互相复用。
- 版面页：`https://www.ctaxnews.net.cn/paper/pc/layout/YYYYMM/DD/node_NN.html`（**带日段**）。裸月段与缺日段的写法实测 403/404。
- 文章页：`…/paper/pc/con/YYYYMM/DD/content_<id>.html`（是 `con/`，不是 `layout/`）。版面页里的 href 是 `../../../con/…`（**三级上跳**），必须按版面页 URL 做 base 解析；写成两级会拼出 `/paper/pc/layout/con/…`，实测 404。
- 每天版面数恒定 8（node_01..08），但**栏目名逐日漂移**：11-17 的第 6 版是「税案传真」、11-18 是「税务研究」、11-20 是「实践探索」。所以栏目只能从页面「第NN版：xxx」字面现读，绝不按版面号硬编。
- 出版日历：30 天连扫第 1 版，200 共 18 天，周几分布 Mon5 / Tue5 / Wed4 / **Thu0** / Fri4 / Sat0 / Sun0。周四、周六、周日实测不发报。**404 是"当天没出报"这条日历事实，不是取数失败**，代码里落成 `no-issue` 一档，别让它冒充当页失败。
- 首页 `http(s)://www.ctaxnews.net.cn/` 回 585 字节壳页（一段 UA 分流 JS），真正的入口是 `/paper/pc/layout/`。

## 二、抽取：正文、标题与图片稿

- **正文在 `<founder-content>…</founder-content>` 里**，实测当天 43 篇全部取到（53~3509 字）。`<div class="newsdetatext">` 那层是壳，直接从它取只拿到十来个字。
- 标题有三种摆法，实测 43/43 全中且互不排斥：`<!--enpproperty … <title>x</title>/enpproperty-->` 注释块、`<h3>`、`<div class="newsdetatit">`。**enpproperty 是注释体**，正则锚点不能带尖括号。
- 元信息同在那块注释里：`<date>`、`<author>`、`<id>`、`<nodeid>`、`<nodename>`、`<siteid>`、`<url>`、`<keyword>`。
- **图片稿**（当天 14/43）：`founder-content` 里的正文为空，`<title>` 是「一版图一」这类占位名，真正可读的字在 `<div class="pic">` 里的图注 `<p>`。本源把它们标 `_image_piece` 并把图注当 content 交回；聚合与判重都不该拿占位名当标题。
- 版面页与文章页都**没有任何 `.pdf` 链接**；`/paper/pc/rss/`、`rss.xml`、`node_01_print.html` 全 404。别按"报纸=有 PDF 版"的常识去找附件。

## 三、没有站内检索：为什么只能扫版面

- 版面页里的检索表单指向 `https://180.76.243.174:8081/servlet/SearchServlet.do`（POST，字段 `contentKey` + hidden `op=single`/`siteID`/`sort=date`）。**这枚接口五种打法全灭**：https（verify  True/False 都试）、根路径、GET 参数四路全是 `SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)'))`；http 明文回 502、0 字节。不是证书配对问题，是 TLS 被直接掐断。
- 当天版面页 19 枚 `<script src>` 全抓下来逐枚看过，唯一接口线索是 `common.js` 里的 `https://sso.ctaxnews.net.cn:9080/SSOv2/`——那是登录口，不是检索。**没有版面清单 API，按日期扫版面是唯一通路。**
- 因此 `search_paper` 的成本是「天数 × 版面数」再加命中的文章页；`fetch_edition` 有六小时缓存，全绿与 `no-issue` 都落缓存，**partial 不落**（半张版面钉六小时等于把一次抖动固化成六小时的错读数）。

## 四、与第六源的重叠裁定（为什么不进聚合）

- 可比 29 枚（图片稿占位名已排除），用三式去 .com.cn 检索（`match=title` 原样带标点 / `q=` 原样整串 / `q=` 前 12 字），判据取标题字面互相包含：**同稿仅 6 枚、定位不到 23 枚**（命中率 20.7%）。
- **反证**：取三式全空的 8 枚，拿专名（即墨税务、邗江税务、福建税务、雄安新区离境…）配 11-20..11-24 日期窗全文检索，**八枚全 `total=0`** ⇒ 数字报大面积独占，不是"第六源已经装着同一堆料"。
- 证据强度如实记：单日样（2026-11-24），且 `.com.cn` 的 `q` 不分词、按整串匹配，使"搜不到"不等于"库里必无"；但专名反证足以坐实独占这件事的方向。
- **同稿异题**是接入方式的决定因素：同一篇稿 `.com.cn` 用全题「本溪高新区税务分局强化医药行业税收监管——从医药推广费用风险核查入手」，数字报用半题「从医药推广费用风险核查入手」。聚合层按标题字符三元 Jaccard 去重（阈值 0.7），进了聚合就会把两条不同地址的稿子错并成一条 ⇒ 本源只走独立取数口（`POST /api/paper`、`tax-doc papers`、MCP `read_tax_paper`），不进 `DEFAULT_SOURCES`。
- 拿正文短语去重搜也不可靠：取正文开头 16 字当短语，命中的三枚里两枚是栏目套话（「■税案评析 本案是一起较为典」`foundNum=18`，首行还是别日别稿）⇒ 正文短语法不能作重叠判据。

## 五、复测入口

- 取一天整版：`python scripts/tax_paper.py --date 2026-11-24 --edition 6`；对照缓存复用看输出里的 `network` 与 `_from_cache`。
- 关键词扫版：`python scripts/tax_paper.py "虚开" --days 10 --editions 6,7`。
- 出报日历：`python scripts/tax_paper.py --list-days --from 2026-11-16 --to 2026-11-24`。
- 检索接口是否复活：照第一节第三行那五种打法重打一次；接口通了，`search_paper` 就该改成先问站内、扫版面退为兜底。
- 外部线索的教训留档：GitHub `blueadark/tax2.0` 那条硬编 `/paper/pc/layout/202604/node_03.html` 缺日段实测 404，它写的 chinatax 正则 `content/\d+\.html` 与真实形状 `/c5253027/content.html` 不匹配。**外部项目的地址与正则一律实测再抄。**
