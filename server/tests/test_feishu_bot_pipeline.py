"""Tests for Feishu bot processing pipeline."""
from __future__ import annotations
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from agents.core.events import MESSAGE_COMPLETE, AgentEvent
from agents.models import AgentSession, ToolCallLog
from chat.models import Conversation
from feishu.bot.service import FeishuBotService
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from projects.models import Project
from repositories.models import Repository
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
 yield # pragma: no cover — makes it a generator
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
 )
 with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)):
 result = await FeishuBotService.process_message("msg_attach")
 await thread.arefresh_from_db
 assert result["status"] == "clarification"
 assert thread.status == FeishuBotThreadStatus.AWAITING_PROJECT_CLARIFICATION
 assert im_service.send_card.await_count == 3
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
 )
 # 预创建 AgentSession + ToolCallLog 供 extract_reference_summaries 查询
 session = await AgentSession.objects.acreate(
 session_id="chat-session-1",
 project=project,
 user=user,
 status=AgentSession.Status.COMPLETED,
 messages=,
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
 result = await FeishuBotService.process_message("msg_success")
 await thread.arefresh_from_db
 assert result["status"] == "answered"
 assert thread.project_id == project.id
 im_service.update_card.assert_awaited_once
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
 result = await FeishuBotService.process_message("msg_fallback")
 await thread.arefresh_from_db
 assert result["status"] == "answered"
 assert thread.last_bot_message_id == "answer_3"
 assert im_service.send_card.await_count == 3
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
 )
 with patch("feishu.bot.service.FeishuIMService.create", new=AsyncMock(return_value=im_service)), patch(
 "feishu.bot.service.ConversationService.create_conversation",
 new=AsyncMock(return_value=await Conversation.objects.acreate(project=project, title="ops")),
 ), patch(
 "feishu.bot.service.ConversationService.send_message_stream",
 new=_error_stream,
 ):
 result = await FeishuBotService.process_message("msg_error")
 assert result["status"] == "error"
 im_service.update_card.assert_not_awaited
 error_card = im_service.send_card.await_args_list[-1].kwargs["card"]
 content = "\n".join(element.get("content", "") for element in error_card["elements"] if isinstance(element, dict))
 assert "联系管理员" in content
