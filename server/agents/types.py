"""跨 Runner 类型定义（为 implementation LangChainAgentRunner 铺路）。

本 phase 仅定义 schema，implementation Runner 落地时直接 import。
本 phase 不修改 server/agents/models.py::AgentSession.add_usage() 签名
（保留 input_tokens/output_tokens 两字段兼容；六字段落地 implementation 一并）。
"""

from __future__ import annotations

from typing import TypedDict


class TokenUsage(TypedDict, total=False):
    """六字段 token 使用统计（v21.0 跨 Provider 归一化 schema）。

    全部字段可选（total=False），Runner 按 Provider 能力按需写入。
    字段命名与 Anthropic API 自然对齐：

    - input          ↔ usage.input_tokens
    - cached_input   ↔ usage.cache_read_input_tokens（Anthropic prompt caching 命中）
    - cache_creation ↔ usage.cache_creation_input_tokens（Anthropic prompt caching 创建）
    - output         ↔ usage.output_tokens
    - reasoning      ↔ OpenAI o1/o3 completion_tokens_details.reasoning_tokens
                       / Gemini usageMetadata.thoughtsTokenCount
    - vision         ↔ 视觉 patch tokens（Provider 差异大，v21.0 占位 0 为主）
    """

    input: int
    cached_input: int
    cache_creation: int
    output: int
    reasoning: int
    vision: int
