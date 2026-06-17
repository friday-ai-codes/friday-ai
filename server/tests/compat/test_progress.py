"""compat.progress 纯函数映射单测 + 安全 sentinel 不泄漏测（VALIDATION 6.1 / 6.4）。

测试覆盖：
  - tool_event_to_progress：各内部工具名 → 中文语义；未知/缺名/非工具事件 → None；
    TOOL_USE_RESULT 一律静默。
  - INV-5 安全：含敏感 sentinel 的 tool_input/result/error 绝不出现在 helper 返回值。
  - make_reasoning_chunk：reasoning_content chunk 结构（object/finish_reason/usage）。
"""

from __future__ import annotations

import json

import pytest

from agents.core.events import (
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
    AgentEvent,
)
from compat.progress import (
    make_reasoning_chunk,
    retrieval_to_progress,
    tool_event_to_progress,
)

# ──────────────────────────────────────────────────────────────────────────────
# 6.1 纯函数映射单测
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("search_rag", "正在检索 RAG"),
        ("search_rag_chunks", "正在检索 RAG"),
        ("grep", "正在 grep 搜索"),
        ("get_file", "正在读取文件"),
        ("analyze_repository", "正在分析仓库"),
        ("route_repository", "正在分析仓库"),
        ("list_space_structure", "正在分析仓库"),
        ("find_related", "正在分析仓库"),
    ],
)
def test_tool_use_start_maps_to_chinese_label(tool_name: str, expected: str) -> None:
    """各内部工具名 TOOL_USE_START → 预期中文 progress 文本。"""
    evt = AgentEvent(type=TOOL_USE_START, data={"tool_name": tool_name})
    assert tool_event_to_progress(evt) == expected


def test_unknown_tool_returns_none() -> None:
    """未知工具名 → None（保守静默，不泄漏内部工具名）。"""
    evt = AgentEvent(type=TOOL_USE_START, data={"tool_name": "some_unknown_tool"})
    assert tool_event_to_progress(evt) is None


def test_missing_tool_name_returns_none() -> None:
    """缺 tool_name → None。"""
    assert tool_event_to_progress(AgentEvent(type=TOOL_USE_START, data={})) is None


def test_tool_use_result_always_silent() -> None:
    """TOOL_USE_RESULT 一律返回 None（即使工具名命中映射表，OQ-3 保守静默）。"""
    evt = AgentEvent(
        type=TOOL_USE_RESULT,
        data={"tool_name": "search_rag", "success": True, "result": "命中若干"},
    )
    assert tool_event_to_progress(evt) is None


@pytest.mark.parametrize("event_type", [THINKING, TEXT_DELTA, MESSAGE_COMPLETE])
def test_non_tool_events_not_matched(event_type: str) -> None:
    """非工具事件即使被误传入也返 None（不误命中）。"""
    evt = AgentEvent(type=event_type, data={"tool_name": "search_rag", "thinking": "x"})
    assert tool_event_to_progress(evt) is None


# ──────────────────────────────────────────────────────────────────────────────
# 6.4 安全 sentinel 不泄漏（INV-5）
# ──────────────────────────────────────────────────────────────────────────────


def test_progress_text_never_leaks_tool_input_sentinel() -> None:
    """TOOL_USE_START.data 含敏感 tool_input → helper 返回值不含 sentinel。"""
    sentinel = "SENTINEL_SECRET_KEY_abc"
    evt = AgentEvent(
        type=TOOL_USE_START,
        data={"tool_name": "search_rag", "tool_input": sentinel, "tool_call_id": "c1"},
    )
    result = tool_event_to_progress(evt)
    assert result == "正在检索 RAG"
    assert sentinel not in (result or "")


def test_progress_text_never_leaks_result_or_error_sentinel() -> None:
    """TOOL_USE_RESULT 含敏感 result/error → helper 返回 None，不泄漏任何 sentinel。"""
    result_sentinel = "SENTINEL_PRIVATE_CODE_xyz"
    error_sentinel = "SENTINEL_TRACEBACK"
    ok_evt = AgentEvent(
        type=TOOL_USE_RESULT,
        data={"tool_name": "search_rag", "success": True, "result": result_sentinel},
    )
    err_evt = AgentEvent(
        type=TOOL_USE_RESULT,
        data={"tool_name": "grep", "success": False, "error": error_sentinel},
    )
    for evt, sentinel in [(ok_evt, result_sentinel), (err_evt, error_sentinel)]:
        out = tool_event_to_progress(evt)
        assert out is None
        assert sentinel not in (out or "")


# ──────────────────────────────────────────────────────────────────────────────
# Plan 02：retrieval_to_progress 纯函数（命中计数→progress 文本，非敏感）
# ──────────────────────────────────────────────────────────────────────────────


class _FakeLayer:
    """鸭子类型层快照：仅暴露 result_count。"""

    def __init__(self, result_count: int) -> None:
        self.result_count = result_count


class _FakeResult:
    """鸭子类型检索结果：兼容 RagSearchResult / HybridSearchResult 字段子集。"""

    def __init__(
        self,
        *,
        final_context: str = "",
        layers: list[_FakeLayer] | None = None,
        repository_ids: list[str] | None = None,
        query: str = "",
    ) -> None:
        self.final_context = final_context
        self.layers = layers or []
        self.repository_ids = repository_ids or []
        self.query = query


def test_retrieval_hit_returns_two_progress_texts() -> None:
    """命中（final_context 非空 + layers result_count=3）→ 两条 progress，第二条含 N=3。"""
    result = _FakeResult(final_context="ctx", layers=[_FakeLayer(3)])
    assert retrieval_to_progress(result) == ["正在检索 RAG…", "检索完成，命中 3 处"]


def test_retrieval_hit_sums_multiple_layers() -> None:
    """多层 result_count 求和（2 + 5 = 7）。"""
    result = _FakeResult(final_context="ctx", layers=[_FakeLayer(2), _FakeLayer(5)])
    assert retrieval_to_progress(result) == ["正在检索 RAG…", "检索完成，命中 7 处"]


def test_retrieval_empty_context_returns_empty() -> None:
    """未命中（final_context 空）→ 空列表（不合成）。"""
    assert retrieval_to_progress(_FakeResult(final_context="")) == []


def test_retrieval_none_result_returns_empty() -> None:
    """result 为 None → 空列表。"""
    assert retrieval_to_progress(None) == []


def test_retrieval_empty_layers_falls_back_to_repository_ids() -> None:
    """layers 空、repository_ids=["a","b"] → N==2（回退计数）。"""
    result = _FakeResult(final_context="ctx", layers=[], repository_ids=["a", "b"])
    assert retrieval_to_progress(result) == ["正在检索 RAG…", "检索完成，命中 2 处"]


def test_retrieval_progress_never_leaks_sentinel() -> None:
    """sentinel 安全：final_context/query 含敏感串 → 两条 progress 文本均不含任一 sentinel。"""
    result = _FakeResult(
        final_context="SENTINEL_CTX_secret 代码上下文片段",
        layers=[_FakeLayer(1)],
        query="SENTINEL_QUERY 用户原始问题",
    )
    texts = retrieval_to_progress(result)
    assert len(texts) == 2
    joined = "".join(texts)
    assert "SENTINEL_CTX_secret" not in joined
    assert "SENTINEL_QUERY" not in joined


# ──────────────────────────────────────────────────────────────────────────────
# 6.1 make_reasoning_chunk 结构
# ──────────────────────────────────────────────────────────────────────────────


def _common() -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "friday-default",
    }


def _parse_chunk(raw: bytes) -> dict[str, object]:
    line = raw.decode()
    assert line.startswith("data: ")
    return json.loads(line[6:].strip())


def test_make_reasoning_chunk_structure_without_usage() -> None:
    """include_usage=False：reasoning_content 正确、finish_reason=None、object 正确、无 usage 键。"""
    payload = _parse_chunk(make_reasoning_chunk(_common(), "正在检索 RAG", False))
    choice = payload["choices"][0]
    assert choice["delta"]["reasoning_content"] == "正在检索 RAG"
    assert choice["finish_reason"] is None
    assert payload["object"] == "chat.completion.chunk"
    assert "usage" not in payload


def test_make_reasoning_chunk_structure_with_usage() -> None:
    """include_usage=True：带 usage 键且为 None（与 TEXT_DELTA/THINKING chunk 一致）。"""
    payload = _parse_chunk(make_reasoning_chunk(_common(), "正在 grep 搜索", True))
    assert payload["choices"][0]["delta"]["reasoning_content"] == "正在 grep 搜索"
    assert "usage" in payload
    assert payload["usage"] is None
