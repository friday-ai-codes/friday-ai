"""Tests for Feishu bot processing pipeline."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.core.events import (
    MESSAGE_COMPLETE,
    PART_DELTA,
    PHASE_TRANSITION,
    TEXT_DELTA,
    TOOL_USE_START,
    AgentEvent,
)
from agents.models import AgentSession, ToolCallLog
from chat.models import Conversation, Message
from feishu.bot.service import FeishuBotService
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from projects.models import Project
from repositories.models import Repository
from services.feishu_im import FeishuIMError

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdac\xfc\xff\x1f\x00\x03\x03\x02\x00\xef\xbf\xa7\xdb"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _fake_stream(
    *,
    session_id: str = "",
    final_answer: str = "",
    usage: dict[str, Any] | None = None,
    cost_usd: float = 0,
) -> AsyncGenerator[AgentEvent, None]:
    """构造 fake send_message_stream AsyncGenerator。"""
    yield AgentEvent(
        type=MESSAGE_COMPLETE,
        data={
            "session_id": session_id,
            "final_answer": final_answer,
            "usage": usage or {},
            "cost_usd": cost_usd,
            "status": "completed",
            "model": "test-model",
        },
    )


async def _error_stream(
    *_args: Any,
    **_kwargs: Any,
) -> AsyncGenerator[AgentEvent, None]:
    """构造抛出异常的 fake send_message_stream AsyncGenerator。"""
    raise RuntimeError("boom")
    yield  # pragma: no cover — makes it a generator


async def _tool_then_complete_stream(
    *,
    tool_name: str,
    final_answer: str,
    session_id: str = "",
) -> AsyncGenerator[AgentEvent, None]:
    yield AgentEvent(
        type=TOOL_USE_START,
        data={
            "tool_name": tool_name,
            "tool_call_id": "toolu_1",
        },
    )
    yield AgentEvent(
        type=MESSAGE_COMPLETE,
        data={
            "session_id": session_id,
            "final_answer": final_answer,
            "usage": {},
            "cost_usd": 0,
            "status": "completed",
            "model": "test-model",
        },
    )


async def _waiting_stream(
    *,
    session_id: str = "waiting-session",
    run_id: str = "run-waiting",
    blocking_task_count: int = 2,
) -> AsyncGenerator[AgentEvent, None]:
    yield AgentEvent(
        type=PHASE_TRANSITION,
        data={
            "phase": "waiting",
            "session_id": session_id,
            "run_id": run_id,
            "blocking_task_count": blocking_task_count,
        },
    )


async def _text_delta_stream(
    *,
    final_answer: str = "你好",
    session_id: str = "",
    tool_name: str = "browse_file_content",
    include_part_delta: bool = False,
) -> AsyncGenerator[AgentEvent, None]:
    """构造 TOOL_USE_START + 多个 TEXT_DELTA(+可选 PART_DELTA) + MESSAGE_COMPLETE 流。

    include_part_delta=True 时混入 PART_DELTA（双轨），用于验证 bot 绝不消费 PART_DELTA
    导致正文翻倍（P-1）。
    """
    yield AgentEvent(type=TOOL_USE_START, data={"tool_name": tool_name, "tool_call_id": "toolu_1"})
    yield AgentEvent(type=TEXT_DELTA, data={"text": "你", "model": "test-model", "session_id": session_id})
    yield AgentEvent(type=TEXT_DELTA, data={"text": "好", "model": "test-model", "session_id": session_id})
    if include_part_delta:
        yield AgentEvent(type=PART_DELTA, data={"text": "不应消费", "delta": "不应消费"})
    yield AgentEvent(
        type=MESSAGE_COMPLETE,
        data={
            "session_id": session_id,
            "final_answer": final_answer,
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "cost_usd": 0.001,
            "status": "completed",
            "model": "test-model",
        },
    )


def _cardkit_im_service(**overrides: Any) -> SimpleNamespace:
    """构造带 CardKit 4 方法的 fake im_service（默认全成功，可按需 override）。"""
    defaults: dict[str, Any] = {
        "send_card": AsyncMock(side_effect=["welcome_ck", "processing_ck"]),
        "update_card": AsyncMock(return_value=True),
        "get_chat_history": AsyncMock(return_value=[]),
        "create_card_entity": AsyncMock(return_value="c_1"),
        "send_card_entity": AsyncMock(return_value="om_1"),
        "stream_card_content": AsyncMock(return_value=True),
        "settle_card_stream": AsyncMock(return_value=True),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.django_db(transaction=True)
class TestFeishuBotPipeline:
    async def test_attachment_only_message_sends_clarification(self) -> None:
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_attach", root_message_id="msg_attach")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_attach",
            thread=thread,
            chat_id="chat_attach",
            sender_open_id="ou_1",
            message_type="file",
            normalized_text="",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={"event": {"message": {"content": '{"file_name":"error.log"}'}}},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_1", "processing_1", "clarify_1"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)):
            result = await FeishuBotService().process_message("msg_attach")

        await thread.arefresh_from_db()
        assert result["status"] == "clarification"
        assert thread.status == FeishuBotThreadStatus.AWAITING_PROJECT_CLARIFICATION
        assert im_service.send_card.await_count == 3

    async def test_image_only_message_downloads_image_and_sends_input_parts(self, settings) -> None:
        settings.DATA_DIR = settings.BASE_DIR / "data-test"
        project = await Project.objects.acreate(name="Friday Vision", feishu_project_key="friday-vision")
        thread = await FeishuBotThread.objects.acreate(
            chat_id="chat_img",
            root_message_id="msg_img",
            project=project,
        )
        await FeishuBotMessage.objects.acreate(
            message_id="msg_img",
            thread=thread,
            chat_id="chat_img",
            sender_open_id="ou_img",
            message_type="image",
            normalized_text="",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={
                "event": {
                    "message": {
                        "message_id": "msg_img",
                        "message_type": "image",
                        "content": '{"image_key":"img_1"}',
                    }
                }
            },
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_img", "processing_img"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
            download_message_resource=AsyncMock(
                return_value=SimpleNamespace(content=PNG_1X1, mime_type="image/png"),
            ),
        )
        captured_kwargs: dict[str, Any] = {}

        async def fake_send_message_stream(*_args: Any, **kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            captured_kwargs.update(kwargs)
            async for event in _fake_stream(final_answer="这是一张界面截图。"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="vision")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_img")

        assert result["status"] == "answered"
        assert captured_kwargs["content"] == "请分析这张图片"
        parts = captured_kwargs["input_parts"]
        assert [part["type"] for part in parts] == ["text", "image"]
        assert parts[0]["text"] == "请分析这张图片"
        assert parts[1]["mime_type"] == "image/png"
        assert parts[1]["storage_ref"].startswith("chat_images/")
        im_service.download_message_resource.assert_awaited_once_with(
            message_id="msg_img",
            file_key="img_1",
            resource_type="image",
        )

    async def test_image_download_failure_updates_non_empty_error_card(self, settings) -> None:
        settings.DATA_DIR = settings.BASE_DIR / "data-test"
        project = await Project.objects.acreate(name="Friday Vision", feishu_project_key="friday-vision")
        thread = await FeishuBotThread.objects.acreate(
            chat_id="chat_img_fail",
            root_message_id="msg_img_fail",
            project=project,
        )
        await FeishuBotMessage.objects.acreate(
            message_id="msg_img_fail",
            thread=thread,
            chat_id="chat_img_fail",
            sender_open_id="ou_img",
            message_type="image",
            normalized_text="",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={
                "event": {
                    "message": {
                        "message_id": "msg_img_fail",
                        "message_type": "image",
                        "content": '{"image_key":"img_bad"}',
                    }
                }
            },
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_fail", "processing_fail"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
            download_message_resource=AsyncMock(side_effect=FeishuIMError("no permission", code=234006)),
        )

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)):
            result = await FeishuBotService().process_message("msg_img_fail")

        assert result["status"] == "error"
        assert result["error"] == "image_download_failed"
        updated_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in updated_card["elements"] if isinstance(element, dict))
        assert "图片" in content
        assert content.strip()

    async def test_successful_pipeline_updates_processing_card_with_real_trace(self, user: Any) -> None:
        repo = await Repository.objects.acreate(name="server", git_url="https://example.com/server.git")
        project = await Project.objects.acreate(name="Friday Server", feishu_project_key="friday-server")
        await project.repositories.aadd(repo)
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_success", root_message_id="msg_success")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_success",
            thread=thread,
            chat_id="chat_success",
            sender_open_id="ou_2",
            message_type="text",
            normalized_text="friday-server websocket 为什么没走 dispatcher",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_2", "processing_2", "error_unused"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        # 预创建 AgentSession + ToolCallLog 供 extract_reference_summaries 查询
        session = await AgentSession.objects.acreate(
            session_id="chat-session-1",
            project=project,
            user=user,
            status=AgentSession.Status.COMPLETED,
            messages=[],
        )
        await ToolCallLog.objects.acreate(
            session=session,
            tool_name="browse_file_content",
            tool_call_id="tool-1",
            arguments={"repository": "server"},
            result_success=True,
            result_output={"path": "feishu/websocket_client.py", "line_start": 42, "summary": "dispatcher 入口仍在旧逻辑"},
            started_at=session.created_at,
            completed_at=session.created_at,
            duration_ms=1,
            iteration=1,
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _fake_stream(
                session_id="chat-session-1",
                final_answer="因为入口还在旧分支里。",
                usage={"input_tokens": 200, "output_tokens": 80},
                cost_usd=0.005,
            ):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ws")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_success")

        await thread.arefresh_from_db()
        assert result["status"] == "answered"
        assert thread.project_id == project.id
        im_service.update_card.assert_awaited_once()
        updated_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in updated_card["elements"] if isinstance(element, dict))
        assert "websocket_client.py" in content
        assert "已参考上下文" in content
        # 验证成本信息展示
        assert "💰" in content
        assert "200" in content

    async def test_update_failure_falls_back_to_new_answer_card(self) -> None:
        repo = await Repository.objects.acreate(name="web", git_url="https://example.com/web.git")
        project = await Project.objects.acreate(name="Friday Web", feishu_project_key="friday-web")
        await project.repositories.aadd(repo)
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_fallback", root_message_id="msg_fallback")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_fallback",
            thread=thread,
            chat_id="chat_fallback",
            sender_open_id="ou_3",
            message_type="text",
            normalized_text="friday-web 首页为什么 500",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_3", "processing_3", "answer_3"]),
            update_card=AsyncMock(return_value=False),
            get_chat_history=AsyncMock(return_value=[]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _fake_stream(
                final_answer="因为后端接口超时。",
            ):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="web")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_fallback")

        await thread.arefresh_from_db()
        assert result["status"] == "answered"
        assert thread.last_bot_message_id == "answer_3"
        assert im_service.send_card.await_count == 3

    async def test_waiting_stream_without_final_answer_keeps_non_empty_background_card(self) -> None:
        project = await Project.objects.acreate(name="Friday Deep", feishu_project_key="friday-deep")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_waiting", root_message_id="msg_waiting")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_waiting",
            thread=thread,
            chat_id="chat_waiting",
            sender_open_id="ou_waiting",
            message_type="text",
            normalized_text="friday-deep 做一次深度分析",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_waiting", "processing_waiting"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _waiting_stream(blocking_task_count=2):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="waiting")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_ATTEMPTS",
            1,
            create=True,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS",
            0,
            create=True,
        ):
            result = await FeishuBotService().process_message("msg_waiting")

        await thread.arefresh_from_db()
        assert result["status"] == "waiting"
        assert thread.last_bot_message_id == "welcome_waiting"
        assert thread.last_bot_message_id != "processing_waiting"
        assert thread.metadata["last_run_phase"] == "waiting"
        assert thread.metadata["last_waiting_task_count"] == 2
        assert thread.metadata["last_waiting_fallback_status"] == "timeout"
        assert im_service.update_card.await_count == 1
        waiting_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in waiting_card["elements"] if isinstance(element, dict))
        assert "后台分析中" in content
        assert "2" in content
        assert "（无回复内容）" not in content

    async def test_waiting_stream_updates_processing_card_from_barrier_final_message(self) -> None:
        project = await Project.objects.acreate(name="Friday Barrier", feishu_project_key="friday-barrier")
        conversation = await Conversation.objects.acreate(project=project, title="barrier")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_barrier", root_message_id="msg_barrier")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_barrier",
            thread=thread,
            chat_id="chat_barrier",
            sender_open_id="ou_barrier",
            message_type="text",
            normalized_text="friday-barrier 深度分析完成后告诉我",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_barrier", "processing_barrier"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _waiting_stream(blocking_task_count=1):
                yield event
            await Message.objects.acreate(
                conversation=conversation,
                role=Message.Role.ASSISTANT,
                content="最终深度分析结果",
                metadata={"session_id": "waiting-session"},
            )

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=conversation),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_ATTEMPTS",
            1,
            create=True,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS",
            0,
            create=True,
        ):
            result = await FeishuBotService().process_message("msg_barrier")

        await thread.arefresh_from_db()
        assert result["status"] == "answered"
        assert thread.last_bot_message_id == "processing_barrier"
        assert thread.metadata["last_waiting_fallback_status"] == "resolved"
        assert im_service.update_card.await_count == 1
        final_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in final_card["elements"] if isinstance(element, dict))
        assert "最终深度分析结果" in content
        assert "（无回复内容）" not in content

    async def test_processing_error_emits_error_card_without_overwriting_processing(self) -> None:
        repo = await Repository.objects.acreate(name="ops", git_url="https://example.com/ops.git")
        project = await Project.objects.acreate(name="Friday Ops", feishu_project_key="friday-ops")
        await project.repositories.aadd(repo)
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_error", root_message_id="msg_error")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_error",
            thread=thread,
            chat_id="chat_error",
            sender_open_id="ou_4",
            message_type="text",
            normalized_text="friday-ops 部署脚本为什么炸了",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_4", "processing_4", "error_4"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ops")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=_error_stream,
        ):
            result = await FeishuBotService().process_message("msg_error")

        assert result["status"] == "error"
        im_service.update_card.assert_awaited_once()
        error_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in error_card["elements"] if isinstance(element, dict))
        assert "联系管理员" in content

    async def test_tool_use_updates_streaming_card(self) -> None:
        project = await Project.objects.acreate(name="Friday Tooling", feishu_project_key="friday-tooling")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_tool", root_message_id="msg_tool")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_tool",
            thread=thread,
            chat_id="chat_tool",
            sender_open_id="ou_tool",
            message_type="text",
            normalized_text="friday-tooling 看一下这个文件",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["welcome_tool", "processing_tool"]),
            update_card=AsyncMock(return_value=True),
            get_chat_history=AsyncMock(return_value=[]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _tool_then_complete_stream(
                tool_name="browse_file_content",
                final_answer="已经看过了。",
            ):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="tool")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_tool")

        assert result["status"] == "answered"
        assert im_service.update_card.await_count == 2
        streaming_card = im_service.update_card.await_args_list[0].args[1]
        content = "\n".join(element.get("content", "") for element in streaming_card["elements"] if isinstance(element, dict))
        assert "思考中..." in content
        assert "浏览文件" in content

    async def test_p2p_message_answers_without_project_clarification(self) -> None:
        project = await Project.objects.acreate(name="Friday Private", feishu_project_key="friday-private")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_p2p", root_message_id="msg_p2p")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_p2p",
            thread=thread,
            chat_id="chat_p2p",
            chat_type="p2p",
            sender_open_id="ou_p2p",
            message_type="text",
            normalized_text="帮我分析下这个问题",
            quote_message_id="",
            mentioned_bot=False,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["processing_p2p"]),
            update_card=AsyncMock(return_value=True),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _fake_stream(final_answer="这是私聊直接回复。"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="p2p")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_p2p")

        await thread.arefresh_from_db()
        assert result["status"] == "answered"
        assert thread.project_id == project.id
        assert im_service.send_card.await_count == 1
        assert im_service.update_card.await_count == 1
        final_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in final_card["elements"] if isinstance(element, dict))
        assert "已自动匹配" not in content

    async def test_p2p_message_with_explicit_project_match_shows_space_badge(self) -> None:
        project = await Project.objects.acreate(name="Friday Explicit", feishu_project_key="friday-explicit")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_p2p_explicit", root_message_id="msg_p2p_explicit")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_p2p_explicit",
            thread=thread,
            chat_id="chat_p2p_explicit",
            chat_type="p2p",
            sender_open_id="ou_p2p_explicit",
            message_type="text",
            normalized_text="friday-explicit 这个空间里有什么？",
            quote_message_id="",
            mentioned_bot=False,
            raw_payload={},
        )
        im_service = SimpleNamespace(
            send_card=AsyncMock(side_effect=["processing_p2p_explicit"]),
            update_card=AsyncMock(return_value=True),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _fake_stream(final_answer="这是自动匹配后的回复。"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="p2p-explicit")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ):
            result = await FeishuBotService().process_message("msg_p2p_explicit")

        assert result["status"] == "answered"
        final_card = im_service.update_card.await_args.args[1]
        content = "\n".join(element.get("content", "") for element in final_card["elements"] if isinstance(element, dict))
        assert "已自动匹配「friday-explicit」空间" in content

    async def test_text_delta_stream_drives_cardkit_incremental(self) -> None:
        project = await Project.objects.acreate(name="Friday Stream", feishu_project_key="friday-stream")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_stream", root_message_id="msg_stream")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_stream",
            thread=thread,
            chat_id="chat_stream",
            sender_open_id="ou_stream",
            message_type="text",
            normalized_text="friday-stream 解释一下这段逻辑",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = _cardkit_im_service()

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _text_delta_stream(final_answer="你好", include_part_delta=True):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="stream")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service._CARDKIT_STREAM_THROTTLE_S",
            0,
        ):
            result = await FeishuBotService().process_message("msg_stream")

        await thread.arefresh_from_db()
        assert result["status"] == "answered"
        # CardKit message_id 作为 last_bot_message_id（W-2/D-3）
        assert thread.last_bot_message_id == "om_1"

        # 惰性创建：首个 TEXT_DELTA 触发一次 create + send，且 create 的是 schema 2.0 卡
        im_service.create_card_entity.assert_awaited_once()
        im_service.send_card_entity.assert_awaited_once()
        assert im_service.create_card_entity.await_args.args[0]["schema"] == "2.0"

        # content 累积全量前缀；终态含 build_answer_markdown 输出
        contents = [call.kwargs["content"] for call in im_service.stream_card_content.await_args_list]
        assert contents[0] == "你"
        assert "你好" in contents[-1]
        assert "**回答**" in contents[-1]
        # P-1 防翻倍：PART_DELTA 文本未被累积、正文不重复
        assert "你好你好" not in contents[-1]
        assert "不应消费" not in contents[-1]

        # sequence 严格递增（content PUT 与 settle 共享单调计数器）
        sequences = [call.kwargs["sequence"] for call in im_service.stream_card_content.await_args_list]
        settle_seq = im_service.settle_card_stream.await_args.kwargs["sequence"]
        all_seq = [*sequences, settle_seq]
        assert all_seq == sorted(all_seq)
        assert len(set(all_seq)) == len(all_seq)
        im_service.settle_card_stream.assert_awaited_once()

        # 工具进度仍走 thinking 卡（D-4）；终态收口 thinking 卡不留「思考中」（W-1）
        assert im_service.update_card.await_count == 2
        tool_card = im_service.update_card.await_args_list[0].args[1]
        tool_content = "\n".join(
            e.get("content", "") for e in tool_card["elements"] if isinstance(e, dict)
        )
        assert "浏览文件" in tool_content
        closeout_card = im_service.update_card.await_args_list[1].args[1]
        closeout_content = "\n".join(
            e.get("content", "") for e in closeout_card["elements"] if isinstance(e, dict)
        )
        assert "思考中" not in closeout_content
        assert "已回复" in closeout_content

    async def test_cardkit_create_failure_falls_back_to_answer_card(self) -> None:
        project = await Project.objects.acreate(name="Friday CKCreate", feishu_project_key="friday-ckcreate")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_ckcreate", root_message_id="msg_ckcreate")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_ckcreate",
            thread=thread,
            chat_id="chat_ckcreate",
            sender_open_id="ou_ckcreate",
            message_type="text",
            normalized_text="friday-ckcreate 解释一下",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = _cardkit_im_service(
            create_card_entity=AsyncMock(side_effect=FeishuIMError("租户未开通", code=99991672)),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _text_delta_stream(final_answer="降级后的回答"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ckcreate")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service._CARDKIT_STREAM_THROTTLE_S",
            0,
        ):
            result = await FeishuBotService().process_message("msg_ckcreate")

        # create 失败 → 绝不推流/收尾，完全降级出 build_answer_card（答案/引用/usage 不丢）
        assert result["status"] == "answered"
        im_service.stream_card_content.assert_not_awaited()
        im_service.settle_card_stream.assert_not_awaited()
        answer_card = im_service.update_card.await_args.args[1]
        content = "\n".join(e.get("content", "") for e in answer_card["elements"] if isinstance(e, dict))
        assert "降级后的回答" in content
        assert "已参考上下文" in content

    async def test_cardkit_stream_failure_midway_degrades(self) -> None:
        project = await Project.objects.acreate(name="Friday CKStream", feishu_project_key="friday-ckstream")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_ckstream", root_message_id="msg_ckstream")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_ckstream",
            thread=thread,
            chat_id="chat_ckstream",
            sender_open_id="ou_ckstream",
            message_type="text",
            normalized_text="friday-ckstream 解释一下",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = _cardkit_im_service(
            stream_card_content=AsyncMock(side_effect=[True, FeishuIMError("rate limit", code=99991400)]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _text_delta_stream(final_answer="中途失败后的回答"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ckstream")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service._CARDKIT_STREAM_THROTTLE_S",
            0,
        ):
            result = await FeishuBotService().process_message("msg_ckstream")

        # 中途推流失败 → 失效后不再推、终态不 settle、降级出 answer 卡
        assert result["status"] == "answered"
        assert im_service.stream_card_content.await_count == 2
        im_service.settle_card_stream.assert_not_awaited()
        answer_card = im_service.update_card.await_args.args[1]
        content = "\n".join(e.get("content", "") for e in answer_card["elements"] if isinstance(e, dict))
        assert "中途失败后的回答" in content
        assert "已参考上下文" in content

    async def test_cardkit_settle_failure_still_answers(self) -> None:
        project = await Project.objects.acreate(name="Friday CKSettle", feishu_project_key="friday-cksettle")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_cksettle", root_message_id="msg_cksettle")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_cksettle",
            thread=thread,
            chat_id="chat_cksettle",
            sender_open_id="ou_cksettle",
            message_type="text",
            normalized_text="friday-cksettle 解释一下",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = _cardkit_im_service(
            settle_card_stream=AsyncMock(side_effect=FeishuIMError("settle fail", code=300317)),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _text_delta_stream(final_answer="你好"):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="cksettle")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service._CARDKIT_STREAM_THROTTLE_S",
            0,
        ):
            result = await FeishuBotService().process_message("msg_cksettle")

        await thread.arefresh_from_db()
        # W-2：内容已送达，仅 settle 失败 → 视为 answered（CardKit message_id），绝不重复发 answer 卡
        assert result["status"] == "answered"
        assert thread.last_bot_message_id == "om_1"
        im_service.settle_card_stream.assert_awaited_once()
        # 仅 TOOL_USE_START + closeout 两次 update_card；绝无第二张 build_answer_card（无「已参考上下文」）
        assert im_service.update_card.await_count == 2
        for call in im_service.update_card.await_args_list:
            card = call.args[1]
            content = "\n".join(e.get("content", "") for e in card["elements"] if isinstance(e, dict))
            assert "已参考上下文" not in content

    async def test_waiting_stream_does_not_create_cardkit(self) -> None:
        project = await Project.objects.acreate(name="Friday CKWait", feishu_project_key="friday-ckwait")
        thread = await FeishuBotThread.objects.acreate(chat_id="chat_ckwait", root_message_id="msg_ckwait")
        await FeishuBotMessage.objects.acreate(
            message_id="msg_ckwait",
            thread=thread,
            chat_id="chat_ckwait",
            sender_open_id="ou_ckwait",
            message_type="text",
            normalized_text="friday-ckwait 做一次深度分析",
            quote_message_id="",
            mentioned_bot=True,
            raw_payload={},
        )
        im_service = _cardkit_im_service(
            send_card=AsyncMock(side_effect=["welcome_ckwait", "processing_ckwait"]),
        )

        async def fake_send_message_stream(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AgentEvent, None]:
            async for event in _waiting_stream(blocking_task_count=2):
                yield event

        with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
            "feishu.bot.service.ConversationService.create_conversation",
            new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ckwait")),
        ), patch(
            "feishu.bot.service.ConversationService.send_message_stream",
            new=fake_send_message_stream,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_ATTEMPTS",
            1,
            create=True,
        ), patch(
            "feishu.bot.service.WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS",
            0,
            create=True,
        ):
            result = await FeishuBotService().process_message("msg_ckwait")

        # F-1 + P-9 边界：waiting 无 TEXT_DELTA → 绝不创建 CardKit 实体，走既有 background 卡
        assert result["status"] == "waiting"
        im_service.create_card_entity.assert_not_awaited()
        im_service.send_card_entity.assert_not_awaited()
        im_service.stream_card_content.assert_not_awaited()
        im_service.settle_card_stream.assert_not_awaited()
        waiting_card = im_service.update_card.await_args.args[1]
        content = "\n".join(e.get("content", "") for e in waiting_card["elements"] if isinstance(e, dict))
        assert "后台分析中" in content
