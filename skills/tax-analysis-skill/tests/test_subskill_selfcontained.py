#!/usr/bin/env python3
"""子技能"自成一体、可单独对外分发"的离线结构用例。不联网、不开浏览器、不调模型。

这一层守的是七件事，全都不问内容对错，只问"这一份文档单独拿出去还站不站得住"：
   下面 1.–5. 是原有的五件；6. 是子技能自己声明的文件哈希（2026-11-26 那一轮加），
   7. 是镜像件的声明要有当日读数背书（同一轮加）。

  1. **两份文档齐全**：每个子技能目录都有 `SKILL.md` 与 `NOTE.md`，且
     `SKILL.md` 里有 `## 工作流` 那一节。只留一份的目录，读者拿到的是命令清单
     而没有做事的顺序；工作流被改名，母技能那句"照子技能那一节走"就落空。
     `chenyiwei-bbs` 是上游件（本仓库不改写它，见它自己的 NOTE.md「收录来源」），
     结构由上游定，这一项对它豁免，其余四项照查。2026-11-26 那轮量到它与上游已分叉，
     所以这里说的是「不改写」，不是「与上游一致」。
  2. **不引用主技能的私有编号**：主技能 `SKILL.md` 那条分析主线有 13 步（①–⑬），
     所以子技能文档里 ⑤ 及以上的圈号只可能是"回 ⑦ 定级""进 ⑧"这种指针——一旦
     子技能被单独分发，收的人手上没有那 13 步，编号就指不到东西。文内自数的
     枚举允许，实测本轮两个根的语料里圈号最大到 ④（chinatax/NOTE.md 的三条与四条
     读法、R&D-Expenses 的三条能力线）；要自数到第五项就改用 `1.` 的阿拉伯
     数字列表。
  3. **路径指针存在**：文档里 `references/…`、`scripts/…`、`tests/…`、`frontend/…`、
     `search_source/…`、`subskills/…`、`eval/…` 那 202 处指针（2026-11-26 本轮实测口径，上一轮 3.62.37 扫到 199）
     见下面"计数"），先按子技能
     目录解、再按仓库根解。R&D-Expenses 有自己的 `references/`，母技能那一份
     在仓库根，两套都算落地；写成 `scripts/tax_browser.BrowserSession` 那种带符号名
     后缀的形态，去掉尾段再试；带 `*` 的按 glob 至少命中一个。
  4. **「第X步／第X节」指针落地**：93 处（2026-11-26 本轮实测，步 21／节 72）逐个解到真实标记。这个仓库里
     两套编号各有唯一形态——步只在 `SKILL.md` 里以 `**第X步 …**` 定义，节只在
     `NOTE.md` 与 `references/*.md` 里以 `## 一、…` 或 `## 第X节` 定义。指针的目标
     先取紧邻前 40 字里最后一个 `.md` 文件名（`NOTE.md`／`SKILL.md` 裸名指向同目录
     那份，前面写着母技能／主技能则指向仓库根 `SKILL.md`），取不到就在本文与同目录
     另一份里找。标题行与 `**第X步` 定义本身不算指针。
  5. **代码符号可核对**：文档里 109 处 `` `tax_模块.符号` `` 反引号引用，import 得到
     该模块且模块有该属性。子技能说"值域常量在 `tax_web_search.FILE_LABELS`"而那个
     名字已漂走，读者按图索骥会扑空，而这句话在文档里读起来完全正常。

计数口径（2026-11-26 本轮重扫；上一轮 3.62.37 扫到语料 29 份、路径 199／符号 106／编号 84）：语料 = `search_source/*/*.md` + `subskills/*/*.md` 共 29 份
（15 个目录：13 个搜索源目录各 2 份、R&D-Expenses 只 1 份 SKILL.md、tax-preference 2 份）；
路径指针 202 处（本轮 199→202 差 3 处）、符号引用 109 处（本轮 106→109 差 3 处）、编号指针 93 处（本轮 84→93 差 9 处，步仍 21、节 63→72）；这三组差值都来自 npc-flk 那一刀新写的指针与它引到的那些符号名（排除标题行与步定义行后）。
这三枚数在本文件里各有一条用例下限盯着，检查规则一旦漏抓（正则被改窄、语料被改空）
就会报红，而不是安静地少查。

每条检查都自带 `test_mutation_*` 自检：往内存副本里注入对应的破坏（把第七步那句
改写成「按 ⑧ 定级层归档」、把 NOTE 里被「第三节」指到的那节序号换成 `## 柒、`、把
`**第四步` 改名、把脚本名拼错一位、符号名加个 `_v2`），确认判据真的会报红。
判据不报红就等于没有。
"""

import ast
import importlib
import hashlib
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
# 3.62.24 起这一层查两个根：search_source/ 是按搜索源分的（十一源各一份），
# subskills/ 只剩业务专题（R&D-Expenses、tax-preference）。分开放是因为两者回答的
# 问题不同——一个说"去哪取数"，一个说"这类业务怎么办"；混在 subskills 里时，
# 读者分不清 ctaxnews 与 tax-preference 是同一类东西。
SEARCH_SOURCE = ROOT / "search_source"
SUBSKILLS = ROOT / "subskills"
DOC_ROOTS = (SEARCH_SOURCE, SUBSKILLS)

# 上游镜像件：结构与措辞由站点定，第 1 项（工作流小节）对它豁免
MIRROR_DOCS = {"chenyiwei-bbs"}

# 内容已并入 SKILL.md（目录结构 + 部署约束）与各资产 README 的技能：不强制 NOTE.md
NO_NOTE_DOCS = {"R&D-Expenses"}

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯"
LOCAL_CIRCLED_MAX = 4            # 文内自数只到 ④；⑤ 起算主技能私有编号
NUM = "一二三四五六七八九十"

PATH_RE = re.compile(r"(?:references|scripts|tests|frontend|search_source|subskills|eval)"
                     r"/[A-Za-z0-9_./*-]+[A-Za-z0-9_./*-]")
SYM_RE = re.compile(r"`(tax_[a-z_]+)\.([A-Za-z_][A-Za-z0-9_]*)`")
SEC_RE = re.compile(r"第([" + NUM + r"]+)(步|节)")
MD_RE = re.compile(r"(?:references|tests|frontend|search_source|subskills|eval)/"
                   r"[A-Za-z0-9_./*-]+\.md|(?:NOTE|SKILL)\.md")
KNOWN_EXT = (".py", ".md", ".html", ".json", ".js", ".txt", ".csv", ".yaml", ".yml")

MIN_PATH_POINTERS = 100
MIN_SYMBOL_REFS = 40
MIN_SECTION_POINTERS = 40


def docs():
    """两个根下的全部文档：search_source/*/*.md + subskills/*/*.md。"""
    return sorted(p for base in DOC_ROOTS for p in base.glob("*/*.md"))


def subskill_dirs():
    return [p for base in DOC_ROOTS for p in sorted(base.iterdir()) if p.is_dir()]


def doc_dir(name):
    """按目录名找它现在住在哪个根下（迁移过的在 search_source，专题的在 subskills）。

    写死一个根的话，哪天再把某源挪回去，用例只会报"目录不存在"这种与病因无关的红。
    """
    for base in DOC_ROOTS:
        q = base / name
        if q.is_dir():
            return q
    raise AssertionError("两个根下都没有 %s/" % name)


def line_no(text, idx):
    return text[:idx].count("\n") + 1


# ── 1 两份文档齐全 ───────────────────────────────────────────

def bundle_gaps(dirs, skill_texts):
    """缺文件与缺「## 工作流」的目录名。skill_texts: {目录名: SKILL.md 文本或 None}。"""
    gaps = []
    for d in dirs:
        if not (d / "SKILL.md").exists():
            gaps.append(f"{d.name}: 缺 SKILL.md")
        if d.name not in NO_NOTE_DOCS and not (d / "NOTE.md").exists():
            gaps.append(f"{d.name}: 缺 NOTE.md")
        if d.name in MIRROR_DOCS:
            continue
        t = skill_texts.get(d.name)
        if t is not None and not re.search(r"(?m)^##\s+.*工作流\s*$", t):
            gaps.append(f"{d.name}: SKILL.md 没有 ## 工作流 这一节")
    return gaps


class TestBundleComplete(unittest.TestCase):
    def test_every_subskill_has_both_docs_and_a_workflow(self):
        dirs = subskill_dirs()
        self.assertTrue(dirs, "两个根下一个目录都没有，语料空了")
        texts = {}
        for d in dirs:
            f = d / "SKILL.md"
            texts[d.name] = f.read_text(encoding="utf-8") if f.exists() else None
        self.assertEqual(bundle_gaps(dirs, texts), [])

    def test_mutation_workflow_heading_renamed_is_caught(self):
        dirs = subskill_dirs()
        victim = next(d for d in dirs if d.name not in MIRROR_DOCS)
        t = (victim / "SKILL.md").read_text(encoding="utf-8").replace(
            "## 工作流", "## 做事顺序", 1)
        self.assertIn(victim.name, " ".join(
            bundle_gaps(dirs, {d.name: (t if d == victim else
                                        (d / "SKILL.md").read_text(encoding="utf-8"))
                               for d in dirs})))

    def test_mirror_exemption_is_named_and_small(self):
        """豁免名单只在真有必要时用，且被豁免的目录其余四项照查。"""
        self.assertIn("chenyiwei-bbs", MIRROR_DOCS)
        self.assertLessEqual(len(MIRROR_DOCS), 2)
        for name in MIRROR_DOCS:
            self.assertTrue((doc_dir(name) / "SKILL.md").exists())


# ── 2 不引用主技能私有编号 ───────────────────────────────────

def parent_number_hits(text):
    """返回 (行号, 圈号) 列表：⑤ 及以上，即主技能那条 13 步线的私有编号。"""
    out = []
    for m in re.finditer("[" + CIRCLED + "]", text):
        if CIRCLED.index(m.group(0)) >= LOCAL_CIRCLED_MAX:
            out.append((line_no(text, m.start()), m.group(0)))
    return out


class TestNoParentStepNumbers(unittest.TestCase):
    def test_subskill_docs_stay_off_the_parent_numbering(self):
        bad = [(str(p.relative_to(ROOT)), hit) for p in docs()
               for hit in parent_number_hits(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], f"子技能文档里出现主技能私有编号：{bad}")

    def test_the_corpus_actually_uses_local_circled_numbers(self):
        """①–④ 确实在用（文内自数），否则第 2 项是在防一件不存在的事。"""
        used = sum(1 for p in docs()
                   for m in re.finditer("[①②③④]", p.read_text(encoding="utf-8")))
        self.assertGreaterEqual(used, 10, f"语料里 ①–④ 只有 {used} 处，规则可能已空转")

    def test_mutation_parent_step_pointer_is_caught(self):
        p = doc_dir("chinatax") / "SKILL.md"
        text = p.read_text(encoding="utf-8")
        anchor = "定级层按 `status`／`effect_level` 归档"
        self.assertIn(anchor, text, "注入点不在这份文档里，先改注入锚")
        broken = text.replace(anchor, "按 ⑧ 定级层归档", 1)
        self.assertTrue(parent_number_hits(broken), "改写成「按 ⑧ 定级」这种指针没被查出来")
        self.assertEqual(parent_number_hits(text), [], "原文本身就该是零命中")


# ── 3 路径指针存在 ──────────────────────────────────────────

def token_paths(token):
    """一个路径指针的候选写法：原样、去掉尾部 `.符号名`、目录尾斜杠去掉。"""
    out, t = [], token.strip("/")
    for _ in range(4):
        out.append(t)
        seg = t.rsplit("/", 1)[-1]
        if "." in seg and not seg.endswith(KNOWN_EXT):
            t = t.rsplit(".", 1)[0]
            out.append(t)
            continue
        break
    return out


def path_resolves(token, sdir):
    for cand in token_paths(token):
        if "*" in cand:
            if any(list(Path(base).glob(cand)) for base in (sdir, ROOT)):
                return True
            continue
        for base in (sdir, ROOT):
            q = Path(base) / cand
            if q.exists() or q.with_suffix(".py").exists():
                return True
    return False


def path_gaps(pairs):
    """pairs: [(相对路径, 子技能目录, 文本)]。返回 [(文件, 行号, 指针)]。"""
    return [(rel, line_no(text, m.start()), m.group(0))
            for rel, sdir, text in pairs
            for m in PATH_RE.finditer(text)
            if not path_resolves(m.group(0), sdir)]


class TestPathPointers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = [(str(p.relative_to(ROOT)), p.parent, p.read_text(encoding="utf-8"))
                     for p in docs()]

    def test_counted_pointer_volume_is_still_there(self):
        n = sum(len(PATH_RE.findall(t)) for _r, _s, t in self.pairs)
        self.assertGreaterEqual(n, MIN_PATH_POINTERS,
                                f"路径指针只有 {n} 处，低于登记口径 {MIN_PATH_POINTERS}："
                                f"要么文档被清空，要么提取正则改窄了")

    def test_every_repo_path_pointer_lands(self):
        self.assertEqual(path_gaps(self.pairs), [])

    def test_local_references_directory_counts_as_resolved(self):
        """R&D-Expenses 自带 references/，指针先按子技能目录解——这条钉住
        两解法的优先级，否则删掉本地那份会被读成断链。"""
        sdir = doc_dir("R&D-Expenses")
        self.assertTrue((sdir / "references").is_dir())
        self.assertTrue(path_resolves("references/rd-mgmt-methodology.md", sdir))

    def test_mutation_bogus_script_name_is_caught(self):
        broken = [("search_source/chinatax/SKILL.md", doc_dir("chinatax"),
                   "入口在 `scripts/tax_web_searchx.py`")]
        gaps = path_gaps(broken)
        self.assertEqual([g[2] for g in gaps], ["scripts/tax_web_searchx.py"],
                         "拼错的脚本名没被查出来")

    def test_mutation_dropped_local_reference_file_is_caught(self):
        sdir = doc_dir("R&D-Expenses")
        real = path_resolves("references/rd-mgmt-methodology.md", sdir)
        ghost = path_resolves("references/rd-mgmt-methodologx.md", sdir)
        self.assertTrue(real)
        self.assertFalse(ghost, "子技能本地 references/ 里不存在的文件被放过了")


# ── 4 「第X步／第X节」指针落地 ───────────────────────────────

def named_md_target(pre, own_path):
    """紧邻前 40 字里最后一个 .md 文件名 → 目标文件；解不到回 None。"""
    hits = list(MD_RE.finditer(pre))
    if not hits:
        return None
    tok = hits[-1].group(0)
    if tok in ("NOTE.md", "SKILL.md"):
        if tok == "SKILL.md" and ("母技能" in pre or "主技能" in pre):
            return ROOT / "SKILL.md"
        return own_path.parent / tok
    for base in (own_path.parent, ROOT):
        q = Path(base) / tok
        if q.exists():
            return q
    return "MISSING"


def marker_exists(text, num, kind):
    if kind == "步":
        return f"**第{num}步" in text
    return bool(re.search(r"(?m)^#{2,4}\s*" + num + "、", text)) or \
        bool(re.search(r"(?m)^#{2,4}\s*第" + num + "节", text))


def section_pointers(text, own_path):
    """[(行号, 原文, [候选目标文件])] —— 定义行（标题、`**第X步`）不算指针。"""
    out = []
    for m in SEC_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].lstrip().startswith("#"):
            continue
        if text[max(0, m.start() - 2):m.start()] == "**":
            continue
        pre = text[max(0, m.start() - 40):m.start()]
        kind = m.group(2)
        tgt = named_md_target(pre, own_path)
        if tgt == "MISSING":
            cands = [Path("〈不存在〉")]
        elif tgt is not None:
            cands = [tgt]
        else:
            cands = [own_path, own_path.parent / "SKILL.md", own_path.parent / "NOTE.md"]
        out.append((line_no(text, m.start()), m.group(0), cands, kind, m.group(1)))
    return out


def section_gaps(pairs, overrides=None):
    """pairs: [(相对路径, 文件 Path, 文本)]；overrides: {Path: 文本} 供变异用。

    候选目标文件先查 overrides，再落盘读——不然在内存里改坏的 NOTE.md，指针那一路
    仍从盘上读到原版，变异注入等于没注入。
    """
    overrides = overrides or {}

    def read(q):
        return overrides.get(q, q.read_text(encoding="utf-8"))

    gaps = []
    for rel, p, text in pairs:
        for ln, raw, cands, kind, num in section_pointers(text, p):
            if not any(c.exists() and marker_exists(read(c), num, kind) for c in cands):
                gaps.append((rel, ln, raw, [str(c) for c in cands]))
    return gaps


class TestSectionPointers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = [(str(p.relative_to(ROOT)), p, p.read_text(encoding="utf-8"))
                     for p in docs()]

    def test_counted_pointer_volume_is_still_there(self):
        n = sum(len(section_pointers(t, p)) for _r, p, t in self.pairs)
        self.assertGreaterEqual(n, MIN_SECTION_POINTERS,
                                f"编号指针只有 {n} 处，低于登记口径 {MIN_SECTION_POINTERS}："
                                f"要么提取正则改窄了，要么指针被删空")

    def test_every_numbered_pointer_lands(self):
        self.assertEqual(section_gaps(self.pairs), [])

    def test_two_numbering_conventions_are_both_in_use(self):
        """步与节各有一套定义形态；某一套消失说明规则在查一件不存在的事。"""
        kinds = {k for _r, p, t in self.pairs for _l, _raw, _c, k, _n in section_pointers(t, p)}
        self.assertEqual(kinds, {"步", "节"}, f"本轮只解出 {kinds} 一种编号")

    def test_mutation_renumbered_note_section_is_caught(self):
        """注入锚选被指针指到的那一节。`chinatax/SKILL.md` 里指 NOTE 的是「第三节」
        与「第四节」，「第二节」没人指——改它报不出红，只能证明用例在查一件不存在的事。"""
        p = doc_dir("chinatax") / "NOTE.md"
        skill = doc_dir("chinatax") / "SKILL.md"
        pairs = [("search_source/chinatax/SKILL.md", skill, skill.read_text(encoding="utf-8")),
                 ("search_source/chinatax/NOTE.md", p, p.read_text(encoding="utf-8"))]
        self.assertEqual(section_gaps(pairs), [], "对照：未破坏时这一路本来全落地")
        anchor = "## 三、search5 的值域"
        self.assertIn(anchor, p.read_text(encoding="utf-8"), "注入点不在 NOTE 里，先改注入锚")
        broken = p.read_text(encoding="utf-8").replace(anchor, "## 柒、search5 的值域", 1)
        hit = [g for g in section_gaps(pairs, overrides={p: broken})
               if g[0].endswith("SKILL.md") and g[2] == "第三节"]
        self.assertTrue(hit, "NOTE 那节的序号改了名，SKILL 里指它的「第三节」却没报红")

    def test_mutation_renamed_step_marker_is_caught(self):
        p = doc_dir("npc-flk") / "SKILL.md"
        text = p.read_text(encoding="utf-8")
        self.assertIn("**第四步 分类编号", text, "注入点不在这份文档里，先改注入锚")
        broken = text.replace("**第四步 分类编号", "**丁四步 分类编号", 1)
        pairs = [("search_source/npc-flk/SKILL.md", p, broken)]
        gaps = section_gaps(pairs, overrides={p: broken})
        self.assertTrue(any(g[2] == "第四步" for g in gaps),
                        f"步定义改名之后指它的「第四步」没被报红：{gaps}")
        self.assertEqual(section_gaps([("search_source/npc-flk/SKILL.md", p, text)]), [],
                         "对照：原文这一路本来全落地")


# ── 5 代码符号可核对 ────────────────────────────────────────

def symbol_gaps(pairs, modules):
    """pairs: [(相对路径, 文本)]；modules: {模块名: 模块对象或 None}。"""
    gaps = []
    for rel, text in pairs:
        for m in SYM_RE.finditer(text):
            mod, sym = m.group(1), m.group(2)
            if sym == "py":          # `tax_x.py` 这种是文件名写法，不是符号
                continue
            obj = modules.get(mod)
            if obj is None or not hasattr(obj, sym):
                gaps.append((rel, line_no(text, m.start()), m.group(0)))
    return gaps


class TestSymbolRefs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        cls.pairs = [(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))
                     for p in docs()]
        names = {m.group(1) for _r, t in cls.pairs for m in SYM_RE.finditer(t)
                 if m.group(2) != "py"}
        cls.modules = {}
        for n in names:
            try:
                cls.modules[n] = importlib.import_module(n)
            except Exception:  # noqa: BLE001 模块取不到本身就是缺口，交给下面那条用例
                cls.modules[n] = None

    def test_counted_pointer_volume_is_still_there(self):
        n = sum(1 for _r, t in self.pairs for m in SYM_RE.finditer(t) if m.group(2) != "py")
        self.assertGreaterEqual(n, MIN_SYMBOL_REFS,
                                f"符号引用只有 {n} 处，低于登记口径 {MIN_SYMBOL_REFS}")

    def test_every_named_symbol_exists_on_the_module(self):
        self.assertEqual(symbol_gaps(self.pairs, self.modules), [])

    def test_missing_module_is_a_gap_not_a_skip(self):
        broken = [("search_source/npc-flk/SKILL.md", "见 `tax_npc_flk.search_npc`")]
        self.assertEqual([g[2] for g in symbol_gaps(broken, {"tax_npc_flk": None})],
                         ["`tax_npc_flk.search_npc`"], "取不到的模块被放过了")

    def test_mutation_renamed_symbol_is_caught(self):
        doc = doc_dir("chinatax") / "SKILL.md"
        pairs = [(doc.relative_to(ROOT).as_posix(), doc.read_text(encoding="utf-8"))]
        self.assertEqual(symbol_gaps(pairs, self.modules), [], "对照：原文本来全落地")
        text = pairs[0][1].replace("`tax_web_search.search_chinatax`",
                                   "`tax_web_search.search_chinatax_v2`", 1)
        self.assertNotEqual(pairs[0][1], text, "注入点没落进文本")
        hit = symbol_gaps([(pairs[0][0], text)], self.modules)
        self.assertEqual([g[2] for g in hit], ["`tax_web_search.search_chinatax_v2`"],
                         f"改名的符号没被报红：{hit}")

    def test_py_filename_form_is_not_read_as_a_symbol(self):
        """`tax_search.py` 里 group(2) 是 "py"，那是文件名不是属性名。"""
        self.assertTrue(SYM_RE.search("`tax_search.py`"))
        self.assertEqual(symbol_gaps([("x.md", "见 `tax_search.py`")],
                                     {"tax_search": self.modules.get("tax_search")}), [])


# ── 6 子技能自己声明的文件哈希可核对 ────────────────────────

# 子技能 NOTE 的「收录来源」表里会写一行文件哈希，读者拿它判断"盘上这份脚本还是不是
# 文档描述的那一份"。这一行一旦没人复算，就会长期停在旧值上：2026-11-26 实测
# `maodocs/NOTE.md` 声明的 `0de9f8a6…` 与盘上 `b8e54c49…` 对不上已经一个多月
# （中途 `4ecd192` 改过 maodocs.py 一句 WAF 文案，声明没跟着换），而文档读起来毫无异常。
# 这一层只问"声明与盘上是否同源"，不问脚本内容对不对。
HEX64_RE = re.compile(r"\b[0-9a-f]{64}\b")
BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")


def declared_hashes(text):
    """从一份 NOTE 的表格里解出 [(声明值, 目标文件名, 行号)]。

    两种写法都认：

      | `maodocs.py` SHA-256 | `<64 位>`（…） |
      | SHA-256 | `<64 位>` |          ← 目标名取上面「文件」那一行

    正文里讲 SHA-256 的句子不算（只认以 `|` 开头的表格行），否则 maodocs 末尾那段
    「NOTE 声明的 `*.py` SHA-256 必须等于盘上现算」会被当成一条声明。
    """
    out = []
    named = None
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        head = cells[0]
        if "SHA-256" not in head and "SHA256" not in head:
            if head in ("文件", "本目录文件"):
                toks = BACKTICK_TOKEN_RE.findall(cells[1])
                named = toks[0] if toks else None
            continue
        toks = [t for t in BACKTICK_TOKEN_RE.findall(head) if "." in t]
        target = toks[0] if toks else named
        m = HEX64_RE.search(cells[1])
        if target and m:
            out.append((m.group(0), target, i))
    return out


def hash_gaps(pairs, overrides=None):
    """pairs: [(相对路径, NOTE 的 Path, 文本)]；overrides: {相对路径: 文本} 供变异用。"""
    overrides = overrides or {}
    gaps = []
    for rel, p, text in pairs:
        for value, name, ln in declared_hashes(text):
            f = p.parent / name
            if not f.exists():
                gaps.append(f"{rel}:{ln} 声明了 {name} 的哈希，但该文件不存在")
                continue
            if name in overrides:
                disk = hashlib.sha256(overrides[name].encode("utf-8")).hexdigest()
            else:
                disk = hashlib.sha256(f.read_bytes()).hexdigest()
            if disk != value:
                gaps.append(f"{rel}:{ln} 声明 {name} 是 {value[:12]}…，盘上是 {disk[:12]}…")
    return gaps


class TestDeclaredFileHashes(unittest.TestCase):
    """NOTE 声明的哈希要与盘上现算一致；不一致时要么改脚本要么改声明，不能两头都不动。"""

    @classmethod
    def setUpClass(cls):
        cls.pairs = [(str(p.relative_to(ROOT)), p, p.read_text(encoding="utf-8"))
                     for p in docs() if p.name == "NOTE.md"]

    def test_every_declared_hash_matches_the_file_on_disk(self):
        self.assertEqual(hash_gaps(self.pairs), [])

    def test_the_three_known_declarations_are_all_parsed(self):
        """语料里到底声明了几枚，用例自己得数得出来——一枚都解不到时这条会红，
        否则「全部对得上」只是因为什么都没查。"""
        got = {(p.parent.name, name) for _r, p, t in self.pairs
               for _v, name, _l in declared_hashes(t)}
        self.assertIn(("maodocs", "maodocs.py"), got)
        self.assertIn(("szse-lawrules", "szse.py"), got)
        self.assertIn(("chenyiwei-bbs", "SKILL.md"), got)

    def test_mutation_stale_declaration_is_caught(self):
        """把 maodocs 那行换回 2026-09-29 的旧值（真发生过的漂移），必须报红。"""
        target = next((r, p, t) for r, p, t in self.pairs if p.parent.name == "maodocs")
        stale = target[2].replace(
            hashlib.sha256((target[1].parent / "maodocs.py").read_bytes()).hexdigest(),
            "0de9f8a6ad6c494d6db6274cf573198399f295b3b948751b70cda4d4b6826a34", 1)
        self.assertNotEqual(stale, target[2], "声明行里已经是旧值了，注入点要先重选")
        gaps = hash_gaps([(target[0], target[1], stale)])
        self.assertTrue(any("maodocs.py" in g for g in gaps), f"旧哈希没被报红：{gaps}")

    def test_mutation_missing_target_file_is_a_gap_not_a_skip(self):
        broken = [("x/NOTE.md", doc_dir("maodocs"),
                   "| `nope.py` SHA-256 | `"
                   + "a" * 64 + "` |")]
        self.assertEqual(len(hash_gaps(broken)), 1)


class TestSzseRenderedAnchors(unittest.TestCase):
    """深交所业务规则页直连只回模板：模板分支里的占位锚不得当成规则条目。

    现场证据（2026-11-26，`.tmp-inspect/szse-stock-direct.html`，30674 字节）：
    `rule/stock/trade/index.html` 直连取回三枚 `art-list-link`——一枚在 HTML 注释里、
    两枚躺在 EJS 模板的 `<% if …%>` 与 `<%}else%>` 两个分支里。`_strip_comments` 只挡
    得住注释那一枚，另外两枚会被解成
    `title='<%=replaceTitle(item.doctitle)%>'` 的假条目。`general`/`bond` 同形。
    这不是"少收几条"，是**假条目静默进索引**：浏览器起了但 JS 没跑完时
    `_enumerate_browser` 拿到模板本身、items 非空 ⇒ 既不报错也不收尾。
    """

    # 照存档页抄下来的那三段（分支一 / 分支二 / 注释），顺序与原文一致
    TEMPLATE = (
        '<div class="title">\n'
        "<%if(!(item.doctype== 'html' || item.doctype== 'pdf') && "
        "item.doctype !== 'link'){%>\n"
        '  <a class="ellipsis art-list-link" href="<%=item.docpuburl%>" '
        'title="<%=replaceTitle(item.doctitle)%>" target="_self">\n'
        "<%}else{%>\n"
        '  <a class="ellipsis art-list-link" href="<%=item.docpuburl%>" '
        'title="<%=replaceTitle(item.doctitle)%>" target="_blank">\n'
        "<%}%>\n"
        '  <!-- <a class="ellipsis art-list-link" href="<%=item.docpuburl%>" '
        'title="<%=replaceTitle(item.doctitle)%>" target="_blank"> -->\n'
        "</div>\n"
    )

    RENDERED = (
        '<div class="list">\n'
        '  <a class="ellipsis art-list-link" '
        'href="/www/lawrules/rule/stock/trade/t20260101_12345.html" '
        'title="深圳证券交易所股票上市规则（2025 年修订）" target="_self">\n'
        '  <span class="time">2026-01-01</span>\n'
        "</div>\n"
    )

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(doc_dir("szse-lawrules")))
        import szse as mod
        cls.szse = mod

    def test_the_fixture_really_has_three_anchors(self):
        """桩得先证明自己是那个形状：三枚锚、剔注释后还剩两枚。"""
        self.assertEqual(self.TEMPLATE.count("art-list-link"), 3)
        self.assertEqual(self.szse._strip_comments(self.TEMPLATE).count("art-list-link"), 2,
                         "剔注释之后仍应是两枚（注释那一枚被剔掉）")

    def test_template_branches_yield_no_items(self):
        self.assertEqual(self.szse._parse_rendered(self.TEMPLATE), [])

    def test_rendered_page_still_parses_with_its_date(self):
        got = self.szse._parse_rendered(self.RENDERED)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["date"], "2026-01-01")
        self.assertTrue(got[0]["title"].startswith("深圳证券交易所股票上市规则"))

    def test_placeholder_is_dropped_without_touching_real_rows(self):
        """同一页里既真有渲染条目又有占位锚时，只丢占位锚。"""
        mixed = self.RENDERED + self.TEMPLATE
        got = self.szse._parse_rendered(mixed)
        self.assertEqual([r["title"] for r in got], ["深圳证券交易所股票上市规则（2025 年修订）"])


class TestBrowserChannelPaging(unittest.TestCase):
    """浏览器通道的页码收尾：只认站点自己写的那个数（2026-11-26 实测）。

    实测在 `rule/stock/trade/index.html` 等 11 枚通道页上，分页那行渲染成
    `当前第<span class="num-cur">1</span>页&nbsp;&nbsp;共<span
    class="num-all">1</span>页`：既没有连续的「共 1 页」文本（旧的 `_PAGES`
    匹配不到），第二屏地址 `index_1.html` 也压根不存在（静态 404、浏览器里
    是 128738 字节的错误页）。当时每枚通道都要白发一次错误页请求。
    """

    ROW = ('  <a class="ellipsis art-list-link" '
           'href="/www/lawrules/rule/stock/trade/t2026010{i}_1234{i}.html" '
           'title="业务规则第{i}条" target="_self">\n'
           '  <span class="time">2026-01-0{i}</span>\n')

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(doc_dir("szse-lawrules")))
        import szse as mod
        cls.szse = mod

    def page(self, total, idx=0):
        """造一枚渲染后的页面：一条条目 + 站点自报的页数（照实测 DOM 形状）。"""
        head = '<div class="list">' + self.ROW.format(i=idx + 1) + '</div>'
        nav = ('<div class="current-page">当前第'
               '<span class="num-cur">' + str(idx + 1) + '</span>页'
               '&nbsp;&nbsp;共<span class="num-all">' + str(total) + '</span>页</div>')
        return head + nav

    def test_the_paginator_text_defeats_the_legacy_regex(self):
        """旧锚认不出这行文本 —— 所以才需要第二枚页码锚。"""
        html = self.page(1)
        self.assertIsNone(self.szse._PAGES.search(html))
        self.assertEqual(self.szse._PAGES_R.search(html).group(1), "1")

    def test_one_page_site_makes_exactly_one_request(self):
        calls = []

        class Sess:
            def read_html(self, url):
                calls.append(url)
                return self.sz_page

        s = Sess()
        s.sz_page = self.page(1)
        got = self.szse._enumerate_browser("rule/stock/trade/index.html", s, 40)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(calls), 1, "站点自报共 1 页时不该再猜第二屏地址：%s" % calls)
        self.assertNotIn("index_1.html", calls[0])

    def test_reported_page_count_is_honoured(self):
        """自报 3 页就取到第 3 屏为止，不多发。"""
        calls = []

        class Sess:
            def read_html(self, url):
                calls.append(url)
                return self.page_for(len(calls) - 1)

        s = Sess()
        s.page_for = lambda i: self.page(3, i)
        got = self.szse._enumerate_browser("rule/stock/trade/index.html", s, 40)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(got), 3)

    def test_empty_second_page_still_stops_cleanly(self):
        """站点没写页数时，退回到旧行为：第二屏空就停，不报错也不越界。"""
        calls = []
        row = self.ROW.format(i=1)

        class Sess:
            def read_html(self, url):
                calls.append(url)
                if len(calls) == 1:
                    return '<div class="list">' + row + '</div>'
                return '<html><body>错误页</body></html>'

        got = self.szse._enumerate_browser("rule/stock/trade/index.html", Sess(), 40)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(calls), 2)


# ── 7 上游镜像件的声明要有当日读数背书 ──────────────────────

# chenyiwei-bbs 那份 NOTE 长期写着「与上游字节一致，未作任何改写」，而本仓库没有任何
# 可复跑的东西量过上游：上面第 6 层哈希守卫只核对「盘上这份 == NOTE 声明的那串」。
# 2026-11-26 第一次量，上游那份只剩 7 枚端点（盘上 13 枚）、逐行不同 305 行，而且
# 盘上表里的 /api/public/related 今天回 410——照 NOTE 旧教的 `curl -o` 直接覆盖会把
# 一份更全的文档换成一份更旧的。这一层不问上游对不对，只问「这句声明有没有当日的
# 读数撑着」：没有日期的句子等于没量过。
MIRROR_DIR = SEARCH_SOURCE / "chenyiwei-bbs"
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")


def calibration_rows(text):
    """实测校正那张表的数据行（带粗体首格的那些），表头与分隔行不算。"""
    body = text.split("## 实测校正", 1)
    assert len(body) == 2, "NOTE 里没有「实测校正」那一节"
    rows = []
    for ln in body[1].split("## 主线里的唯一入口", 1)[0].splitlines():
        s = ln.strip()
        if not s.startswith("|") or s.count("|") < 4:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if "**" in cells[0]:
            rows.append(ln)
    return rows


def probe_plan(path):
    """从探针源码里解出端点清单与请求上限（不发请求，纯静态读）。"""
    plan = cap = None
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", "")
            if name == "ENDPOINT_PROBES":
                plan = ast.literal_eval(node.value)
            elif name == "MAX_REQUESTS":
                cap = ast.literal_eval(node.value)
    return plan, cap


class TestMirrorClaimBackedByReadings(unittest.TestCase):
    """镜像件的收录声明、实测校正表与常驻探针三者要互相对得上。"""

    @classmethod
    def setUpClass(cls):
        cls.note = (MIRROR_DIR / "NOTE.md").read_text(encoding="utf-8")
        cls.probe = MIRROR_DIR / "probe_mirror.py"

    def test_a_rerunnable_probe_exists_next_to_the_mirror(self):
        """没有可复跑的探针，「与上游比过」这句话就只是叙述。"""
        self.assertTrue(self.probe.exists(),
                        "chenyiwei-bbs 目录里没有 probe_mirror.py——镜像声明没人能复算")

    def test_the_source_table_admits_divergence_instead_of_claiming_identity(self):
        row = [ln for ln in self.note.splitlines() if ln.strip().startswith("| 文件 |")]
        self.assertEqual(1, len(row), "收录来源表里那一行「文件」不唯一")
        self.assertIn("分叉", row[0],
                      "「文件」那一行仍在声称与上游一致；上游已改，这句必须写成分叉")
        self.assertTrue(DATE_RE.search(row[0]), "分叉那句没带量到它的日期")

    def test_every_calibration_row_carries_a_measured_date(self):
        rows = calibration_rows(self.note)
        self.assertGreaterEqual(len(rows), 6,
                                "校正表少于 6 行（本轮 %d 行），判据面被改空了" % len(rows))
        undated = [ln.split("|")[1].strip()[:24] for ln in rows if not DATE_RE.search(ln)]
        self.assertEqual([], undated, "这些行没有日期，等于没量过：%s" % undated)

    def test_the_probe_plan_matches_the_request_count_the_note_promises(self):
        """NOTE 教的复测入口写了几发，探针就得计划几发（上游一发 + 端点逐枚一发）。"""
        plan, cap = probe_plan(self.probe)
        self.assertTrue(plan, "探针里没有 ENDPOINT_PROBES 这张表")
        self.assertTrue(cap, "探针里没有 MAX_REQUESTS 这个上限")
        total = 1 + len(plan)
        self.assertLessEqual(total, cap, "计划 %d 发超过上限 %d" % (total, cap))
        entry = [ln for ln in self.note.splitlines() if "%d 发" % total in ln]
        self.assertTrue(entry,
                        "NOTE 里没有「%d 发」这句（探针计划 1 发上游 + %d 枚端点）"
                        % (total, len(plan)))

    def test_the_wider_docs_do_not_repeat_the_byte_identity_claim(self):
        for rel in ("README.md", "references/out_of_library_layers.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            bad = [ln.strip()[:60] for ln in text.splitlines()
                   if "字节一致" in ln and ("chenyiwei" in ln.lower() or "auditdog" in ln)]
            self.assertEqual([], bad, "%s 还在声称那份镜像与上游字节一致：%s" % (rel, bad))

    def test_mutation_an_undated_calibration_row_is_caught(self):
        """把某一行里的日期全抹掉，那一行必须报红（判据不报红等于没有）。"""
        hit = next(ln for ln in calibration_rows(self.note) if DATE_RE.search(ln))
        broken = self.note.replace(hit, DATE_RE.sub("当日", hit), 1)
        self.assertNotEqual(broken, self.note, "注入没改动文本，注入点要重选")
        undated = [ln.split("|")[1].strip()[:24]
                   for ln in calibration_rows(broken) if not DATE_RE.search(ln)]
        self.assertEqual(1, len(undated), "无日期行没被抓到：%s" % undated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
