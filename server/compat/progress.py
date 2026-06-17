"""compat progress 透出的纯函数机制层（TRACE-01 机制 / INV-5 安全）。

本模块把 Friday 内部工具事件（AgentEvent）翻译为对外 OpenAI 兼容的
progress 文本，并构造 `delta.reasoning_content` progress chunk。设计为
与 adapter / view 完全解耦的纯函数，便于独立单测，并为 Phase 57
（Anthropic thinking block 复用同一映射）预留抽象。

安全约束（INV-5，硬约束）：
- 只读 `tool_name` 翻成高层中文语义，**绝不**内联 `tool_input` / `result`
  / `error` / 模型 CoT / query 原文（这些字段可能含敏感代码片段或注入内容）。
- 未知 / 缺 tool_name → 返回 None（保守静默，避免泄漏内部工具名细节）。
- `TOOL_USE_RESULT` 一律返回 None（完成态计数派生留 Plan 02 的检索 progress 处理）。

设计注（P-1）：
- **不** import §15 event_taxonomy 常量来驱动 progress——那套事件（`knowledge.recalling`
  等）不在 AgentEvent 流里，仅做语义对齐（progress 文本的人类可读释义对齐 taxonomy 语义），
  不是数据源。
"""

from __future__ import annotations

from typing import Any

from agents.core.events import TOOL_USE_START, AgentEvent

from .streaming import sse_encode

__all__ = ["make_reasoning_chunk", "tool_event_to_progress"]


# 工具名 → 中文高层语义映射表（纯数据常量）。
# 措辞对齐 §15 taxonomy 人类可读释义（knowledge.recalling / repo.routing），
# 但刻意不 import event_taxonomy 常量（P-1，那套事件不在 AgentEvent 流）。
_TOOL_PROGRESS_LABELS: dict[str, str] = {
    # RAG 检索（语义对应 knowledge.recalling）
    "search_rag": "正在检索 RAG",
    "search_rag_chunks": "正在检索 RAG",
    # 文本搜索
    "grep": "正在 grep 搜索",
    # 读文件
    "get_file": "正在读取文件",
    # 仓库分析 / 路由（语义对应 repo.routing / repo.research.*）
    "analyze_repository": "正在分析仓库",
    "route_repository": "正在分析仓库",
    "list_space_structure": "正在分析仓库",
    "find_related": "正在分析仓库",
}


def tool_event_to_progress(evt: AgentEvent) -> str | None:
    """把工具事件翻译为对外 progress 文本，未命中 / 不该透出时返回 None。

    行为契约：
    - 仅 `TOOL_USE_START`：取 `evt.data["tool_name"]` 查映射表，命中返回中文语义文本，
      未命中 / 缺 tool_name → None。
    - `TOOL_USE_RESULT` 及其余所有事件类型 → 一律 None（保守静默，OQ-3：完成态计数
      派生留 Plan 02 的 retrieval_to_progress 处理）。

    安全（INV-5）：只读 `tool_name`，绝不读取 / 内联 tool_input / result / error。
    """
    if evt.type != TOOL_USE_START:
        return None
    tool_name = evt.data.get("tool_name")
    if not tool_name:
        return None
    return _TOOL_PROGRESS_LABELS.get(tool_name)


def make_reasoning_chunk(common: dict[str, Any], text: str, include_usage: bool) -> bytes:
    """构造一个 `delta.reasoning_content` progress chunk 字节（复用 sse_encode）。

    结构与 adapter THINKING → reasoning_content chunk 逐字一致：
    `object` 来自 common、`choices=[{index:0, delta:{reasoning_content:text}, finish_reason:None}]`，
    `include_usage=True` 时带 `usage=None`（与 TEXT_DELTA / THINKING chunk 一致）。
    """
    chunk: dict[str, Any] = {
        **common,
        "choices": [{
            "index": 0,
            "delta": {"reasoning_content": text},
            "finish_reason": None,
        }],
    }
    if include_usage:
        chunk["usage"] = None
    return sse_encode(chunk)
