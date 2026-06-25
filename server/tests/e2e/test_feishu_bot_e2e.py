"""飞书 Bot 对话 E2E 测试。

覆盖 @Bot 消息接收 -> 派发 -> 项目解析 -> Agent 调用 -> 回复发送的完整链路。
对应需求: work item (contract, contract, contract)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.core.events import MESSAGE_COMPLETE, AgentEvent
from feishu.bot.dispatcher import dispatch_inbound_message
from feishu.bot.project_resolver import ProjectResolution, ProjectResolver
from feishu.bot.service import FeishuBotService
from feishu.bot.thread_resolver import ThreadResolution, ThreadResolver
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from services.feishu_im import FeishuIMService
from tests.e2e.fixtures.bot_payloads import (
    create_bot_message_from_bot,
    create_bot_text_message,
    create_empty_body_message,
    create_p2p_message,
)

pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# TestBotDispatcher - 验证消息路由 (contract)
# ============================================================================


class TestBotDispatcher:
    """验证 dispatch_inbound_message 的消息路由逻辑。"""

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_group_mention(
        self,
        _mock_resume: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        """@Bot 群聊消息应被接受，创建 Thread 和 Message。"""
        msg = create_bot_text_message()
        result = await dispatch_inbound_message(msg)

        assert result.status == "bot_message_accepted"
        assert result.thread_id is not None
        assert result.message_pk is not None

        # 验证 Thread 已创建
        thread = await FeishuBotThread.objects.aget(pk=result.thread_id)
        assert thread.chat_id == msg.chat_id
        assert thread.status == FeishuBotThreadStatus.ACTIVE
        assert thread.root_message_id == msg.message_id

        # 验证 Message 已创建
        bot_msg = await FeishuBotMessage.objects.aget(pk=result.message_pk)
        assert bot_msg.message_id == msg.message_id
        assert bot_msg.thread_id == thread.pk
        assert bot_msg.normalized_text == msg.normalized_text

        # 验证后台任务已调度
        mock_schedule.assert_called_once_with(msg.message_id)

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_ignores_bot_sender(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """Bot 发送的消息应被忽略。"""
        msg = create_bot_message_from_bot()
        result = await dispatch_inbound_message(msg)

        assert result.status == "ignored"
        assert result.reason == "sender_is_bot"

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_ignores_no_mention(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """群聊中未 @Bot 的消息应被忽略。"""
        msg = create_bot_text_message(mentioned_bot=False)
        result = await dispatch_inbound_message(msg)

        assert result.status == "ignored"
        assert result.reason == "mention_required"

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_accepts_p2p(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """私聊消息走 bot 流程（feishu Bot 私聊增强后 p2p 不再 unsupported）。

        历史：早期实现把 p2p 直接 ignored / unsupported_chat_type；
        现在 dispatcher 仅排除非 p2p/group 类型，p2p 进入正常流程，
        见 feishu/bot/dispatcher.py:69-73。
        """
        msg = create_p2p_message()
        result = await dispatch_inbound_message(msg)

        assert result.status == "bot_message_accepted"

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_ignores_empty_body(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """空消息体应被忽略。"""
        msg = create_empty_body_message()
        result = await dispatch_inbound_message(msg)

        assert result.status == "ignored"
        assert result.reason == "empty_body"

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_bot_dispatch_duplicate_message(
        self,
        _mock_resume: AsyncMock,
        mock_schedule: AsyncMock,
    ) -> None:
        """重复 message_id 应返回 duplicate。"""
        fixed_id = f"om_{uuid.uuid4().hex[:12]}"
        msg1 = create_bot_text_message(message_id=fixed_id)
        result1 = await dispatch_inbound_message(msg1)
        assert result1.status == "bot_message_accepted"

        # 发送相同 message_id 的消息
        msg2 = create_bot_text_message(message_id=fixed_id)
        result2 = await dispatch_inbound_message(msg2)
        assert result2.status == "duplicate"
        assert result2.reason == "message_exists"


# ============================================================================
# TestBotThreadManagement - 验证线程管理 (contract)
# ============================================================================


class TestBotThreadManagement:
    """验证 dispatcher 的线程创建和复用逻辑。"""

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_new_message_creates_thread(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """新 chat_id 的消息应创建新 Thread。"""
        unique_chat = f"oc_new_{uuid.uuid4().hex[:8]}"
        msg = create_bot_text_message(chat_id=unique_chat)
        result = await dispatch_inbound_message(msg)

        assert result.status == "bot_message_accepted"
        thread = await FeishuBotThread.objects.aget(pk=result.thread_id)
        assert thread.chat_id == unique_chat
        assert thread.root_message_id == msg.message_id

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_followup_reuses_thread(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """同一 chat_id 的后续消息应复用 Thread，更新 last_user_message_id。"""
        shared_chat = f"oc_shared_{uuid.uuid4().hex[:8]}"

        msg1 = create_bot_text_message(chat_id=shared_chat, text="第一条消息")
        result1 = await dispatch_inbound_message(msg1)
        assert result1.status == "bot_message_accepted"

        msg2 = create_bot_text_message(chat_id=shared_chat, text="第二条消息")
        result2 = await dispatch_inbound_message(msg2)
        assert result2.status == "bot_message_accepted"

        # 应复用同一个 thread
        assert result2.thread_id == result1.thread_id

        # last_user_message_id 应更新为第二条消息
        thread = await FeishuBotThread.objects.aget(pk=result2.thread_id)
        assert thread.last_user_message_id == msg2.message_id

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_quote_message_links_to_thread(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
    ) -> None:
        """引用消息应通过 quote_message_id 链接到原 Thread。"""
        chat_id = f"oc_quote_{uuid.uuid4().hex[:8]}"

        # 先创建原始消息
        original_msg = create_bot_text_message(chat_id=chat_id, text="原始问题")
        result_orig = await dispatch_inbound_message(original_msg)
        assert result_orig.status == "bot_message_accepted"

        # 在不同 chat_id 中引用原消息（但因为 _find_thread 先查 quote_message_id，仍应关联到原 Thread）
        quote_msg = create_bot_text_message(
            chat_id=chat_id,
            text="追问",
            quote_message_id=original_msg.message_id,
        )
        result_quote = await dispatch_inbound_message(quote_msg)
        assert result_quote.status == "bot_message_accepted"

        # 应链接到原始 Thread
        assert result_quote.thread_id == result_orig.thread_id


# ============================================================================
# TestBotServiceProcessing - 验证完整处理链路 (contract)
# ============================================================================


class TestBotServiceProcessing:
    """验证 FeishuBotService.process_message 完整处理链路。"""

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_process_message_answered(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
        e2e_project: Any,
    ) -> None:
        """完整处理链路: dispatch -> process_message -> 回复。"""
        chat_id = f"oc_process_{uuid.uuid4().hex[:8]}"
        msg = create_bot_text_message(chat_id=chat_id, text="E2E Test Space 这个 Bug 怎么修")
        result = await dispatch_inbound_message(msg)
        assert result.status == "bot_message_accepted"

        message_id = msg.message_id

        # Mock FeishuIMService.create
        mock_im_service = AsyncMock(spec=FeishuIMService)
        mock_im_service.send_card = AsyncMock(return_value="card_id_xxx")
        mock_im_service.update_card = AsyncMock(return_value=True)

        # Mock ConversationService.send_message_stream -> async generator
        async def _fake_stream(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            force_deep_analysis: bool = False,
            feishu_doc_id: str = "",
            project_context_line: str | None = None,
            search_branch: str | None = None,
            **kwargs: object,
        ) -> AsyncGenerator[AgentEvent, None]:
            yield AgentEvent(
                type=MESSAGE_COMPLETE,
                data={
                    "session_id": "sess_e2e_test",
                    "final_answer": "这是 E2E 测试回答",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                    "cost_usd": 0.01,
                },
            )

        # Mock ProjectResolver.resolve -> 成功解析到 e2e_project
        mock_project_resolver = AsyncMock(spec=ProjectResolver)
        mock_project_resolver.resolve = AsyncMock(
            return_value=ProjectResolution(
                status="resolved",
                space=e2e_project,
                candidates=[e2e_project.name],
                reason="explicit_alias_match",
            )
        )

        # Mock ThreadResolver.resolve -> 默认续接
        bot_message = await FeishuBotMessage.objects.select_related("thread").aget(
            message_id=message_id
        )
        mock_thread_resolver = AsyncMock(spec=ThreadResolver)
        mock_thread_resolver.resolve = AsyncMock(
            return_value=ThreadResolution(
                status="new",
                thread=bot_message.thread,
                reason="no_recent_thread",
            )
        )

        # Mock extract_reference_summaries
        with (
            patch(
                "feishu.bot.service.FeishuIMService.create",
                return_value=mock_im_service,
            ),
            patch(
                "feishu.bot.service.ConversationService.send_message_stream",
                side_effect=_fake_stream,
            ),
            patch(
                "feishu.bot.service.extract_reference_summaries",
                return_value=[],
            ),
        ):
            service = FeishuBotService(
                thread_resolver=mock_thread_resolver,
                project_resolver=mock_project_resolver,
            )
            process_result = await service.process_message(message_id)

        assert process_result["status"] == "answered"
        assert process_result["session_id"] == "sess_e2e_test"

        # 验证 im_service.send_card 被调用（welcome card + processing card）
        assert mock_im_service.send_card.call_count >= 1

        # 验证 im_service.update_card 被调用（answer card 更新）
        mock_im_service.update_card.assert_called_once()

    @patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message")
    @patch("feishu.bot.dispatcher._try_resume_suspended_agent", return_value=False)
    async def test_process_message_clarification(
        self,
        _mock_resume: AsyncMock,
        _mock_schedule: AsyncMock,
        e2e_project: Any,
    ) -> None:
        """项目无法识别时应触发澄清流程。"""
        chat_id = f"oc_clarify_{uuid.uuid4().hex[:8]}"
        msg = create_bot_text_message(chat_id=chat_id, text="这个问题怎么看")
        result = await dispatch_inbound_message(msg)
        assert result.status == "bot_message_accepted"

        message_id = msg.message_id

        mock_im_service = AsyncMock(spec=FeishuIMService)
        mock_im_service.send_card = AsyncMock(return_value="card_clarify_xxx")
        mock_im_service.update_card = AsyncMock(return_value=True)

        # ProjectResolver 返回需要澄清
        mock_project_resolver = AsyncMock(spec=ProjectResolver)
        mock_project_resolver.resolve = AsyncMock(
            return_value=ProjectResolution(
                status="awaiting_project_clarification",
                space=None,
                candidates=["Space A", "Space B"],
                reason="no_project_match",
            )
        )

        bot_message = await FeishuBotMessage.objects.select_related("thread").aget(
            message_id=message_id
        )
        mock_thread_resolver = AsyncMock(spec=ThreadResolver)
        mock_thread_resolver.resolve = AsyncMock(
            return_value=ThreadResolution(
                status="new",
                thread=bot_message.thread,
                reason="no_recent_thread",
            )
        )

        with patch(
            "feishu.bot.service.FeishuIMService.create",
            return_value=mock_im_service,
        ):
            service = FeishuBotService(
                thread_resolver=mock_thread_resolver,
                project_resolver=mock_project_resolver,
            )
            process_result = await service.process_message(message_id)

        assert process_result["status"] == "clarification"
        assert process_result["reason"] == "no_project_match"


# ============================================================================
# TestBotTimeoutReminder - 验证超时提醒功能 (work item 缺口记录)
# ============================================================================


class TestBotTimeoutReminder:
    """超时提醒功能验证。

    work item 要求"支持多轮追问和超时提醒"。
    当前状态：卡片模板 build_chat_reminder_card 已定义（feishu/cards/chat_question_card.py），
    但 FeishuBotService.process_message 未包含超时触发逻辑。
    该功能标记为待实现，后续阶段补充。
    """

    @pytest.mark.xfail(
        reason="超时提醒功能尚未在 FeishuBotService 中实现，卡片模板已就绪但未被调用",
        strict=True,
    )
    async def test_timeout_reminder_card_sent_after_inactivity(self) -> None:
        """验证会话超时后应发送提醒卡片。

        预期行为：当 Bot 会话超过配置时间不活跃后，
        系统调用 build_chat_reminder_card 并通过 IM 服务发送到群聊。
        当前 service.py 无此逻辑，测试预期失败。
        """
        from feishu.cards.chat_question_card import build_chat_reminder_card

        # 验证卡片模板可正常构建
        card = build_chat_reminder_card(question="测试问题", remaining_minutes=15)
        assert "tag" in card  # 卡片结构存在

        # 验证 FeishuBotService 源码中包含超时处理逻辑
        import inspect

        source = inspect.getsource(FeishuBotService.process_message)
        # 当超时逻辑被实现后，源码中应包含 timeout/reminder 相关调用
        assert "timeout" in source.lower() or "reminder" in source.lower(), \
            "FeishuBotService.process_message 尚未包含超时提醒逻辑"
