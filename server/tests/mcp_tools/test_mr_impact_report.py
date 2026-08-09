"""MCP ``create_merge_request`` 影响面附加 + workflow↔MCP 对等哨兵桩（DIFF-04 / D-14）。

归属 Plan 124-03：与 ``test_coding_impact_report`` 共用 ``build_impact_report_section``。
⛔ 不得改 ``mcp/`` submodule；⛔ 不得改 ``repo_router_v2.py``（D-16）。

Wave 0（Plan 124-00）只登记 pytest 节点名；实现由 Plan 124-03 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 124-02/124-03 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_mcp_create_mr_appends_impact_section() -> None:
    """MCP 建 MR 缺省 description 路径追加 ``## 影响面``。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_mcp_explicit_description_append_idempotent() -> None:
    """显式 description：无标记则 append；已含标记不重复。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_mcp_create_mr_failsoft_on_impact_error() -> None:
    """影响面失败仍创建 MR（D-09 fail-soft）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_workflow_mcp_impact_section_parity() -> None:
    """同一 (repo, compare) fixture 下 workflow 与 MCP 段规范化后一致（D-14）。"""
    pytest.fail("Wave 0 桩")
