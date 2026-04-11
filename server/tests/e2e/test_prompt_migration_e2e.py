"""Phase 端到端：title_service 迁移后 LLM payload 字节级等价验证。
目标：证明真实 generate_title 调用链下（fire-and-forget + async），
anthropic SDK 收到的 messages payload 与迁移前行为等价（DB 空 fallback 路径）。
"""
from __future__ import annotations
from typing import Any
import pytest
from chat.models import Conversation, Message
from chat.title_service import TITLE_PROMPT, generate_title
from projects.models import Project
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
@pytest.mark.django_db(transaction=True)
class TestPromptMigrationE2E:
 """title_service 端到端最简链路：generate_title → render_prompt → anthropic mock."""
 @pytest.fixture(autouse=True)
 def _reseed(self, db: Any) -> None:
 """确保 AUX_TITLE_GENERATION seed 存在。"""
 if not Prompt.objects.filter(
 slug=PromptSlugs.AUX_TITLE_GENERATION,
 scope=PromptScope.SYSTEM,
 ).exists:
 prompt = Prompt.objects.create(
 slug=PromptSlugs.AUX_TITLE_GENERATION,
 scope=PromptScope.SYSTEM,
 project=None,
 category="aux_model",
 title="标题生成",
 description="Phase e2e re-seed",
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
 project = Project.objects.create(
 name="e2e-title-project",
 feishu_project_key="e2e-title-key",
 )
 conv = Conversation.objects.create(project=project, title="")
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
 ).adelete
 captured: dict[str, Any] = {}
 class _Block:
 def __init__(self, text: str) -> None:
 self.text = text
 class _Response:
 def __init__(self) -> None:
 self.content = [_Block("端到端标题")]
 class _Messages:
 async def create(self, **kwargs: Any) -> _Response:
 captured["content"] = kwargs["messages"][0]["content"]
 return _Response
 class _MockClient:
 def __init__(self, *args: Any, **kwargs: Any) -> None:
 self.messages = _Messages
 import anthropic
 monkeypatch.setattr(anthropic, "AsyncAnthropic", _MockClient)
 from chat import title_service as ts
 async def _fake_setting(key: Any) -> str | None:
 key_str = str(key).lower
 if "api_key" in key_str:
 return "fake-key-e2e"
 if "model" in key_str:
 return "claude-3-haiku"
 return None
 monkeypatch.setattr(ts, "aget_setting_value", _fake_setting)
 # 触发迁移后调用栈
 result = await generate_title(str(conv_with_first_message.id), "端到端测试消息")
 assert result == "端到端标题"
 # 字节级等价断言
 expected = TITLE_PROMPT.replace("{{user_message}}", "端到端测试消息")
 assert captured["content"] == expected, (
 f"E2E payload mismatch:\n"
 f" expected: {expected!r}\n"
 f" got: {captured['content']!r}"
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
 class _Block:
 def __init__(self, text: str) -> None:
 self.text = text
 class _Response:
 def __init__(self) -> None:
 self.content = [_Block("T")]
 class _Messages:
 async def create(self, **kwargs: Any) -> _Response:
 captured["content"] = kwargs["messages"][0]["content"]
 return _Response
 class _MockClient:
 def __init__(self, *args: Any, **kwargs: Any) -> None:
 self.messages = _Messages
 import anthropic
 monkeypatch.setattr(anthropic, "AsyncAnthropic", _MockClient)
 from chat import title_service as ts
 async def _fake_setting(key: Any) -> str | None:
 key_str = str(key).lower
 if "api_key" in key_str:
 return "fake-key"
 return None
 monkeypatch.setattr(ts, "aget_setting_value", _fake_setting)
 await generate_title(str(conv_with_first_message.id), "hello")
 content = captured["content"]
 assert "根据以下用户消息" in content # prompt 核心模板文本
 assert "<user_message>hello</user_message>" in content # XML 包裹的变量
