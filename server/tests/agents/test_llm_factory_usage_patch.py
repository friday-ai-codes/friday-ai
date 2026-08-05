"""langchain-anthropic usage 解析补丁的回归测试。

复现线上事故：Anthropic 兼容网关（ops-ai-gateway）返回的 ``usage.cache_creation``
里键存在但值为 ``null``，``_create_usage_metadata`` 对其 ``+=`` 直接 TypeError，
导致内容本身成功的 LLM 调用整个被判失败（项目描述生成 422「未配置 AI Provider」
误导提示）。补丁语义：原函数解析失败时回退最小 UsageMetadata，官方路径行为不变。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from core.patches import patch_langchain_anthropic_usage_metadata


class _CacheCreation(BaseModel):
    """模拟网关返回：键存在但值为 null。"""

    ephemeral_5m_input_tokens: int | None = None
    ephemeral_1h_input_tokens: int | None = None


class _GatewayUsage(BaseModel):
    """模拟 ops 网关的 usage：cache 计费字段全是 null。"""

    input_tokens: int | None = 10
    output_tokens: int | None = 5
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_creation: _CacheCreation | None = _CacheCreation()


class _OfficialUsage(BaseModel):
    """模拟官方 API 的正常 usage（cache 字段是真实整数）。"""

    input_tokens: int = 100
    output_tokens: int = 20
    cache_read_input_tokens: int = 30
    cache_creation_input_tokens: int = 0
    cache_creation: _CacheCreation | None = None


@pytest.fixture
def patched_module():
    """应用补丁并返回 langchain_anthropic.chat_models 模块。"""
    from langchain_anthropic import chat_models

    patch_langchain_anthropic_usage_metadata()
    return chat_models


class TestUsageMetadataPatch:
    def test_gateway_null_cache_fields_fall_back(self, patched_module):
        """⭐ 网关 null 计费字段不再 TypeError，回退到最小 usage。"""
        meta = patched_module._create_usage_metadata(_GatewayUsage())
        assert meta["input_tokens"] >= 10
        assert meta["output_tokens"] == 5
        assert meta["total_tokens"] == meta["input_tokens"] + meta["output_tokens"]

    def test_official_usage_unchanged(self, patched_module):
        """官方 API 正常 usage 走原函数：cache_read 计入 input 总数（既有语义）。"""
        meta = patched_module._create_usage_metadata(_OfficialUsage())
        assert meta["input_tokens"] == 130  # 100 + cache_read 30
        assert meta["output_tokens"] == 20

    def test_patch_is_idempotent(self, patched_module):
        """⭐ 重复应用不叠包：第二次调用后仍是同一个包装函数。"""
        first = patched_module._create_usage_metadata
        patch_langchain_anthropic_usage_metadata()
        assert patched_module._create_usage_metadata is first
        assert getattr(first, "_friday_usage_patch", False) is True

    def test_none_token_counts_fall_back_to_zero(self, patched_module):
        """input/output 本身也是 null 时回退为 0，不抛。"""
        usage = _GatewayUsage(input_tokens=None, output_tokens=None)
        meta = patched_module._create_usage_metadata(usage)
        assert meta["total_tokens"] == meta["input_tokens"] + meta["output_tokens"]
