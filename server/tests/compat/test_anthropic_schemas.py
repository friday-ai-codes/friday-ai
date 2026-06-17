"""AnthropicMessagesRequestSerializer + anthropic_to_openai_messages 纯函数单测（57-01 Task 1）。

测试覆盖：
  serializer 校验：max_tokens 必填、system 可选（string/blocks）、role 仅 user/assistant、
    content parts 校验、temperature 范围。
  anthropic_to_openai_messages：system 提顶摊平、block→text part、空 system 不插入。
"""

from __future__ import annotations

from compat.request_handler import anthropic_to_openai_messages
from compat.schemas import AnthropicMessagesRequestSerializer

# ──────────────────────────────────────────────────────────────────────────────
# serializer 校验
# ──────────────────────────────────────────────────────────────────────────────


def _base_payload(**overrides) -> dict:
    payload = {
        "model": "claude-3-5-sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    }
    payload.update(overrides)
    return payload


def test_max_tokens_required() -> None:
    """max_tokens 缺失 → is_valid() False（Anthropic 必填）。"""
    payload = _base_payload()
    del payload["max_tokens"]
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert not serializer.is_valid()
    assert "max_tokens" in serializer.errors


def test_max_tokens_zero_invalid() -> None:
    """max_tokens=0 → False（min_value=1）。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload(max_tokens=0))
    assert not serializer.is_valid()
    assert "max_tokens" in serializer.errors


def test_valid_minimal_payload() -> None:
    """合法最小 payload（含 max_tokens≥1）→ True。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload())
    assert serializer.is_valid(), serializer.errors


def test_system_optional_omitted() -> None:
    """system 省略合法。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload())
    assert serializer.is_valid(), serializer.errors


def test_system_string_valid() -> None:
    """system 给 string 合法。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload(system="你是助手"))
    assert serializer.is_valid(), serializer.errors


def test_system_blocks_valid() -> None:
    """system 给 content blocks 数组合法。"""
    payload = _base_payload(system=[{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_message_role_system_invalid() -> None:
    """messages role=system → False（仅 user/assistant）。"""
    payload = _base_payload(messages=[{"role": "system", "content": "x"}])
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert not serializer.is_valid()


def test_message_role_user_valid() -> None:
    """messages role=user 合法。"""
    payload = _base_payload(messages=[{"role": "user", "content": "x"}])
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_content_string_valid() -> None:
    """content 为 string 合法。"""
    payload = _base_payload(messages=[{"role": "user", "content": "hello"}])
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_content_text_parts_valid() -> None:
    """content 为 [{type:text,text}] 合法。"""
    payload = _base_payload(
        messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    )
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors


def test_content_bogus_part_invalid() -> None:
    """content 为 [{type:bogus}] → False。"""
    payload = _base_payload(
        messages=[{"role": "user", "content": [{"type": "bogus"}]}]
    )
    serializer = AnthropicMessagesRequestSerializer(data=payload)
    assert not serializer.is_valid()


def test_temperature_out_of_range_invalid() -> None:
    """temperature=1.5 → False（max 1.0）。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload(temperature=1.5))
    assert not serializer.is_valid()


def test_temperature_in_range_valid() -> None:
    """temperature=0.5 合法。"""
    serializer = AnthropicMessagesRequestSerializer(data=_base_payload(temperature=0.5))
    assert serializer.is_valid(), serializer.errors


# ──────────────────────────────────────────────────────────────────────────────
# anthropic_to_openai_messages 规整纯函数
# ──────────────────────────────────────────────────────────────────────────────


def test_system_string_lifted_to_first() -> None:
    """system="你是助手" → 结果首位 {role:system,content:你是助手}，其后透传 user。"""
    result = anthropic_to_openai_messages("你是助手", [{"role": "user", "content": "hi"}])
    assert result[0] == {"role": "system", "content": "你是助手"}
    assert result[1] == {"role": "user", "content": "hi"}


def test_system_blocks_flattened() -> None:
    """system 为 [{text:A},{text:B}] → 摊平 "AB"。"""
    result = anthropic_to_openai_messages(
        [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
        [{"role": "user", "content": "hi"}],
    )
    assert result[0] == {"role": "system", "content": "AB"}


def test_system_none_not_inserted() -> None:
    """system 为 None → 不插入 system。"""
    result = anthropic_to_openai_messages(None, [{"role": "user", "content": "hi"}])
    assert all(m["role"] != "system" for m in result)
    assert result[0] == {"role": "user", "content": "hi"}


def test_system_empty_string_not_inserted() -> None:
    """system 为 "" → 不插入 system。"""
    result = anthropic_to_openai_messages("", [{"role": "user", "content": "hi"}])
    assert all(m["role"] != "system" for m in result)


def test_message_blocks_keep_only_text() -> None:
    """messages content 为 [text, image] → 规整 content 仅含 {type:text,text:x}。"""
    result = anthropic_to_openai_messages(
        None,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "x"},
                    {"type": "image", "source": {"foo": "bar"}},
                ],
            }
        ],
    )
    assert result[0]["content"] == [{"type": "text", "text": "x"}]
