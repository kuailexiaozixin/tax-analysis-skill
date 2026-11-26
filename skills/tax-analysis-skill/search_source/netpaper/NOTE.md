# 中国税务报网络报（数字报）的形状与实测读数

本文件只记实测到的形状。读数来自两轮：**2026-11-24 那八轮只读探针**（脚本与原始输出留在 `D:\DeepSeek Harness WorkSpace\.tmp-inspect\netpaper-probe23*.txt`）与 **2026-11-26 那一轮复跑**（六把 `probe41a`–`probe41f`，约 90 次请求，逐把读数落 `.tmp-inspect\probe41*-run.txt`，页面存证 `netpaper-node06-20261125.pdf`）。工作流在 `search_source/netpaper/SKILL.md`。

## 一、地址形状与出版日历

- **这一站与第六源是两台主机。** `www.ctaxnews.net.cn` 是中国税务报的报纸电子阅览版（方正数字报）；`www.ctaxnews.com.cn` 是中国税网（见 `search_source/ctaxnews/`）。两边模板不共用：`.com.cn` 的正文在 `<article>` / `article-main`，`founder-content` 与 `newsdetatext` 全不存在；数字报反过来——`founder-content`、`newsdetatext` 在，`<article>` 不在。抽取器绝不能互相复用。
- 版面页：`https://www.ctaxnews.net.cn/paper/pc/layout/YYYYMM/DD/node_NN.html`（**带日段**）。裸月段与缺日段的写法实测 403/404；2026-11-26 复量：带日段 200／36,192 字节，裸月段与缺日段各 404／353 字节，一字不差。
- 文章页：`…/paper/pc/con/YYYYMM/DD/content_<id>.html`（是 `con/`，不是 `layout/`）。版面页里的 href 是 `../../../con/…`（**三级上跳**），必须按版面页 URL 做 base 解析；写成两级会拼出 `/paper/pc/layout/con/…`，实测 404。
- 每天版面数恒定 8（node_01..08），但**栏目名逐日漂移**：11-17 的第 6 版是「税案传真」、11-18 是「税务研究」、11-20 是「实践探索」。所以栏目只能从页面「第NN版：xxx」字面现读，绝不按版面号硬编。2026-11-26 八版现读：11-25＝`税收要闻/要闻/税务新闻/税务新闻/财税理论专刊/实践探索/税务研究/博览`，11-23＝`税收要闻/要闻/税务新闻/税务新闻/税收文化专刊/新青年/税史春秋/税苑`，11-24＝`税收要闻/要闻/税务新闻/广告/税收法治专刊/税案传真/法治视点/税收诚信`。
- **同一天可以有两个版面同名**（11-23 与 11-25 的 node_03 与 node_04 都叫「税务新闻」）。⇒ 按栏目名反推版面号一定会撞，只能版面号与名字各记各的。这条是 2026-11-26 量到的，上一轮没记。
- **node_04 可以是「广告」版**（11-24 那一期），那一版整版只 2 篇：1 篇真稿（3,574 字）+ 1 篇图片稿（正文 0 字）。⇒ 「按版面号取当天要闻」这条路会撞进广告版。
- 出版日历：30 天连扫第 1 版，200 共 18 天，周几分布 Mon5 / Tue5 / Wed4 / **Thu0** / Fri4 / Sat0 / Sun0。周四、周六、周日实测不发报。**404 是"当天没出报"这条日历事实，不是取数失败**，代码里落成 `no-issue` 一档，别让它冒充当页失败。2026-11-26 复量 11-01..11-30：出报 15 天＝`25,24,23,20,18,17,16,13,11,10,9,6,4,3,2`，未出 15 天＝`30,29,28,27,26,22,21,19,15,14,12,8,7,5,1`；本轮这 15 天里周四／周六／周日一枚都不在 200 之列，与旧记同向。**已知缺口：本轮没有重打「200 的日子按周几分布」那张表**，只数了本轮这 15 天里没出现周四/周六/周日，"周四停刊"这条仍是 2026-11-24 那一轮的读数。
- 首页 `http(s)://www.ctaxnews.net.cn/` 回 585 字节壳页（一段 UA 分流 JS），真正的入口是 `/paper/pc/layout/`。

## 二、抽取：正文、标题与图片稿

- **正文在 `<founder-content>…</founder-content>` 里**，实测当天 43 篇全部取到（53~3509 字）。`<div class="newsdetatext">` 那层是壳，直接从它取只拿到十来个字。
- 标题有三种摆法，实测 43/43 全中且互不排斥：`<!--enpproperty … <title>x</title>/enpproperty-->` 注释块、`<h3>`、`<div class="newsdetatit">`。**enpproperty 是注释体**，正则锚点不能带尖括号。
- 元信息同在那块注释里：`<date>`、`<author>`、`<id>`、`<nodeid>`、`<nodename>`、`<siteid>`、`<url>`、`<keyword>`。
- **图片稿**（当天 14/43）：`founder-content` 里的正文为空，`<title>` 是「一版图一」这类占位名，真正可读的字在 `<div class="pic">` 里的图注 `<p>`。本源把它们标 `_image_piece` 并把图注当 content 交回；聚合与判重都不该拿占位名当标题。
- 版面页与文章页的**响应头不带 charset**（`Content-Type: text/html`），`requests` 于是按 ISO-8859-1 解 ⇒ 直接用 `r.text` 判中文锚，一枚都判不中（2026-11-26 亲测：版面页 `r.text` 里「税收要闻」False、「第01版」False，而同一份 `r.content` 按 utf-8 解 True）。生产 `_http_get` 已经把这类响应补成 utf-8，**复测必须走 `_http_get`，别自己拿 requests 读 `.text` 再判中文**。
- **整版 PDF：版面页每版挂一枚，址在 `data-url` 上**（2026-11-26 量到，改写此前那句假话）。逐字形状：

  ```html
  <em>第01版：税收要闻</em>
  <a href="javascript:;" class="pdf-btn" onclick="downloadPDF(this)"
     data-url="../../../att/202611/25/c963147d-a52a-4509-a201-861d4308ad79.pdf"
     target="_self"></a>
  <span class="download-warning">您没有下载权限</span>
  ```

  - 覆盖度：三天 × 八版 **24/24 每版恰一枚**，全部 `200` / `application/pdf` / 头字节 `%PDF`；最小 844,149 字节（11-25 node_06）、最大 5,236,296 字节（11-24 node_04 那版广告）。全量下过最小那枚验完整性：Content-Length 与实际字节相符、尾含 `%%EOF`。
  - **址不可预测**：文件名是 uuid4，逐版互不相干。三种直觉拼法（`…/att/202611/25/node_01.pdf`、`/att/202611/25/<uuid>.pdf`、`/paper/att/…`）实测**全 404／353 字节** ⇒ 只能现读版面页的 `data-url`，不许猜。
  - 文章页确实没有：三篇样本里 `data-url` 0 枚、`att/` 字样 0 处 ⇒ PDF 只在版面页。
  - **那句「您没有下载权限」不拦 HTTP**：前端 `downloadPDF(obj)` 只在 `hasAuthorize` 为真时才 `window.open(data-url)`，否则弹提示；权限判定走 `GET <xyUrl>/amuc/api/read/ifAccess`（带 `mid_fouNder` 这枚 SSO cookie 当 uid）。干净会话（`session.cookies` 数 0）直取该址实测 **200 / `%PDF`** ⇒ 页面上那行文案不是取不到的证据。
  - 本层**只交回链接、不下载**：一版 0.8～5.2MB×8，且本机没有可用的 PDF 文本层解析器（`references/source_defects.md` 记过这台机器只有 pdfplumber 解得动、`pypdf`/`fitz` 未装、Read 工具读 PDF 因缺 poppler 必失败）。
  - 生产落点：`scripts/tax_paper.py` 的 `_PDF_DATA_URL_RE` / `_edition_pdf(node_html, base_url)`；`fetch_edition` 交回的字典多一枚 `pdf_url`（读不到是空串，不猜）。
  - 此前这句是**假话**（2026-11-24 记）：「版面页与文章页都没有任何 `.pdf` 链接」。它的成因是只扫了 `href` 与 `src` 两类属性——版面页里 `.pdf` 字样其实有 3 处（CSS 类名 `.pdf-btn`、上面那枚 `data-url`、JS 里的 `$('.pdf-btn')`），`href` 含 .pdf 与 `src` 含 .pdf 才各是 0。**教训已固化成用例**：`test_href_and_src_alone_would_have_missed_it` 与 `test_the_css_and_js_mentions_are_not_a_link`。「报纸=有 PDF 版」这个常识这次站得住，只是它挂在 `data-*` 上。
- `/paper/pc/rss/`、`rss.xml`、`node_01_print.html` 全 404（2026-11-26 复量同数：404／353 字节）。

## 三、没有站内检索：为什么只能扫版面

- 版面页里的检索表单指向 `https://180.76.243.174:8081/servlet/SearchServlet.do`（POST，字段 `contentKey` + hidden `op=single`/`siteID`/`sort=date`）。**这枚接口五种打法全灭**：https（verify  True/False 都试）、根路径、GET 参数四路全是 `SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)'))`；http 明文回 502、0 字节。不是证书配对问题，是 TLS 被直接掐断。2026-11-26 复打五路，仍是同一组读数。
- 当天版面页 19 枚 `<script src>` 全抓下来逐枚看过，唯一接口线索是 `common.js` 里的 `https://sso.ctaxnews.net.cn:9080/SSOv2/`——那是登录口，不是检索（2026-11-26 复量该址 200／14,385 字节）。版面页里另外那枚 `/amuc/api/read/ifAccess` 是下载权限判定，不是检索。**没有版面清单 API，按日期扫版面是唯一通路。**
- 因此 `search_paper` 的成本是「天数 × 版面数」再加命中的文章页；`fetch_edition` 有六小时缓存，全绿与 `no-issue` 都落缓存，**partial 不落**（半张版面钉六小时等于把一次抖动固化成六小时的错读数）。

## 四、与第六源的重叠裁定（为什么不进聚合）

- 可比 29 枚（图片稿占位名已排除），用三式去 .com.cn 检索（`match=title` 原样带标点 / `q=` 原样整串 / `q=` 前 12 字），判据取标题字面互相包含：**同稿仅 6 枚、定位不到 23 枚**（命中率 20.7%）。
- **反证**：取三式全空的 8 枚，拿专名（即墨税务、邗江税务、福建税务、雄安新区离境…）配 11-20..11-24 日期窗全文检索，**八枚全 `total=0`** ⇒ 数字报大面积独占，不是"第六源已经装着同一堆料"。
- 证据强度如实记：单日样（2026-11-24），且 `.com.cn` 的 `q` 不分词、按整串匹配，使"搜不到"不等于"库里必无"；但专名反证足以坐实独占这件事的方向。这一节 2026-11-26 未重做（要重做就是几十发检索 + 逐篇比标题，留作下一轮）。
- **同稿异题**是接入方式的决定因素：同一篇稿 `.com.cn` 用全题「本溪高新区税务分局强化医药行业税收监管——从医药推广费用风险核查入手」，数字报用半题「从医药推广费用风险核查入手」。聚合层按标题字符三元 Jaccard 去重（阈值 0.7），进了聚合就会把两条不同地址的稿子错并成一条 ⇒ 本源只走独立取数口（`POST /api/paper`、`tax-doc papers`、MCP `read_tax_paper`），不进 `DEFAULT_SOURCES`。
- 拿正文短语去重搜也不可靠：取正文开头 16 字当短语，命中的三枚里两枚是栏目套话（「■税案评析 本案是一起较为典」`foundNum=18`，首行还是别日别稿）⇒ 正文短语法不能作重叠判据。

## 五、复测入口

- 取一天整版：`python scripts/tax_paper.py --date 2026-11-24 --edition 6`；对照缓存复用看输出里的 `network` 与 `_from_cache`，`pdf_url` 那一枚一并看。
- 关键词扫版：`python scripts/tax_paper.py "虚开" --days 10 --editions 6,7`。
- 出报日历：`python scripts/tax_paper.py --list-days --from 2026-11-16 --to 2026-11-24`。
- 整版 PDF 那一层：现读版面页 `data-url` 枚数（要 24/24 才叫没改版）、只发 HEAD 或首段字节验魔数，**不要默认全量下**（一版到 5MB）；页面文案「您没有下载权限」不计入失败。判据走 `tax_paper._http_get`（第三节末与第二节那条 charset 坑）。
- 检索接口是否复活：照第一节第三行那五种打法重打一次；接口通了，`search_paper` 就该改成先问站内、扫版面退为兜底。
- 外部线索的教训留档：GitHub `blueadark/tax2.0` 那条硬编 `/paper/pc/layout/202604/node_03.html` 缺日段实测 404，它写的 chinatax 正则 `content/\d+\.html` 与真实形状 `/c5253027/content.html` 不匹配。**外部项目的地址与正则一律实测再抄。**
