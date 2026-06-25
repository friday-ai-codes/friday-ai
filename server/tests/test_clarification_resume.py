"""``ConversationService.resume_clarification_run`` 单元测试。

回归保护（waiting_clarification 卡死 bug）：

旧实现中 ``ClarificationAnswerView`` 直接
``graph.ainvoke(Command(resume=...), {"configurable": {"thread_id": ...}})``：

1. LangGraph checkpoint 不保存 configurable —— resume 时 executing_node 的
   ``_build_chat_runner`` 拿不到 api_key，静默返回 ``phase=error``（不抛异常、
   不写 DB、不打日志）；
2. resume 完成后无人更新 OrchestrationRun 终态、无人 finalize 落 assistant
   消息。

结果：run 永久停在 ``status=WAITING, phase=waiting_clarification``，前端
runtime 轮询永远显示 "waiting_clarification..."。

本测试断言新实现的核心契约：

- resume 时 graph config 携带完整 configurable（api_key / model / session_id）
- run 终态：graph 完成 → COMPLETED + phase 同步；finalize_conversation 被调用
- graph 异常 → run/conversation 落 ERROR + 兜底 assistant 消息
- 无 waiting run → no-op 不抛
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from chat.conversation_service import ConversationService
from chat.models import Conversation, Message
from orchestration.models import OrchestrationRun


@pytest.fixture
def conversation(project) -> Conversation:
    return Conversation.objects.create(
        space=project,
        title="clarification resume test",
        status=Conversation.Status.RUNNING,
    )


@pytest.fixture
def waiting_run(conversation: Conversation) -> OrchestrationRun:
    return OrchestrationRun.objects.create(
        conversation=conversation,
        thread_id=str(conversation.id),
        status=OrchestrationRun.Status.WAITING,
        phase=OrchestrationRun.Phase.WAITING_CLARIFICATION,
    )


def _fake_sdk_config() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="chat-test-session",
        model="test-model",
        api_key="sk-test-key",
        api_base_url="https://api.example.com",
        system_prompt="system prompt",
        space_id="",
        max_budget_usd=None,
        force_deep_analysis=False,
        available_models=None,
    )


@pytest.fixture
def _mock_build_sdk_config(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    agent_session = SimpleNamespace(id=uuid.uuid4())
    sdk_config = _fake_sdk_config()

    async def _fake_build(conv: Any, **kwargs: Any) -> tuple[Any, Any]:
        return sdk_config, agent_session

    monkeypatch.setattr("chat.config.build_sdk_config", _fake_build)
    return sdk_config


@pytest.fixture
def _mock_finalize(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_finalize(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("chat.finalize.finalize_conversation", _fake_finalize)
    return captured


def _mock_graph(
    monkeypatch: pytest.MonkeyPatch,
    final_state: dict[str, Any] | None = None,
    raise_exc: Exception | None = None,
) -> dict[str, Any]:
    """打桩 conversation_service 模块级 get_compiled_graph，捕获 astream config。"""
    captured: dict[str, Any] = {}

    class _FakeGraph:
        def astream(self, command: Any, *, config: dict[str, Any], **kwargs: Any) -> Any:
            captured["command"] = command
            captured["config"] = config

            async def _gen():
                if raise_exc is not None:
                    raise raise_exc
                yield {"type": "values", "data": final_state or {}}

            return _gen()

    async def _fake_get_compiled_graph() -> Any:
        return _FakeGraph()

    monkeypatch.setattr(
        "chat.conversation_service.get_compiled_graph",
        _fake_get_compiled_graph,
    )
    return captured


_RESUME_PAYLOAD = {
    "clarification_id": "c-001",
    "selected_option_id": "opt-A",
    "selected_option_label": "study-app",
    "freeform_text": None,
    "implies": {},
}


@pytest.mark.django_db(transaction=True)
class TestResumeClarificationRun:
    def test_resume_config_carries_full_configurable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        waiting_run: OrchestrationRun,
        _mock_build_sdk_config: SimpleNamespace,
        _mock_finalize: dict[str, Any],
    ) -> None:
        """核心回归：resume config 必须带 api_key 等 configurable，
        否则 executing_node 静默 error、run 卡死在 waiting_clarification。"""
        captured = _mock_graph(monkeypatch, final_state={
            "phase": "completed",
            "final_answer": "已根据你的选择继续分析。",
        })

        asyncio.run(ConversationService.resume_clarification_run(
            str(conversation.id), _RESUME_PAYLOAD,
        ))

        cfg = captured["config"]["configurable"]
        assert cfg["api_key"] == "sk-test-key"
        assert cfg["model"] == "test-model"
        assert cfg["session_id"] == "chat-test-session"
        assert cfg["system_prompt"] == "system prompt"
        assert cfg["thread_id"] == str(conversation.id)
        assert cfg["conversation_id"] == str(conversation.id)

    def test_completed_run_finalized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        waiting_run: OrchestrationRun,
        _mock_build_sdk_config: SimpleNamespace,
        _mock_finalize: dict[str, Any],
    ) -> None:
        _mock_graph(monkeypatch, final_state={
            "phase": "completed",
            "final_answer": "最终回答",
            "result_metadata": {"status": "completed"},
        })

        asyncio.run(ConversationService.resume_clarification_run(
            str(conversation.id), _RESUME_PAYLOAD,
        ))

        waiting_run.refresh_from_db()
        assert waiting_run.status == OrchestrationRun.Status.COMPLETED
        assert waiting_run.phase == "completed"
        # finalize 被调用并拿到 graph 终态
        assert _mock_finalize["final_content"] == "最终回答"
        assert _mock_finalize["user_message"] == "study-app"

    def test_graph_error_marks_run_and_conversation_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        waiting_run: OrchestrationRun,
        _mock_build_sdk_config: SimpleNamespace,
        _mock_finalize: dict[str, Any],
    ) -> None:
        _mock_graph(monkeypatch, raise_exc=RuntimeError("boom"))

        asyncio.run(ConversationService.resume_clarification_run(
            str(conversation.id), _RESUME_PAYLOAD,
        ))

        waiting_run.refresh_from_db()
        conversation.refresh_from_db()
        assert waiting_run.status == OrchestrationRun.Status.ERROR
        assert conversation.status == Conversation.Status.ERROR
        # 兜底 assistant 消息让前端有反馈
        assert Message.objects.filter(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            metadata__status="error",
        ).exists()

    def test_config_error_non_valueerror_marks_run_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        waiting_run: OrchestrationRun,
        _mock_finalize: dict[str, Any],
    ) -> None:
        """回归：build_sdk_config 抛非 ValueError（如后台任务继承请求上下文导致的
        "CurrentThreadExecutor already quit or is broken"）也必须把 run 标成
        ERROR + 落兜底消息，不能让 run 永久停在 waiting_clarification。"""

        async def _broken_build(conv: Any, **kwargs: Any) -> tuple[Any, Any]:
            raise RuntimeError("CurrentThreadExecutor already quit or is broken")

        monkeypatch.setattr("chat.config.build_sdk_config", _broken_build)
        captured = _mock_graph(monkeypatch, final_state={"phase": "completed"})

        asyncio.run(ConversationService.resume_clarification_run(
            str(conversation.id), _RESUME_PAYLOAD,
        ))

        waiting_run.refresh_from_db()
        conversation.refresh_from_db()
        assert waiting_run.status == OrchestrationRun.Status.ERROR
        assert conversation.status == Conversation.Status.ERROR
        assert "config" not in captured  # graph 不应被触发
        assert Message.objects.filter(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            metadata__status="error",
        ).exists()

    def test_no_waiting_run_is_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conversation: Conversation,
        _mock_build_sdk_config: SimpleNamespace,
        _mock_finalize: dict[str, Any],
    ) -> None:
        """没有 waiting_clarification 的 run（已被 resume 过/已超时关闭）→ 安静返回。"""
        captured = _mock_graph(monkeypatch, final_state={"phase": "completed"})

        asyncio.run(ConversationService.resume_clarification_run(
            str(conversation.id), _RESUME_PAYLOAD,
        ))

        assert "config" not in captured  # graph 未被触发
        assert not _mock_finalize
