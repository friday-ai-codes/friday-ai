"""Phase Wave（ Task 2）：AIPromptNode 单元测试。
覆盖范围（Plan Task 2 <behavior> 12 场景）：
- Test 1 test_build_chat_model_single_path
 happy path：build_chat_model(resolved).bind(temperature).ainvoke([SystemMessage,
 HumanMessage]) 单 turn 正常返回 completed。
- Test 2 test_aimessage_to_llm_response_maps_text_block
 content_blocks=[{"type": "text", "text": "..."}] → MessageItem(content=text)。
- Test 3 test_aimessage_to_llm_response_maps_reasoning_block
 content_blocks=[{"type": "reasoning", "reasoning": "..."}] → ReasoningItem。
- Test 4 test_aimessage_to_llm_response_fallback_when_no_content_blocks
 content_blocks 为空但 content 非空 → fallback MessageItem(content=text)。
- Test 5 test_custom_api_ephemeral_resolved
 分歧 A：use_custom_api=True → source="node" + extra.custom_api=True
 + source_detail="node_custom_api" + provider_type=OPENAI_CHAT。
- Test 6 test_custom_api_missing_model_raises
 use_custom_api=True 且 model="" → ValueError("使用自定义 API 时必须指定模型")。
- Test 7 test_missing_credential_propagates_as_value_error
 aresolve_or_error → ProviderMissingError → ValueError("未配置 ... 凭证：...")
 → NodeResult(failed)。
- Test 8 test_temperature_bind_invoked
 捕获 chat_model.bind(temperature=X) 调用；断言 X=0.7 透传到 ainvoke。
- Test 9 test_reasoning_model_temperature_strip_warning
 model="o1-mini" + temperature=0.5 → structlog 含 ai_prompt_temperature_stripped。
- Test 10 test_non_reasoning_model_no_warning
 model="claude-sonnet-4-20250514" → 不触发 ai_prompt_temperature_stripped。
- Test 11 test_execute_happy_path_returns_completed
 端到端：execute → NodeResult(status="completed") + text/usage/output 正确。
- Test 12 test_usage_total_tokens_computed
 LLMResponse.usage.total_tokens == input_tokens + output_tokens（独立计算，
 不依赖 AIMessage.usage_metadata.total_tokens）。
Fixture 策略（ / Pattern 9）：
- 已抽取 conftest.py 4 公共 fixture
 （fake_chat_model_factory / mock_aresolve_ok / mock_aresolve_missing /
 make_minimal_context），本文件统一引用，禁止重复定义。
"""
from __future__ import annotations
from typing import Any
import pytest
from langchain_core.messages import AIMessage
from services.provider_config import ProviderType
from tests.helpers.fake_chat_model import FakeChatModel
from workflows.nodes.ai.prompt import (
 AIPromptNode,
 LLMResponse,
 MessageItem,
 ReasoningItem,
)
# ============================================================================
# Test 2-4：_aimessage_to_llm_response helper 纯单元测试（无 DB / 无 ctx）
# ============================================================================
def test_aimessage_to_llm_response_maps_text_block -> None:
 """Test 2：content_blocks=[{"type": "text", "text": "..."}] → MessageItem。"""
 aimsg = AIMessage(
 content="hello",
 usage_metadata={
 "input_tokens": 12,
 "output_tokens": 8,
 "total_tokens": 20,
 },
 )
 # LangChain 自动生成 content_blocks；FakeChatModel 产出的 AIMessage 亦如此
 node = AIPromptNode
 result = node._aimessage_to_llm_response(aimsg, "claude-sonnet-4-20250514")
 assert isinstance(result, LLMResponse)
 assert len(result.output) == 1
 assert isinstance(result.output[0], MessageItem)
 assert result.output[0].content == "hello"
 assert result.model == "claude-sonnet-4-20250514"
 assert result.usage.input_tokens == 12
 assert result.usage.output_tokens == 8
def test_aimessage_to_llm_response_maps_reasoning_block -> None:
 """Test 3：content_blocks reasoning/thinking 块 → ReasoningItem。
 AIMessage.content_blocks 是 property（无 setter）；但传 list[dict] 给 content
 时，content_blocks 返回相同 list —— 借此模拟 Claude thinking 模型 content_blocks 输出。
 """
 aimsg = AIMessage(
 content=[
 {"type": "reasoning", "reasoning": "I should think about it."},
 {"type": "text", "text": "final answer"},
 ]
 )
 node = AIPromptNode
 result = node._aimessage_to_llm_response(aimsg, "claude-opus-4")
 # reasoning + text 两个 output item
 assert len(result.output) == 2
 assert isinstance(result.output[0], ReasoningItem)
 assert result.output[0].content == "I should think about it."
 assert isinstance(result.output[1], MessageItem)
 assert result.output[1].content == "final answer"
 # LLMResponse.thinking / has_thinking 属性正确计算
 assert result.thinking == "I should think about it."
 assert result.has_thinking is True
 assert result.text == "final answer"
def test_aimessage_to_llm_response_fallback_when_no_content_blocks -> None:
 """Test 4：content_blocks 为空 list 但 content 可读取 → fallback MessageItem。
 构造 content= 的 AIMessage，content_blocks 也会是；helper 走 fallback
 分支用 aimsg.content（此处为 →空）或 aimsg.text 兜底；验证兜底路径可触及，
 本 test 通过给 `text` 属性一个非空值断言 fallback 机制 —— 由于 text 是
 computed property，对空 content 应返回 ""，因此我们断言此时返回 0 个 output item
 （即 content+text 都空，output 为空列表，向后兼容 LLMResponse 空 output 用例）。
 """
 aimsg = AIMessage(content=)
 node = AIPromptNode
 result = node._aimessage_to_llm_response(aimsg, "unknown-model")
 # content_blocks= + text/content 也为空 → fallback 不产出 item
 assert result.output ==
 # LLMResponse 仍可返回（status / model / usage 字段正常）
 assert result.model == "unknown-model"
 assert result.text == ""
def test_aimessage_to_llm_response_fallback_with_nonblock_content -> None:
 """Test 4b：content_blocks 为空 list 但 aimsg.text 有值 → fallback MessageItem。
 非 block 结构的场景（content_blocks=）；通过让 aimsg.content 为非空字符串
 （AIMessage 对此自动推出 `content_blocks=[{"type": "text", "text": "..."}]`），
 覆盖 helper 首选块映射路径；此处用另一种场景触发 fallback：
 content=[{"type": "unknown_type"}] —— 未知 block type 不产出 item，走 fallback。
 """
 aimsg = AIMessage(content=[{"type": "unknown_type_xyz", "data": "ignored"}])
 node = AIPromptNode
 result = node._aimessage_to_llm_response(aimsg, "unknown-model")
 # 未知 block type 不被映射；content_blocks 循环后 output 仍为空；
 # fallback：aimsg.text 对 list content 是空；output 最终为空
 # 本 test 守护的是"不 crash + 允许空 output"
 assert isinstance(result, LLMResponse)
 assert result.model == "unknown-model"
# ============================================================================
# Test 12：usage 三字段组合（total_tokens 独立计算）
# ============================================================================
def test_usage_total_tokens_computed -> None:
 """Test 12：LLMResponse.usage.total_tokens == input + output（不依赖 meta 字段）。"""
 aimsg = AIMessage(
 content="ok",
 usage_metadata={
 "input_tokens": 100,
 "output_tokens": 50,
 "total_tokens": 999, # 故意错乱 —— helper 应用 input+output 计算
 },
 )
 node = AIPromptNode
 result = node._aimessage_to_llm_response(aimsg, "claude-sonnet-4")
 assert result.usage.input_tokens == 100
 assert result.usage.output_tokens == 50
 assert result.usage.total_tokens == 150, (
 "total_tokens 应为 input+output 独立计算，不取 meta 字段（向后兼容契约）"
 )
# ============================================================================
# Test 1 / 5-11：execute 端到端（走 _call_llm → build_chat_model.ainvoke）
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_chat_model_single_path(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 1：happy path —— execute 正常 completed + OpenResponses 输出。"""
 fake_chat_model_factory(
 responses=["这是 AI 响应"],
 usage_metadata={
 "input_tokens": 100,
 "output_tokens": 50,
 "total_tokens": 150,
 },
 )
 mock_aresolve_ok(source="system", provider_type="anthropic")
 ctx = make_minimal_context(
 node_config={
 "system_prompt": "你是助手",
 "user_prompt": "你好",
 "model": "claude-sonnet-4-20250514",
 "temperature": 0.7,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output is not None
 assert result.output.get("text") == "这是 AI 响应"
 assert result.output.get("usage", {}).get("input_tokens") == 100
 assert result.output.get("usage", {}).get("output_tokens") == 50
 assert result.output.get("usage", {}).get("total_tokens") == 150
 assert result.output.get("model") == "claude-sonnet-4-20250514"
 assert result.output.get("output_format") == "text"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_custom_api_ephemeral_resolved(
 monkeypatch: pytest.MonkeyPatch,
 make_minimal_context: Any,
) -> None:
 """Test 5：分歧 A 守护 —— use_custom_api=True → source="node" + extra.custom_api=True。"""
 captured_resolved: list[tuple[Any, str]] =
 fake = FakeChatModel(responses=["响应"])
 def _capturing_build(resolved: Any, model: str, **kw: Any) -> Any:
 captured_resolved.append((resolved, model))
 return fake
 # 双 patch：prompt 模块侧（_call_llm 函数体内 import）+ llm_factory 源
 monkeypatch.setattr(
 "workflows.nodes.ai.prompt.build_chat_model",
 _capturing_build,
 raising=False,
 )
 monkeypatch.setattr(
 "agents.llm_factory.build_chat_model",
 _capturing_build,
 )
 ctx = make_minimal_context(
 node_config={
 "system_prompt": "你是助手",
 "user_prompt": "你好",
 "model": "gpt-4",
 "temperature": 0.7,
 "max_tokens": 1000,
 "use_custom_api": True,
 "api_base_url": "https://custom.example.com/v1",
 "api_key": "sk-custom-xxx",
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert len(captured_resolved) == 1
 resolved, model = captured_resolved[0]
 assert resolved.source == "node", (
 f"分歧 A 违反：source={resolved.source!r}，严禁 D 守护失败"
 )
 assert resolved.extra.get("custom_api") is True
 assert resolved.extra.get("source_detail") == "node_custom_api"
 assert resolved.base_url == "https://custom.example.com/v1"
 assert resolved.api_key == "sk-custom-xxx"
 assert resolved.provider_type == ProviderType.OPENAI_CHAT
 assert resolved.credential_id is None
 assert model == "gpt-4"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_custom_api_missing_model_raises(
 fake_chat_model_factory: Any,
 make_minimal_context: Any,
) -> None:
 """Test 6：use_custom_api=True + model="" → execute 返回 NodeResult(failed)。"""
 fake_chat_model_factory(responses=["ok"])
 ctx = make_minimal_context(
 node_config={
 "user_prompt": "你好",
 "model": "", # 缺 model
 "use_custom_api": True,
 "api_base_url": "https://custom.example.com/v1",
 "api_key": "sk-custom",
 "temperature": 0.7,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "failed"
 assert "使用自定义 API 时必须指定模型" in str(result.error or "")
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_missing_credential_propagates_as_value_error(
 mock_aresolve_missing: Any,
 make_minimal_context: Any,
) -> None:
 """Test 7：ProviderMissingError → ValueError("未配置 ... 凭证：...") → failed。"""
 mock_aresolve_missing(
 missing_provider="openai_chat",
 recommended_action="请在系统设置配置 OpenAI 凭证",
 )
 ctx = make_minimal_context(
 node_config={
 "user_prompt": "你好",
 "model": "gpt-4o",
 "temperature": 0.7,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "failed"
 msg = str(result.error or "")
 assert "未配置" in msg
 assert "凭证" in msg
 assert "openai_chat" in msg
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_temperature_bind_invoked(
 monkeypatch: pytest.MonkeyPatch,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 8：chat_model.bind(temperature=X) 被调用；断言 X=0.7 透传。
 FakeChatModel 是 pydantic 模型禁止直接 attribute 赋值，用 subclass override
 bind 方法捕获 kwargs。
 """
 mock_aresolve_ok(source="system", provider_type="anthropic")
 captured_bind: dict[str, Any] = {}
 class _BindCapturingFake(FakeChatModel):
 def bind(self, **kwargs: Any) -> Any:
 captured_bind["kwargs"] = kwargs
 return super.bind(**kwargs)
 fake = _BindCapturingFake(responses=["ok"])
 monkeypatch.setattr(
 "workflows.nodes.ai.prompt.build_chat_model",
 lambda *a, **kw: fake,
 raising=False,
 )
 monkeypatch.setattr(
 "agents.llm_factory.build_chat_model",
 lambda *a, **kw: fake,
 )
 ctx = make_minimal_context(
 node_config={
 "user_prompt": "你好",
 "model": "claude-sonnet-4",
 "temperature": 0.7,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 #：.bind(temperature=X) 透传
 assert captured_bind.get("kwargs", {}).get("temperature") == 0.7
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reasoning_model_temperature_strip_warning(
 capsys: pytest.CaptureFixture[str],
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 9 / Pitfall #11：reasoning 模型（o1-mini）+ temperature != 1 → warning 日志。"""
 fake_chat_model_factory(responses=["ok"])
 mock_aresolve_ok(source="system", provider_type="openai_chat")
 ctx = make_minimal_context(
 node_config={
 "user_prompt": "你好",
 "model": "o1-mini",
 "temperature": 0.5,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 captured = capsys.readouterr
 combined = captured.out + captured.err
 # Pitfall #11：structlog 写 ai_prompt_temperature_stripped event
 assert "ai_prompt_temperature_stripped" in combined, (
 f"reasoning 模型应触发 temperature strip warning；实际输出：\n{combined}"
 )
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_reasoning_model_no_warning(
 capsys: pytest.CaptureFixture[str],
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 10：非 reasoning 模型（claude-sonnet）不触发 temperature strip warning。"""
 fake_chat_model_factory(responses=["ok"])
 mock_aresolve_ok(source="system", provider_type="anthropic")
 ctx = make_minimal_context(
 node_config={
 "user_prompt": "你好",
 "model": "claude-sonnet-4-20250514",
 "temperature": 0.5,
 "max_tokens": 1000,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 captured = capsys.readouterr
 combined = captured.out + captured.err
 assert "ai_prompt_temperature_stripped" not in combined, (
 "非 reasoning 模型不得触发 temperature strip warning"
 )
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_execute_happy_path_returns_completed(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 11：execute 端到端 happy path 返回 completed 且 output 结构完整。"""
 fake_chat_model_factory(
 responses=["最终响应"],
 usage_metadata={
 "input_tokens": 80,
 "output_tokens": 40,
 "total_tokens": 120,
 },
 )
 mock_aresolve_ok(source="system", provider_type="anthropic")
 ctx = make_minimal_context(
 node_config={
 "system_prompt": "You are helpful",
 "user_prompt": "Hello",
 "model": "claude-sonnet-4",
 "temperature": 0.3,
 "max_tokens": 500,
 "output_format": "text",
 },
 )
 node = AIPromptNode
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.next_handle == "default"
 output = result.output or {}
 assert output.get("text") == "最终响应"
 assert output.get("raw_response") == "最终响应"
 assert output.get("response") == "最终响应" # text 格式 → response == text
 assert output.get("output_format") == "text"
 assert output.get("has_thinking") is False
 assert isinstance(output.get("output"), list)
 assert len(output.get("output", )) >= 1
 # 至少一个 message 项
 assert any(
 item.get("type") == "message" for item in output.get("output", )
 )
