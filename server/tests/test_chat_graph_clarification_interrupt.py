"""chat_graph 协商 interrupt 单元测试（implementation / work item）。

走 ``_extract_pending_clarification`` + ``wait_clarification_node`` 单元覆盖，
**不**启动真实 ``ChatAnthropicRunner`` —— 真 LLM 集成测试需要 Anthropic key
+ MemorySaver checkpointer，已超出 plan 03 scope。本文件聚焦：

- ``_extract_pending_clarification`` 能正确识别 dict 与 JSON 字符串两种形态。
- ``wait_clarification_node`` 在 mock interrupt 下能把 resume payload merge
  到 ``result_metadata.inferred_intent`` 与 ``user_message``。
- ``route_after_executing`` 在 ``phase=waiting_clarification`` 时返回
  ``"wait_clarification"`` 分支。
- ``build_graph()`` 的 builder 包含 ``wait_clarification`` 节点与
  ``executing`` 之间的边。
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from orchestration.graph import (
    _extract_pending_clarification,
    build_graph,
    route_after_executing,
    wait_clarification_node,
)
from orchestration.state import RunPhase


def _ask_clarification_tool_call(result: Any) -> dict[str, Any]:
    return {
        "id": "tool-1",
        "name": "ask_clarification",
        "input": {"question": "你想改哪个仓库？"},
        "result": result,
        "status": "done",
    }


def _ask_clarification_payload() -> dict[str, Any]:
    return {
        "clarification_id": "abc123",
        "pending": True,
        "marker": "ask_clarification",
        "question": "你想改哪个仓库？",
        "options": [
            {"id": "opt-A", "label": "改 friday-server"},
            {"id": "opt-B", "label": "改 friday-web"},
        ],
        "allow_freeform": True,
    }


class TestExtractPendingClarification:
    """``_extract_pending_clarification`` 能从 tool_calls 字典里识别 marker。"""

    def test_dict_result_extracted(self) -> None:
        tool_calls = {"tool-1": _ask_clarification_tool_call(_ask_clarification_payload())}
        payload = _extract_pending_clarification(tool_calls)
        assert payload is not None
        assert payload["clarification_id"] == "abc123"
        assert payload["allow_freeform"] is True
        assert len(payload["options"]) == 2

    def test_json_string_result_extracted(self) -> None:
        """chat_runner 把 dict result 序列化成 JSON string 再放入 messages。"""
        tool_calls = {
            "tool-1": _ask_clarification_tool_call(
                json.dumps(_ask_clarification_payload(), ensure_ascii=False),
            ),
        }
        payload = _extract_pending_clarification(tool_calls)
        assert payload is not None
        assert payload["clarification_id"] == "abc123"

    def test_other_tool_not_extracted(self) -> None:
        tool_calls = {
            "tool-1": {
                "id": "tool-1",
                "name": "search_repository_code",
                "result": {"matched": 3},
                "status": "done",
            }
        }
        assert _extract_pending_clarification(tool_calls) is None

    def test_missing_marker_not_extracted(self) -> None:
        bad = {**_ask_clarification_payload(), "marker": "other_marker"}
        tool_calls = {"tool-1": _ask_clarification_tool_call(bad)}
        assert _extract_pending_clarification(tool_calls) is None

    def test_missing_pending_flag_not_extracted(self) -> None:
        bad = {**_ask_clarification_payload(), "pending": False}
        tool_calls = {"tool-1": _ask_clarification_tool_call(bad)}
        assert _extract_pending_clarification(tool_calls) is None

    def test_invalid_json_string_not_extracted(self) -> None:
        tool_calls = {"tool-1": _ask_clarification_tool_call("not valid json {")}
        assert _extract_pending_clarification(tool_calls) is None


class TestRouteAfterExecuting:
    """``route_after_executing`` 在 ``phase=waiting_clarification`` 分支正确。"""

    def test_waiting_clarification_routes_to_wait_clarification(self) -> None:
        state = {
            "phase": RunPhase.WAITING_CLARIFICATION.value,
            "pending_clarification": _ask_clarification_payload(),
        }
        assert route_after_executing(state) == "wait_clarification"  # type: ignore[arg-type]

    def test_finalizing_unchanged_for_normal_phase(self) -> None:
        state = {"phase": RunPhase.EXECUTING.value}
        assert route_after_executing(state) == "finalizing"  # type: ignore[arg-type]


class TestBuildGraph:
    """``build_graph()`` 注册 ``wait_clarification`` 节点 + edges。"""

    def test_wait_clarification_node_registered(self) -> None:
        builder = build_graph()
        assert "wait_clarification" in builder.nodes

    def test_wait_clarification_edge_back_to_executing(self) -> None:
        """resume 后 wait_clarification → executing。"""
        builder = build_graph()
        edges = builder.edges
        # builder.edges 是 set of tuples (start, end)
        assert ("wait_clarification", "executing") in edges


class TestWaitClarificationNode:
    """``wait_clarification_node`` 在 resume 后正确改写 user_message + metadata。"""

    @pytest.mark.asyncio
    async def test_resume_with_implies_merges_into_metadata(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """interrupt 返回的 resume 值是 dict，wait_clarification_node 解析后注入
        ``result_metadata.inferred_intent`` 与 ``user_message``。

        通过 monkeypatch 替换 ``orchestration.graph.interrupt`` 模拟 resume。
        """
        from orchestration import graph as graph_module

        captured: dict[str, Any] = {}

        def fake_interrupt(payload: Any) -> Any:
            captured["interrupt_payload"] = payload
            return {
                "clarification_id": "abc123",
                "selected_option_id": "opt-A",
                "selected_option_label": "改 friday-server",
                "freeform_text": None,
                "implies": {"selected_repository_ids": ["uuid-1"]},
            }

        monkeypatch.setattr(graph_module, "interrupt", fake_interrupt)

        state: dict[str, Any] = {
            "pending_clarification": _ask_clarification_payload(),
            "result_metadata": {"already": "kept"},
        }
        result = await wait_clarification_node(state)  # type: ignore[arg-type]

        # interrupt payload 含 clarification_id / question / options
        assert captured["interrupt_payload"]["clarification_id"] == "abc123"
        assert captured["interrupt_payload"]["question"] == "你想改哪个仓库？"
        # resume 后 phase 回到 executing，user_message 改成用户答复
        assert result["phase"] == RunPhase.EXECUTING.value
        assert result["user_message"] == "改 friday-server"
        # pending_clarification 清空
        assert result["pending_clarification"] == {}
        # result_metadata 合并 inferred + 保留原 key
        assert result["result_metadata"]["already"] == "kept"
        assert result["result_metadata"]["inferred_intent"] == {
            "selected_repository_ids": ["uuid-1"],
        }
        assert result["result_metadata"]["last_clarification_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_freeform_overrides_selected_label(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from orchestration import graph as graph_module

        def fake_interrupt(payload: Any) -> Any:
            return {
                "clarification_id": "abc123",
                "selected_option_id": "opt-A",
                "selected_option_label": "选项 A 标签",
                "freeform_text": "我自己写答案：改 X 模块",
                "implies": {},
            }

        monkeypatch.setattr(graph_module, "interrupt", fake_interrupt)

        result = await wait_clarification_node(  # type: ignore[arg-type]
            {"pending_clarification": _ask_clarification_payload()},
        )
        assert result["user_message"] == "我自己写答案：改 X 模块"

    @pytest.mark.asyncio
    async def test_empty_resume_safe_defaults(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """resume payload 非 dict 时降级到空值，不抛异常。"""
        from orchestration import graph as graph_module

        monkeypatch.setattr(graph_module, "interrupt", lambda _payload: None)

        result = await wait_clarification_node(  # type: ignore[arg-type]
            {"pending_clarification": _ask_clarification_payload()},
        )
        assert result["phase"] == RunPhase.EXECUTING.value
        assert result["user_message"] == ""
        assert result["result_metadata"]["inferred_intent"] == {}
