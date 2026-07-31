"""start_feature_solution 对话工具守护测试。

对话入口是 MCP 之外的第二条链路，它复用同一套编排但走 chat 的 HITL 通道，容易在两条链路
之一改动时漂移。这里钉住三件事：

- 待确认时返回 **plan 多题澄清 marker**（前端据此渲染 plan 卡，收答走 91-04 专路由），
  而不是 chat 单题 marker——两者物理隔离，混了会写错 ConversationIntentTrace。
- 调研在途时返回 ``__blocking_task__``（复用容器完成自动续驱 + barrier 回灌）。
- 无 feature list 来源时明确报错，不静默空跑。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.feature_solution_tools import start_feature_solution
from agents.tools.plan_research_tools import PLAN_CLARIFICATION_RENDER_MARKER
from initiatives.services.feature_solution_service import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RESEARCHING,
    FeatureSolutionError,
    FeatureSolutionState,
)

_CONV = "11111111-1111-1111-1111-111111111111"
_SPACE = "22222222-2222-2222-2222-222222222222"


def _state(status: str, **kwargs) -> FeatureSolutionState:
    return FeatureSolutionState(
        session_id="33333333-3333-3333-3333-333333333333",
        status=status,
        feature_count=2,
        classification={"summary": {"new": 1, "modify": 1, "unclear": 0}},
        **kwargs,
    )


def _patch_service(result=None, error: Exception | None = None):
    mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=result)
    return patch(
        "initiatives.services.feature_solution_service.FeatureSolutionService.start",
        new=mock,
    )


def _patch_context(actor=None, bound_project=None):
    return patch(
        "agents.tools.feature_solution_tools._resolve_conversation_context",
        new=AsyncMock(return_value=(actor, bound_project)),
    )


@pytest.mark.asyncio
async def test_awaiting_confirmation_returns_plan_clarification_marker() -> None:
    state = _state(
        STATUS_AWAITING_CONFIRMATION,
        clarification_id="44444444-4444-4444-4444-444444444444",
        questions=[{"question_id": "q1", "question": "请确认仓库"}],
    )
    with _patch_context(), _patch_service(state):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert result.success is True
    out = result.output
    # 必须是 plan 多题 marker，绝不能是 chat 单题的 ask_clarification。
    assert out["marker"] == PLAN_CLARIFICATION_RENDER_MARKER
    assert out["marker"] != "ask_clarification"
    assert out["pending"] is True
    assert out["clarification_id"] == "44444444-4444-4444-4444-444444444444"
    assert out["session_id"] == state.session_id
    assert "新增 1" in out["question"]


@pytest.mark.asyncio
async def test_researching_returns_blocking_task() -> None:
    state = _state(STATUS_RESEARCHING)
    with (
        _patch_context(),
        _patch_service(state),
        patch(
            "agents.tools.blocking_task_registry.register_blocking_task",
            new=AsyncMock(),
        ) as reg,
    ):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert result.success is True
    assert result.output["__blocking_task__"] is True
    assert result.output["task_type"] == "plan_research"
    assert result.output["task_id"] == state.session_id
    reg.assert_awaited_once()


@pytest.mark.asyncio
async def test_completed_returns_markdown() -> None:
    state = _state(
        STATUS_COMPLETED,
        markdown="# 技术方案\n\n## 分仓方案",
        artifact_version_id="55555555-5555-5555-5555-555555555555",
    )
    with _patch_context(), _patch_service(state):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert result.success is True
    assert result.output["status"] == "done"
    assert "## 分仓方案" in result.output["markdown"]
    assert result.output["classification_summary"] == {"new": 1, "modify": 1, "unclear": 0}


@pytest.mark.asyncio
async def test_failed_surfaces_error() -> None:
    state = _state(STATUS_FAILED, error={"message": "融合失败"})
    with _patch_context(), _patch_service(state):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert result.success is False
    assert "融合失败" in result.error


@pytest.mark.asyncio
async def test_failed_result_carries_session_id_for_bubble_binding() -> None:
    """110-HI-01：失败出口也带 session_id（经 metadata 出网）。

    与上一条分开写：`start_feature_solution` 的失败分支结构上只有一个自由文本 `error`，
    前端气泡因此绑不到自己那次编排，「失败后重跑」时会改显示新一轮的实时时间线。
    """
    state = _state(STATUS_FAILED, error={"message": "融合失败"})
    with _patch_context(), _patch_service(state):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert result.metadata == {"session_id": "33333333-3333-3333-3333-333333333333"}


@pytest.mark.asyncio
async def test_missing_source_without_bound_project_rejected() -> None:
    """既没给文本/分支、会话也没绑项目 → 明确报错并给出可操作提示。"""
    with _patch_context(actor=None, bound_project=None):
        result = await start_feature_solution(space_id=_SPACE, conversation_id=_CONV)

    assert result.success is False
    assert "feature_list_text" in result.error


@pytest.mark.asyncio
async def test_bound_project_used_when_no_explicit_source() -> None:
    """会话已绑定项目时，默认取该项目已录入的 feature list。"""
    state = _state(STATUS_AWAITING_CONFIRMATION, clarification_id="c1")
    bound = "66666666-6666-6666-6666-666666666666"
    with (
        _patch_context(actor=SimpleNamespace(id="u1"), bound_project=bound),
        _patch_service(state) as start_mock,
    ):
        await start_feature_solution(space_id=_SPACE, conversation_id=_CONV)

    assert start_mock.await_args.kwargs["project_id"] == bound


@pytest.mark.asyncio
async def test_explicit_text_takes_precedence_over_bound_project() -> None:
    """显式给了文本时不用项目的 feature list（用户贴的优先）。"""
    state = _state(STATUS_AWAITING_CONFIRMATION, clarification_id="c1")
    with (
        _patch_context(bound_project="66666666-6666-6666-6666-666666666666"),
        _patch_service(state) as start_mock,
    ):
        await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert start_mock.await_args.kwargs["project_id"] is None
    assert start_mock.await_args.kwargs["feature_list_text"] == "- 功能点 A"


@pytest.mark.asyncio
async def test_conversation_id_is_passed_to_session() -> None:
    """必须把 conversation_id 传进编排会话。

    前端 plan 澄清卡由 ``runtime.pending_plan_clarification`` 驱动，而 runtime 是
    **按 conversation_id 反查 ConvergenceSession** 的；收答专路由同理。漏传不会报错，
    但对话里确认卡渲染不出来、用户也无法作答——静默失效，必须钉住。
    """
    state = _state(STATUS_AWAITING_CONFIRMATION, clarification_id="c1")
    with _patch_context(), _patch_service(state) as start_mock:
        await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, feature_list_text="- 功能点 A"
        )

    assert start_mock.await_args.kwargs["conversation_id"] == _CONV
    assert start_mock.await_args.kwargs["entrypoint"] == "chat"


@pytest.mark.asyncio
async def test_service_error_surfaced_as_tool_error() -> None:
    with (
        _patch_context(),
        _patch_service(error=FeatureSolutionError("branch_not_bound", "分支未绑定任何项目")),
    ):
        result = await start_feature_solution(
            space_id=_SPACE, conversation_id=_CONV, branch_name="feat/x"
        )

    assert result.success is False
    assert "分支未绑定" in result.error
