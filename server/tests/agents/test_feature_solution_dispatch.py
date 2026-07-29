from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from agents.feature_solution_dispatch import dispatch_feature_solution
from agents.tools.base import ToolResult
from agents.tools.plan_research_tools import PLAN_CLARIFICATION_RENDER_MARKER
from orchestration.state import RunPhase


class _SessionQuery:
    def __init__(self, active: object | None = None) -> None:
        self.active = active

    def exclude(self, **_kwargs: object) -> _SessionQuery:
        return self

    def order_by(self, *_args: object) -> _SessionQuery:
        return self

    async def afirst(self) -> object | None:
        return self.active


@pytest.fixture
def dispatch_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    from agents import feature_solution_dispatch as module
    from delivery.models import ConvergenceSession
    from initiatives.services.feature_solution_service import FeatureSolutionService

    monkeypatch.setattr(
        ConvergenceSession.objects,
        "filter",
        lambda **_kwargs: _SessionQuery(),
    )
    monkeypatch.setattr(
        module,
        "_resolve_conversation_context",
        AsyncMock(return_value=(SimpleNamespace(id="user-1"), "project-1")),
    )
    start = AsyncMock()
    get = AsyncMock()
    monkeypatch.setattr(FeatureSolutionService, "start", start)
    monkeypatch.setattr(FeatureSolutionService, "get", get)
    return start, get


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_result", "expected_phase"),
    [
        (
            ToolResult(
                success=True,
                output={
                    "marker": PLAN_CLARIFICATION_RENDER_MARKER,
                    "question": "请确认范围",
                    "session_id": "session-1",
                },
            ),
            RunPhase.FINALIZING.value,
        ),
        (
            ToolResult(
                success=True,
                output={
                    "__blocking_task__": True,
                    "task_id": "session-1",
                    "task_type": "plan_research",
                },
            ),
            RunPhase.WAITING.value,
        ),
        (
            ToolResult(success=True, output={"status": "done", "markdown": "# 技术方案"}),
            RunPhase.FINALIZING.value,
        ),
        (
            ToolResult(success=False, error="方案失败"),
            RunPhase.ERROR.value,
        ),
    ],
)
async def test_dispatch_maps_service_state_without_chat_clarification(
    monkeypatch: pytest.MonkeyPatch,
    dispatch_mocks: tuple[AsyncMock, AsyncMock],
    tool_result: ToolResult,
    expected_phase: str,
) -> None:
    from agents import feature_solution_dispatch as module

    start, _get = dispatch_mocks
    state = SimpleNamespace(
        session_id="session-1",
        status="awaiting_confirmation",
    )
    start.return_value = state
    monkeypatch.setattr(module, "_map_state", AsyncMock(return_value=tool_result))

    patch = await dispatch_feature_solution(
        conversation_id="conversation-1",
        bound_project_id="project-1",
        initiated_by_user_id="user-1",
    )

    assert patch["phase"] == expected_phase
    assert patch.get("pending_clarification") == {}
    assert all(
        call.get("result", {}).get("marker") != "ask_clarification"
        for call in patch.get("tool_calls", [])
    )
    start.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_reuses_active_feature_solution_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import feature_solution_dispatch as module
    from delivery.models import ConvergenceSession
    from initiatives.services.feature_solution_service import FeatureSolutionService

    active = SimpleNamespace(id="active-session")
    monkeypatch.setattr(
        ConvergenceSession.objects,
        "filter",
        lambda **_kwargs: _SessionQuery(active),
    )
    monkeypatch.setattr(
        module,
        "_resolve_conversation_context",
        AsyncMock(return_value=(SimpleNamespace(id="user-1"), "project-1")),
    )
    state = SimpleNamespace(session_id="active-session", status="completed")
    get = AsyncMock(return_value=state)
    start = AsyncMock()
    monkeypatch.setattr(FeatureSolutionService, "get", get)
    monkeypatch.setattr(FeatureSolutionService, "start", start)
    monkeypatch.setattr(
        module,
        "_map_state",
        AsyncMock(
            return_value=ToolResult(
                success=True,
                output={"status": "done", "markdown": "# 已有方案"},
            )
        ),
    )

    patch = await dispatch_feature_solution(
        conversation_id="conversation-1",
        bound_project_id="project-1",
    )

    assert patch["final_answer"] == "# 已有方案"
    get.assert_awaited_once_with(session_id="active-session", actor=ANY)
    start.assert_not_awaited()
