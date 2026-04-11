"""Phase: code_review 循环外预渲染测试。"""
from __future__ import annotations
from typing import Any
from unittest.mock import MagicMock
import pytest
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from workflows.nodes.ai.code_review import REVIEW_SYSTEM_PROMPT
@pytest.mark.django_db(transaction=True)
class TestCodeReviewMigration:
 @pytest.fixture(autouse=True)
 def _ensure_seed(self, db: Any) -> None:
 """每个测试开始前确保 AI_NODE_CODE_REVIEW seed 存在。"""
 if not Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_CODE_REVIEW,
 scope=PromptScope.SYSTEM,
 ).exists:
 prompt = Prompt.objects.create(
 slug=PromptSlugs.AI_NODE_CODE_REVIEW,
 scope=PromptScope.SYSTEM,
 project=None,
 category="ai_node",
 title="AI 节点 - 代码审查",
 description="Phase test re-seed",
 is_builtin=True,
 )
 version = PromptVersion.objects.create(
 prompt=prompt,
 version=1,
 body=REVIEW_SYSTEM_PROMPT,
 variables_schema={},
 change_note="test re-seed",
 )
 prompt.active_version = version
 prompt.save(update_fields=["active_version", "updated_at"])
 @pytest.mark.asyncio
 async def test_db_hit_returns_db_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """DB 命中：render_prompt 返回 DB body（由 seed migration 提供）。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 result = await render_prompt(
 PromptSlugs.AI_NODE_CODE_REVIEW,
 project_id=None,
 variables={},
 fallback=REVIEW_SYSTEM_PROMPT,
 )
 # seed 的 DB body 应与常量字节级相等（由 Task 2 的 hash contract 保证）
 assert result == REVIEW_SYSTEM_PROMPT
 @pytest.mark.asyncio
 async def test_db_empty_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """DB 空：删除 seed 后走 fallback 返回常量。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 await Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_CODE_REVIEW,
 scope=PromptScope.SYSTEM,
 ).adelete
 result = await render_prompt(
 PromptSlugs.AI_NODE_CODE_REVIEW,
 project_id=None,
 variables={},
 fallback=REVIEW_SYSTEM_PROMPT,
 )
 assert result == REVIEW_SYSTEM_PROMPT
 @pytest.mark.asyncio
 async def test_flag_disabled_returns_fallback(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """flag 禁用：即使 DB 有记录也走 fallback。"""
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.code_review.system")
 result = await render_prompt(
 PromptSlugs.AI_NODE_CODE_REVIEW,
 project_id=None,
 variables={},
 fallback=REVIEW_SYSTEM_PROMPT,
 )
 assert result == REVIEW_SYSTEM_PROMPT
 def test_hook_still_returns_constant(self) -> None:
 """get_system_prompt hook 保持同步签名返回常量（base class 契约不变）。"""
 from workflows.nodes.ai.code_review import AICodeReviewNode
 node = AICodeReviewNode
 ctx = MagicMock
 assert node.get_system_prompt(ctx) == REVIEW_SYSTEM_PROMPT
