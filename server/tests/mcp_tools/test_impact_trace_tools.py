"""``impact_analysis`` / ``trace_call_path`` 两个 MCP 工具的守护测试（覆盖 IMPACT-06）。

范式照 ``test_reverse_lookup_tool.py``：模块级 ``pytestmark`` + 模块级 URL 常量 +
``mcp_client`` / ``indexed_repository`` 两个 conftest fixture（前者返回
``(APIClient, plaintext_token)``，已带 Bearer 头）。

⚠️ ``tests/mcp_tools/test_schema_snapshot.py`` 的两条字面量条目**不在本 plan**：它与
``mcp_tools/urls.py`` + ``TOOL_SCHEMA_SNAPSHOT`` 必须同批落地（归 122-08），否则那条
urls ↔ snapshot 的双向断言会在两个 wave 之间一直红着。

Wave 0（Plan 122-01）只落骨架，用例由 122-08 / 122-10 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

IMPACT_URL = "/api/mcp/tools/impact_analysis/"
TRACE_URL = "/api/mcp/tools/trace_call_path/"


@pytest.mark.skip(reason="Wave 0 桩：由 122-08 落地")
def test_impact_tool_unauthenticated() -> None:
    """MCP：未带 PAT → 401 ``authentication_failed``。

    （Req: IMPACT-06, 决策: D-21）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-08 落地")
def test_impact_tool_repository_not_indexed() -> None:
    """MCP：未索引仓 → 400 ``repository_not_indexed``。

    （Req: IMPACT-06, 决策: D-03 / D-21）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-08 落地")
def test_degradation_markers_surfaced() -> None:
    """四个降级标记 + **数值** ``resolution_rate`` 全部出现在两面输出里。

    ⚠️ 全仓解析率中位数只有 0.17，``low_resolution`` 布尔值在这个常态下没有信息量——
    ``resolution_rate`` 必须始终透出**数值**（121-10 写给本相位的硬要求）。

    （Req: IMPACT-06, 决策: D-23）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-08 落地")
def test_excluded_files_invisible() -> None:
    """被排除文件的符号不出现在 impact/trace 输出（Phase 121 SC-4 的端到端兑现）。

    Phase 121 已在**装配阶段**过滤（节点根本不入图），本条补的是端到端回归——造数模板照
    ``test_reverse_lookup_tool.py`` 的 ``.env`` 用例。

    （Req: GRAPH-04 回填, 决策: D-17）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-08 落地")
def test_staleness_declared() -> None:
    """staleness 端到端：``behind_commits`` 有值时声明里含该数字，⛔ 不编造。

    （Req: IMPACT-06, 决策: D-22）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-10 落地")
def test_two_surfaces_same_payload() -> None:
    """**双面同源**：同一输入下 MCP 与对话壳产出的 ``data`` 段逐字节相同（D-21 防漂移）。

    全仓**第一条**此类守护。最接近的一对（``search_delivery_knowledge``）恰恰没有它，
    且已经在失败语义上漂移：同一个异常，MCP 面报「没有结果」、对话面报「工具坏了」。

    （Req: IMPACT-06, 决策: D-21）
    """
    pytest.fail("Wave 0 桩")
