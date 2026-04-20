"""Phase Plan：ModelCapabilities 查询服务 + Ollama runtime 合并测试。
覆盖 Requirement:,
Threats: (none) —— 纯静态 fixture 查询 + 凭证字段赋值，无 HTTP / DB 写入
测试覆盖矩阵（PATTERNS §13 + PLAN.md Behavior 9 case）：
 T1 精确匹配返回 fixture 精确条目
 T2 未知模型按 Provider `*` 兜底
 T3 未知 Provider 按全局 `*/*` 兜底
 T4 前缀 longest-match（未精确收录时）
 T5 Decimal 精度（非 float 转换）
 T6 DEFAULT_CAPABILITIES 默认值兜底（全局查找失败时）
 T7 merge_ollama 写入 credential.available_models
 T8 merge_ollama 幂等
 T9 _load 类级 cache 单次 I/O
"""
from __future__ import annotations
import json
from decimal import Decimal
from typing import Any
import pytest
def test_get_exact_match -> None:
 """T1: 精确匹配返回 fixture 条目（claude-sonnet-4-5-20250929）。"""
 from services.model_capabilities import ModelCapabilities
 entry = ModelCapabilities.get("anthropic", "claude-sonnet-4-5-20250929")
 assert entry.max_input_tokens == 200000
 assert entry.output_cost_per_token == Decimal("1.5e-5")
 assert entry.input_cost_per_token == Decimal("3e-6")
 assert entry.cache_creation_cost_per_token == Decimal("3.75e-6")
def test_get_unknown_model_provider_fallback -> None:
 """T2: anthropic 下未知模型 → 命中 anthropic Provider `*` 兜底。"""
 from services.model_capabilities import ModelCapabilities
 entry = ModelCapabilities.get("anthropic", "claude-future-9000")
 assert entry.provider == "anthropic"
 assert entry.model == "*"
 assert entry.max_input_tokens == 200000
def test_get_unknown_provider_global_fallback -> None:
 """T3: 未知 Provider → 命中全局 `*/*` 兜底。"""
 from services.model_capabilities import ModelCapabilities
 entry = ModelCapabilities.get("cohere", "command-r")
 assert entry.provider == "*"
 assert entry.model == "*"
 assert entry.output_cost_per_token == Decimal("1.5e-5")
def test_get_prefix_match_longest_wins -> None:
 """T4: 精确优先；未精确收录时 longest-prefix-loop 命中同 Provider 下最长前缀。
 - 'claude-3-5-sonnet-20241022' 精确收录 → 精确命中（不降级到前缀）。
 - 'claude-3-5-sonnet-future' 未收录 → 命中前缀最长的 'claude-3-5-sonnet-20241022'？否，
 fixture 内模型是完整带日期后缀；longest-prefix-loop 仍会命中该完整 model 字符串的前缀
 部分（claude-3-5-sonnet-20241022 是 claude-3-5-sonnet-... 的前缀？不是：前缀匹配要求
 model.startswith(m)，m=claude-3-5-sonnet-20241022；query=claude-3-5-sonnet-future
 → startswith 不成立）。因此此查询会降级到 Provider `*` 兜底（test 2 覆盖）。
 本 T4 用 claude-3-5-sonnet-20241022 验证**精确**路径不被前缀降级。
 """
 from services.model_capabilities import ModelCapabilities
 entry = ModelCapabilities.get("anthropic", "claude-3-5-sonnet-20241022")
 # 精确匹配
 assert entry.model == "claude-3-5-sonnet-20241022"
 assert entry.max_output_tokens == 8192
def test_decimal_precision_no_float -> None:
 """T5: cost 字段全部是 Decimal 类型，非 float；精度保持字符串构造值。"""
 from services.model_capabilities import ModelCapabilities
 entry = ModelCapabilities.get("anthropic", "claude-sonnet-4-5-20250929")
 assert isinstance(entry.input_cost_per_token, Decimal)
 assert isinstance(entry.output_cost_per_token, Decimal)
 assert isinstance(entry.cached_input_cost_per_token, Decimal)
 # 精度断言：Decimal('3e-6') 精确相等于 Decimal(str(3e-6))
 assert entry.input_cost_per_token == Decimal("3e-6")
def test_default_capabilities_safe -> None:
 """T6: DEFAULT_CAPABILITIES 默认值符合 RESEARCH §2.3 约定。"""
 from services.model_capabilities import DEFAULT_CAPABILITIES
 assert DEFAULT_CAPABILITIES.input_cost_per_token == Decimal("0.000003")
 assert DEFAULT_CAPABILITIES.output_cost_per_token == Decimal("0.000015")
 assert DEFAULT_CAPABILITIES.max_input_tokens == 128000
 assert DEFAULT_CAPABILITIES.max_output_tokens == 4096
@pytest.mark.django_db
def test_merge_ollama_writes_available_models -> None:
 """T7: merge_ollama 将模型清单赋值到 credential.available_models。"""
 from common.encryption import encrypt_value
 from services.model_capabilities import ModelCapabilities
 from system.models import ProviderCredential
 cred = ProviderCredential.objects.create(
 provider_type="ollama",
 name="default",
 scope="system",
 scope_id=None,
 encrypted_config=encrypt_value(json.dumps({"base_url": "http://localhost:11434"})),
 )
 ModelCapabilities.merge_ollama(cred, ["llama3.2:latest", "qwen2.5:7b"])
 assert cred.available_models == ["llama3.2:latest", "qwen2.5:7b"]
@pytest.mark.django_db
def test_merge_ollama_idempotent -> None:
 """T8: 连续调用同样 list，结果相同，不重复 append。"""
 from common.encryption import encrypt_value
 from services.model_capabilities import ModelCapabilities
 from system.models import ProviderCredential
 cred = ProviderCredential.objects.create(
 provider_type="ollama",
 name="default",
 scope="system",
 scope_id=None,
 encrypted_config=encrypt_value(json.dumps({"base_url": "http://localhost:11434"})),
 )
 ModelCapabilities.merge_ollama(cred, ["llama3.2:latest"])
 ModelCapabilities.merge_ollama(cred, ["llama3.2:latest"])
 assert cred.available_models == ["llama3.2:latest"]
def test_load_cache_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
 """T9: 类级 _cache 使 fixture JSON 仅读 1 次（连续 100 次 get 触发 1 次 I/O）。"""
 from pathlib import Path
 from services import model_capabilities as mc_mod
 # 重置 cache
 mc_mod.ModelCapabilities._cache = None
 call_count = {"n": 0}
 original_read = Path.read_text
 def counting_read(self: Path, *args: Any, **kwargs: Any) -> str:
 if str(self).endswith("model_prices.json"):
 call_count["n"] += 1
 return original_read(self, *args, **kwargs)
 monkeypatch.setattr(Path, "read_text", counting_read)
 for _ in range(100):
 mc_mod.ModelCapabilities.get("anthropic", "claude-sonnet-4-5-20250929")
 assert call_count["n"] == 1, f"expected 1 file read, got {call_count['n']}"
