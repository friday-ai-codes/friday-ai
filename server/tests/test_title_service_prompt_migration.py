"""implementation / implementation contract: title_service prompt 迁移字节级等价测试。

implementation contract（implementation plan）迁移后：
- 原 Anthropic SDK 客户端拦截改为 `build_chat_model` seam + `FakeChatModel`
- 保留字节级 hash 比对能力：通过 `_CapturingFake` 子类在 `ainvoke` 时捕获
  `HumanMessage.content`，验证 3 个分支（DB 命中 / DB 空 / PROMPT_CENTER_DISABLED_KEYS）
  与 fallback `.replace('{{user_message}}', ...)` 字节级等价
- security mitigation 注入防护（变量值中 `{{ }}` HTML entity 替换）不变
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from chat.models import Conversation, Message
from chat.title_service import TITLE_PROMPT, generate_title
from projects.models import Space
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel


def _resolved_anthropic_stub() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )


@pytest.fixture
def mock_langchain(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """contract 迁移后的 prompt 迁移 fixture：捕获 ainvoke 收到的 HumanMessage.content。

    关键：`_CapturingFake.ainvoke` 捕获 `messages[0].content` 字节级字符串，
    等价于原 `anthropic messages.create` kwargs["messages"][0]["content"] 的值。
    """
    captured: dict[str, Any] = {}

    class _CapturingFake(FakeChatModel):
        async def ainvoke(
            self, input_: Any, config: Any = None, **kwargs: Any
        ) -> Any:
            if isinstance(input_, list) and input_:
                last = input_[-1]
                captured["last_content"] = getattr(last, "content", "") or str(last)
            return await super().ainvoke(input_, config, **kwargs)

    fake = _CapturingFake(responses=["标题文本"])

    monkeypatch.setattr(
        "chat.title_service.build_chat_model",
        lambda *a, **kw: fake,
    )
    monkeypatch.setattr(
        "chat.title_service.ProviderConfigService.aresolve_or_error",
        _make_resolve_stub(),
    )

    async def _fake_legacy_config() -> dict[str, str]:
        return {
            "api_key": "sk-fake",
            "base_url": "https://api.anthropic.com",
            "default_model": "claude-3-haiku",
            "small_model": "",
        }

    monkeypatch.setattr(
        "chat.title_service.aget_legacy_anthropic_config",
        _fake_legacy_config,
    )
    return captured


def _make_resolve_stub() -> Any:
    """构造 aresolve_or_error 的 async stub。"""

    async def _stub(
        node_config: Any = None, conversation: Any = None, project: Any = None
    ) -> ResolvedProviderConfig:
        return _resolved_anthropic_stub()

    return _stub


@pytest.mark.django_db(transaction=True)
class TestTitleServiceMigration:
    """title_service 三态 + 注入防护（contract 迁移后）。"""

    @pytest.fixture(autouse=True)
    def _ensure_title_seed(self, db: Any) -> None:
        """每个测试开始前确保 AUX_TITLE_GENERATION seed 存在（避免前测 delete 污染）。"""
        from prompts.models import PromptVersion

        if not Prompt.objects.filter(
            slug=PromptSlugs.AUX_TITLE_GENERATION,
            scope=PromptScope.SYSTEM,
        ).exists():
            prompt = Prompt.objects.create(
                slug=PromptSlugs.AUX_TITLE_GENERATION,
                scope=PromptScope.SYSTEM,
                space=None,
                category="aux_model",
                title="标题生成",
                description="implementation test re-seed",
                is_builtin=True,
            )
            version = PromptVersion.objects.create(
                prompt=prompt,
                version=1,
                body=TITLE_PROMPT,
                variables_schema={},
                change_note="test re-seed",
            )
            prompt.active_version = version
            prompt.save(update_fields=["active_version", "updated_at"])

    @pytest.fixture
    def conversation(self, db: Any) -> Conversation:
        project = Space.objects.create(
            name="title-test-project",
            feishu_project_key="title-test-key",
        )
        conv = Conversation.objects.create(space=project, title="")
        Message.objects.create(
            conversation=conv,
            role=Message.Role.USER,
            content="帮我实现登录功能",
        )
        return conv

    @pytest.mark.asyncio
    async def test_db_hit_uses_db_body(
        self,
        conversation: Conversation,
        mock_langchain: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 命中：LLM 收到的 prompt 来自 DB body（含 XML tag 包裹变量）。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        # pytest-django 已通过 0002 migration seed AUX_TITLE_GENERATION —— 直接调用
        await generate_title(str(conversation.id), "帮我实现登录功能")
        content = mock_langchain["last_content"]
        # DB 路径变量被 XML tag 包裹（_sanitize_variables 输出）
        assert "<user_message>" in content
        assert "</user_message>" in content
        assert "帮我实现登录功能" in content

    @pytest.mark.asyncio
    async def test_db_empty_returns_fallback(
        self,
        conversation: Conversation,
        mock_langchain: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 空：走 fallback 路径，与 .replace('{{user_message}}', ...) 字节级等价。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        # 删掉 seed 数据强制走 DB 空路径
        await Prompt.objects.filter(
            slug=PromptSlugs.AUX_TITLE_GENERATION,
            scope=PromptScope.SYSTEM,
        ).adelete()

        await generate_title(str(conversation.id), "hello")
        content = mock_langchain["last_content"]
        expected = TITLE_PROMPT.replace("{{user_message}}", "hello")
        assert content == expected

    @pytest.mark.asyncio
    async def test_flag_disabled_returns_fallback(
        self,
        conversation: Conversation,
        mock_langchain: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PROMPT_CENTER_DISABLED_KEYS 命中：即使 DB 有记录也走 fallback。"""
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "aux.title_generation")
        # DB 仍有 seed 记录（不删）
        await generate_title(str(conversation.id), "flag test")
        content = mock_langchain["last_content"]
        expected = TITLE_PROMPT.replace("{{user_message}}", "flag test")
        assert content == expected
        assert "<user_message>" not in content  # 证明没走 DB 命中路径

    @pytest.mark.asyncio
    async def test_title_prompt_injection_sanitized(
        self,
        conversation: Conversation,
        mock_langchain: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """security mitigation: 变量值中的 {{ }} 应被 HTML entity 替换，不二次渲染。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        # 确保 DB 有 seed 记录（走清洗路径）
        prompt = await Prompt.objects.filter(
            slug=PromptSlugs.AUX_TITLE_GENERATION,
            scope=PromptScope.SYSTEM,
        ).afirst()
        assert prompt is not None, "seed should have provided AUX_TITLE_GENERATION"

        await generate_title(str(conversation.id), "{{evil}}")
        content = mock_langchain["last_content"]
        assert "{{evil}}" not in content  # 裸 {{evil}} 不得出现
        assert "&#123;&#123;evil&#125;&#125;" in content  # 被 HTML entity 替换

    @pytest.mark.asyncio
    async def test_passes_human_message_to_langchain(
        self,
        conversation: Conversation,
        mock_langchain: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """contract：验证 ainvoke 输入是 [HumanMessage(content=rendered_prompt)] 单一路径。

        保证 work item implementation 字节级 hash 等价契约：title_service 不引入
        ChatPromptTemplate 二次封装，保留 rendered_prompt → HumanMessage 透传。
        """
        captured_inputs: list[Any] = []

        # 再包一层捕获 input_ 类型
        orig_ainvoke_setter = mock_langchain

        class _TypeCheckingFake(FakeChatModel):
            async def ainvoke(
                self, input_: Any, config: Any = None, **kwargs: Any
            ) -> Any:
                captured_inputs.append(input_)
                return await super().ainvoke(input_, config, **kwargs)

        fake = _TypeCheckingFake(responses=["ok"])
        monkeypatch.setattr(
            "chat.title_service.build_chat_model",
            lambda *a, **kw: fake,
        )

        await generate_title(str(conversation.id), "hello")

        assert len(captured_inputs) == 1
        input_ = captured_inputs[0]
        assert isinstance(input_, list)
        assert len(input_) == 1
        assert isinstance(input_[0], HumanMessage)
        # 兼容中文 prompt 的 str 或 list content（本路径应是 str）
        assert isinstance(input_[0].content, str)
        assert "hello" in input_[0].content
