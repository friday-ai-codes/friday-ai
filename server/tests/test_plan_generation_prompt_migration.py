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
 _PLAN_GENERATION_BASE_PROMPT,
 TECHNICAL_PLAN_JSON_SCHEMA,
 AIPlanGenerationNode,
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
 async def test_render_prompt_db_hit_xml_wraps_schema_json(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """Phase 行为参考：render_prompt DB 命中路径会 XML 包裹变量 & 触发截断。
 本测试记录 Phase services.render_prompt 的行为。Phase 的
 plan_generation.execute **不**走此路径（ retreat），而是手工读取
 get_active_prompt + str.replace，见
 test_execute_schema_json_not_truncated_by_retreat_path。
 """
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
 async def test_execute_schema_json_not_truncated_by_retreat_path(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """ retreat（ regression fix）：schema_json 4KB+ 在 execute 预渲染后
 必须保留完整内容，不被 Phase _sanitize_variables 的 1024 字符截断。
 Phase code review 发现：schema_json 实测 4432 字符，走 render_prompt
 会被截到 1024 → 切在中间产生残缺 JSON → LLM 看到 garbage。
 修复策略：plan_generation.execute 改为手工 get_active_prompt + str.replace，
 绕过 Jinja2 sandbox + 清洗流程（符合 work-item 的 retreat 机制）。
 """
 from prompts.services import get_active_prompt
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
 # 前置假设：schema_json 必须 > 1024 字符才能真正触发 regression
 assert len(schema_json) > 1024, (
 f"TECHNICAL_PLAN_JSON_SCHEMA 必须 > 1024 字符才能验证 修复 "
 f"(实测 {len(schema_json)})"
 )
 # 模拟 execute 的 retreat 逻辑
 version = await get_active_prompt(
 PromptSlugs.AI_NODE_PLAN_GENERATION, project_id=None
 )
 assert version is not None, "fixture 应已种入 seed"
 body_template = version.body
 rendered = body_template.replace("{{schema_json}}", schema_json)
 # 回归断言：
 # 1. 完整 schema_json 必须出现在 rendered 里（未被截到 1024）
 assert schema_json in rendered, (
 " regression: schema_json 被截断或未完整替换"
 )
 # 2. 没有 XML tag 包裹（ retreat 绕过了 _sanitize_variables）
 assert "<schema_json>" not in rendered, (
 " regression: 预渲染不应使用 XML tag 包裹路径"
 )
 # 3. rendered 长度应大致 = base_prompt 长度 - 占位符长度 + schema_json 长度
 expected_len = len(body_template) - len("{{schema_json}}") + len(schema_json)
 assert len(rendered) == expected_len, (
 f"长度不匹配: expected {expected_len}, got {len(rendered)}"
 )
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
