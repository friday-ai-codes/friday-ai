"""Phase: title_service 迁移三态回退测试 + T- 注入防护。"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock
import pytest
from chat.models import Conversation, Message
from chat.title_service import TITLE_PROMPT, generate_title
from projects.models import Project
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope
@pytest.fixture
def mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
 """拦截 anthropic.AsyncAnthropic 并记录最后一次 messages.create 的 content。"""
 captured: dict[str, Any] = {}
 class _Block:
 def __init__(self, text: str) -> None:
 self.text = text
 class _Response:
 def __init__(self) -> None:
 self.content = [_Block("标题文本")]
 class _Messages:
 async def create(self, **kwargs: Any) -> _Response:
 captured["last_content"] = kwargs["messages"][0]["content"]
 return _Response
 class _Client:
 def __init__(self, *args: Any, **kwargs: Any) -> None:
 self.messages = _Messages
 import anthropic
 monkeypatch.setattr(anthropic, "AsyncAnthropic", _Client)
 # 注入 api_key 与 model
 from chat import title_service as ts_module
 async def _fake_setting(key: Any) -> str | None:
 # 任意 key 都返回固定测试值（SettingKeys 是小写字符串）
 key_str = str(key).lower
 if "api_key" in key_str:
 return "fake-key"
 if "base_url" in key_str:
 return None
 if "model" in key_str:
 return "claude-3-haiku"
 return None
 monkeypatch.setattr(ts_module, "aget_setting_value", _fake_setting)
 return captured
@pytest.mark.django_db(transaction=True)
class TestTitleServiceMigration:
 """title_service 三态 + 注入防护。"""
 @pytest.fixture(autouse=True)
 def _ensure_title_seed(self, db: Any) -> None:
 """每个测试开始前确保 AUX_TITLE_GENERATION seed 存在（避免前测 delete 污染）。"""
 from prompts.models import PromptVersion
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
 description="Phase test re-seed",
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
 project = Project.objects.create(
 name="title-test-project",
 feishu_project_key="title-test-key",
 )
 conv = Conversation.objects.create(project=project, title="")
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
 mock_anthropic: dict[str, Any],
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """DB 命中：LLM 收到的 prompt 来自 DB body（含 XML tag 包裹变量）。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 # pytest-django 已通过 0002 migration seed AUX_TITLE_GENERATION —— 直接调用
 await generate_title(str(conversation.id), "帮我实现登录功能")
 content = mock_anthropic["last_content"]
 # DB 路径变量被 XML tag 包裹（_sanitize_variables 输出）
 assert "<user_message>" in content
 assert "</user_message>" in content
 assert "帮我实现登录功能" in content
 @pytest.mark.asyncio
 async def test_db_empty_returns_fallback(
 self,
 conversation: Conversation,
 mock_anthropic: dict[str, Any],
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """DB 空：走 fallback 路径，与 .replace('{{user_message}}', ...) 字节级等价。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 # 删掉 seed 数据强制走 DB 空路径
 await Prompt.objects.filter(
 slug=PromptSlugs.AUX_TITLE_GENERATION,
 scope=PromptScope.SYSTEM,
 ).adelete
 await generate_title(str(conversation.id), "hello")
 content = mock_anthropic["last_content"]
 expected = TITLE_PROMPT.replace("{{user_message}}", "hello")
 assert content == expected
 @pytest.mark.asyncio
 async def test_flag_disabled_returns_fallback(
 self,
 conversation: Conversation,
 mock_anthropic: dict[str, Any],
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """PROMPT_CENTER_DISABLED_KEYS 命中：即使 DB 有记录也走 fallback。"""
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "aux.title_generation")
 # DB 仍有 seed 记录（不删）
 await generate_title(str(conversation.id), "flag test")
 content = mock_anthropic["last_content"]
 expected = TITLE_PROMPT.replace("{{user_message}}", "flag test")
 assert content == expected
 assert "<user_message>" not in content # 证明没走 DB 命中路径
 @pytest.mark.asyncio
 async def test_title_prompt_injection_sanitized(
 self,
 conversation: Conversation,
 mock_anthropic: dict[str, Any],
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """T-: 变量值中的 {{ }} 应被 HTML entity 替换，不二次渲染。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 # 确保 DB 有 seed 记录（走清洗路径）
 prompt = await Prompt.objects.filter(
 slug=PromptSlugs.AUX_TITLE_GENERATION,
 scope=PromptScope.SYSTEM,
 ).afirst
 assert prompt is not None, "seed should have provided AUX_TITLE_GENERATION"
 await generate_title(str(conversation.id), "{{evil}}")
 content = mock_anthropic["last_content"]
 assert "{{evil}}" not in content # 裸 {{evil}} 不得出现
 assert "&#123;&#123;evil&#125;&#125;" in content # 被 HTML entity 替换
