"""AICodingNode / mr_service 建 MR 路径影响面附加用例桩（DIFF-04）。

归属 Plan 124-03：直调 ``_create_mr_for_repo`` / ``create_mr_for_task``，
fail-soft 不阻断 ``create_merge_request``。

Wave 0（Plan 124-00）只登记 pytest 节点名；实现由 Plan 124-03 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 124-02/124-03 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_create_mr_appends_impact_section() -> None:
    """``_create_mr_for_repo`` 成功路径 description 含 ``## 影响面`` 段。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_create_mr_failsoft_on_impact_error() -> None:
    """影响面 helper 异常仍调用 ``create_merge_request``（D-09）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_create_mr_description_contains_stub_on_timeout() -> None:
    """超时 → description 含 stub ``timeout``（D-10/D-11）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_create_mr_for_task_failsoft_appends_impact() -> None:
    """``mr_service.create_mr_for_task``：成功 append；helper 异常仍建 MR。"""
    pytest.fail("Wave 0 桩")
