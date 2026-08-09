"""``impact`` / ``trace`` 对话工具壳的注册与 fail-closed 守护（覆盖 IMPACT-06）。

注册要**两处都挂**才对 LLM 可见：``agents/tools/__init__.py`` 的顶层 import 触发 ``@tool``
注册，``agents/chat_runner.py`` 的白名单常量决定它进不进对话。本仓已经为「漏挂白名单」还过
一次债（``find_api_callers`` 那批），所以这条断言两处都要查。

Wave 0（Plan 122-01）只落骨架，用例由 122-09 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(reason="Wave 0 桩：由 122-09 落地")
def test_registered_and_whitelisted() -> None:
    """对话：``@tool`` 已注册且在 ``chat_runner._INDEXED_TOOL_NAMES`` 白名单内。

    （Req: IMPACT-06, 决策: D-21）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-09 落地")
def test_conversation_owner_required_fail_closed() -> None:
    """拿不到会话 owner 时工具必须自己拒绝（fail-closed）。

    🚨 这条对本相位是**硬要求**而非可选：``get_graph(user=None)`` 会走「系统路径」
    （埋点记 ``system``、ACL 空实现放行），**不会**被拒。所以对话壳必须在入口先挡住
    ``user is None``，不能指望取图那一层兜底。

    （Req: IMPACT-06, 决策: D-12）
    """
    pytest.fail("Wave 0 桩")
