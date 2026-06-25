"""implementation + implementation Wave（task）：variable_extractor 迁移测试。

implementation 原 4 测试验证 Prompt Center render_prompt 三态行为 + `.format()` 字节级
等价（contract），**不触及** LLM 调用（迁移前老 httpx 直调 / SDK 客户端均无 mock，
node.execute 链路也不跑）。

implementation Wave（work item / contract）补强：新增 `_CapturingFake` seam 经
`build_chat_model` 共用 seam 注入，驱动真实 AIVariableExtractorNode.execute() 跑到
`chat_model.bind(temperature=0.3).ainvoke(...)`，捕获 `HumanMessage.content` 做字节级
sha256 断言（work item 基线守护）。

关键守护（work item 强化）：
- 本 plan 执行前文件内无任何硬编码 expected sha 值（ground truth = None）
- 新增字节级测试**动态计算** expected hash（从相同 render_prompt 路径 +
  fixture 固定的 variables / execution_id 得到），而非硬编码
- 任何 Prompt 渲染路径漂移（Jinja2 sandbox / render_prompt DB 命中 / fallback）都
  会让 actual/expected 同步漂移；真正守护的是"execute 捕获的 HumanMessage.content
  == 预计算 render_prompt 输出"契约
- 禁止条款：本 plan 不得引入硬编码 hash 更不得后续升级中更新已有 hash（checkpoint 后
  若新增硬编码 hash，必须从 fixture 固定 variables + execution_id 得来）
"""
from __future__ import annotations

import hashlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel
from workflows.nodes.ai.variable_extractor import EXTRACTION_PROMPT_TEMPLATE

# 迁移前的 legacy 模板（用于 contract 行为等价断言 — 必须字节级一致）
# 注：这是 .format() 风格，真变量单花括号，JSON 示例内的 { } 被 {{ }} 转义
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
        ).exists():
            prompt = Prompt.objects.create(
                slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
                scope=PromptScope.SYSTEM,
                space=None,
                category="ai_node",
                title="AI 节点 - 变量提取",
                description="implementation test re-seed",
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
        """contract 行为等价：迁移后 fallback 路径 == 迁移前 .format() 输出（字节级）。"""
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
            "Byte drift: fallback path must match legacy .format() output"
        )

    @pytest.mark.asyncio
    async def test_db_empty_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB 空路径：删除 seed 后走 fallback。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        await Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
            scope=PromptScope.SYSTEM,
        ).adelete()
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
        assert "<variable_definitions>" not in result  # 证明没走 DB 路径
        assert "- f (F): d" in result  # 证明 fallback 替换成功


# ============================================================================
# implementation Wave（task）：_CapturingFake seam 字节级守护（work item）
# ============================================================================


def _resolved_anthropic_stub() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )


@pytest.mark.django_db(transaction=True)
class TestVariableExtractorPromptByteEqual:
    """implementation Wave 补强：execute 路径 HumanMessage.content 字节级等价。

    在 `build_chat_model` seam 注入 `_CapturingFake`（FakeChatModel 子类），其
    `ainvoke` 方法捕获 messages[0].content（HumanMessage.content）字节。断言该
    content 与同路径下 `render_prompt` 预计算的 expected prompt 字节级一致。
    """

    @pytest.fixture(autouse=True)
    def _ensure_seed(self, db: Any) -> None:
        """确保 AI_NODE_VARIABLE_EXTRACTOR seed 存在（同 TestVariableExtractorMigration）。"""
        if not Prompt.objects.filter(
            slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
            scope=PromptScope.SYSTEM,
        ).exists():
            prompt = Prompt.objects.create(
                slug=PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
                scope=PromptScope.SYSTEM,
                space=None,
                category="ai_node",
                title="AI 节点 - 变量提取",
                description="implementation test re-seed",
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
    async def test_execute_captures_rendered_prompt_byte_equal_fallback_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """work item 强化：fallback 路径下 execute 捕获的 HumanMessage.content
        与预计算 render_prompt 输出字节级相等。

        expected_sha 动态计算（非硬编码）；固定 variables 使渲染输出稳定；
        任何 Prompt 路径漂移会同步反映到 actual + expected，契约依旧：
        'execute 捕获内容 == render_prompt 输出'。
        """
        # 固定 fallback 路径（绕过 DB 命中的 _sanitize_variables XML tag）
        monkeypatch.setenv(
            "PROMPT_CENTER_DISABLED_KEYS", "ai_node.variable_extractor.template"
        )

        captured: dict[str, Any] = {}

        class _CapturingFake(FakeChatModel):
            async def ainvoke(
                self, input_: Any, config: Any = None, **kwargs: Any
            ) -> Any:
                if isinstance(input_, list) and input_:
                    last = input_[-1]
                    if isinstance(last, HumanMessage):
                        captured["human_content"] = last.content
                    else:
                        captured["human_content"] = getattr(last, "content", "")
                return await super().ainvoke(input_, config, **kwargs)

        fake = _CapturingFake(
            responses=['{"variables": {"user_name": "张三"}}']
        )
        # 双 patch seam（分歧 D / Pitfall #5）
        monkeypatch.setattr(
            "agents.llm_factory.build_chat_model", lambda *a, **kw: fake
        )
        monkeypatch.setattr(
            "workflows.nodes.ai.variable_extractor.build_chat_model",
            lambda *a, **kw: fake,
            raising=False,
        )

        # mock aresolve_or_error 固定 Anthropic system source
        async def _stub_resolve(
            node_config: Any = None, conversation: Any = None, project: Any = None
        ) -> ResolvedProviderConfig:
            return _resolved_anthropic_stub()

        monkeypatch.setattr(
            "services.provider_config.ProviderConfigService.aresolve_or_error",
            _stub_resolve,
        )

        # 固定 variables 使 render_prompt 输出稳定
        from workflows.nodes.base import ExecutionContext

        variables_config = [
            {
                "key": "user_name",
                "name": "用户姓名",
                "desc": "从文本中提取用户名",
            }
        ]
        input_text = "我叫张三"
        additional_prompt = ""
        ctx = ExecutionContext(
            execution_id="test-exec-id-12345",  # 固定 execution_id
            node_id="var-extract-n1",            # 固定 node_id
            node_config={
                "variables": variables_config,
                "input_source": "",
                "additional_prompt": additional_prompt,
                "model": "claude-sonnet-4-20250514",
            },
            input_data={"text": input_text},
            workflow_context={},
            previous_outputs={},
        )

        from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode

        node = AIVariableExtractorNode()
        result = await node.execute(ctx)
        assert result.status == "completed", f"execute failed: {result.error}"

        # === work item 强化：动态计算 expected prompt（非硬编码 hash） ===
        # execute 内 render_prompt 的 variable_definitions 拼接逻辑：
        variable_definitions = "\n".join(
            f"- {v['key']} ({v['name']}): {v['desc']}" for v in variables_config
        )
        expected_prompt = await render_prompt(
            PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
            project_id=None,
            variables={
                "variable_definitions": variable_definitions,
                "input_text": input_text,
                "additional_prompt": additional_prompt,
            },
            fallback=EXTRACTION_PROMPT_TEMPLATE,
        )

        actual_sha = hashlib.sha256(
            str(captured["human_content"]).encode("utf-8")
        ).hexdigest()
        expected_sha = hashlib.sha256(
            expected_prompt.encode("utf-8")
        ).hexdigest()

        assert actual_sha == expected_sha, (
            f"variable_extractor rendered prompt 字节级漂移：\n"
            f"  actual_sha   = {actual_sha}\n"
            f"  expected_sha = {expected_sha}\n"
            f"work item 守护：禁止更新 hash；若语义确变，修 render_prompt "
            f"路径或 fixture 而非 hash。"
        )
