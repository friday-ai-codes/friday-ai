"""initial implementation plan：calculate_cost_v2 六字段定价测试。

覆盖 Requirement: contract
Threats: (none) —— 纯计算 + 静态 fixture

测试覆盖:
  T1 Anthropic 六字段求和 (input + cached_input + cache_creation + output)
  T2 OpenAI reasoning 字段无 fixture cost → 按 0 不 raise
  T3 Gemini reasoning 字段独立 cost
  T4 Ollama 未知模型 → Provider `*` 兜底 (cost = 0)
  T5 Decimal 精度 6 位小数
  T6 部分 usage 字段缺失不 raise
  T7 旧 calculate_cost API 向后兼容 (pricing compatibility)
"""

from __future__ import annotations

from decimal import Decimal

from services.pricing import calculate_cost, calculate_cost_v2


def test_calculate_cost_v2_anthropic_six_fields() -> None:
    """T1: 六字段求和与手算一致。"""
    usage = {
        "input": 1000,
        "cached_input": 500,
        "cache_creation": 200,
        "output": 300,
        "reasoning": 0,
        "vision": 0,
    }
    cost = calculate_cost_v2("anthropic", "claude-sonnet-4-5-20250929", usage)
    expected = (
        Decimal("3e-6") * 1000
        + Decimal("3e-7") * 500
        + Decimal("3.75e-6") * 200
        + Decimal("1.5e-5") * 300
    ).quantize(Decimal("0.000001"))
    assert cost == expected, f"got {cost}, expected {expected}"


def test_calculate_cost_v2_openai_reasoning_no_field_fallback_zero() -> None:
    """T2: OpenAI gpt-5 fixture 无 reasoning_cost_per_token → 按 0 计算不 raise。"""
    usage = {"input": 1000, "output": 500, "reasoning": 100}
    cost = calculate_cost_v2("openai", "gpt-5", usage)
    expected = (Decimal("1.25e-6") * 1000 + Decimal("1e-5") * 500).quantize(Decimal("0.000001"))
    assert cost == expected


def test_calculate_cost_v2_gemini_reasoning_distinct_field() -> None:
    """T3: Gemini-2.5-flash fixture 含 reasoning_cost_per_token → reasoning 项独立计价。"""
    usage = {"input": 1000, "output": 500, "reasoning": 100}
    cost = calculate_cost_v2("gemini", "gemini-2.5-flash", usage)
    expected = (
        Decimal("3e-7") * 1000
        + Decimal("2.5e-6") * 500
        + Decimal("2.5e-6") * 100
    ).quantize(Decimal("0.000001"))
    assert cost == expected


def test_calculate_cost_v2_ollama_zero_cost() -> None:
    """T4: Ollama 未知模型 → Provider `*` 兜底 (本地零成本)。"""
    usage = {"input": 1000, "output": 500}
    cost = calculate_cost_v2("ollama", "llama3.2:latest", usage)
    assert cost == Decimal("0").quantize(Decimal("0.000001"))


def test_calculate_cost_v2_decimal_precision() -> None:
    """T5: 返回类型 Decimal，精度 ≤ 6 位小数。"""
    cost = calculate_cost_v2("anthropic", "claude-3-5-haiku-20241022", {"input": 1, "output": 1})
    assert isinstance(cost, Decimal)
    # 6 位小数：exponent = -6
    exponent = cost.as_tuple().exponent
    assert isinstance(exponent, int), f"expected int exponent, got {type(exponent)}"
    assert -exponent <= 6, f"expected <=6 decimals, got exponent={exponent}"


def test_calculate_cost_v2_partial_usage_no_keyerror() -> None:
    """T6: usage 缺失字段按 0 计算，不抛 KeyError / AttributeError。"""
    cost = calculate_cost_v2("anthropic", "claude-sonnet-4-5-20250929", {"input": 100})
    expected = (Decimal("3e-6") * 100).quantize(Decimal("0.000001"))
    assert cost == expected


def test_legacy_calculate_cost_backward_compatible() -> None:
    """T7: pricing compatibility——老 API 必须保留可调用。"""
    cost_old = calculate_cost("claude-sonnet-4", input_tokens=1000, output_tokens=500)
    assert isinstance(cost_old, Decimal)
    assert cost_old > Decimal("0")
