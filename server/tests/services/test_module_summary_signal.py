"""``services/module_summary_signal.py`` Wave 0 验收桩（MOD-04 / D-15）。

行为用例由 125-04 去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_apply_signal_failsoft_on_error() -> None:
    """signal 侧任意异常 → 原样返回 router 排序（fail-soft）。

    （Req: MOD-04, 决策: D-15）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_apply_signal_appends_evidence_without_changing_router_base() -> None:
    """evidence / reason 文本追加；默认不改 router_base 分数。

    （Req: MOD-04, 决策: D-15）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-04 落地")
def test_empty_summaries_noop() -> None:
    """无模块摘要时零扰动（恒等返回）。

    （Req: MOD-04, 决策: D-15）
    """
    pytest.fail("Wave 0 桩")
