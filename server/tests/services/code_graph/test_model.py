"""``services/code_graph/model.py`` 的契约用例（覆盖 GRAPH-01）。

本文件目前只有用例桩，由 **Plan 121-02** 填充实现：四档置信度枚举
（resolved / bare_name / cross_repo / chunk_level）与数值映射，以及 ``reason``
字符串「输出时现推、不进边属性」的 D-08 决策。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名，否则验证链条从头就断。
"""

from __future__ import annotations

import pytest


# 121-VALIDATION.md：四档置信度枚举与数值映射（resolved=1.0 / bare_name=0.3 /
# cross_repo=match_confidence 原值 / chunk_level 默认关）。
@pytest.mark.skip(reason="stub：由 Plan 121-02 实现")
def test_edge_confidence_values() -> None:
    pass


# 121-VALIDATION.md：`reason` 现推不存（D-08）——边属性维持 3 个以内，
# reason 不得出现在 MultiDiGraph 的边属性字典里。
@pytest.mark.skip(reason="stub：由 Plan 121-02 实现")
def test_reason_not_stored_on_edge_attrs() -> None:
    pass
