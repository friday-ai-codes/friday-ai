"""Phase: plan_generation execute 预渲染 + hook 双路径。"""
from __future__ import annotations
import json
from typing import Any
from unittest.mock import MagicMock
import pytest
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from workflows.nodes.ai.plan_generation import (
 AIPlanGenerationNode,
 TECHNICAL_PLAN_JSON_SCHEMA,
 _PLAN_GENERATION_BASE_PROMPT,
)
@pytest.mark.django_db(transaction=True)
class TestPlanGenerationMigration:
 @pytest.fixture(autouse=True)
 def _ensure_seed(self, db: Any) -> None:
 """每个测试开始前确保 AI_NODE_PLAN_GENERATION seed 存在。"""
 if not Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
 scope=PromptScope.SYSTEM,
 ).exists:
 prompt = Prompt.objects.create(
 slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
 scope=PromptScope.SYSTEM,
 project=None,
 category="ai_node",
 title="AI 节点 - 方案生成",
 description="Phase test re-seed",
 is_builtin=True,
 )
 version = PromptVersion.objects.create(
 prompt=prompt,
 version=1,
 body=_PLAN_GENERATION_BASE_PROMPT,
 variables_schema={},
 change_note="test re-seed",
 )
 prompt.active_version = version
 prompt.save(update_fields=["active_version", "updated_at"])
 @pytest.mark.asyncio
 async def test_db_hit_xml_wraps_schema_json(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """DB 命中路径：schema_json 变量被 XML tag 包裹（ 接受副作用）。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 result = await render_prompt(
 PromptSlugs.AI_NODE_PLAN_GENERATION,
 project_id=None,
 variables={"schema_json": "MY_SCHEMA_PLACEHOLDER"},
 fallback=_PLAN_GENERATION_BASE_PROMPT,
 )
 # DB 命中路径变量被 _sanitize_variables XML tag 包裹
 assert "<schema_json>MY_SCHEMA_PLACEHOLDER</schema_json>" in result
 @pytest.mark.asyncio
 async def test_db_empty_fallback_byte_equivalent(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """DB 空路径：走 _render_fallback regex 替换 — 与直接 str.replace 字节级等价。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 await Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_PLAN_GENERATION,
 scope=PromptScope.SYSTEM,
 ).adelete
 schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
 result = await render_prompt(
 PromptSlugs.AI_NODE_PLAN_GENERATION,
 project_id=None,
 variables={"schema_json": schema_json},
 fallback=_PLAN_GENERATION_BASE_PROMPT,
 )
 expected = _PLAN_GENERATION_BASE_PROMPT.replace("{{schema_json}}", schema_json)
 assert result == expected
 @pytest.mark.asyncio
 async def test_flag_disabled_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """flag 禁用：走 fallback 路径。"""
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.plan_generation.system")
 schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
 result = await render_prompt(
 PromptSlugs.AI_NODE_PLAN_GENERATION,
 project_id=None,
 variables={"schema_json": schema_json},
 fallback=_PLAN_GENERATION_BASE_PROMPT,
 )
 assert "<schema_json>" not in result # 证明未走 DB 清洗
 assert schema_json in result # 证明 fallback 替换成功
 def test_hook_uses_precomputed_when_set(self) -> None:
 """get_system_prompt 在 _precomputed_base_prompt 被预填时优先返回它。"""
 node = AIPlanGenerationNode
 node._precomputed_base_prompt = "PRECOMPUTED_SENTINEL"
 ctx = MagicMock
 ctx.node_config = {}
 result = node.get_system_prompt(ctx)
 assert result == "PRECOMPUTED_SENTINEL"
 def test_hook_falls_back_to_f_string_when_not_set(self) -> None:
 """get_system_prompt 在 _precomputed_base_prompt 为 None 时走降级路径(与迁移前字节级等价)。"""
 node = AIPlanGenerationNode
 # 默认 __init__ 里已设为 None
 node._precomputed_base_prompt = None
 ctx = MagicMock
 ctx.node_config = {}
 result = node.get_system_prompt(ctx)
 schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
 expected = _PLAN_GENERATION_BASE_PROMPT.replace("{{schema_json}}", schema_json)
 assert result == expected
