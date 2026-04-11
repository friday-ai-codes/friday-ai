"""Phase: variable_extractor 迁移测试 + 行为等价。"""
from __future__ import annotations
from typing import Any
import pytest
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from workflows.nodes.ai.variable_extractor import EXTRACTION_PROMPT_TEMPLATE
# 迁移前的 legacy 模板（用于 行为等价断言 — 必须字节级一致）
# 注：这是 .format 风格，真变量单花括号，JSON 示例内的 { } 被 {{ }} 转义
LEGACY_EXTRACTION_PROMPT_TEMPLATE = """请从以下文本中提取指定的变量信息。
需要提取的变量：
{variable_definitions}
文本内容：
---
{input_text}
---
{additional_prompt}
请严格按照以下 JSON 格式返回提取结果：
```json
{{
 "variables": {{
 "variableKey": "提取的值",
 ...
 }},
 "extraction_notes": {{
 "variableKey": "提取说明或未能提取的原因"
 }}
}}
```
注意：
1. 如果某个变量无法从文本中提取，请在 extraction_notes 中说明原因，variables 中不要包含该 key
2. 提取的值应该尽量保持原文中的表述
3. 确保返回的是有效的 JSON 格式"""
@pytest.mark.django_db(transaction=True)
class TestVariableExtractorMigration:
 @pytest.fixture(autouse=True)
 def _ensure_seed(self, db: Any) -> None:
 """每个测试开始前确保 AI_NODE_VARIABLE_EXTRACTOR seed 存在。"""
 if not Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 scope=PromptScope.SYSTEM,
 ).exists:
 prompt = Prompt.objects.create(
 slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 scope=PromptScope.SYSTEM,
 project=None,
 category="ai_node",
 title="AI 节点 - 变量提取",
 description="Phase test re-seed",
 is_builtin=True,
 )
 version = PromptVersion.objects.create(
 prompt=prompt,
 version=1,
 body=EXTRACTION_PROMPT_TEMPLATE,
 variables_schema={},
 change_note="test re-seed",
 )
 prompt.active_version = version
 prompt.save(update_fields=["active_version", "updated_at"])
 @pytest.mark.asyncio
 async def test_fallback_path_equivalent_to_legacy_format(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """ 行为等价：迁移后 fallback 路径 == 迁移前 .format 输出（字节级）。"""
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.variable_extractor.template")
 new_output = await render_prompt(
 PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 project_id=None,
 variables={
 "variable_definitions": "- foo (Foo): 描述",
 "input_text": "hello",
 "additional_prompt": "extra",
 },
 fallback=EXTRACTION_PROMPT_TEMPLATE,
 )
 legacy_output = LEGACY_EXTRACTION_PROMPT_TEMPLATE.format(
 variable_definitions="- foo (Foo): 描述",
 input_text="hello",
 additional_prompt="extra",
 )
 assert new_output == legacy_output, (
 "Byte drift: fallback path must match legacy .format output"
 )
 @pytest.mark.asyncio
 async def test_db_empty_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """DB 空路径：删除 seed 后走 fallback。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 await Prompt.objects.filter(
 slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 scope=PromptScope.SYSTEM,
 ).adelete
 result = await render_prompt(
 PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 project_id=None,
 variables={
 "variable_definitions": "- x (X): y",
 "input_text": "abc",
 "additional_prompt": "",
 },
 fallback=EXTRACTION_PROMPT_TEMPLATE,
 )
 assert "- x (X): y" in result
 assert "abc" in result
 @pytest.mark.asyncio
 async def test_db_hit_xml_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
 """DB 命中：变量被 _sanitize_variables XML tag 包裹。"""
 monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
 result = await render_prompt(
 PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 project_id=None,
 variables={
 "variable_definitions": "- v (V): d",
 "input_text": "text",
 "additional_prompt": "",
 },
 fallback=EXTRACTION_PROMPT_TEMPLATE,
 )
 assert "<variable_definitions>- v (V): d</variable_definitions>" in result
 assert "<input_text>text</input_text>" in result
 @pytest.mark.asyncio
 async def test_flag_disabled_returns_fallback(
 self,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", "ai_node.variable_extractor.template")
 result = await render_prompt(
 PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
 project_id=None,
 variables={
 "variable_definitions": "- f (F): d",
 "input_text": "t",
 "additional_prompt": "",
 },
 fallback=EXTRACTION_PROMPT_TEMPLATE,
 )
 assert "<variable_definitions>" not in result # 证明没走 DB 路径
 assert "- f (F): d" in result # 证明 fallback 替换成功
