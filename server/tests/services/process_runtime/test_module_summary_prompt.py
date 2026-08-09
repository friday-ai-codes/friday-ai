"""调研 prompt「模块摘要」段 Wave 0 验收桩（MOD-04 / D-16）。

行为用例由 125-04 去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_empty_module_summaries_omits_section() -> None:
    """``module_summaries`` 为空时省略整段，不留空标题。

    （Req: MOD-04, 决策: D-16）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_budget_truncation_marks_truncated() -> None:
    """超 token 预算截断并标记 truncated。

    （Req: MOD-04, 决策: D-16, 威胁: T-125-04）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_relevance_sort_before_truncate() -> None:
    """截断前先按相关度排序，保留更相关社区摘要。

    （Req: MOD-04, 决策: D-16）
    """
    pytest.fail("Wave 0 桩")
