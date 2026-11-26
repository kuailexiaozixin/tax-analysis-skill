#!/usr/bin/env python3
"""路由与检索词整形的离线用例。

这里每一条都只依赖字符串与打桩，不联网：改别名表、改排序、改降级规则之后
跑这一份就能知道有没有把已经修好的归类撞回去。联网那部分（检索词真不真能
翻出文件）由 test_tax_search.py 的 sta 专题可达性用例负责，两边不重复。

用法：python tests/test_routing_terms.py
"""

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tax_answer as AN          # noqa: E402
import tax_analyze as AA         # noqa: E402
import tax_evidence as E         # noqa: E402
import tax_fgk                   # noqa: E402
import tax_search as T           # noqa: E402
import tax_terms as TT           # noqa: E402
import tax_web_search as W       # noqa: E402


def test_strip_options():
    # 选项里的干扰税种不能参与归类：题干问车船税，选项里有"扣缴义务人"
    stem = TT.strip_options(
        "下列各项中，符合车船税征收管理规定的是（ ）。　"
        "A.扣缴义务人代收代缴；B.纳税地点为登记地；C.次月发生义务；D.使用人为纳税人")
    assert "车船税" in stem and "扣缴义务人" not in stem, stem
    # 题干自己写着 A. 这种编号但不是选项（不足两个并列标记）时不截断
    plain = "增值税的税率 A.13% 是怎么规定的"
    assert TT.strip_options(plain) == plain, "单个 A. 不该被当成选项头"
    # 只有 A、B 两个标记也要截：两选项题真实存在
    two = TT.strip_options("契税的纳税人是谁？　A.卖方；B.买方")
    assert two == "契税的纳税人是谁？", two
    assert TT.strip_options("") == ""
    print("  [PASS] strip_options：两个以上并列标记才截，单字母编号不误伤")


def test_cited_documents():
    q = "查询、阅读、分析、解读《关于企业重组业务所得税处理有关征管问题的公告》（2026年第13号）"
    cited = TT.cited_documents(q)
    assert len(cited) == 1, cited
    assert cited[0]["doc_number"] == "2026年第13号", cited[0]
    assert cited[0]["core"].startswith("企业重组"), cited[0]
    # 财税〔2009〕59号 这种带方括号的写法也要认
    assert TT.doc_number_of("依据财税〔2009〕59号文件") == "财税〔2009〕59号"
    assert TT.doc_number_of("没文号") == ""
    # 没点名的题面不该产出点名结果
    assert TT.cited_documents("研发费用加计扣除比例是多少") == []
    print("  [PASS] cited_documents：书名号标题与两种文号写法都能取出")


def test_title_candidates():
    title = "国家税务总局关于企业重组业务所得税处理有关征管问题的公告"
    cands = TT.title_candidates(title)
    # 由长到短，且第一个短词必须落在"企业重组"这个真正的主题上
    assert cands[0].startswith("企业重组"), cands
    assert "企业重组" in cands, cands
    assert len(set(cands)) == len(cands), f"候选词有重复：{cands}"
    assert all(len(c) >= 2 for c in cands), cands
    # 短标题剥掉文种之后不该再产出碎词候选
    assert TT.title_candidates("增值税暂行条例") == ["增值税"], \
        TT.title_candidates("增值税暂行条例")
    print(f"  [PASS] title_candidates：{cands}")


def test_title_similarity_orders_document_first():
    want = title = "关于企业重组业务所得税处理有关征管问题的公告"
    doc = "国家税务总局关于企业重组业务所得税处理有关征管问题的公告"
    interp = "关于《国家税务总局关于企业重组业务所得税处理有关征管问题的公告》的解读"
    other = "国家税务总局关于非货币性资产投资企业所得税有关征管问题的公告"
    assert TT.title_similarity(want, doc) >= TT.title_similarity(want, other)
    # 解读与原文字面几乎并列，靠 tax_answer 里的排序惩罚分开，这里只验纯相似度
    assert TT.title_similarity(want, interp) > TT.title_similarity(want, other)
    assert TT.title_similarity("", "x") == 0.0
    print("  [PASS] title_similarity：目标文件高于同域其他文件")


# 点名「税收征管法」时，总局法规库按 tax_terms.title_candidates 召回的
# 六条标题（按字符命中率降序）。六条里没有一条是《中华人民共和国税收征收管理法》：
# 排第一那份只是在自己的标题里引用了这部法，字符命中率却是满分 1.0。
FGK_SIX_FOR_ZGL = [
    "国家税务总局关于农业税、牧业税、耕地占用税、契税征收管理暂参照"
    "《中华人民共和国税收征收管理法》执行的通知",
    "国家税务总局关于发布《税收减免管理办法》的公告",
    "深化税收征管体制改革持续加力",
    "第一届“一带一路”税收征管合作论坛",
    "国家税务总局关于印发全国统一税收执法文书式样的通知",
    "欠税公告办法（试行）",
]


def test_title_identity_tells_named_from_cited():
    """点名文件要判的是"是不是这一份"，字符命中率判不出这个区别。"""
    for t in FGK_SIX_FOR_ZGL:
        assert TT.title_similarity("税收征管法", t) > 0, t      # 老尺子照样给分
        assert TT.title_identity("税收征管法", t) == "", \
            f"标题里引用了这部法，被认成了它本身：{t}"
    # 该认的两档：多一个发文机关前缀算字面同一，漏字简称算缩略同一
    assert TT.title_identity(
        "关于企业重组业务企业所得税处理有关征管问题的公告",
        "国家税务总局关于企业重组业务企业所得税处理有关征管问题的公告") == "same"
    assert TT.title_identity("税收征管法",
                             "中华人民共和国税收征收管理法") == "abbrev"
    # 文种不同就不是同一份：点《增值税法》时不能拿《增值税法实施条例》顶上，
    # 也不能拿"增值税法施行后……的公告"顶上——后者的核心标题含住前者。
    assert TT.title_identity("增值税法", "中华人民共和国增值税法实施条例") == ""
    assert TT.title_identity("增值税法",
                             "国家税务总局关于增值税法施行后若干征管事项的公告") == ""
    assert TT.title_identity("", "中华人民共和国增值税法") == ""
    print("  [PASS] title_identity：引用式标题与邻近文种都不再冒充被点名的文件")


def test_locate_cited_document_needs_an_identity_match():
    """桩打在 fgk 检索入口：定位这一层的判据是"是不是这一份"，不是谁排前面。"""
    real = AN.FGK.search_fgk

    def stub(rows):
        AN.FGK.search_fgk = lambda kw, size=6: {
            "results": [{"title": t, "url": "u%d" % i}
                        for i, t in enumerate(rows)]}

    try:
        stub(FGK_SIX_FOR_ZGL)
        rows, tried, state = AN.locate_cited_document("税收征管法")
        assert tried and rows, (tried, rows)
        assert state == "", state          # 取成了，只是没一份是目标
        assert all(not r.get("_cited_identity") for r in rows), \
            [r.get("_cited_identity") for r in rows]

        # 真目标混在这一堆里时必须排到第一，哪怕别人的字面命中率一样高
        stub([FGK_SIX_FOR_ZGL[0], "中华人民共和国税收征收管理法"])
        rows, _, state = AN.locate_cited_document("税收征管法")
        assert state == "", state
        assert rows[0]["title"] == "中华人民共和国税收征收管理法", rows[0]
        assert rows[0]["_cited_identity"] == "abbrev", rows[0]
    finally:
        AN.FGK.search_fgk = real
    print("  [PASS] locate_cited_document：无同一性证据就不打点名标记")


def _stub_by_word(table, default=None):
    """按候选词返回预制信封；没列出的词走 default。记下发过哪些词。"""
    seen = []

    def stub(keyword, size=6, **kw):
        seen.append(keyword)
        if keyword in table:
            return table[keyword]
        return default if default is not None else {"results": [], "_empty_reason":
                                                    "0 条：这一词在站内没有命中"}
    stub.seen = seen
    return stub


def test_cited_locate_separates_channel_failure_from_no_hit():
    """零召回必须分得清"没连上"与"库里没有"——两句结论对读者完全不同。

    实测（2026-11-24，六档全过）：改之前 `search_fgk` 抛异常被 `except Exception:
    continue` 无痕吞掉，交回 _error 时循环又从不读那两枚键，于是 HTTP 500 那一轮
    与诚实 0 命中那一轮，compose 给出的 cited_note 逐字相同，而且那句「召回的标题
    都只是在字面上含住这几个字」在一条都没召回时是关于站点的假陈述。
    """
    real = AN.FGK.search_fgk
    want = "税收征管法"

    def composed(state, rows):
        plan = AN.build_plan("请解读《税收征管法》修订草案")
        plan["terms"] = dict(plan.get("terms") or {}, cited=[{"title": want}])
        plan["rounds"] = []
        plan["cited_located"] = bool(rows) and bool(rows[0].get("_cited_identity"))
        plan["cited_state"] = state
        plan["evidence"] = E.grade_all(rows)
        return AN.compose(plan)

    try:
        # 每一次检索都失败（交回 _error，不抛异常）→ channel-failed
        AN.FGK.search_fgk = _stub_by_word(
            {}, default={"results": [], "_error": "search5 检索失败：HTTP 500",
                         "_fetch_failed": True})
        rows, tried, state = AN.locate_cited_document(want)
        assert not rows and tried, (rows, tried)
        assert state.startswith("channel-failed"), state
        assert "HTTP 500" in state, state
        note = composed(state, rows)["cited_note"]
        assert "检索通道没取成" in note and "不是库里没有" in note, note
        assert "字面上含住" not in note, note      # 零召回时这句是假陈述

        # 每一次都成功、站点诚实回 0 条 → no-hit，且不许报成通道故障
        AN.FGK.search_fgk = _stub_by_word({})
        rows, tried, state = AN.locate_cited_document(want)
        assert not rows and tried, (rows, tried)
        assert state.startswith("no-hit"), state
        note = composed(state, rows)["cited_note"]
        assert "逐枚试检都是 0 条" in note, note
        assert "检索通道没取成" not in note, note

        # 候选词直接抛异常 → 同样记成 channel-failed，不再无痕丢弃
        def boom(keyword, size=6, **kw):
            raise TimeoutError("goto timeout")
        AN.FGK.search_fgk = boom
        rows, tried, state = AN.locate_cited_document(want)
        assert not rows and tried, (rows, tried)
        assert state.startswith("channel-failed"), state
        assert "TimeoutError" in state, state

        # 有失败也有取成的（取到的不是目标）→ partial：旧那句仍为真，但要补
        # "这一轮不完整"，否则目标可能落在没取成的那枚底下却无人知晓
        n = {"i": 0}

        def flaky(keyword, size=6, **kw):
            n["i"] += 1
            if n["i"] == 1:
                return {"results": [], "_error": "search5 检索失败：HTTP 500",
                        "_fetch_failed": True}
            return {"results": [{"title": FGK_SIX_FOR_ZGL[0], "url": "u110"}]}
        AN.FGK.search_fgk = flaky
        rows, tried, state = AN.locate_cited_document(want)
        assert rows, rows
        assert state.startswith("partial"), state
        note = composed(state, rows)["cited_note"]
        assert "字面上含住" in note and "没取成" in note, note

        # 控制组：全都取成且第一条就是目标 → 空状态、无 note
        AN.FGK.search_fgk = _stub_by_word(
            {want: {"results": [{"title": "中华人民共和国税收征收管理法",
                                 "url": "u-law"}]}})
        rows, tried, state = AN.locate_cited_document(want)
        assert state == "", state
        assert composed(state, rows)["cited_note"] == "", "定位成功不该有提醒"
    finally:
        AN.FGK.search_fgk = real
    print("  [PASS] 点名定位四档互斥：channel-failed / no-hit / partial / 取成")


def test_unlocated_cited_document_falls_back_with_a_note():
    """没定位到点名文件：主依据回到分层判据，并且把"没定位到"写进答案层。"""
    plan = AN.build_plan("请使用技能查询、阅读、分析、解读《税收征管法》修订草案")
    plan["terms"] = dict(plan.get("terms") or {}, cited=[{"title": "税收征管法"}])
    plan["cited_located"] = False
    plan["evidence"] = E.grade_all([
        {"title": FGK_SIX_FOR_ZGL[0], "url": "u110", "effect_level": "规范性文件",
         "status": "已废止", "document_number": "国税发〔2001〕110号"},
        {"title": "中华人民共和国税收征收管理法", "effect_level": "法律",
         "status": "现行有效"},
    ])
    a = AN.compose(plan)
    # 修复前这一格是那份已废止的 2001 年通知，现行有效的法律被挤到它后面
    assert a["primary"]["title"] == "中华人民共和国税收征收管理法", a["primary"]
    assert "没有定位到同一份文件" in a["cited_note"], a["cited_note"]
    # 没点名的题不带这句，免得答案里凭空多一段不相关的提醒
    plain = AN.compose({k: v for k, v in plan.items() if k != "cited_located"})
    assert plain["cited_note"] == "", plain["cited_note"]
    print("  [PASS] cited_located=False：主依据回到分层，点名未命中如实标注")


def test_route_by_tax_type_not_cross_topic():
    cases = [
        ("企业重组业务中适用特殊性税务处理需要满足哪些条件", "企业所得税"),
        ("下列属于稿酬所得项目的是", "个人所得税"),
        ("国际重复征税产生的根本原因是什么", "税收协定"),
        # 横切专题的别名要长过税种别名两个字以上才允许抢占
        ("某公司进口货物被海关征收滞纳金，应按关税还是滞纳金计算", "关税"),
        ("个人所得税的专项附加扣除怎么填报", "个人所得税"),
    ]
    for text, want in cases:
        got = (T.resolve_tax_type(text) or {}).get("type", "")
        assert got == want, f"{text[:24]} 归到 {got}，应为 {want}"
    print(f"  [PASS] 归类：{len(cases)} 条按税种优先、别名补齐后各归其位")


def test_alias_table_pins_accepted_and_rejected_words():
    """别名表两类要钉住：收进来的词必须归对，量过后没收的词不许回来。

    没收的理由不是"没测"，是实测会抢题（见 tax_search 里那段注释）：排序按别名
    长度定胜负，跨税种通用的长词会把整题从真正所属的税种抢走，所以它们要一直
    留在未路由那一边，由界面按字面检索如实报出来。
    """
    accepted = [
        ("中国籍船舶驶入国内港口，按吨位缴纳的船舶吨税怎么计算", "船舶吨税"),
        ("占用耕地建设厂房要不要缴纳耕地占用税", "耕地占用税"),
        ("企业发生的长期待摊费用，在企业所得税前如何分期摊销扣除", "企业所得税"),
        ("企业取得的资产损失，所得税前能不能扣除", "企业所得税"),
        # 日式字形「増」U+5827：NFKC 折不成「增」，只能靠表里收下这个写法
        ("土地増值税清算的条件有哪些", "土地增值税"),
        ("任职受雇取得的工资、薪金所得怎么预扣预缴", "个人所得税"),
        ("一般纳税人选择简易计税方法，征收率是多少", "增值税"),
    ]
    for text, want in accepted:
        got = (T.resolve_tax_type(text) or {}).get("type", "")
        assert got == want, f"{text[:24]} 归到 {got}，应为 {want}"

    # 本体法不许挂错：船舶吨税与车船税是两部法律，吨税不得挂在车船税法下
    assert (T.TAX_TYPE_KEYWORDS["船舶吨税"]["parent_law"]
            == "中华人民共和国船舶吨税法")
    assert "船舶吨税" not in T.TAX_TYPE_KEYWORDS["车船税"]["aliases"]

    rejected = [
        # 跨税种通用：收进企业所得税会抢走别的税种（应纳税所得额实测改判 13 题，
        # 业务招待费与广告费改判 6 题），所以这三个词一直没进表
        "企业取得的应纳税所得额如何计算",
        "业务招待费的扣除比例是多少",
        "广告费和业务宣传费的扣除限额是多少",
        # 归个税，不是企业所得税
        "个人转让限售股取得的所得怎么征收个人所得税",
    ]
    for text in rejected:
        info = T.resolve_tax_type(text) or {}
        if "限售股" in text:
            assert info.get("type") == "个人所得税", (text, info)
        else:
            assert info.get("type") != "企业所得税", \
                f"「{text[:20]}」又被企业所得税抢走了，这个别名被收回去过"
    print(f"  [PASS] 别名表：{len(accepted)} 个新收词归对，"
          f"{len(rejected)} 个量过后没收的词没有被重新收进来")


def test_route_prefers_stem_and_falls_back_to_options():
    # 题干有税种时，选项里的别的税种不抢
    hijack = T.resolve_tax_type(
        "下列各项中，符合车船税征收管理规定的是（ ）。　"
        "A.扣缴义务人代收代缴车船税；B.纳税地点；C.纳税义务发生时间；D.自行申报")
    assert hijack["type"] == "车船税", hijack
    assert hijack.get("matched_from", "stem") == "stem", hijack
    # 题干问的是"哪种税制"，税种名只出现在选项里——这时必须回退到全句才路由得到
    only_opts = T.resolve_tax_type(
        "关于哪一种税制实行了多次课征制，以下选项中正确的是（）。"
        "　A.车辆购置税 B.个人所得税 C.企业所得税 D.增值税")
    assert only_opts and only_opts.get("matched_from") == "options", only_opts
    print("  [PASS] 路由：题干优先，题干无信号时按选项兜底并标注来源")


def test_search_terms_uses_cited_title():
    terms = AN.search_terms(
        "查询、阅读、分析、解读《关于企业重组业务所得税处理有关征管问题的公告》（2026年第13号）")
    assert terms["topic"] == "企业所得税", terms
    # 法规库那一轮要找的是这份文件本身，不是本体法
    assert terms["fgk"].startswith("企业重组"), terms["fgk"]
    assert terms["npc"] == "中华人民共和国企业所得税法", terms["npc"]
    assert terms["cited"][0]["doc_number"] == "2026年第13号", terms
    print(f"  [PASS] 检索词装配：点名文件走标题，上位法留给 npc 轮 → fgk={terms['fgk']}")


def test_sta_search_terms_present_and_renamed():
    sta = {k: v for k, v in T.TAX_TYPE_KEYWORDS.items() if v.get("authority") == "sta"}
    missing = [k for k, v in sta.items() if not v.get("search_term")]
    assert not missing, f"sta 专题缺 search_term：{missing}"
    # "税收协定"这个检索词翻不出法规库条目了，表里必须换成能翻出来的那个
    assert sta["税收协定"]["search_term"] == "双重征税", sta["税收协定"]
    print(f"  [PASS] {len(sta)} 个 sta 专题均有 search_term，税收协定已换用「双重征税」")


class _Resp:
    """假的 requests 响应，只带 search_chinatax 真正用到的两个方法。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def _payload(total, items):
    return {"searchResultAll": {"total": total, "searchTotal": items}}


_ITEM = {"title": "国家税务总局关于企业重组业务所得税处理有关征管问题的公告",
         "url": "http://fgk.chinatax.gov.cn/zcfgk/c100012/c5251155/content.html",
         "pubDate": "2026-07-08 00:00:00",
         "cwrq": "2026-07-08 00:00:00",
         "content": "现对企业重组业务所得税处理有关征管问题公告如下",
         "pubName": "国家税务总局",
         "govDoc": {"docNum": "国家税务总局公告2026年第13号"},
         "xxgk_aging": "全文有效",
         "xxgk_effectLevel": "税务规范性文件"}


class _SugResp:
    """假的 suggestFGK 响应。构造入参是**已经序列化好的正文文本**——站方回的是
    「包了一层引号的 JSON 字符串」，顶层 parse 得到 str，要二次 parse（2026-11-26
    实测，与 public.js 里先 JSON.parse(res) 再读 suggestFGKList 的写法对得上）。"""

    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.content = text.encode("utf-8")

    def json(self):
        return json.loads(self.text)


def _sug_body(titles):
    return json.dumps(json.dumps({"suggestFGKList": titles}, ensure_ascii=False),
                      ensure_ascii=False)


def test_suggest_fgk_strips_highlight_and_keeps_order():
    """联想只交回标题清单：高亮标签要剥掉、站点给的原顺序要留住。"""
    saved = W.requests.get
    sent = []

    def fake(url, params=None, **kw):
        sent.append((url, dict(params or {})))
        return _SugResp(_sug_body([
            "中华人民共和国<span>增</span><span>值</span><span>税</span>法",
            "<span>增值税</span>暂行条例",
            "关于明确<span>增值税</span>若干征管事项的公告"]))

    try:
        W.requests.get = fake
        out = W.suggest_fgk("增值税")
    finally:
        W.requests.get = saved
    assert out["titles"] == ["中华人民共和国增值税法", "增值税暂行条例",
                             "关于明确增值税若干征管事项的公告"], out
    assert out["count"] == 3, out
    assert sent[0][0].endswith("/search5/search/suggestFGK"), sent[0][0]
    assert sent[0][1]["searchWord"] == "增值税", sent[0][1]
    print("  [PASS] suggestFGK 剥标签、保顺序、走 www 主机的 suggestFGK 端点")


def test_suggest_fgk_double_encoded_payload_is_parsed():
    """双层 JSON（顶层 parse 出来还是字符串）必须解得开；解不开要报失败而不是崩。"""
    saved = W.requests.get
    try:
        W.requests.get = lambda url, params=None, **kw: _SugResp(_sug_body(["甲", "乙"]))
        ok = W.suggest_fgk("测试")
        assert ok["titles"] == ["甲", "乙"], ok
        # 站点也可能直接回对象（不再套一层）：两种都要读得出。
        W.requests.get = lambda url, params=None, **kw: _SugResp(
            json.dumps({"suggestFGKList": ["丙"]}, ensure_ascii=False))
        one = W.suggest_fgk("测试")
        assert one["titles"] == ["丙"], one
        # 彻底不是 JSON 的正文：报 _error，不许抛异常。
        class _Junk:
            status_code = 200
            text = "<html>网关错误</html>"

            def json(self):
                raise ValueError("no json")
        W.requests.get = lambda url, params=None, **kw: _Junk()
        junk = W.suggest_fgk("测试")
        assert junk["titles"] == [] and junk.get("_error"), junk
        assert junk.get("_fetch_failed"), junk
    finally:
        W.requests.get = saved
    print("  [PASS] suggestFGK 双层 JSON / 单层对象 / 非 JSON 三种正文都归位")


def test_suggest_fgk_empty_list_is_not_an_error():
    """typename 越界（比如「新闻」）站点回 {"suggestFGKList":[]}：这是「这个频道没有联想」，
    不是取数失败——把它报成失败会让调用方误以为整条路不通。"""
    saved = W.requests.get
    try:
        W.requests.get = lambda url, params=None, **kw: _SugResp(_sug_body([]))
        out = W.suggest_fgk("增值税")
    finally:
        W.requests.get = saved
    assert out["titles"] == [], out
    assert out["count"] == 0, out
    assert "_error" not in out and "_fetch_failed" not in out, out
    assert out.get("_zero_hit"), out
    print("  [PASS] suggestFGK 空清单归 _zero_hit，不是 _fetch_failed")


def test_suggest_fgk_is_not_wired_into_the_search_chain():
    """这一档是只读旁路：检索主链不能被它改动（联想只当标题基数用，
    接进主链就等于让一个说不清性质的端点影响「有没有这份文件」的结论）。
    CLI 那一支可以调它（人手动问一次联想），但 answer/search 层不许。"""
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts" / "tax_web_search.py").read_text(encoding="utf-8")
    body = src[src.index("def search_chinatax("):src.index("def _clean(")]
    assert "suggest_fgk(" not in body, "suggest_fgk 不该被 search_chinatax 调用"
    for name in ("tax_search.py", "tax_answer.py", "tax_cases.py",
                 "tax_aggregator.py"):
        other = (root / "scripts" / name).read_text(encoding="utf-8")
        assert "suggest_fgk" not in other, f"{name} 不该消费联想端点"
    print("  [PASS] suggest_fgk 只在 tax_web_search 里，主链与答句层都没接")


def test_search5_page_index_is_zero_based():
    """翻页基准由本用例确认：search5 的 pageNum 从 0 起算，接口层减 1，对外 page 从 1 起算。

    这条用例对应的缺陷：按 1 起算发请求等于每轮都丢掉相关度最高的首屏，
    命中不足 10 条时首屏是唯一一页，取回空列表就被读成"库里没有这份文件"。
    """
    saved = W.requests.get
    sent = []

    def fake(url, params=None, **kw):
        sent.append(dict(params))
        return _Resp(_payload(3, [_ITEM]))

    try:
        W.requests.get = fake
        r1 = W.search_chinatax("企业重组业务所得税处理", page=1)
        r3 = W.search_chinatax("企业重组业务所得税处理", page=3)
    finally:
        W.requests.get = saved

    assert sent[0]["pageNum"] == 0, sent[0]
    assert sent[1]["pageNum"] == 2, sent[1]
    assert r1["total"] == 3 and len(r1["results"]) == 1, r1
    print("  [PASS] 检索接口翻页基准：对外 page 从 1 起算，上线 pageNum 从 0 起算")


def test_aging_and_doc_number_come_from_the_source():
    """时效与文号要能从接口录入项带下来，否则每条法规都只能报"时效未标明"。"""
    saved = W.requests.get

    def fake(url, params=None, **kw):
        return _Resp(_payload(1, [_ITEM]))

    try:
        W.requests.get = fake
        row = W.search_chinatax("企业重组业务所得税处理")["results"][0]
    finally:
        W.requests.get = saved

    assert row["document_number"] == "国家税务总局公告2026年第13号", row
    assert row["status"] == "全文有效", row
    assert row["effect_level"] == "税务规范性文件", row
    assert row["publish_date"] == "2026-07-08", row

    g = E.grade(row, at="2026-09-29")
    assert g["validity"] == "effective", g
    assert g["rank"] == "normative", g
    print("  [PASS] 文号/时效/效力级别随清单落下来，定级据此判出现行有效")


def test_search5_filters_reach_the_query_string_and_are_echoed():
    """五组收窄维度必须真的进到发出去的 query 里。

    对应的坑：这批参数只记在文档里、没接进命令行时，发出去的 query 并不带它们。
    接进命令行之后这条用例是唯一的把关——如果哪天 params.update 那行被删掉，发出的 query 里没有这些键，
    本用例就会红，而不是静默地按未过滤去检索。
    """
    saved = W.requests.get
    sent = []

    def fake(url, params=None, **kw):
        sent.append(dict(params))
        return _Resp(_payload(1, [_ITEM]))

    filters = W.build_filters(in_title=True, precise=True, tax_type="增值税",
                              doc_type="财政部 税务总局公告", doc_year="2018",
                              doc_no="119", cwrq_from="2024-01-01",
                              cwrq_to="2024-12-31")
    try:
        W.requests.get = fake
        W.search_chinatax("增值税", filters=filters)
    finally:
        W.requests.get = saved

    q = sent[0]
    # 每组各断一个键，键名要逐字对上接口（写错一个字母接口就静默忽略）
    assert q["wordPlace"] == "1", q
    assert q["participleRule"] == "5", q
    assert q["xxgkSonTaxPolicy"] == "增值税", q
    assert q["docType"] == "财政部税务总局公告", q        # 空格已被去掉
    assert q["docYear"] == "2018", q
    assert q["docNo"] == "119", q
    assert q["cwrqStart"] == "2024-01-01 00:00:00", q     # 补成完整时间戳
    assert q["cwrqEnd"] == "2024-12-31 23:59:59", q
    print("  [PASS] 五组收窄维度逐键进入发出的 query，docType 去空格、cwrq 补时间戳")


def test_search5_zero_with_filters_says_it_might_be_too_narrow():
    """带维度却 0 条：不能读成「库里没有」，要报出可能是维度拼窄了并回显 filters。"""
    saved = W.requests.get

    def fake(url, params=None, **kw):
        return _Resp(_payload(0, []))

    try:
        W.requests.get = fake
        r = W.search_chinatax("增值税", filters={"docType": "财税", "docYear": "2018"})
        bare = W.search_chinatax("增值税")   # 没带维度的 0 条不该出这句
    finally:
        W.requests.get = saved

    assert r["total"] == 0 and "_error" not in r, r
    assert "分不清" in r.get("_filter_note", ""), r
    assert r["filters"] == {"docType": "财税", "docYear": "2018"}, r
    assert "_filter_note" not in bare, "没带维度就不该报维度拼窄那句"
    print("  [PASS] 带维度 0 条报「可能拼窄」并回显 filters；无维度的 0 条不误报")


def test_build_filters_rejects_malformed_values():
    """build_filters 对非法年/号/日期在发出前报错——接口自己不为这一枚拦，
    放过去只能从命中数反推这一枚参数到底生没生效。"""
    for bad in ({"doc_year": "18"}, {"doc_no": "abc"}, {"cwrq_from": "2024-1-1"},
                {"cwrq_to": "2024/01/01"}, {"cwrq_from": "2024-13-01"}):
        try:
            W.build_filters(**bad)
            raise AssertionError(f"应报错却没报：{bad}")
        except ValueError:
            pass
    # 合法的日历日期要放行（strptime 只拦格式与真实日期越界，不误杀 2024-01-01）
    assert W.build_filters(cwrq_from="2024-01-01")["cwrqStart"] == "2024-01-01 00:00:00"
    assert W.build_filters() == {}, "全不填就该是空 dict（等于不发维度）"
    print("  [PASS] build_filters 拦住非法年份/编号/日期，空输入返回空 dict")


def test_aging_and_effect_level_domains():
    """时效与效力等级两维：域内的值原样进 filters，域外的值在发请求前报错。

    为什么要在这一层拦：接口对不认识的取值不发错误码，回的是 `total=0`，与"这一维
    真的没有内容"在响应里是同一个形态（域外值那两发的读数与口径见
    search_source/chinatax/NOTE.md 第三节）。调用方看到的是一条筛得很干净的 0 条，
    以为这一维收到底了，其实是值域写错。
    """
    assert W.build_filters(aging="全文有效") == {"xxgkAging": "全文有效"}
    assert W.build_filters(effect_level="财税文件") == {"xxgkEffectLevel": "财税文件"}
    # 五个时效值与八个效力等级值全部放行，取值域整表钉住（少一档就会被发现）
    assert len(W.AGING_VALUES) == 5 and len(W.EFFECT_LEVEL_VALUES) == 8
    for a in W.AGING_VALUES:
        assert W.build_filters(aging=a)["xxgkAging"] == a
    for e in W.EFFECT_LEVEL_VALUES:
        assert W.build_filters(effect_level=e)["xxgkEffectLevel"] == e
    # NPC 那侧的写法（现行有效／已废止）不在 search5 值域里，必须报错而不是发出
    for bad in ("现行有效", "有效", "废止", "全文有效,已修改"):
        try:
            W.build_filters(aging=bad)
            raise AssertionError(f"域外时效却放行：{bad!r}")
        except ValueError:
            pass
    for bad in ("部门规章", "税法", "null"):
        try:
            W.build_filters(effect_level=bad)
            raise AssertionError(f"域外效力等级却放行：{bad!r}")
        except ValueError:
            pass
    # 空串等于不发这一维（界面「全部」与命令行不填都走这条路）
    assert W.build_filters(aging="", effect_level="") == {}
    # 两侧带空白的合法值要放行（build_filters 自己 strip）；只剩空白的要报错，
    # 因为"填了但筛不动"与"没填"是两件事，静默当成没填会谎报筛过
    assert W.build_filters(aging=" 全文有效 ")["xxgkAging"] == "全文有效"
    for blank in ("   ", "\t", "\n"):
        try:
            W.build_filters(aging=blank)
            raise AssertionError(f"纯空白时效却放行：{blank!r}")
        except ValueError:
            pass
        try:
            W.build_filters(effect_level=blank)
            raise AssertionError(f"纯空白效力等级却放行：{blank!r}")
        except ValueError:
            pass
    print("  [PASS] 时效五档、效力等级八档逐档放行，域外写法（含 NPC 值域）报错")


def test_aging_with_unrecorded_effect_level_blocked_before_send():
    """效力等级那三档不录时效的族，与时效同发在发出前就报错——接口对这一组回
    total=0，与"库里确实没有"同一个形态，放过去就是把必然为空的查询当成结论。

    2026-11-25 二十四发实测（「增值税」基线 1910，逐发隔 2.6 秒，读 total 与同格
    agingList；换「留抵退税」基线 58 交叉复认三档同发仍为 0）：
      带时效桶的五档同发正常：法律 9→8、行政法规 10→7、国务院文件 9→7、
                              税务部门规章 30→15、税务规范性文件 681→216
      只有空桶的三档同发归零：财税文件 637→0、其他文件 62→0、工作通知 190→0
    归零跟着效力等级这一族走、不跟着检索词走，所以判得死。读数在
    search_source/chinatax/NOTE.md「效力等级与时效同发为什么归零」那一段。
    """
    assert W.AGING_UNRECORDED_LEVELS == ("财税文件", "其他文件", "工作通知"), \
        W.AGING_UNRECORDED_LEVELS
    # 三档 × 五档时效的全部组合都要拦住
    for e in W.AGING_UNRECORDED_LEVELS:
        for a in W.AGING_VALUES:
            try:
                W.build_filters(aging=a, effect_level=e)
                raise AssertionError(f"必然为 0 的组合却放行：{e} × {a}")
            except ValueError:
                pass
    # 另外五档同发是正常交集，不许顺手拦掉（拦了就是把能用的组合堵死）
    for e in W.EFFECT_LEVEL_VALUES:
        if e in W.AGING_UNRECORDED_LEVELS:
            continue
        got = W.build_filters(aging="全文有效", effect_level=e)
        assert got == {"xxgkAging": "全文有效", "xxgkEffectLevel": e}, (e, got)
    # 单独发这三档不受影响——它们是有货的（财税文件单发 637）
    assert W.build_filters(effect_level="财税文件") == {"xxgkEffectLevel": "财税文件"}
    assert W.build_filters(aging="全文有效") == {"xxgkAging": "全文有效"}
    # 报错文案要说出去哪儿：换一个维度，时效回来读条目的 status
    try:
        W.build_filters(aging="全文有效", effect_level="财税文件")
    except ValueError as ex:
        assert "不录时效" in str(ex) and "status" in str(ex), str(ex)
    print("  [PASS] 三档不录时效的族与时效同发拦住，另五档同发放行，单发两维照旧")


# 2026-11-25 六发 54 条实测（.tmp-inspect\probe29c.py）里的真实原文，逐字抄下来
repeal_NOTE = ("根据《国家税务总局关于废止〈增值税一般纳税人登记管理办法〉的决定》"
               "（国家税务总局令第62号），自2026年1月1日起，全文废止。")
LONG_NOTE = "1.根据《国家税务总局关于发布已失效或废止的税收规范性文件目录的通知》" \
            "（国税发〔2006〕62号），第一条第三款废止。2." + "修" * 900   # 实测最长 983 字符
BLANKISH = ["", "null"]


def _item_with(desc):
    it = dict(_ITEM)
    it["xxgk_description"] = desc
    return it


def _row_for(desc):
    saved = W.requests.get
    try:
        W.requests.get = lambda url, params=None, **kw: _Resp(
            _payload(1, [_item_with(desc)]))
        return W.search_chinatax("增值税一般纳税人登记管理")["results"][0]
    finally:
        W.requests.get = saved


def test_status_note_carries_the_repeal_basis_and_blanks_stay_blank():
    """废止依据从接口的 xxgk_description 带下来，空值写法不许当成一句说明。

    对应的坑（2026-11-25 二十四发实测，`.tmp-inspect\\probe29a.py`/`probe29c.py`）：
    清单层的 xxgk_abolishDate 在 54 条里只有空串与字符串 "null"，一个真日期都没给过；
    但同一批条目的 xxgk_description 有 45/54 带着「依据哪份文件、自何日起全文废止」
    的原文（全文废止档 10/10 有值、25/54 含日期）。这一栏以前整个没接进输出，于是
    读者只剩两条路：去抠正文，或者被一句「这一栏没有录入」劝退。
    """
    row = _row_for(repeal_NOTE)
    assert row["status_note"] == repeal_NOTE, row.get("status_note")
    # 来源要写清是哪一栏，否则下游没法解释这句话从哪来
    assert row["status_note_from"] == "法规库录入项 xxgk_description", row
    # 只带原文，不抠日期：这一栏在全文有效档偶尔装的是立法沿革
    assert "自2026年1月1日起" in row["status_note"]

    # 空串与字符串 "null" 都不许写键——带上下游就是把 "null" 当一句处置说明引用出去
    for blank in BLANKISH:
        r = _row_for(blank)
        assert "status_note" not in r, (blank, r)
        assert "status_note_from" not in r, (blank, r)

    # 超长要截断：实测「已修改」档最长 983 字符是整部修改史，清单层装不下
    long_row = _row_for(LONG_NOTE)
    note = long_row["status_note"]
    assert len(note) == W.STATUS_NOTE_LIMIT + len("…（原文更长，见详情页）"), len(note)
    assert note.endswith("…（原文更长，见详情页）"), note[-30:]
    assert note[:W.STATUS_NOTE_LIMIT] == LONG_NOTE[:W.STATUS_NOTE_LIMIT]

    # 穿过法规库那一层：tax_fgk 的透传元组漏了这一栏，法规库这一路就还是"没录入"
    fgk_src = (SCRIPTS / "tax_fgk.py").read_text(encoding="utf-8")
    assert '"status_note", "status_note_from"' in fgk_src, "tax_fgk 透传元组没这两枚键"
    saved = tax_fgk.search_chinatax
    try:
        tax_fgk.search_chinatax = lambda keyword, page=1, size=10, filters=None, **kw: \
            {"total": 1, "results": [_item_row(page)]}
        got = tax_fgk._scan_list("增值税一般纳税人登记管理", size=99,
                                 max_pages=1, adaptive=False)["results"][0]
    finally:
        tax_fgk.search_chinatax = saved
    assert got["status_note"] == repeal_NOTE, got
    assert got["status_note_from"] == "法规库录入项 xxgk_description", got

    # 命令行文本输出要当场看得见这一行，否则读清单的人还是得去 --json 里翻
    saved = W.requests.get
    buf = io.StringIO()
    try:
        W.requests.get = lambda url, params=None, **kw: _Resp(
            _payload(1, [_item_with(repeal_NOTE)]))
        argv = sys.argv
        sys.argv = ["tax_web_search.py", "增值税一般纳税人登记管理"]
        try:
            with contextlib.redirect_stdout(buf):
                W.main()
        finally:
            sys.argv = argv
    finally:
        W.requests.get = saved
    out = buf.getvalue()
    assert "处置: " in out and "全文废止" in out, out
    print("  [PASS] 废止依据从 xxgk_description 带下来：原文在位、空值不写键、"
          "超长截断、穿过法规库层、命令行打得出来")


def _item_row(page):
    """给 tax_fgk._scan_list 用的一条：URL 必须带法规库标识才收进结果。"""
    row = _row_for(repeal_NOTE)
    row["url"] = "http://fgk.chinatax.gov.cn/zcfgk/c100010/c5230001/content.html"
    row["source_label"] = "税务总局法规库"
    return row


def test_doc_year_help_says_the_document_number_year():
    """`--doc-year` 的帮文要说"发文字号里的年份"，不能写成"成文年份"。

    依据是 2026-10-20 空词整档的两发对照（`docYear=2024` 回 82、`xxgkFormulatedYear=2024`
    回 90，两发的 10 行里能逐条指出 1 条差异：《中华人民共和国增值税法》文号空、制定年 2024，
    只被后者收到；其余 7 条差额要翻页才比得齐，本机没取），逐发口径记在
    `search_source/chinatax/NOTE.md` 第三节。帮文写错时照着填的人会拿成文日期那年
    去填这一栏，命中的是另一批条目。成文日期那一维另有两枚开关（`--cwrq-from`／
    `--cwrq-to`），帮文里必须把这层分开。
    变异验证：把 help 改回「成文年份四位（docYear）」，本条报红。
    """
    parser = argparse.ArgumentParser()
    W.add_filter_args(parser)
    text = parser.format_help()
    assert "发文字号里的年份" in text, text
    assert "成文年份" not in text, "docYear 读的是文号里的年份，不是成文年份"
    print("  [PASS] --doc-year 帮文说的是文号里的年份，与成文日期两枚开关分开")


def test_file_labels_is_the_default_scope():
    """不发 --all-labels 时 label 必须发 FILE_LABELS，而不是空串（全站）。

    对应的缺陷：不发这一维等于搜全站。实测「转让定价」全站前 3 屏一条法规库条目
    都没有（自适应在第 3 页收尾，整趟取回 0 条），发白名单后同一词 18 条全部取回。
    变异验证：把 params 里 label 的三元表达式改回常量空串，本条与下一条一起报红。
    """
    saved = W.requests.get
    sent = []

    def fake(url, params=None, **kw):
        sent.append(dict(params))
        return _Resp(_payload(1, [_ITEM]))

    try:
        W.requests.get = fake
        W.search_chinatax("转让定价")                      # 默认
        W.search_chinatax("转让定价", file_only=True)      # 显式开
    finally:
        W.requests.get = saved

    for q in sent:
        assert q["label"] == W.FILE_LABELS, q
        assert set(W.FILE_LABELS.split(",")) == {
            "法律", "行政法规", "国务院文件", "税务部门规章", "税务规范性文件",
            "财税文件", "其他文件", "工作通知", "政策指引", "文字政策解读"}, q["label"]
        # 白名单里必须留着解读那一类，否则 ④ 要的官方说明会被一起挡掉
        assert "文字政策解读" in q["label"], q
        # 默认排序仍是相关度
        assert q["orderBy"] == W.ORDER_VALUES["relevance"], q
    # 命令行与清单回显那句「十类」是照着名单写的：加一类却不改文案，回显就开始撒谎
    assert W.FILE_LABELS.count(",") + 1 == 10, W.FILE_LABELS
    assert "十类" in W.label_scope_text(True), W.label_scope_text(True)
    print("  [PASS] 默认发十类文件标签（含文字政策解读），排序默认相关度")


def test_all_labels_switch_reopens_the_whole_site():
    """--all-labels / file_only=False 时 label 要退回空串，两档范围得能切换。"""
    saved = W.requests.get
    sent = []

    def fake(url, params=None, **kw):
        sent.append(dict(params))
        return _Resp(_payload(1, [_ITEM]))

    try:
        W.requests.get = fake
        W.search_chinatax("小微企业", file_only=False, order="date_desc")
    finally:
        W.requests.get = saved

    q = sent[0]
    assert q["label"] == W.ALL_LABELS == "", q
    assert q["orderBy"] == "1", q          # date_desc 发的是 orderBy=1
    try:
        W.search_chinatax("小微企业", order="newest")
        raise AssertionError("域外排序名却发了请求")
    except ValueError:
        pass
    print("  [PASS] 关白名单退回全站空串；date_desc 发 orderBy=1；域外排序名报错")


def test_out_of_range_page_and_missing_list_are_told_apart():
    """命中数大于 0 却是空页：翻页越界与首屏没给清单，两种成因的文案不同。"""
    saved = W.requests.get

    def fake(url, params=None, **kw):
        return _Resp(_payload(3, []))

    try:
        W.requests.get = fake
        beyond = W.search_chinatax("企业重组", page=2)      # 3 条只占 1 页
        first = W.search_chinatax("企业重组", page=1)       # 首屏就该有条目
    finally:
        W.requests.get = saved

    assert "已翻过末页" in beyond.get("_empty_reason", ""), beyond
    assert "没给条目清单" in first.get("_empty_reason", ""), first
    assert "_error" not in first, "接口空页不是请求失败"

    # 清单层把这个空页原样透出，不许写成"翻完 N 页未筛出法规库条目"
    saved_scan = tax_fgk.search_chinatax
    try:
        def stub(keyword, page=1, size=10, filters=None, **opts):
            return first        # opts 收 file_only/order，签名要跟 _scan_list 同步
        tax_fgk.search_chinatax = stub
        r = tax_fgk._scan_list("企业重组业务所得税处理", size=5, max_pages=3)
    finally:
        tax_fgk.search_chinatax = saved_scan
    assert r["total"] == 0, r
    assert "未筛出法规库条目" not in r["_error"], r["_error"]
    print("  [PASS] 翻页越界与首屏空列表分开报，都不读成库里没有")


def test_request_failure_is_flagged_not_read_as_no_hit():
    """请求真失败时要带 _fetch_failed，不能和"翻了没结果/库里没有"共用一个空壳。

    对应的坑：取数失败（连接超时、HTTP 5xx、响应非 JSON）也走 _empty_result，
    界面若只看 total==0 就把三种成因印成同一句"未找到"，用户会以为换个词重搜
    就有，实际上服务根本连上了——这是静默降级。前端靠 _fetch_failed 才分得开。
    """
    saved = W.requests.get

    def boom(url, params=None, **kw):
        raise W.requests.RequestException("连接超时")

    try:
        W.requests.get = boom
        r = W.search_chinatax("增值税")
    finally:
        W.requests.get = saved

    assert r["_fetch_failed"] is True, r
    assert r["total"] == 0 and r.get("_error"), r
    # 请求失败不是"库里没有"：不能带 _filter_note / _empty_reason 那两种措辞
    assert "_filter_note" not in r and "_empty_reason" not in r, r
    print("  [PASS] search_chinatax 请求失败带 _fetch_failed，不与空命中/维度拼窄混用")


def test_column_guard_truth_table():
    """column_unhonoured 只在"发号码且响应没回显这枚号"时下结论。

    对应 3.62.32 实测：column=abc / 不存在的栏目名 都回 total=0 而 columnId=None，
    与 column=5739 那种"合法号、这一主题下真 0 条"（回显 columnId='5739'）在现判据
    下必须分得开——否则站点没接这个值会被答成「这个栏目里没有」。
    """
    # 发号码：回显等于发出的号 ⇒ 认了，不报
    assert W.column_unhonoured("5739", {"columnId": "5739"}) is False
    assert W.column_unhonoured("5741", {"columnId": "5741"}) is False
    # 发号码：回显是别的号 / 干脆没有 ⇒ 没认，报
    assert W.column_unhonoured("5742", {"columnId": "5738"}) is True
    assert W.column_unhonoured("abc", {"columnId": None}) is False  # abc 不是号码
    assert W.column_unhonoured("9999", {"columnId": None}) is True
    assert W.column_unhonoured("0", {}) is True
    # 发名字：这一维认了也不回 columnId，不能假装能判 ⇒ 一律不报
    assert W.column_unhonoured("政策法规", {"columnId": None}) is False
    assert W.column_unhonoured("税收政策", {"columnId": "5742"}) is False
    # 没发这一维 / 空值 / 非 dict ⇒ 不报
    assert W.column_unhonoured(None, {"columnId": None}) is False
    assert W.column_unhonoured("", {"columnId": None}) is False
    assert W.column_unhonoured("  ", {"columnId": None}) is False
    assert W.column_unhonoured("5741", None) is False
    assert W.column_unhonoured("5741", []) is False
    print("  [PASS] column_unhonoured 只对「号码未被回显」报，名字维一律不报")


def test_column_name_ambiguity_is_named_not_resolved():
    """column_echo_absent 负责把"发名字分不清"说出口，但不替站点选一种成因。"""
    # 发名字、响应不回 columnId ⇒ 分不清（合法名与乱写的名字同形）
    assert W.column_echo_absent("政策法规", {"columnId": None}) is True
    assert W.column_echo_absent("不存在的栏目名", {}) is True
    # 发名字、响应把名字换成了号 ⇒ 分得清，不报
    assert W.column_echo_absent("税收政策", {"columnId": "5742"}) is False
    # 发号码 / 没发 ⇒ 不归这一枚判据管
    assert W.column_echo_absent("5739", {"columnId": None}) is False
    assert W.column_echo_absent(None, {"columnId": None}) is False
    assert W.column_echo_absent("abc", {"columnId": None}) is True  # 乱写的值也走名字那条路
    print("  [PASS] column_echo_absent 只声明分不清，不冒充能判")


def test_unhonoured_column_is_not_read_as_empty_channel():
    """端到端：发号码未被认下 ⇒ _empty_reason 在位、不打 _zero_hit；合法号真 0 条 ⇒ 打 _zero_hit。

    这一发桩的 payload 逐字对 probe32e/32i 的实测形状：abc 与不存在的栏目名都回
    total=0 且 columnId=None，而 5739 回 columnId='5739'。红线⑦要防的就是把前两者
    答成"这个栏目里没有相关条目"。
    """
    saved = W.requests.get

    def fake(url, params=None, **kw):
        col = (params or {}).get("column", "")
        if col == "5739":
            # 合法号、真 0 条：站点回显 columnId
            return _Resp({"columnId": "5739", "column": "总局概况",
                          **_payload(0, [])})
        if col == "abc":
            # 不是号码：原样回显 column，columnId 为 None
            return _Resp({"columnId": None, "column": "abc", **_payload(0, [])})
        if col == "不存在的栏目名":
            return _Resp({"columnId": None, "column": "不存在的栏目名",
                          **_payload(0, [])})
        if col == "政策法规":
            # 合法栏目名但不在 columns 表里：认了也不回 columnId
            return _Resp({"columnId": None, "column": "政策法规", **_payload(0, [])})
        return _Resp(_payload(0, []))

    try:
        W.requests.get = fake
        bad = W.search_chinatax("骗取出口退税", column="9999")
        abc = W.search_chinatax("骗取出口退税", column="abc")
        ghost = W.search_chinatax("骗取出口退税", column="不存在的栏目名")
        name = W.search_chinatax("骗取出口退税", column="政策法规")
        real_empty = W.search_chinatax("骗取出口退税", column="5739")
    finally:
        W.requests.get = saved

    # 9999 走 0 字节 _error 那一档，这里桩回的是 JSON，所以按"号码未被回显"报
    assert "没有被站点认下" in bad.get("_empty_reason", ""), bad
    assert "_zero_hit" not in bad, "站点没认这个号，不能读成栏目里真 0 条"
    # abc 不是号码，走"名字维分不清"那一支
    assert "分不清" in abc.get("_empty_reason", ""), abc
    assert "_zero_hit" not in abc, abc
    assert "分不清" in ghost.get("_empty_reason", ""), ghost
    assert "_zero_hit" not in ghost, ghost
    # 合法栏目名同样只声明分不清——不假装能判
    assert "分不清" in name.get("_empty_reason", ""), name
    assert "_zero_hit" not in name, name
    # 合法号真 0 条：这一路才是答案真是 0 条，打 _zero_hit、不带成因句
    assert real_empty.get("_zero_hit") is True, real_empty
    assert "_empty_reason" not in real_empty, real_empty
    print("  [PASS] 栏目号未被认下与合法号真 0 条分开报，前者不打 _zero_hit")


def test_accounting_gap_flags_questions_keyed_on_accounting():
    """税法条款借用会计结果时，① 要登记会计口径缺口——六个税收源都不收准则条文。"""
    cases = {
        "企业合并中乙企业净资产账面价值1000万元，特殊性税务处理怎么适用":
            "损益落在哪一期、账面价值按什么计量",
        "以自产产品抵偿到期债务，达成债务重组协议，所得税怎么处理":
            "该交易在准则里按哪一类业务处理",
        "会计上作为固定资产核算并按5年计提折旧，税法最低年限是多少":
            "题目直接问会计口径，先取准则原文",
        "境外分支机构利润的收入确认时间是哪一天":
            "收入在会计上确认于哪一期、金额多少",
        "存货计提跌价准备后，可抵扣暂时性差异要不要确认递延所得税":
            "账面价值与计税基础差在哪一期、要不要确认递延所得税",
    }
    for q, want in cases.items():
        got = AA.accounting_gap(q)
        assert got, f"这道题的会计依赖被漏了：{q}"
        assert want in got, f"{q}\n  期望：{want}\n  实得：{got}"
    print(f"  [PASS] accounting_gap：{len(cases)} 类会计要件题都能登记缺口")


def test_accounting_gap_does_not_flag_pure_tax_wording():
    """这两道是拿公开题库逐题量出来的误伤样本，不收进词表就说不上"改得动"。

    "计税基础"是企业所得税法自己的用词，"财务、会计处理办法备案"问的是期限，
    两者都不需要查准则。误伤多认一次只是多一次检索，但把税法术语说成会计缺口
    会让答案去引准则作答，那是引错依据。
    """
    for q in ("企业收取的下列费用中，应计入消费税计税基础的有（ ）。",
              "固定资产大修理支出需达到取得固定资产时计税基础的50%以上，比例是多少",
              "从事生产经营的纳税人应自领取税务登记证件之日起30日内，将其采用的"
              "财务、会计制度和具体的财务、会计处理办法报送备案",
              "小规模纳税人季度销售额30万元是否免征增值税",
              "印花税的税目有哪些",
              # 词表外的写法：只描述业务事实、不点会计科目名。这一条是边界，不是缺陷，
              # 记在这里是为了让"词表认不到"这件事有实例可查（见 SKILL.md ⑩）。
              "这笔以货物抵偿到期债务的交易按什么性质处理"):
        assert AA.accounting_gap(q) == [], AA.accounting_gap(q)
    assert AA.accounting_gap("") == []
    print("  [PASS] accounting_gap：计税基础/会计处理办法备案这类税法措辞不标缺口")


def test_accounting_gap_reaches_the_answer_layer():
    """缺口必须在 --answer 的骨架里，不能只停在判型那一步就丢掉。"""
    plan = AN.build_plan("企业合并中乙企业净资产账面价值1000万元，特殊性税务处理怎么适用")
    assert plan["accounting_gap"], plan
    a = AN.compose(plan)
    assert a["accounting_gap"] == plan["accounting_gap"], a.keys()
    # 没有会计依赖的题不带这一栏，免得答案里凭空多一段不相关的提醒
    plain = AN.compose(AN.build_plan("小规模纳税人季度销售额30万元是否免征增值税"))
    assert plain["accounting_gap"] == [], plain
    print("  [PASS] accounting_gap：build_plan → compose 一路带到答案骨架")


def test_legislative_stage_flags_draft_wording():
    """点名立法过程文件时必须在 ① 认出来：六个税收源收的都是已公布文本。

    三组措辞各盯一条 `tax_analyze.LEGISLATIVE_STAGES` 判据。用户原话里
    "国务院常务会议审议并原则通过…决定将草案提请全国人大常委会审议"同时命中
    草案与提请审议两组，因为"审议通过"是国务院层面的动作，不等于文本已表决公布。
    """
    cases = {
        "2026年8月31日，国务院常务会议审议并原则通过新版《税收征管法》修订草案，"
        "决定将草案提请全国人大常委会审议。请解读《税收征管法》修订草案":
            ["草案阶段：文本尚未表决通过",
             "提请审议阶段：已通过后内部审议，尚未由立法机关表决公布"],
        "增值税法征求意见稿里新增了哪些内容": ["征求意见阶段：文本尚未定稿"],
        "企业所得税法修正稿的送审进展": ["草案阶段：文本尚未表决通过"],
    }
    for q, want in cases.items():
        got = AA.legislative_stage(q)
        for w in want:
            assert w in got, f"{q}\n  期望：{w}\n  实得：{got}"
    print(f"  [PASS] legislative_stage：{len(cases)} 类立法过程题都能标出阶段")


def test_legislative_stage_is_silent_for_promulgated_texts():
    """问已公布文本时不带这一栏，否则每条答案都凭空多一段"你这是草案"。

    最后一例是原题变体：点名 2026 年第 13 号公告问的是已公布的文件。
    """
    for q in ("增值税的征税范围有哪些",
              "中华人民共和国增值税法什么时候施行",
              "小规模纳税人季度销售额30万元是否免征增值税",
              "请使用技能查询、阅读、分析、解读《关于企业重组业务所得税处理"
              "有关征管问题的公告》（2026年第13号）"):
        assert AA.legislative_stage(q) == [], q
    assert AA.legislative_note([]) == ""
    print("  [PASS] legislative_stage：已公布文本的提问不标阶段")


def test_legislative_note_reaches_the_answer_layer():
    """阶段判据要一路到答案骨架，跟 accounting_gap 同一条通道。

    只在判型那一步认出来不够：拿现行有效版当草案内容写进答案，界面上看不出
    任何异样——现行有效的法律本身就是"看起来对"的东西。
    """
    plan = AN.build_plan("请解读《税收征管法》修订草案的主要变化")
    assert plan["legislative_stage"], plan
    a = AN.compose(plan)
    assert "立法过程文件" in a["legislative_note"], a["legislative_note"]
    assert "现行有效版本" in a["legislative_note"], a["legislative_note"]
    plain = AN.compose(AN.build_plan("小规模纳税人季度销售额30万元是否免征增值税"))
    assert plain["legislative_note"] == "", plain
    print("  [PASS] legislative_note：build_plan → compose 一路带到答案骨架")


def test_content_decides_and_form_only_breaks_ties():
    """判型表钉两组：内容信号压过填空形态，零内容时形态才说话。

    这两组分起来才解释得通兜底率，合起来写就会漏掉一半：
    - 填空题形态（留空、没有"下列"引子）不得无条件拿 +3：把带留空的算税题
      改写成"术语填空"，检索计划跟着从"计税依据与税率"换成"该术语的定义条款"；
      1001 题上这一步单独量出来是 137 题被形态抢走，而兜底数一题不变。
    - 留空前是系动词"是/为"时，不得被当成列举动词剥夺填空分；题面又没有
      "下列/以下"引子拿不到选项分，会落进 confidence=0.30 的兜底档。
    """
    cases = [
        # 带留空的算税题：题面给了完整数据，内容分必须赢过形态分
        ("刘某2022年2月15日从4S店购买小轿车一辆，支付含增值税价款47.46万元。"
         "该型号轿车车船税年税额840元，刘某2022年应缴纳车船税为（ ）。",
         "liability"),
        ("2019年12月大风公司进口一辆本单位自用小汽车，关税完税价格为200000元，"
         "关税税率为10%，消费税税率为5%。大风公司应纳车辆购置税（ ）元。",
         "liability"),
        # 零内容信号时形态才决定：留空前是系动词，填的是术语/期限
        ("资本弱化特殊事项文档应当在关联交易发生年度次年6月30日之前准备完毕，"
         "应当自税务机关要求之日起的一定时间内提供，该时间限定是（ ）。",
         "fill_blank"),
        # 集合动词收尾的留空要逐项列，归选项判断
        ("下列不属于印花税应税凭证的有（ ）。", "option_judge"),
        ("转让定价方法包括（ ）。", "option_judge"),
        # "下列…应缴纳…的有（ ）"不能被算税抢走：选项形态 +2 顶得住
        ("下列各项中，应缴纳增值税的有（ ）。", "option_judge"),
        # 不带"下列"引子的择一提问，不得整片落进兜底档
        ("在考察税收执法监督的主旨时，下面哪一项论述是正确的（ ）。",
         "option_judge"),
        # 真实提问写法：疑问句式而不是考题形态
        ("小规模纳税人季度销售额30万元是否免征增值税", "entitlement"),
        # "哪种…更划算"是方案比较，不许被选项判断抢走（所以没收到裸的"哪种"）
        ("个人转让股权，哪种计税方式更划算？", "compare"),
    ]
    for text, want in cases:
        got = AA.classify(text)
        assert got["type"] == want, f"{text[:30]} 判成 {got['type']}，应为 {want}"
    print(f"  [PASS] 判型：内容定胜负、形态只补零信号，{len(cases)} 条各归其位")


def test_classify_tables_reject_measured_harmful_words():
    """量过之后没收的词要一直没收：这几个写法都会把别的类的题抢进测算/资格判定。

    与 test_alias_table_pins_accepted_and_rejected_words 同一套路子——
    拒绝的理由不是"没必要"，是实测改判会把本来判对的题判错，所以必须留用例。
    """
    liab = AA.QUESTION_TYPES["liability"]["signals"]
    ent = AA.QUESTION_TYPES["entitlement"]["signals"]
    opt = AA.QUESTION_TYPES["option_judge"]["signals"]
    # 裸「缴纳」在现码上会把数值题判对数从 100 推到 134，同时把误抢从 11 涨到 22
    # （5 道选项判断、5 道事项定性、6 道流程时限被抢），净收益 34:11，比
    # 「应缴纳」的 40:2 差一个量级
    assert "缴纳" not in liab, "裸「缴纳」被收回来了，先重跑 probe_classify --oracle"
    assert "应缴纳" in liab
    # 裸「免征/减征」会把陈述句里的免税列举抓成资格判定
    assert "免征" not in ent and "减征" not in ent, "裸「免征/减征」被收回来了"
    assert "是否免征" in ent
    # 裸「哪种/哪个/哪些」是 compare 已经在量的轴，收进选项判断会抢方案比较题
    for w in ("哪种", "哪个", "哪些"):
        assert w not in opt, f"「{w}」被收进 option_judge，会和方案比较抢题"
    # 系动词不是列举动词
    assert "是" not in AA._ENUM_VERBS and "为" not in AA._ENUM_VERBS, \
        "系动词回到了 _ENUM_VERBS，兜底档会翻倍"
    print("  [PASS] 判型词表：四类量过没收的写法没有被重新收进来")


def test_intent_vocabularies_agree():
    """检索路的意图词表有三处主人，键集合必须一模一样。

    `tax_search.detect_intent` 出码，`tax_formatter.INTENT_HEADERS` 把它写成
    markdown 标题，`tax_server.INTENT_LABELS` 把它写成界面标签。两张表都是
    `.get(intent, 兜底)`：新增一档意图而忘了改表，程序不报错，界面上直接印出
    `risk_check` 这样的英文码，markdown 标题退成"查询结果"。

    同时钉住它和主线九类题型互斥——`--intent` 传不了 `liability` 这类主线键，
    两套词表量的是不同的轴：检索档只决定展示措辞，题型决定检索计划与结论形态。
    """
    import tax_formatter as FM
    import tax_server as SV
    assert set(T.INTENTS) == set(FM.INTENT_HEADERS) == set(SV.INTENT_LABELS), (
        f"取值域 {sorted(T.INTENTS)} / markdown {sorted(FM.INTENT_HEADERS)} / "
        f"界面 {sorted(SV.INTENT_LABELS)}")
    # 取值域里的每一档都要真的能被判出来，否则 INTENTS 就是在声明一个死值
    probed = {T.detect_intent(q) for q in [
        "增值税专用发票丢了怎么办", "金税四期会查什么风险", "年度汇算清缴怎么申报",
        "我公司能享受小微企业优惠吗", "增值税税率多少"]}
    assert probed == set(T.INTENTS), f"这些判不出来：{set(T.INTENTS) - probed}"
    assert not (set(T.INTENTS) & set(AA.QUESTION_TYPES)), \
        "检索意图与主线题型用了同一个键名，读代码的人会以为两者能互换"
    print("  [PASS] 意图词表：检索档三处键集合一致，且与主线九类互不混用")


def main():
    tests = [
        test_strip_options,
        test_cited_documents,
        test_title_candidates,
        test_title_similarity_orders_document_first,
        test_title_identity_tells_named_from_cited,
        test_locate_cited_document_needs_an_identity_match,
        test_unlocated_cited_document_falls_back_with_a_note,
        test_route_by_tax_type_not_cross_topic,
        test_alias_table_pins_accepted_and_rejected_words,
        test_route_prefers_stem_and_falls_back_to_options,
        test_content_decides_and_form_only_breaks_ties,
        test_classify_tables_reject_measured_harmful_words,
        test_search_terms_uses_cited_title,
        test_sta_search_terms_present_and_renamed,
        test_search5_page_index_is_zero_based,
        test_aging_and_doc_number_come_from_the_source,
        test_search5_filters_reach_the_query_string_and_are_echoed,
        test_search5_zero_with_filters_says_it_might_be_too_narrow,
        test_build_filters_rejects_malformed_values,
        test_aging_and_effect_level_domains,
        test_aging_with_unrecorded_effect_level_blocked_before_send,
        test_status_note_carries_the_repeal_basis_and_blanks_stay_blank,
        test_doc_year_help_says_the_document_number_year,
        test_file_labels_is_the_default_scope,
        test_all_labels_switch_reopens_the_whole_site,
        test_out_of_range_page_and_missing_list_are_told_apart,
        test_request_failure_is_flagged_not_read_as_no_hit,
        test_column_guard_truth_table,
        test_column_name_ambiguity_is_named_not_resolved,
        test_unhonoured_column_is_not_read_as_empty_channel,
        test_accounting_gap_flags_questions_keyed_on_accounting,
        test_accounting_gap_does_not_flag_pure_tax_wording,
        test_accounting_gap_reaches_the_answer_layer,
        test_legislative_stage_flags_draft_wording,
        test_legislative_stage_is_silent_for_promulgated_texts,
        test_legislative_note_reaches_the_answer_layer,
        test_intent_vocabularies_agree,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
    print("=" * 50)
    print(f"结果：{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
