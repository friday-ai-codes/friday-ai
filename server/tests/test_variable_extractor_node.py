"""Phase Wave（ Task 2）：AIVariableExtractorNode 单元测试。
覆盖范围（Plan Task 2 <behavior> 8 场景）：
- Test 1 test_ainvoke_single_turn_returns_text_and_usage
 happy path：_call_llm 单 turn ainvoke 返回 (text, usage)；usage 含 input/output_tokens。
- Test 2 test_extraction_happy_path_via_execute
 execute 全链路：render_prompt → _call_llm → _parse_ai_response → 注册全局变量。
- Test 3 test_temperature_0_3_bound_to_chat_model
 守护：chat_model.bind(temperature=0.3) 实际捕获；kwargs["temperature"]==0.3。
- Test 4 test_missing_credential_propagates_as_value_error
 aresolve_or_error → ProviderMissingError → ValueError("未配置 ... 凭证")。
- Test 5 test_missing_model_raises
 config_model="" + claude_config.model="" → ValueError("未配置默认模型...")。
- Test 6 test_json_parse_failure_falls_back_to_error_status
 LLM 返回非 JSON 文本 → _parse_ai_response 返回 None → NodeResult(failed)。
- Test 7 test_httpx_not_called
 守护：variable_extractor 不再走 httpx.AsyncClient 直调（monkeypatch
 httpx.AsyncClient 为 forbidden raise）。
- Test 8 test_aget_claude_config_only_for_model_fallback
 守护：aget_claude_config 仅在 config_model="" 时被调用拿 model；api_key /
 base_url 走 aresolve_or_error 产出。
Fixture 策略（ / Pattern 9 / Q6 决策 / ）：
- 已抽取 conftest.py 公共 fixture（fake_chat_model_factory /
 mock_aresolve_ok / mock_aresolve_missing / make_minimal_context），本文件统一引用，
 **禁止**重复定义。 静态扫描拦截。
"""
from __future__ import annotations
import hashlib
from typing import Any
import pytest
from services.provider_config import ProviderType
from tests.helpers.fake_chat_model import FakeChatModel
# ============================================================================
# Test 1: happy path 单 turn ainvoke
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ainvoke_single_turn_returns_text_and_usage(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 1：_call_llm 单 turn ainvoke 返回 (text, usage)。"""
 fake_chat_model_factory(
 responses=['{"variables": {"name": "张三"}}'],
 usage_metadata={
 "input_tokens": 50,
 "output_tokens": 30,
 "total_tokens": 80,
 },
 )
 mock_aresolve_ok(source="system", provider_type="anthropic")
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "name", "name": "姓名", "desc": "姓名"}],
 "model": "claude-sonnet-4-20250514",
 },
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 text, usage = await node._call_llm(
 prompt="提取姓名",
 model="claude-sonnet-4-20250514",
 context=ctx,
 )
 assert '"name"' in text
 assert usage["input_tokens"] == 50
 assert usage["output_tokens"] == 30
# ============================================================================
# Test 2: execute happy path 全链路
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_extraction_happy_path_via_execute(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 2：execute 完整链路：render_prompt → _call_llm → _parse_ai_response。"""
 fake_chat_model_factory(
 responses=['```json\n{"variables": {"user_name": "张三"}}\n```'],
 )
 mock_aresolve_ok(source="system")
 ctx = make_minimal_context(
 node_config={
 "variables": [
 {
 "key": "user_name",
 "name": "用户姓名",
 "desc": "从文本中提取的用户姓名",
 }
 ],
 "model": "claude-sonnet-4-20250514",
 },
 input_data={"text": "我叫张三"},
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 result = await node.execute(ctx)
 assert result.status == "completed", f"execute failed: {result.error}"
 assert "user_name" in result.output["variables"]
 assert result.output["variables"]["user_name"]["value"] == "张三"
# ============================================================================
# Test 3: temperature 0.3 bind 守护
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_temperature_0_3_bound_to_chat_model(
 monkeypatch: pytest.MonkeyPatch,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 3： 守护 —— chat_model.bind(temperature=0.3) 实际捕获。"""
 bind_kwargs_captured: list[dict[str, Any]] =
 class _CapturingBindFake(FakeChatModel):
 def bind(self, **kwargs: Any) -> Any: # type: ignore[override]
 bind_kwargs_captured.append(kwargs)
 # 复用父类默认 bind（RunnableBinding）链式语义
 return super.bind(**kwargs)
 fake = _CapturingBindFake(
 responses=['{"variables": {}}'],
 usage_metadata={
 "input_tokens": 10,
 "output_tokens": 5,
 "total_tokens": 15,
 },
 )
 # 双 patch seam：llm_factory + 节点模块（分歧 D / Pitfall #5）
 monkeypatch.setattr(
 "agents.llm_factory.build_chat_model", lambda *a, **kw: fake
 )
 monkeypatch.setattr(
 "workflows.nodes.ai.variable_extractor.build_chat_model",
 lambda *a, **kw: fake,
 raising=False,
 )
 mock_aresolve_ok(source="system")
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 "model": "claude-sonnet-4-20250514",
 },
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 await node._call_llm(
 prompt="提取", model="claude-sonnet-4-20250514", context=ctx
 )
 assert len(bind_kwargs_captured) >= 1, "bind 未被调用"
 assert bind_kwargs_captured[0].get("temperature") == 0.3
# ============================================================================
# Test 4: ProviderMissingError → ValueError
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_missing_credential_propagates_as_value_error(
 fake_chat_model_factory: Any,
 mock_aresolve_missing: Any,
 make_minimal_context: Any,
) -> None:
 """Test 4：aresolve_or_error → ProviderMissingError → ValueError。"""
 fake_chat_model_factory(responses=['{"variables": {}}'])
 mock_aresolve_missing(
 missing_provider="anthropic",
 recommended_action="请在系统设置中配置 Anthropic 凭证",
 )
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 "model": "claude-sonnet-4-20250514",
 },
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 with pytest.raises(ValueError) as exc_info:
 await node._call_llm(
 prompt="p",
 model="claude-sonnet-4-20250514",
 context=ctx,
 )
 msg = str(exc_info.value)
 assert "未配置" in msg
 assert "凭证" in msg
 assert "anthropic" in msg
# ============================================================================
# Test 5: 缺模型 raise
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_missing_model_raises(
 monkeypatch: pytest.MonkeyPatch,
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 5：config_model="" + claude_config.model="" → ValueError。"""
 fake_chat_model_factory(responses=['{"variables": {}}'])
 mock_aresolve_ok(source="system")
 # stub aget_claude_config 返回 model=""
 async def _fake_cc(project: Any = None) -> Any:
 from services.claude_config import ClaudeConfig
 return ClaudeConfig(
 api_key=None, base_url=None, model="", source="system"
 )
 monkeypatch.setattr(
 "services.claude_config.aget_claude_config", _fake_cc
 )
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 },
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 with pytest.raises(ValueError) as exc_info:
 await node._call_llm(prompt="p", model="", context=ctx)
 assert "未配置默认模型" in str(exc_info.value)
# ============================================================================
# Test 6: JSON 解析失败 fallback
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_json_parse_failure_falls_back_to_error_status(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 6：LLM 返回非 JSON 文本 → _parse_ai_response None → NodeResult(failed)."""
 fake_chat_model_factory(responses=["这不是 JSON，只是纯文本响应"])
 mock_aresolve_ok(source="system")
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 "model": "claude-sonnet-4-20250514",
 },
 input_data={"text": "input"},
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 result = await node.execute(ctx)
 assert result.status == "failed"
 # _parse_ai_response 返回 None 时 error="AI 响应解析失败"
 # 包含 raw_response 字段
 assert "raw_response" in result.output or "解析失败" in (result.error or "")
# ============================================================================
# Test 7: httpx 未被调用（ 守护）
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_httpx_not_called(
 monkeypatch: pytest.MonkeyPatch,
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 7： 守护 —— variable_extractor 不走 httpx.AsyncClient 直调。"""
 import httpx as _httpx
 calls: list[Any] =
 class _ForbiddenClient:
 def __init__(self, *a: Any, **kw: Any) -> None:
 calls.append((a, kw))
 raise AssertionError("不应创建 httpx.AsyncClient（ 违反）")
 async def __aenter__(self) -> Any:
 return self
 async def __aexit__(self, *a: Any) -> None:
 pass
 monkeypatch.setattr(_httpx, "AsyncClient", _ForbiddenClient)
 fake_chat_model_factory(responses=['{"variables": {"x": "v"}}'])
 mock_aresolve_ok(source="system")
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 "model": "claude-sonnet-4-20250514",
 },
 input_data={"text": "hello"},
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 result = await node.execute(ctx)
 # 不 crash：要么 completed 要么 failed，只要没因为 httpx raise 崩溃
 assert result.status in ("completed", "failed")
 assert calls ==, "httpx.AsyncClient 被调用（ 违反）"
# ============================================================================
# Test 8: aget_claude_config 仅用于 model fallback
# ============================================================================
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aget_claude_config_only_for_model_fallback(
 monkeypatch: pytest.MonkeyPatch,
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 make_minimal_context: Any,
) -> None:
 """Test 8： 守护 —— aget_claude_config 仅在 config_model="" 时拿 model。
 断言：
 - aget_claude_config 被调用（拿 model fallback）；
 - resolved.api_key 来自 aresolve_or_error（固定 "sk-ok"），而非 cc.api_key；
 - resolved.base_url 来自 aresolve_or_error。
 """
 cc_calls: list[Any] =
 async def _tracked_cc(project: Any = None) -> Any:
 cc_calls.append(project)
 from services.claude_config import ClaudeConfig
 # cc 返回"错误"的 api_key / base_url，用于验证它们不会被使用
 return ClaudeConfig(
 api_key="SHOULD_NOT_BE_USED",
 base_url="https://WRONG.example.com",
 model="claude-sonnet-4-fallback",
 source="system",
 )
 monkeypatch.setattr(
 "services.claude_config.aget_claude_config", _tracked_cc
 )
 # 记录 build_chat_model 收到的 resolved / model
 captured_calls: list[dict[str, Any]] =
 fake = FakeChatModel(responses=['{"variables": {}}'])
 def _tracking_builder(*args: Any, **kwargs: Any) -> Any:
 captured_calls.append(
 {
 "args": args,
 "kwargs": kwargs,
 "resolved": kwargs.get("resolved"),
 "model": kwargs.get("model"),
 }
 )
 return fake
 monkeypatch.setattr(
 "agents.llm_factory.build_chat_model", _tracking_builder
 )
 monkeypatch.setattr(
 "workflows.nodes.ai.variable_extractor.build_chat_model",
 _tracking_builder,
 raising=False,
 )
 mock_aresolve_ok(
 source="system",
 provider_type="anthropic",
 api_key="sk-ok",
 base_url="https://api.anthropic.com",
 )
 ctx = make_minimal_context(
 node_config={
 "variables": [{"key": "x", "name": "X", "desc": "X"}],
 # 空 model → 走 fallback
 "model": "",
 },
 )
 from workflows.nodes.ai.variable_extractor import AIVariableExtractorNode
 node = AIVariableExtractorNode
 await node._call_llm(prompt="p", model="", context=ctx)
 # aget_claude_config 被调用一次（model fallback）
 assert len(cc_calls) == 1, "aget_claude_config 应被调用一次（拿 model fallback）"
 # build_chat_model 收到的 resolved.api_key 来自 aresolve_or_error
 assert len(captured_calls) == 1
 resolved_used = captured_calls[0]["resolved"]
 assert (
 resolved_used.api_key == "sk-ok"
 ), "api_key 必须来自 aresolve_or_error，不得使用 claude_config 返回值"
 assert (
 resolved_used.base_url == "https://api.anthropic.com"
 ), "base_url 必须来自 aresolve_or_error，不得使用 claude_config 返回值"
 assert resolved_used.provider_type == ProviderType.ANTHROPIC
 # model 来自 claude_config fallback
 assert (
 captured_calls[0]["model"] == "claude-sonnet-4-fallback"
 ), "model 应走 aget_claude_config fallback"
# ============================================================================
# 辅助：hashlib 导入保留供未来 sha256 验证扩展
# ============================================================================
_ = hashlib # 避免 F401
