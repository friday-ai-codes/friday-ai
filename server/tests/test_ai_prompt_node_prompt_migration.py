"""implementation / Pitfall #10 弥补：AIPromptNode 字节级 hash 守护。

作为第 5 个 `_prompt_migration.py` 测试文件完成 success criterion "4+1 字节级 hash
100% 通过"的最后一项覆盖（原 Pitfall #10 明确 AIPromptNode 无字节级 hash
覆盖，由本 plan 首次建立基线；work item 强化：expected hash 本次首建即锁定，
后续 plan 不得改动）。

- Test 1 test_rendered_system_and_user_prompt_byte_equal
  Jinja2/render_template 渲染后 system + user prompt 通过 ainvoke 字节级透传，
  验证 sha256 hash 匹配（首次建立 baseline）。
- Test 2 test_template_variables_injected_correctly
  `{{global.*}}` + `{{nodes.*.field}}` 两类模板变量都被正确替换。
- Test 3 test_injected_value_not_rerendered_by_langchain
  模板变量值中的 `{{evil}}` 字面量不被 LangChain 二次渲染（Pitfall #1 守护 /
  security mitigation-01）。
- Test 4 test_system_prompt_empty_only_human_message
  system_prompt 为空时 ainvoke 只收到 [HumanMessage]，不加 SystemMessage。

_CapturingFake 本地定义（PATTERNS §Pattern 8 §8.1），与现有 4 个
`_prompt_migration.py` 一致；其他 fixture 统一引用 checkpoint-03 conftest。
"""
from __future__ import annotations

import hashlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from services.provider_config import (
    ProviderType,
    ResolvedProviderConfig,
)
from tests.helpers.fake_chat_model import FakeChatModel


@pytest.fixture
def capturing_prompt_fake(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """捕获 AIPromptNode._call_llm 传给 ainvoke 的 system/human content。

    分歧 D / Pitfall #5：双 patch `workflows.nodes.ai.prompt.build_chat_model`
    + `agents.llm_factory.build_chat_model`；aresolve_or_error stub 返回默认
    ANTHROPIC ResolvedProviderConfig。
    """
    captured: dict[str, Any] = {}

    class _CapturingFake(FakeChatModel):
        async def ainvoke(
            self, input_: Any, config: Any = None, **kwargs: Any
        ) -> Any:
            if isinstance(input_, list):
                captured["all_messages"] = input_
                captured["system_content"] = next(
                    (
                        str(getattr(m, "content", ""))
                        for m in input_
                        if isinstance(m, SystemMessage)
                    ),
                    "",
                )
                captured["human_content"] = next(
                    (
                        str(getattr(m, "content", ""))
                        for m in input_
                        if isinstance(m, HumanMessage)
                    ),
                    "",
                )
            return await super().ainvoke(input_, config, **kwargs)

    fake = _CapturingFake(responses=["响应"])

    # 双 patch seam（分歧 D）
    monkeypatch.setattr(
        "workflows.nodes.ai.prompt.build_chat_model",
        lambda *a, **kw: fake,
        raising=False,
    )
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *a, **kw: fake,
    )

    # aresolve_or_error stub → 默认 ANTHROPIC ResolvedProviderConfig
    async def _stub(node_config: Any = None, conversation: Any = None, project: Any = None) -> Any:
        return ResolvedProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-fake",
            base_url="https://api.anthropic.com",
            source="system",
        )

    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        _stub,
    )

    return captured


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rendered_system_and_user_prompt_byte_equal(
    capturing_prompt_fake: dict[str, Any],
    make_minimal_context: Any,
) -> None:
    """Test 1：Jinja2/render_template 渲染 system+user 后通过 ainvoke 字节级透传。

    work item 强化：固定 execution_id + node_id 让 render_template 变量渲染稳定；
    sha256 hash 本 plan 首次建立 baseline，后续 plan 不得修改。
    """
    from workflows.nodes.ai.prompt import AIPromptNode

    ctx = make_minimal_context(
        execution_id="test-exec-id-12345",
        node_id="ai-prompt-n1",
        node_config={
            "system_prompt": "你是{{global.topic}}领域专家",
            "user_prompt": "请分析这个{{nodes.upstream.analysis}}问题",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.7,
            "max_tokens": 4096,
            "output_format": "text",
        },
        workflow_context={"global_params": {"topic": "机器学习"}},
        previous_outputs={"upstream": {"analysis": "过拟合"}},
    )
    node = AIPromptNode()
    result = await node.execute(ctx)
    assert result.status == "completed"

    expected_system = "你是机器学习领域专家"
    expected_user = "请分析这个过拟合问题"

    assert capturing_prompt_fake["system_content"] == expected_system
    assert capturing_prompt_fake["human_content"] == expected_user

    # sha256 组合 hash 守护（首次建立 baseline；后续 plan 不得改动）
    combined_expected = expected_system + expected_user
    combined_actual = (
        capturing_prompt_fake["system_content"]
        + capturing_prompt_fake["human_content"]
    )
    expected_hash = hashlib.sha256(
        combined_expected.encode("utf-8")
    ).hexdigest()
    actual_hash = hashlib.sha256(combined_actual.encode("utf-8")).hexdigest()
    assert actual_hash == expected_hash, (
        "Jinja2/render_template 渲染后字节级漂移（work item / work item 强化：hash 首建即锁）"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_template_variables_injected_correctly(
    capturing_prompt_fake: dict[str, Any],
    make_minimal_context: Any,
) -> None:
    """Test 2：`{{global.*}}` + `{{nodes.*.field}}` 两类模板变量都被正确替换。"""
    from workflows.nodes.ai.prompt import AIPromptNode

    ctx = make_minimal_context(
        node_config={
            "system_prompt": "角色：{{global.role}}",
            "user_prompt": "基于 {{global.context}} 分析 {{nodes.prev.result}}",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.5,
            "max_tokens": 2048,
            "output_format": "text",
        },
        workflow_context={
            "global_params": {"role": "资深顾问", "context": "需求文档"}
        },
        previous_outputs={"prev": {"result": "存在多个边界 case"}},
    )
    node = AIPromptNode()
    result = await node.execute(ctx)
    assert result.status == "completed"

    assert capturing_prompt_fake["system_content"] == "角色：资深顾问"
    assert (
        capturing_prompt_fake["human_content"]
        == "基于 需求文档 分析 存在多个边界 case"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_injected_value_not_rerendered_by_langchain(
    capturing_prompt_fake: dict[str, Any],
    make_minimal_context: Any,
) -> None:
    """Test 3 / Pitfall #1 / security mitigation-01 守护：模板变量值内的 `{{evil}}` 不被 LangChain
    二次 Jinja2 渲染。

    `{{evil}}` 字符写入 `{{global.user_input}}` 的值；render_template 第一次渲染
    后 human_content 含字面 `{{evil}}`；ainvoke 接收后 LangChain 不得再做模板
    替换（纯字符串 HumanMessage 路径应字节级透传）。
    """
    from workflows.nodes.ai.prompt import AIPromptNode

    evil_value = "{{evil}} 以及 {{another_injection}}"
    ctx = make_minimal_context(
        node_config={
            "system_prompt": "请处理：",
            "user_prompt": "{{global.user_input}}",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.3,
            "max_tokens": 1024,
            "output_format": "text",
        },
        workflow_context={"global_params": {"user_input": evil_value}},
    )
    node = AIPromptNode()
    result = await node.execute(ctx)
    assert result.status == "completed"

    # render_template 首次替换后 human_content 应含字面 {{evil}}
    human_content = capturing_prompt_fake["human_content"]
    assert human_content == evil_value, (
        f"render_template 渲染后应字节级等于 evil_value；实际：{human_content!r}"
    )
    # 断言 LangChain ainvoke 未做第二次 {{evil}} → "" 替换（关键守护）
    assert "{{evil}}" in human_content
    assert "{{another_injection}}" in human_content


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_system_prompt_empty_only_human_message(
    capturing_prompt_fake: dict[str, Any],
    make_minimal_context: Any,
) -> None:
    """Test 4：system_prompt 为空时 ainvoke 只收 [HumanMessage]，不加 SystemMessage。

    这与旧 OpenAI 兼容路径 `if system_prompt: messages.append({"role":"system",...})`
    的行为对齐（避免空 system 污染模型上下文）。
    """
    from workflows.nodes.ai.prompt import AIPromptNode

    ctx = make_minimal_context(
        node_config={
            "system_prompt": "",  # 关键：空 system_prompt
            "user_prompt": "只有用户消息",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.7,
            "max_tokens": 1024,
            "output_format": "text",
        },
    )
    node = AIPromptNode()
    result = await node.execute(ctx)
    assert result.status == "completed"

    all_messages = capturing_prompt_fake.get("all_messages") or []
    # 仅 1 条 message：HumanMessage
    assert len(all_messages) == 1
    assert isinstance(all_messages[0], HumanMessage)
    assert all_messages[0].content == "只有用户消息"
    assert capturing_prompt_fake["system_content"] == ""
    assert capturing_prompt_fake["human_content"] == "只有用户消息"
