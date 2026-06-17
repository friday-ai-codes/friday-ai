"""``chat.recovery.recover_orphaned_run`` 单元测试。

回归保护（zombie run 卡死 bug）：

``uvicorn --reload`` 热重载 / 进程退出会在「graph 已写完终态 checkpoint」与
「Django 落库 assistant 消息」之间把收尾 task 杀掉，留下
``OrchestrationRun.status=running + phase=finalizing`` + ``Conversation.status=running``
+ 缺失 assistant 消息的孤儿 run，前端永久卡在「正在整理回答…」+ 空气泡。

``recover_orphaned_run`` 从 LangGraph checkpoint 兜底落库。本测试断言其核心契约：

- graph 已 END（``snapshot.next`` 空）且 phase 终态 → claim run + 复用
  ``finalize_conversation`` 落库，run 收敛到 COMPLETED。
- graph 仍 pending（``snapshot.next`` 非空，如 waiting_clarification）→ 不动。
- phase 非终态 → 不动。
- run 太新（年龄闸内）→ 让在线收尾路径先处理，不动。
- run 已终态 → no-op。
- 已有 assistant 消息（在线路径落库成功只是没改 run 状态）→ 不重复落库，仅修 run。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agents.models import AgentSession
from chat.models import Conversation, Message
from chat.recovery import recover_orphaned_run
from orchestration.models import OrchestrationRun


@pytest.fixture
def conversation(project) -> Conversation:
    return Conversation.objects.create(
        project=project,
        title="orphan recovery test",
        status=Conversation.Status.RUNNING,
        model="deepseek-test",
    )


@pytest.fixture
def running_run(conversation: Conversation) -> OrchestrationRun:
    return OrchestrationRun.objects.create(
        conversation=conversation,
        thread_id=str(conversation.id),
        status=OrchestrationRun.Status.RUNNING,
        phase=OrchestrationRun.Phase.FINALIZING,
    )


@pytest.fixture
def agent_session(conversation: Conversation, project) -> AgentSession:
    return AgentSession.objects.create(
        session_id=f"chat-{conversation.id}-test",
        project=project,
        metadata={"conversation_id": str(conversation.id)},
    )


def _patch_graph(
    monkeypatch: pytest.MonkeyPatch,
    *,
    next_nodes: tuple[str, ...] = (),
    values: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> None:
    """打桩 graph：aget_state 返回可控的 snapshot.next / snapshot.values。"""

    class _FakeGraph:
        async def aget_state(self, config: dict[str, Any]) -> Any:
            if raise_exc is not None:
                raise raise_exc
            return SimpleNamespace(next=next_nodes, values=values or {})

    async def _get() -> Any:
        return _FakeGraph()

    monkeypatch.setattr("orchestration.graph.get_compiled_graph", _get)

    async def _noop_clear(run_id: str) -> None:
        return None

    monkeypatch.setattr("orchestration.graph._clear_streaming_snapshot", _noop_clear)


@pytest.fixture
def _mock_finalize(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {"calls": 0}

    async def _fake_finalize(**kwargs: Any) -> list[Any]:
        captured["calls"] += 1
        captured.update(kwargs)
        return []

    monkeypatch.setattr("chat.finalize.finalize_conversation", _fake_finalize)
    return captured


_COMPLETED_STATE = {
    "phase": "completed",
    "final_answer": "最终回答内容",
    "accumulated_thinking": ["想了想"],
    "tool_calls": [{"id": "t1", "name": "search_repository_code", "input": {}, "result": "ok", "status": "done"}],
    "parts": [{"type": "text", "id": "p1", "index": 0, "text": "最终回答内容", "state": "done"}],
    "result_metadata": {"status": "completed"},
}


@pytest.mark.django_db(transaction=True)
class TestRecoverOrphanedRun:
    def test_recovers_completed_orphan(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        running_run: OrchestrationRun,
        agent_session: AgentSession,
        _mock_finalize: dict[str, Any],
    ) -> None:
        state = {**_COMPLETED_STATE, "agent_session_id": str(agent_session.id)}
        _patch_graph(monkeypatch, next_nodes=(), values=state)

        recovered = asyncio.run(recover_orphaned_run(running_run, min_age_seconds=0))

        assert recovered is True
        running_run.refresh_from_db()
        assert running_run.status == OrchestrationRun.Status.COMPLETED
        assert running_run.phase == OrchestrationRun.Phase.COMPLETED
        # finalize 被调用且拿到 checkpoint 终态
        assert _mock_finalize["calls"] == 1
        assert _mock_finalize["final_content"] == "最终回答内容"
        assert len(_mock_finalize["parts"]) == 1
        assert _mock_finalize["tool_calls"][0]["name"] == "search_repository_code"

    def test_skips_when_graph_still_pending(
        self,
        monkeypatch: pytest.MonkeyPatch,
        running_run: OrchestrationRun,
        _mock_finalize: dict[str, Any],
    ) -> None:
        # waiting_clarification：graph 在 interrupt() 节点暂停，snapshot.next 非空。
        _patch_graph(
            monkeypatch,
            next_nodes=("wait_clarification",),
            values={"phase": "waiting_clarification"},
        )

        recovered = asyncio.run(recover_orphaned_run(running_run, min_age_seconds=0))

        assert recovered is False
        running_run.refresh_from_db()
        assert running_run.status == OrchestrationRun.Status.RUNNING
        assert _mock_finalize["calls"] == 0

    def test_skips_when_phase_not_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        running_run: OrchestrationRun,
        _mock_finalize: dict[str, Any],
    ) -> None:
        # next 空但 phase 仍是 executing（理论上罕见）→ 保守不动。
        _patch_graph(monkeypatch, next_nodes=(), values={"phase": "executing"})

        recovered = asyncio.run(recover_orphaned_run(running_run, min_age_seconds=0))

        assert recovered is False
        running_run.refresh_from_db()
        assert running_run.status == OrchestrationRun.Status.RUNNING
        assert _mock_finalize["calls"] == 0

    def test_skips_when_run_too_fresh(
        self,
        monkeypatch: pytest.MonkeyPatch,
        running_run: OrchestrationRun,
        agent_session: AgentSession,
        _mock_finalize: dict[str, Any],
    ) -> None:
        # 刚创建的 run（年龄闸内）让在线收尾路径先处理。
        state = {**_COMPLETED_STATE, "agent_session_id": str(agent_session.id)}
        _patch_graph(monkeypatch, next_nodes=(), values=state)

        recovered = asyncio.run(recover_orphaned_run(running_run, min_age_seconds=3600))

        assert recovered is False
        running_run.refresh_from_db()
        assert running_run.status == OrchestrationRun.Status.RUNNING
        assert _mock_finalize["calls"] == 0

    def test_skips_when_run_already_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        _mock_finalize: dict[str, Any],
    ) -> None:
        done_run = OrchestrationRun.objects.create(
            conversation=conversation,
            thread_id=str(conversation.id),
            status=OrchestrationRun.Status.COMPLETED,
            phase=OrchestrationRun.Phase.COMPLETED,
        )
        _patch_graph(monkeypatch, next_nodes=(), values=_COMPLETED_STATE)

        recovered = asyncio.run(recover_orphaned_run(done_run, min_age_seconds=0))

        assert recovered is False
        assert _mock_finalize["calls"] == 0

    def test_idempotent_when_assistant_message_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        running_run: OrchestrationRun,
        _mock_finalize: dict[str, Any],
    ) -> None:
        # 在线路径其实落库成功只是没改 run 状态 → 不重复创建消息，仅修 run + 会话终态。
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content="已经落库的回答",
        )
        _patch_graph(monkeypatch, next_nodes=(), values=_COMPLETED_STATE)

        recovered = asyncio.run(recover_orphaned_run(running_run, min_age_seconds=0))

        assert recovered is True
        running_run.refresh_from_db()
        conversation.refresh_from_db()
        assert running_run.status == OrchestrationRun.Status.COMPLETED
        assert conversation.status == Conversation.Status.COMPLETED
        # 未重复落库
        assert _mock_finalize["calls"] == 0
        assert (
            Message.objects.filter(
                conversation=conversation, role=Message.Role.ASSISTANT
            ).count()
            == 1
        )
