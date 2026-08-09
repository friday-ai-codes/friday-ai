"""``impact`` / ``trace`` / ``detect_changes`` 对话工具壳的注册与 fail-closed 守护。

注册要**两处都挂**才对 LLM 可见：``agents/tools/__init__.py`` 的顶层 import 触发 ``@tool``
注册，``agents/chat_runner.py`` 的白名单常量决定它进不进对话。本仓已经为「漏挂白名单」还过
一次债（``find_api_callers`` 那批），所以这条断言两处都要查。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agents.tools.base import _tool_registry

pytestmark = pytest.mark.django_db


def test_registered_and_whitelisted() -> None:
    """对话：``@tool`` 已注册且在 ``chat_runner._INDEXED_TOOL_NAMES`` 白名单内。

    （Req: IMPACT-06, 决策: D-21）
    """
    import agents.tools  # noqa: F401 — 顶层 import 触发 @tool 注册
    from agents.chat_runner import _INDEXED_TOOL_NAMES

    want = {"impact_analysis", "trace_call_path"}
    assert want <= set(_tool_registry)
    assert want <= set(_INDEXED_TOOL_NAMES)
    for name in want:
        props = _tool_registry[name].parameters.get("properties") or {}
        assert "conversation_id" in props


def test_detect_changes_registered_in_indexed_tools() -> None:
    """``detect_changes`` 已注册且挂进索引模式白名单（注册 ≠ 暴露）。

    （Req: DIFF-01/DIFF-02, 决策: D-13）
    """
    import agents.tools  # noqa: F401 — 顶层 import 触发 @tool 注册
    from agents.chat_runner import _INDEXED_TOOL_NAMES
    from agents.tools import detect_changes as exported

    assert "detect_changes" in _tool_registry
    assert "detect_changes" in _INDEXED_TOOL_NAMES
    assert exported is _tool_registry["detect_changes"].func or callable(exported)
    props = _tool_registry["detect_changes"].parameters.get("properties") or {}
    assert "conversation_id" in props
    assert "compare" in props
    assert "branch" not in props


@pytest.mark.asyncio
async def test_conversation_owner_required_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """拿不到会话 owner 时工具必须自己拒绝（fail-closed）。

    🚨 这条对本相位是**硬要求**而非可选：``get_graph(user=None)`` 会走「系统路径」
    （埋点记 ``system``、ACL 空实现放行），**不会**被拒。所以对话壳必须在入口先挡住
    ``user is None``，不能指望取图那一层兜底。

    （Req: IMPACT-06, 决策: D-12）
    """
    import agents.tools.graph_tools as graph_tools

    run_impact = AsyncMock()
    resolve_repo = AsyncMock()
    monkeypatch.setattr("services.code_graph_tools.run_impact", run_impact)
    monkeypatch.setattr(graph_tools, "_resolve_tool_repo", resolve_repo)

    # 三种取不到 owner 的输入：空串 / 非法格式 / 合法但不存在的 UUID
    bad_ids = ["", "not-a-uuid", "00000000-0000-4000-8000-000000000099"]
    for conversation_id in bad_ids:
        result = await graph_tools.impact_analysis(
            repository_id="00000000-0000-4000-8000-000000000001",
            symbol="Foo",
            conversation_id=conversation_id,
        )
        assert result.success is False
        assert "fail-closed" in (result.error or "")
        assert run_impact.call_count == 0
        assert resolve_repo.call_count == 0

        result = await graph_tools.trace_call_path(
            repository_id="00000000-0000-4000-8000-000000000001",
            source="Foo",
            target="Bar",
            conversation_id=conversation_id,
        )
        assert result.success is False
        assert "fail-closed" in (result.error or "")
        assert run_impact.call_count == 0
        assert resolve_repo.call_count == 0


@pytest.mark.asyncio
async def test_detect_changes_fail_closed_without_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无会话 owner 时 ``detect_changes`` fail-closed，且不触达编排/取仓。

    （Req: DIFF-01/DIFF-02, 威胁: T-123-ACL）
    """
    import agents.tools.graph_tools as graph_tools

    run_detect = AsyncMock()
    resolve_repo = AsyncMock()
    monkeypatch.setattr("services.code_graph_tools.run_detect_changes", run_detect)
    monkeypatch.setattr(graph_tools, "_resolve_tool_repo", resolve_repo)

    bad_ids = ["", "not-a-uuid", "00000000-0000-4000-8000-000000000099"]
    for conversation_id in bad_ids:
        result = await graph_tools.detect_changes(
            repository_id="00000000-0000-4000-8000-000000000001",
            compare="feature/foo",
            conversation_id=conversation_id,
        )
        assert result.success is False
        assert "fail-closed" in (result.error or "")
        assert run_detect.call_count == 0
        assert resolve_repo.call_count == 0
