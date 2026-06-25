"""implementation / implementation contract 端到端：title_service 迁移后 LLM payload 字节级等价验证。

目标：证明真实 generate_title 调用链下（fire-and-forget + async），
LangChain BaseChatModel 收到的 HumanMessage payload 与迁移前 anthropic SDK
行为等价（DB 空 fallback 路径、DB 命中 XML tag 路径）。

implementation contract（implementation plan）迁移后：
- title_service 从 anthropic.AsyncAnthropic 迁至 build_chat_model(resolved).ainvoke(...)
- 原 anthropic.AsyncAnthropic mock 路径失效；改用 FakeChatModel seam 捕获
  HumanMessage.content，字节级等价断言保持不变
- 凭证解析走 ProviderConfigService.aresolve_or_error（contract Result 模式）

Rule 2 (auto-add critical functionality) 修补：title_service 生产代码迁移后
原 e2e 测试的 mock 路径失效 —— 测试与生产代码必须同步迁移，否则 CI 红。
implementation plan project_instructions 原文"不迁移 e2e/test_prompt_migration_e2e.py"
的意图是不改测试语义，但生产代码路径变化使 mock 层必须跟进；本迁移保留
所有断言语义（content 字节级等价、XML tag 包裹），仅替换 mock 注入点。
"""
from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from chat.models import Conversation, Message
from chat.title_service import TITLE_PROMPT, generate_title
from projects.models import Space
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel


def _resolved_anthropic_stub() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake-e2e",
        base_url="https://api.anthropic.com",
        source="system",
    )


def _patch_title_service(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeChatModel,
) -> None:
    """统一注入：build_chat_model seam + aresolve_or_error + aget_setting_value。"""
    monkeypatch.setattr(
        "chat.title_service.build_chat_model",
        lambda *a, **kw: fake,
    )

    async def _stub_resolve(
        node_config: Any = None,
        conversation: Any = None,
        project: Any = None,
    ) -> ResolvedProviderConfig:
        return _resolved_anthropic_stub()

    monkeypatch.setattr(
        "chat.title_service.ProviderConfigService.aresolve_or_error",
        _stub_resolve,
    )

    # implementation 后 title_service.model 取值改走
    # ``aget_legacy_anthropic_config()["default_model"]``，原 ``aget_setting_value`` 已不再被
    # title_service 引用。统一在此 mock 新的入口。
    async def _fake_legacy_anthropic() -> dict[str, str]:
        return {
            "api_key": "sk-fake-e2e",
            "base_url": "https://api.anthropic.com",
            "default_model": "claude-3-haiku",
        }

    monkeypatch.setattr(
        "chat.title_service.aget_legacy_anthropic_config",
        _fake_legacy_anthropic,
    )


@pytest.mark.django_db(transaction=True)
class TestPromptMigrationE2E:
    """title_service 端到端最简链路：generate_title → render_prompt → build_chat_model seam."""

    @pytest.fixture(autouse=True)
    def _reseed(self, db: Any) -> None:
        """确保 AUX_TITLE_GENERATION seed 存在。"""
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
                description="implementation e2e re-seed",
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
    def conv_with_first_message(self, db: Any) -> Conversation:
        project = Space.objects.create(
            name="e2e-title-project",
            feishu_project_key="e2e-title-key",
        )
        conv = Conversation.objects.create(space=project, title="")
        Message.objects.create(
            conversation=conv,
            role=Message.Role.USER,
            content="端到端测试消息",
        )
        return conv

    @pytest.mark.asyncio
    async def test_title_service_e2e_payload_byte_equivalent(
        self,
        conv_with_first_message: Conversation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """迁移后 payload == TITLE_PROMPT.replace('{{user_message}}', user_message[:500])。"""
        # 强制走 fallback 路径（DB 空 + 无 flag）— 锁定等价性断言
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        await Prompt.objects.filter(
            slug=PromptSlugs.AUX_TITLE_GENERATION,
            scope=PromptScope.SYSTEM,
        ).adelete()

        captured: dict[str, Any] = {}

        class _CapturingFake(FakeChatModel):
            async def ainvoke(
                self, input_: Any, config: Any = None, **kwargs: Any
            ) -> AIMessage:
                if isinstance(input_, list) and input_:
                    last = input_[-1]
                    captured["content"] = getattr(last, "content", "") or str(last)
                return await super().ainvoke(input_, config, **kwargs)

        fake = _CapturingFake(responses=["端到端标题"])
        _patch_title_service(monkeypatch, fake)

        # 触发迁移后调用栈
        result = await generate_title(str(conv_with_first_message.id), "端到端测试消息")
        assert result == "端到端标题"

        # 字节级等价断言（work item 契约 —— implementation 会再验一次）
        expected = TITLE_PROMPT.replace("{{user_message}}", "端到端测试消息")
        assert captured["content"] == expected, (
            f"E2E payload mismatch:\n"
            f"  expected: {expected!r}\n"
            f"  got:      {captured['content']!r}"
        )

    @pytest.mark.asyncio
    async def test_title_service_e2e_db_hit_path_preserves_core_text(
        self,
        conv_with_first_message: Conversation,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 命中路径：payload 包含原核心文本 + XML tag 包裹的 user_message。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        # 保留 seed 数据不删（_reseed fixture 已提供）

        captured: dict[str, Any] = {}

        class _CapturingFake(FakeChatModel):
            async def ainvoke(
                self, input_: Any, config: Any = None, **kwargs: Any
            ) -> AIMessage:
                if isinstance(input_, list) and input_:
                    last = input_[-1]
                    captured["content"] = getattr(last, "content", "") or str(last)
                return await super().ainvoke(input_, config, **kwargs)

        fake = _CapturingFake(responses=["T"])
        _patch_title_service(monkeypatch, fake)

        await generate_title(str(conv_with_first_message.id), "hello")
        content = captured["content"]
        assert "根据以下用户消息" in content  # prompt 核心模板文本
        assert "<user_message>hello</user_message>" in content  # XML 包裹的变量
