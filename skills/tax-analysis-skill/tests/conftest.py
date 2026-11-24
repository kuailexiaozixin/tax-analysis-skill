"""pytest 单进程跑全树时的缓存落点兜底。

三层防线各挡一条别挡不住的路（2026-11-24 实测）：
  1. `tests/run_all.py` 的 `_gate_env()`：门禁是 subprocess 逐文件直跑，
     conftest.py **不参与**那条路；
  2. `test_source_defects.py` / `test_tax_search.py` 文件头那句 setdefault：
     管的是「单独 `python tests/xxx.py` 直跑」；
  3. 本文件：管的是 `python -m pytest tests`（一个进程收全部测试）。

为什么第 2 层单独不够：单进程里模块按收集顺序导入，
`test_detail_cache.py` 排在 `test_source_defects.py` 之前，它一 import 就把
`tax_detail` 导入进来，`tax_detail._detail_cache` 当场按**用户真实目录**定型；
等后面的文件再设环境变量已经晚了。当天实测正是这样漏出 2 枚
`SHARED-OK-<12hex>` / `SHARED-NOCACHE-<12hex>` 条目。conftest 在所有测试模块
之前加载，所以它设的值对所有模块级缓存都算"导入时"。

不清理这个目录：测试子进程可能还在往里写，而它本身就在系统临时目录下。
"""

import os
import tempfile

os.environ.setdefault("TAX_CACHE_DIR", tempfile.mkdtemp(prefix="tax-pytest-cache-"))
