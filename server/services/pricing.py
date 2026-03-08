"""定价服务 — 多 Provider 模型定价表与成本计算。
提供常见 LLM 模型的默认定价（input/output per 1K tokens），
支持前缀匹配和未知模型的回退定价。用户可在设置页覆盖价格。
"""
from decimal import Decimal
from typing import TypedDict
class ModelPricing(TypedDict):
 """单个模型的定价信息（美元/每千 tokens）。"""
 input_per_1k: str # Decimal 字符串，避免浮点精度问题
 output_per_1k: str
# 默认定价表：模型前缀 → 定价
# 价格基于各 Provider 公开定价（2025 年数据），用户可覆盖
PRICING_TABLE: dict[str, ModelPricing] = {
 # Anthropic
 "claude-opus-4": {"input_per_1k": "0.015", "output_per_1k": "0.075"},
 "claude-sonnet-4": {"input_per_1k": "0.003", "output_per_1k": "0.015"},
 "claude-haiku": {"input_per_1k": "0.0008", "output_per_1k": "0.004"},
 # OpenAI
 "gpt-4o": {"input_per_1k": "0.0025", "output_per_1k": "0.010"},
 "gpt-4o-mini": {"input_per_1k": "0.00015", "output_per_1k": "0.0006"},
 "gpt-4-turbo": {"input_per_1k": "0.010", "output_per_1k": "0.030"},
 "o1": {"input_per_1k": "0.015", "output_per_1k": "0.060"},
 "o3": {"input_per_1k": "0.010", "output_per_1k": "0.040"},
 # Google
 "gemini-2.0-flash": {"input_per_1k": "0.0001", "output_per_1k": "0.0004"},
 "gemini-2.5-pro": {"input_per_1k": "0.00125", "output_per_1k": "0.010"},
 "gemini-2.5-flash": {"input_per_1k": "0.00015", "output_per_1k": "0.0006"},
}
# 未知模型的回退定价
DEFAULT_PRICING: ModelPricing = {"input_per_1k": "0.003", "output_per_1k": "0.015"}
def _find_pricing(model: str) -> ModelPricing:
 """通过前缀匹配查找模型定价。
 优先匹配最长前缀（如 "gpt-4o-mini" 优先于 "gpt-4o"）。
 Args:
 model: 模型 ID（如 "claude-sonnet-4-20250514"）
 Returns:
 匹配的定价信息，未匹配时返回 DEFAULT_PRICING
 """
 model_lower = model.lower
 best_match: ModelPricing | None = None
 best_length = 0
 for prefix, pricing in PRICING_TABLE.items:
 if model_lower.startswith(prefix) and len(prefix) > best_length:
 best_match = pricing
 best_length = len(prefix)
 return best_match or DEFAULT_PRICING
def calculate_cost(
 model: str,
 input_tokens: int,
 output_tokens: int,
) -> Decimal:
 """计算 LLM 调用成本。
 Args:
 model: 模型 ID
 input_tokens: 输入 token 数
 output_tokens: 输出 token 数
 Returns:
 总成本（美元），精度 6 位小数
 """
 pricing = _find_pricing(model)
 input_cost = Decimal(pricing["input_per_1k"]) * input_tokens / 1000
 output_cost = Decimal(pricing["output_per_1k"]) * output_tokens / 1000
 total = input_cost + output_cost
 return total.quantize(Decimal("0.000001"))
