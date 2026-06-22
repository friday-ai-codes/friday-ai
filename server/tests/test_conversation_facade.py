"""ConversationService.send_message_stream() facade 集成测试。

验证 send_message_stream() 已降级为 graph facade：
- 通过 graph.astream() 驱动会话（work item）
- 从 graph state 读取结果并调用 finalize_conversation() 落库（work item）
- 不直接创建 SDKAgentRunner（work item）
- 事件顺序由 graph StreamWriter → Queue → yield 保持一致（work item）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.core.events import (
    KEEPALIVE,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    TITLE_GENERATED,
    TOOL_USE_RESULT,
    TOOL_USE_START,
    AgentEvent,
)
from services.provider_config import ProviderType


@dataclass
class _SdkConfigStub:
    """SdkRunnerConfig 的最小化替身。"""

    system_prompt: str = "test prompt"
    model: str = "claude-sonnet-4-5"
    space_id: str = ""
    session_id: str = "chat-test-session-001"
    provider_type: ProviderType = ProviderType.ANTHROPIC
    conversation_id: str = ""
    api_key: str = "sk-test-key"
    api_base_url: str = "https://api.example.com"
    max_turns: int = 30
    timeout_seconds: int = 0
    agent_session: Any = None
    max_budget_usd: float | None = None
    force_deep_analysis: bool = False
    available_models: Any = None


class _SessionStub:
    """AgentSession 的最小化替身。"""

    def __init__(self) -> None:
        self.id = 99999
        self.session_id = "chat-test-session-001"


class _MockGraph:
    """Mock LangGraph compiled graph — astream 返回 custom + values 块。"""

    def __init__(
        self,
        custom_events: list[dict[str, Any]],
        final_state: dict[str, Any],
    ) -> None:
        self._custom_events = custom_events
        self._final_state = final_state
        self.last_input_data: dict[str, Any] | None = None
        self.last_config: dict[str, Any] | None = None

    async def astream(
        self,
        input_data: dict[str, Any],
        *,
        config: dict[str, Any],
        stream_mode: list[str],
        version: str,
    ):
        self.last_input_data = input_data
        self.last_config = config
        for event in self._custom_events:
            yield {"type": "custom", "data": event}
        yield {"type": "values", "data": self._final_state}


_DEFAULT_EVENTS: list[dict[str, Any]] = [
    {"type": TEXT_DELTA, "data": {"delta": "Hello"}},
    {"type": TEXT_DELTA, "data": {"delta": " world"}},
    {"type": MESSAGE_COMPLETE, "data": {"usage": {"input_tokens": 100}}},
]

_DEFAULT_FINAL_STATE: dict[str, Any] = {
    "final_answer": "Hello world",
    "accumulated_thinking": ["thinking..."],
    "tool_calls": [],
    "result_metadata": {"status": "completed"},
    "phase": "completed",
}


def _make_graph(
    events: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
) -> _MockGraph:
    return _MockGraph(
        events if events is not None else list(_DEFAULT_EVENTS),
        state if state is not None else dict(_DEFAULT_FINAL_STATE),
    )


async def _create_conversation(project: Any) -> Any:
    from chat.models import Conversation

    conv = await Conversation.objects.acreate(project=project, title="Test")
    return await Conversation.objects.select_related("project").aget(id=conv.id)


def _facade_patches(
    conversation: Any,
    graph: _MockGraph | None = None,
    finalize_return: list[AgentEvent] | None = None,
    finalize_mock: AsyncMock | None = None,
    sdk_config: _SdkConfigStub | None = None,
) -> tuple[tuple[Any, Any, Any], AsyncMock]:
    """构建 facade 三件套 mock + finalize_mock 引用。"""
    if graph is None:
        graph = _make_graph()
    if finalize_mock is None:
        finalize_mock = AsyncMock(return_value=finalize_return or [])

    config_stub = sdk_config or _SdkConfigStub()
    config_stub.conversation_id = str(conversation.id)
    config_stub.space_id = str(conversation.project_id)
    session_stub = _SessionStub()

    patches = (
        patch(
            "chat.config.build_sdk_config",
            new=AsyncMock(return_value=(config_stub, session_stub)),
        ),
        patch(
            "chat.conversation_service.get_compiled_graph",
            new=AsyncMock(return_value=graph),
        ),
        patch("chat.finalize.finalize_conversation", finalize_mock),
    )
    return patches, finalize_mock


@pytest.mark.django_db(transaction=True)
class TestConversationFacade:
    """Facade 行为集成测试。"""

    async def test_facade_yields_events_from_graph(self, project: Any) -> None:
        """work item, graph 事件通过 Queue 桥接到 facade yield。"""
        conversation = await _create_conversation(project)
        (p1, p2, p3), _ = _facade_patches(conversation)
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            events = [
                e
                async for e in ConversationService.send_message_stream(
                    conversation_id=str(conversation.id),
                    content="Hello",
                )
                if e.type != KEEPALIVE
            ]

        types = [e.type for e in events]
        assert TEXT_DELTA in types
        assert MESSAGE_COMPLETE in types

    async def test_facade_creates_orchestration_run(self, project: Any) -> None:
        """每次运行创建 OrchestrationRun 并在完成后更新状态。"""
        conversation = await _create_conversation(project)
        (p1, p2, p3), _ = _facade_patches(conversation)
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            async for _ in ConversationService.send_message_stream(
                conversation_id=str(conversation.id),
                content="Hello",
            ):
                pass

        from orchestration.models import OrchestrationRun

        run = await OrchestrationRun.objects.filter(
            conversation=conversation,
        ).afirst()
        assert run is not None
        assert run.thread_id == str(conversation.id)
        assert run.status == OrchestrationRun.Status.COMPLETED

    async def test_facade_persists_user_input_parts_and_passes_them_to_graph(self, project: Any) -> None:
        """input_parts 是可选增量：含图 user message 落 parts，content 仍只保存文本。"""
        conversation = await _create_conversation(project)
        parts = [
            {"type": "text", "id": "p_text", "index": 0, "text": "看图", "state": "done"},
            {
                "type": "image",
                "id": "p_img",
                "index": 1,
                "mime_type": "image/png",
                "size_bytes": 12,
                "width": None,
                "height": None,
                "detail": "auto",
                "storage_ref": "chat_images/p_img.png",
                "source_url": "",
                "alt_text": "截图",
            },
        ]
        graph = _make_graph()
        (p1, p2, p3), _ = _facade_patches(conversation, graph=graph)

        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            async for _ in ConversationService.send_message_stream(
                conversation_id=str(conversation.id),
                content="看图",
                input_parts=parts,
            ):
                pass

        from chat.models import Message

        user_msg = await Message.objects.filter(conversation=conversation, role=Message.Role.USER).aget()
        assert user_msg.content == "看图"
        assert user_msg.parts == parts
        assert user_msg.metadata["parts_schema_version"] == 2
        assert user_msg.metadata["image_count"] == 1
        assert graph.last_input_data is not None
        assert graph.last_input_data["user_parts"] == parts

    async def test_facade_rejects_image_when_bound_model_has_no_image_modality(
        self, project: Any,
    ) -> None:
        """聊天发图只信 Provider 绑定模型能力，不让 text-only 模型收到图片占位。"""
        from system.models import ProviderCredential

        credential = await ProviderCredential.objects.acreate(
            provider_type="anthropic",
            name="deepseek-anthropic",
            scope="system",
            encrypted_config="{}",
            base_url="https://api.deepseek.com/anthropic",
            default_model="deepseek-v4-pro",
            available_models=[
                {
                    "id": "deepseek-v4-pro",
                    "display_name": "deepseek-v4-pro",
                    "input_modalities": ["text"],
                }
            ],
        )
        conversation = await _create_conversation(project)
        conversation.provider_credential_id = credential
        conversation.model = "deepseek-v4-pro"
        await conversation.asave(update_fields=["provider_credential_id", "model"])

        parts = [
            {"type": "text", "id": "p_text", "index": 0, "text": "看图", "state": "done"},
            {
                "type": "image",
                "id": "p_img",
                "index": 1,
                "mime_type": "image/png",
                "size_bytes": 12,
                "width": None,
                "height": None,
                "detail": "auto",
                "storage_ref": "chat_images/p_img.png",
                "source_url": "",
                "alt_text": "截图",
            },
        ]
        graph = _make_graph()
        (p1, p2, p3), _ = _facade_patches(
            conversation,
            graph=graph,
            sdk_config=_SdkConfigStub(model="deepseek-v4-pro"),
        )

        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            with pytest.raises(ValueError, match="当前模型不支持图片"):
                async for _ in ConversationService.send_message_stream(
                    conversation_id=str(conversation.id),
                    content="看图",
                    input_parts=parts,
                ):
                    pass

        assert graph.last_input_data is None

    async def test_facade_saves_assistant_message_from_graph_state(
        self, project: Any,
    ) -> None:
        """从 graph state 读取 final_answer 传给 finalize_conversation。"""
        conversation = await _create_conversation(project)
        fin_mock = AsyncMock(return_value=[])
        graph = _make_graph(
            state={
                "final_answer": "Custom answer",
                "accumulated_thinking": ["step1"],
                "tool_calls": [{"id": "tc1", "name": "search"}],
                "result_metadata": {"status": "completed", "cost_usd": 0.05},
                "phase": "completed",
            },
        )
        (p1, p2, p3), _ = _facade_patches(
            conversation, graph=graph, finalize_mock=fin_mock,
        )
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            async for _ in ConversationService.send_message_stream(
                conversation_id=str(conversation.id),
                content="Hello",
            ):
                pass

        fin_mock.assert_called_once()
        kw = fin_mock.call_args.kwargs
        assert kw["final_content"] == "Custom answer"
        assert kw["accumulated_thinking"] == ["step1"]
        assert kw["tool_calls"] == [{"id": "tc1", "name": "search"}]
        assert kw["result_metadata"]["cost_usd"] == 0.05

    async def test_facade_preserves_event_order(self, project: Any) -> None:
        """事件顺序与 graph StreamWriter 推送顺序一致。"""
        conversation = await _create_conversation(project)
        ordered = [
            {"type": TOOL_USE_START, "data": {"tool_name": "search"}},
            {"type": TOOL_USE_RESULT, "data": {"result": "found"}},
            {"type": TEXT_DELTA, "data": {"delta": "Based on"}},
            {"type": TEXT_DELTA, "data": {"delta": " search..."}},
            {"type": MESSAGE_COMPLETE, "data": {}},
        ]
        graph = _make_graph(events=ordered)
        (p1, p2, p3), _ = _facade_patches(conversation, graph=graph)
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            events = [
                e
                async for e in ConversationService.send_message_stream(
                    conversation_id=str(conversation.id),
                    content="Search",
                )
                if e.type != KEEPALIVE
            ]

        types = [e.type for e in events]
        assert types == [
            TOOL_USE_START,
            TOOL_USE_RESULT,
            TEXT_DELTA,
            TEXT_DELTA,
            MESSAGE_COMPLETE,
        ]

    async def test_facade_does_not_create_sdk_runner_directly(self) -> None:
        """facade 不直接创建 SDKAgentRunner。"""
        import inspect

        from chat.conversation_service import ConversationService

        source = inspect.getsource(ConversationService.send_message_stream)
        assert "SDKAgentRunner(" not in source

    async def test_facade_generates_title_event(self, project: Any) -> None:
        """finalize_conversation 返回的 title 事件被 yield。"""
        conversation = await _create_conversation(project)
        title_ev = AgentEvent(type=TITLE_GENERATED, data={"title": "Auto Title"})
        (p1, p2, p3), _ = _facade_patches(
            conversation, finalize_return=[title_ev],
        )
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            events = [
                e
                async for e in ConversationService.send_message_stream(
                    conversation_id=str(conversation.id),
                    content="Hello",
                )
            ]

        title_events = [e for e in events if e.type == TITLE_GENERATED]
        assert len(title_events) == 1
        assert title_events[0].data["title"] == "Auto Title"

    async def test_facade_synthesizes_message_complete_when_graph_omits_it(
        self, project: Any,
    ) -> None:
        """若 SDK/graph 未显式发送 message_complete，facade 仍兜底补发。"""
        conversation = await _create_conversation(project)
        graph = _make_graph(
            events=[{"type": TEXT_DELTA, "data": {"text": "Partial answer"}}],
            state={
                "final_answer": "Partial answer",
                "accumulated_thinking": ["thinking..."],
                "tool_calls": [],
                "result_metadata": {
                    "status": "completed",
                    "input_tokens": 12,
                    "output_tokens": 34,
                    "cost_usd": 0.01,
                },
                "phase": "completed",
            },
        )
        (p1, p2, p3), _ = _facade_patches(conversation, graph=graph)
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            events = [
                e
                async for e in ConversationService.send_message_stream(
                    conversation_id=str(conversation.id),
                    content="Hello",
                )
                if e.type != KEEPALIVE
            ]

        completion_events = [e for e in events if e.type == MESSAGE_COMPLETE]
        assert len(completion_events) == 1
        assert completion_events[0].data["final_answer"] == "Partial answer"
        assert completion_events[0].data["usage"] == {
            "input_tokens": 12,
            "output_tokens": 34,
        }

    async def test_facade_handles_generator_exit(self, project: Any) -> None:
        """SSE 断连后后台 Task 完成 finalize。"""
        conversation = await _create_conversation(project)
        fin_mock = AsyncMock(return_value=[])
        (p1, p2, p3), _ = _facade_patches(
            conversation, finalize_mock=fin_mock,
        )
        with p1, p2, p3:
            from chat.conversation_service import ConversationService

            gen = ConversationService.send_message_stream(
                conversation_id=str(conversation.id),
                content="Hello",
            )
            first = await gen.__anext__()
            assert first is not None
            await gen.aclose()

            await asyncio.sleep(0.5)

        fin_mock.assert_called_once()
        assert fin_mock.call_args.kwargs["publish_title_event"] is False
