#!/usr/bin/env python3
"""缓存落点出口（TAX_CACHE_DIR）的离线用例。

为什么有这枚出口：2026-11-24 用 .tmp-inspect/cache_write_footprint.py 逐文件实测，
tests/test_source_defects.py **每跑一遍**就往用户真实 ~/.cache/tax-analysis-skill
漏 2 枚 detail 条目（id 形如 SHARED-OK-<12hex>，uuid 每次不同 ⇒ 只增不减），
盘上已积 167 枚、占 detail 命名空间 94%；tests/test_tax_search.py 里那句
`CacheManager(enabled=True).clear()` 更是拿默认命名空间直接删用户盘的条目。

为什么不能只在测试侧解决：tests/run_all.py 的门禁是 subprocess 直跑**单个测试文件**
（走文件自身的 `if __name__ == "__main__"`），conftest.py 兜不住那条路。所以出口开在
生产代码里，测试在子进程入口设环境变量；本文件钉住这个口的五条性质：
  1. 设了出口：任何命名空间构造出来的 CacheManager 都落在该目录（默认关也生效）；
  2. 没设/设空：仍然回 ~/.cache/tax-analysis-skill（既有用户缓存不失联）；
  3. 写盘只落出口目录，用户真实目录一枚不多、一枚不少；模块级缓存
     （tax_detail._detail_cache 等）在导入那一刻就按当时的出口定型；
  4. clear() 依旧越不出自己的目录，也依旧只清自己的命名空间；
  5. tests/run_all.py 的门禁给每枚子进程都带上出口（兜住将来忘设的测试文件）。
全程离线，不联网，不往用户真实目录写任何东西（只读计数）。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tax_cache import CacheManager                       # noqa: E402

DEFAULT_DIR = Path.home() / ".cache" / "tax-analysis-skill"
PY = sys.executable

# 本模块被导入的那一刻出口是什么——只有 conftest.py（或外层门禁）先设过，
# 这里才可能非空。后面的用例用它判断"当前是 pytest 进程还是直跑"。
_ENV_AT_IMPORT = os.environ.get("TAX_CACHE_DIR", "").strip()
_IN_PYTEST = "PYTEST_CURRENT_TEST" in os.environ

# 子进程里要比的是「落点等不等于出口目录」，不能让 Windows 用户名（含中文）
# 经过 stdout 回读——GBK 控制台会把非 ASCII 变（?），比对就假失败。
# 读数一律只打印 ASCII 的 True/False。
_CHILD = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
expect = Path(sys.argv[2])
import tax_detail
import tax_sogou
print("detail_module", tax_detail._detail_cache.dir == expect)
print("sogou_module", tax_sogou._cache.dir == expect)
"""


class _set_exit:
    """临时把 TAX_CACHE_DIR 设成 path（None=清掉），退出时还原原状。"""

    def __init__(self, path):
        self._path = path
        self._had = "TAX_CACHE_DIR" in os.environ
        self._old = os.environ.get("TAX_CACHE_DIR")

    def __enter__(self):
        if self._path is None:
            os.environ.pop("TAX_CACHE_DIR", None)
        else:
            os.environ["TAX_CACHE_DIR"] = str(self._path)
        return self

    def __exit__(self, *exc):
        if self._had:
            os.environ["TAX_CACHE_DIR"] = str(self._old)
        else:
            os.environ.pop("TAX_CACHE_DIR", None)
        return False


def _user_entries() -> int:
    """只读数一下用户真实目录里的 json 条目；目录不存在按 0 算。"""
    if not DEFAULT_DIR.is_dir():
        return 0
    return sum(1 for p in DEFAULT_DIR.iterdir() if p.suffix == ".json")


def test_env_exit_sets_dir_for_every_namespace():
    """性质 1：设了出口，任何命名空间构造出来的 CacheManager 都指向它。"""
    with tempfile.TemporaryDirectory() as td:
        with _set_exit(td):
            for ns in ("default", "detail", "search", "fgk", "sogou"):
                cm = CacheManager(enabled=False, namespace=ns)
                assert cm.dir == Path(td), f"{ns} 没走出口：{cm.dir}"
                assert cm.enabled is False, "默认关的语义不能被出口改掉"
    return True


def test_unset_or_blank_falls_back_to_the_original_home_dir():
    """性质 2：没设、设空串、设纯空白，三种都回退原落点，既有缓存不失联。

    空白三档是核心（出口读的是 `os.environ.get(...).strip()`，去掉 strip 就漏）；
    「没设」那一档只有在**本进程导入时本来就没设**时才当场验——`python -m pytest`
    单进程跑时 conftest.py 已经先把出口设进临时目录（正是它挡住漏盘的第三层防线），
    把环境变量清掉也不会让已导入的模块回到未设状态，所以那种场合交给下一条的子进程。
    """
    if not _IN_PYTEST or not _ENV_AT_IMPORT:
        with _set_exit(None):
            assert CacheManager(enabled=True, namespace="detail").dir == DEFAULT_DIR, \
                "没设出口时落点变了，既有用户缓存会失联"
    else:
        print("  (未设那一档改由下面的子进程当场验：本进程出口在导入前已由 conftest 设好)")
    # 子进程里把出口彻底抹掉，落点必须还是用户目录——这一档与父进程状态无关，
    # 任何跑法都验得到，也正是"清空出口不会让已导入模块回退"那条事实的对照。
    env = dict(os.environ)
    env.pop("TAX_CACHE_DIR", None)
    r = subprocess.run([PY, "-c", _CHILD, str(SCRIPTS_DIR), str(DEFAULT_DIR)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    assert r.returncode == 0, f"子进程导入失败：{(r.stderr or '').strip()[:200]}"
    flags = dict(line.split() for line in r.stdout.splitlines() if line.strip())
    assert flags.get("detail_module") == "True", \
        f"没设出口时详情缓存落点变了：{flags}"
    assert flags.get("sogou_module") == "True", \
        f"没设出口时搜狗缓存落点变了：{flags}"
    for blank in ("", "   ", "\t"):
        with _set_exit(blank):
            cm = CacheManager(enabled=True, namespace="detail")
            assert cm.dir == DEFAULT_DIR, f"空白值 {blank!r} 没回退：{cm.dir}"
    return True


def test_writes_land_only_in_the_exit_dir():
    """性质 3：写盘只进出口目录，用户真实目录一枚不多、一枚不少。"""
    before = _user_entries()
    with tempfile.TemporaryDirectory() as td:
        with _set_exit(td):
            a = CacheManager(enabled=True, namespace="search")
            b = CacheManager(enabled=True, namespace="detail")
            a.set(a._key("search", "kw"), {"v": 1})
            b.set(b._key("detail", "ID-EXIT"), {"v": 2})
            got = {}
            for p in Path(td).iterdir():
                got[p.name] = json.loads(p.read_text(encoding="utf-8"))
            assert set(got) == {a._key("search", "kw") + ".json",
                                b._key("detail", "ID-EXIT") + ".json"}, \
                f"出口目录里的条目不对：{sorted(got)}"
            assert {d["_ns"] for d in got.values()} == {"search", "detail"}, \
                f"命名空间标记不对：{sorted(got)}"
    assert _user_entries() == before, "用户真实目录被写动了"
    return True


def test_module_level_cache_is_fixed_at_import():
    """性质 3 的来龙去脉：模块级缓存在**导入那一刻**读出口。

    这就是 tax_source_defects / test_tax_search 把 setdefault 放在导入 scripts
    之前的原因：晚一步设，_detail_cache 已经按用户目录定型了。用子进程验，
    因为在测试自己的进程里已经 import 过一遍，换不出第二次"导入时"。
    """
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env["TAX_CACHE_DIR"] = td
        r = subprocess.run([PY, "-c", _CHILD, str(SCRIPTS_DIR), td],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
        assert r.returncode == 0, f"子进程导入失败：{(r.stderr or '').strip()[:200]}"
        flags = dict(line.split() for line in r.stdout.splitlines() if line.strip())
        assert flags.get("detail_module") == "True", \
            f"tax_detail._detail_cache 没按出口定型：{flags}"
        assert flags.get("sogou_module") == "True", \
            f"tax_sogou._cache 没按出口定型：{flags}"
    return True


def test_clear_still_confined_to_exit_dir_and_own_namespace():
    """性质 4：出口改了落点，clear() 的两条边界一条都不能松。

    第二条边界尤其要紧：test_tax_search 那句 `CacheManager(enabled=True).clear()`
    用的就是**默认命名空间**，历史上它删的是用户盘。有了出口之后它只能清出口。
    """
    before = _user_entries()
    with tempfile.TemporaryDirectory() as td:
        with _set_exit(td):
            a = CacheManager(enabled=True, namespace="search")
            b = CacheManager(enabled=True, namespace="detail")
            a.set(a._key("search", "one"), {"v": 1})
            b.set(b._key("detail", "two"), {"v": 2})
            assert a.stats()["entries"] == 1 and b.stats()["entries"] == 1
            removed = a.clear()
            assert removed == 1, f"只该删自己命名空间那 1 条，实际 {removed}"
            assert b.stats()["entries"] == 1, "别家命名空间被误删"
            assert (Path(td) / (b._key("detail", "two") + ".json")).exists()

            # 默认命名空间清一次：既不能碰同目录别家，更不能碰用户盘
            d = CacheManager(enabled=True)
            d.clear()
            assert b.stats()["entries"] == 1, "默认命名空间把 detail 的条目清了"
    assert _user_entries() == before, "clear() 动到用户真实目录"
    return True


def test_gate_children_carry_the_exit():
    """性质 5：门禁这层兜底要在场——将来新测试忘了设，也漏不到用户盘。"""
    src = (TESTS_DIR / "run_all.py").read_text(encoding="utf-8")
    assert "def _gate_env()" in src, "门禁没有 _gate_env 这层兜底了"
    assert 'env["TAX_CACHE_DIR"]' in src, "兜底没设出口变量"
    assert "env=_gate_env()" in src, "子进程没把兜底环境传下去"
    return True


def test_test_files_set_the_exit_before_importing_scripts():
    """已知的两枚写入者必须把 setdefault 放在**导入 scripts 之前**。

    放在后面就晚了：模块级 _detail_cache 已经定型（上一用例验的就是这件事）。
    这里按字节顺序比，不依赖中文文案。
    """
    for name in ("test_source_defects.py", "test_tax_search.py"):
        src = (TESTS_DIR / name).read_text(encoding="utf-8")
        at_exit = src.find('os.environ.setdefault("TAX_CACHE_DIR"')
        assert at_exit != -1, f"{name} 没有设出口的语句"
        cut = src.find("import tax_detail")
        if cut == -1:
            cut = src.find("from tax_")
        assert cut != -1 and at_exit < cut, \
            f"{name} 的出口设晚了（在导入 scripts 之后）：{at_exit} vs {cut}"
    return True


def test_conftest_covers_the_single_process_run():
    """第三层防线：`python -m pytest tests` 是**一个进程**收全部测试。

    这条路上文件头的 setdefault 会漏：`test_detail_cache.py` 在收集顺序上排到
    `test_source_defects.py` 前面，它一 import 就把 `tax_detail` 拉进来，
    `_detail_cache` 当场按用户目录定型。当天实测这样漏出 2 枚条目。
    conftest.py 在所有测试模块之前加载，所以它设的值对模块级缓存才算"导入时"。
    """
    conftest = TESTS_DIR / "conftest.py"
    assert conftest.exists(), "tests/conftest.py 不见了，单进程跑法失去兜底"
    src = conftest.read_text(encoding="utf-8")
    at_exit = src.find('os.environ.setdefault("TAX_CACHE_DIR"')
    assert at_exit != -1, "conftest.py 没设出口"
    assert src.find("import") < at_exit, "conftest 里出口应在导入之后立刻设"
    assert "mkdtemp" in src, "conftest 的出口不是临时目录"
    # 而且它必须真的生效：pytest 收测试的场合，本进程此刻的出口应非空
    # （由 conftest 或外层门禁设上）。直跑本文件时没有 conftest，跳过这半条。
    if _IN_PYTEST:
        assert CacheManager(enabled=True, namespace="detail").dir != DEFAULT_DIR, \
            "当前进程的缓存落点还是用户目录——兜底层没起作用"
    return True


TESTS = [
    ("设出口后各命名空间同改道", test_env_exit_sets_dir_for_every_namespace),
    ("没设/设空仍回原落点", test_unset_or_blank_falls_back_to_the_original_home_dir),
    ("写盘只落出口目录", test_writes_land_only_in_the_exit_dir),
    ("模块级缓存在导入时定型", test_module_level_cache_is_fixed_at_import),
    ("clear 边界不松", test_clear_still_confined_to_exit_dir_and_own_namespace),
    ("门禁子进程带出口", test_gate_children_carry_the_exit),
    ("写入者测试先设出口再导入", test_test_files_set_the_exit_before_importing_scripts),
    ("conftest 兜住单进程跑法", test_conftest_covers_the_single_process_run),
]


def main():
    passed = 0
    print(f"缓存落点出口用例（{len(TESTS)} 条，全离线）")
    for name, fn in TESTS:
        try:
            fn()
            passed += 1
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}")
            print(f"         {e}")
        except Exception as e:                          # noqa: BLE001
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
    print(f"\n  结果：{passed}/{len(TESTS)} 通过")
    return 0 if passed == len(TESTS) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
