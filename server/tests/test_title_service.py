"""标题生成服务测试。

implementation contract（implementation plan）迁移后：
- title_service 调用链从旧 Anthropic SDK 直调改为
  ``agents.llm_factory.build_chat_model(resolved).ainvoke(...)``
- mock 注入点统一收敛到 ``build_chat_model`` + ``FakeChatModel``
- 凭证解析通过 ``ProviderConfigService.aresolve_or_error``（contract Result 模式）

测试保留原 4 个 generate_title 分支 + 3 个 should_generate_title 分支（共 7 tests）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from chat.models import Conversation, Message
from projects.models import Space
from services.provider_config import (
    ProviderMissingError,
    ProviderType,
    ResolvedProviderConfig,
)
from tests.helpers.fake_chat_model import FakeChatModel

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_project(db: Any) -> Space:
    """创建测试项目。"""
    return Space.objects.create(name="Title Test Space")


@pytest.fixture
def conversation(db: Any, test_project: Space) -> Conversation:
    """创建测试对话。"""
    return Conversation.objects.create(space=test_project, title="新对话")


@pytest.fixture
def first_message(db: Any, conversation: Conversation) -> Message:
    """创建首条用户消息。"""
    return Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content="帮我分析一下项目架构",
    )


def _resolved_anthropic_stub() -> ResolvedProviderConfig:
    """最小 ResolvedProviderConfig stub（title_service 不在意 api_key 真伪）。"""
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )


# ============================================================================
# should_generate_title 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestShouldGenerateTitle:
    """should_generate_title 首条消息判断测试。"""

    async def test_first_message_returns_true(
        self, conversation: Conversation, first_message: Message
    ) -> None:
        """对话有且仅有 1 条 user 消息时返回 True。"""
        from chat.title_service import should_generate_title

        assert await should_generate_title(str(conversation.id)) is True

    async def test_multiple_messages_returns_false(
        self, conversation: Conversation, first_message: Message
    ) -> None:
        """多条 user 消息时返回 False。"""
        from chat.title_service import should_generate_title

        # 添加第二条消息
        await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.USER,
            content="第二条消息",
        )
        assert await should_generate_title(str(conversation.id)) is False

    async def test_no_messages_returns_false(
        self, conversation: Conversation
    ) -> None:
        """无消息时返回 False。"""
        from chat.title_service import should_generate_title

        assert await should_generate_title(str(conversation.id)) is False


# ============================================================================
# generate_title 测试（contract 迁移后：FakeChatModel + build_chat_model seam）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestGenerateTitle:
    """generate_title 标题生成测试。"""

    async def test_generate_title_success(
        self,
        conversation: Conversation,
        first_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract：成功生成标题并更新数据库（FakeChatModel seam）。"""
        from chat.title_service import generate_title

        fake = FakeChatModel(responses=["项目架构分析"])
        monkeypatch.setattr(
            "chat.title_service.build_chat_model",
            lambda *a, **kw: fake,
        )
        # 走 aresolve_or_error stub，返回 Anthropic ResolvedProviderConfig
        monkeypatch.setattr(
            "chat.title_service.ProviderConfigService.aresolve_or_error",
            AsyncMock(return_value=_resolved_anthropic_stub()),
        )
        monkeypatch.setattr(
            "chat.services.aget_setting_value",
            AsyncMock(return_value=None),  # ANTHROPIC_MODEL 走 fallback
        )

        result = await generate_title(str(conversation.id), "帮我分析一下项目架构")

        assert result == "项目架构分析"
        # 验证数据库更新
        await conversation.arefresh_from_db()
        assert conversation.title == "项目架构分析"

    async def test_generate_title_api_error_returns_none(
        self,
        conversation: Conversation,
        first_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract：LLM 调用抛异常时返回 None，不 raise。"""
        from chat.title_service import generate_title

        class _BoomFake(FakeChatModel):
            async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
                raise Exception("API Error")

        fake = _BoomFake(responses=["x"])
        monkeypatch.setattr(
            "chat.title_service.build_chat_model",
            lambda *a, **kw: fake,
        )
        monkeypatch.setattr(
            "chat.title_service.ProviderConfigService.aresolve_or_error",
            AsyncMock(return_value=_resolved_anthropic_stub()),
        )
        monkeypatch.setattr(
            "chat.services.aget_setting_value",
            AsyncMock(return_value=None),
        )

        result = await generate_title(str(conversation.id), "test")

        assert result is None
        # 标题未变
        await conversation.arefresh_from_db()
        assert conversation.title == "新对话"

    async def test_generate_title_no_api_key_returns_none(
        self,
        conversation: Conversation,
        first_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract：凭证解析返回 ProviderMissingError 时返回 None。"""
        from chat.title_service import generate_title

        missing = ProviderMissingError(
            missing_provider="anthropic",
            recommended_action="请在系统设置添加 Anthropic 凭证",
            source_attempted="system",
        )
        monkeypatch.setattr(
            "chat.title_service.ProviderConfigService.aresolve_or_error",
            AsyncMock(return_value=missing),
        )

        result = await generate_title(str(conversation.id), "test")

        assert result is None

    async def test_generate_title_empty_response_returns_none(
        self,
        conversation: Conversation,
        first_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract：LLM 返回空内容时返回 None。"""
        from chat.title_service import generate_title

        # AIMessage.content 非空但全空白 → strip 后为空
        fake = FakeChatModel(responses=["   "])
        monkeypatch.setattr(
            "chat.title_service.build_chat_model",
            lambda *a, **kw: fake,
        )
        monkeypatch.setattr(
            "chat.title_service.ProviderConfigService.aresolve_or_error",
            AsyncMock(return_value=_resolved_anthropic_stub()),
        )
        monkeypatch.setattr(
            "chat.services.aget_setting_value",
            AsyncMock(return_value=None),
        )

        result = await generate_title(str(conversation.id), "test")

        assert result is None
