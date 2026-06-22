"""chat.config.build_sdk_config 单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from agents.chat_runner import ChatRunnerConfig
from services.provider_config import ProviderType


@dataclass
class _ResolvedStub:
    api_key: str = "sk-test-key"
    base_url: str = "https://api.example.com"
    provider_type: ProviderType = ProviderType.ANTHROPIC
    credential_id: None = None


@pytest.mark.django_db(transaction=True)
class TestBuildSdkConfig:
    """build_sdk_config() 配置构建测试。"""

    async def test_returns_config_and_session(self, project):
        from chat.config import build_sdk_config
        from chat.models import Conversation

        conversation = await Conversation.objects.acreate(
            project=project,
            title="test",
            model="claude-sonnet-4-5",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(return_value=_ResolvedStub()),
            ),
            patch(
                "chat.config.aget_setting_value",
                new=AsyncMock(return_value=None),
            ),
        ):
            config, agent_session = await build_sdk_config(conversation)

        assert isinstance(config, ChatRunnerConfig)
        assert config.api_key == "sk-test-key"
        assert config.api_base_url == "https://api.example.com"
        assert config.model == "claude-sonnet-4-5"
        assert config.space_id == str(project.id)
        assert config.conversation_id == str(conversation.id)
        assert config.max_turns == 50
        assert config.timeout_seconds == 0
        assert agent_session.status == "running"
        assert agent_session.session_id.startswith(f"chat-{conversation.id}-")

    async def test_uses_conversation_model_over_system(self, project):
        from chat.config import build_sdk_config
        from chat.models import Conversation

        conversation = await Conversation.objects.acreate(
            project=project,
            title="test",
            model="claude-opus-5",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        async def mock_setting(key: str) -> str | None:
            if key == "anthropic_model":
                return "claude-sonnet-4-5"
            return None

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(return_value=_ResolvedStub()),
            ),
            patch(
                "chat.config.aget_setting_value",
                new=AsyncMock(side_effect=mock_setting),
            ),
        ):
            config, _ = await build_sdk_config(conversation)

        assert config.model == "claude-opus-5"

    async def test_uses_system_model_fallback(self, project):
        """对话未指定 model 时 fallback 到系统级 ProviderCredential.default_model。

        v8.1 之后：legacy 路径走 aget_legacy_anthropic_config() 读 ProviderCredential，
        不再走 SettingKeys.ANTHROPIC_MODEL（已被硬删，见 services/provider_config.py:359）。
        """
        from chat.config import build_sdk_config
        from chat.models import Conversation

        conversation = await Conversation.objects.acreate(
            project=project,
            title="test",
            model="",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(return_value=_ResolvedStub()),
            ),
            patch(
                "chat.config.aget_legacy_anthropic_config",
                new=AsyncMock(
                    return_value={
                        "api_key": "sk-test",
                        "base_url": "",
                        "default_model": "claude-sonnet-4-5",
                    },
                ),
            ),
        ):
            config, _ = await build_sdk_config(conversation)

        assert config.model == "claude-sonnet-4-5"

    async def test_raises_on_provider_error(self, project):
        from chat.config import build_sdk_config
        from chat.models import Conversation
        from services.provider_config import ProviderConfigError

        conversation = await Conversation.objects.acreate(
            project=project,
            title="test",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(side_effect=ProviderConfigError("No API key configured")),
            ),
            pytest.raises(ValueError, match="No API key configured"),
        ):
            await build_sdk_config(conversation)

    async def test_no_space_conversation_builds_general_config(self):
        """无空间对话（project=None）：space_id 为空串 + prompt 注入无空间指引。

        行为契约：space_id="" → chat_runner._get_tool_names 不注入任何空间工具；
        system prompt 引导 LLM 在任务涉及空间知识时要求用户先选择空间。
        """
        from chat.config import build_sdk_config
        from chat.models import Conversation
        from services.provider_config import ProviderType

        @dataclass
        class _FullResolvedStub:
            api_key: str = "sk-test-key"
            base_url: str = "https://api.example.com"
            provider_type: ProviderType = ProviderType.ANTHROPIC
            credential_id: None = None

        conversation = await Conversation.objects.acreate(
            project=None,
            title="general",
            model="claude-sonnet-4-5",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(return_value=_FullResolvedStub()),
            ),
            patch(
                "chat.config.aget_setting_value",
                new=AsyncMock(return_value=None),
            ),
        ):
            config, agent_session = await build_sdk_config(conversation)

        assert config.space_id == ""
        assert "未绑定任何空间" in config.system_prompt
        assert agent_session.project_id is None

    async def test_budget_from_settings(self, project):
        from chat.config import build_sdk_config
        from chat.models import Conversation

        conversation = await Conversation.objects.acreate(
            project=project,
            title="test",
            model="claude-sonnet-4-5",
        )
        conversation = await Conversation.objects.select_related("project").aget(
            id=conversation.id,
        )

        async def mock_setting(key: str) -> str | None:
            if key == "max_budget_usd":
                return "5.0"
            return None

        with (
            patch(
                "chat.config.ProviderConfigService.aresolve",
                new=AsyncMock(return_value=_ResolvedStub()),
            ),
            patch(
                "chat.config.aget_setting_value",
                new=AsyncMock(side_effect=mock_setting),
            ),
        ):
            config, _ = await build_sdk_config(conversation)

        assert config.max_budget_usd == 5.0
