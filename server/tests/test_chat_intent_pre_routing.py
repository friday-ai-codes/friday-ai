"""chat_graph 编排前置 gate 集成测试（unit 层）。

复用 ``test_chat_graph_clarification_interrupt`` 的 monkeypatch + helper 模式，
聚焦 ``_annotate_intent_classification`` 写入与 LLM 主动 ``ask_clarification``
路径（``_extract_pending_clarification``）。

注：编排层基于 RELEV 低置信「强制澄清」的硬约束已下线 —— 是否澄清完全由
LLM 自行决定（调 ask_clarification 工具），故相关测试一并移除。

不启动真实 ChatAnthropicRunner —— 这与 plan 03 单测一致，避免触碰 Anthropic
API key + OrchestrationRun UUID 校验等集成依赖；端到端联动需走人工 UAT。
"""
from __future__ import annotations

from typing import Any

import pytest

from agents.intent_router import IntentClassification
from chat.conversation_service import _build_system_prompt
from orchestration.graph import (
    _annotate_intent_classification,
    _extract_pending_clarification,
    route_after_executing,
)
from orchestration.state import RunPhase


def _relev_tool_call(result: Any) -> dict[str, Any]:
    return {
        "id": "tool-relev-1",
        "name": "analyze_repository_relevance",
        "input": {"query": "test"},
        "result": result,
        "status": "done",
    }


def _low_confidence_relev() -> dict[str, Any]:
    return {
        "data": {
            "candidates": [
                {
                    "repository_id": "r1",
                    "repository_name": "friday-server",
                    "score": 0.9,
                    "selected_by_user_final": True,
                    "evidence": "5 个文件",
                },
                {
                    "repository_id": "r2",
                    "repository_name": "friday-web",
                    "score": 0.85,  # ratio 0.94 → low
                    "selected_by_user_final": True,
                    "evidence": "4 个文件",
                },
            ],
        },
        "metadata": {"trace_id": "trace-1"},
    }


class TestAnnotateIntentClassification:
    def test_writes_classification_to_metadata(self) -> None:
        state = {"user_message": "帮我修复 favorites"}
        result = _annotate_intent_classification(state, {})  # type: ignore[arg-type]
        assert "intent_classification" in result
        cls = result["intent_classification"]
        assert cls["is_coding_request"] is True
        assert cls["confidence"] == "high"
        assert "修复" in cls["matched_verbs"]

    def test_preserves_existing_metadata_keys(self) -> None:
        state = {"user_message": "改一下"}
        result = _annotate_intent_classification(  # type: ignore[arg-type]
            state, {"existing_key": "value", "input_tokens": 100},
        )
        assert result["existing_key"] == "value"
        assert result["input_tokens"] == 100
        assert "intent_classification" in result

    def test_low_signal_for_qa_message(self) -> None:
        state = {"user_message": "为什么 X 跳到 Y？"}
        result = _annotate_intent_classification(state, {})  # type: ignore[arg-type]
        assert result["intent_classification"]["is_coding_request"] is False
        assert result["intent_classification"]["confidence"] == "low_signal"


class TestRouteAfterExecutingWithClarification:
    """phase=waiting_clarification 路由分支已在 plan 03 验证；此处补一个集成断言：
    pending_clarification 非空时 graph 的 phase 必然写成 waiting_clarification。
    """

    def test_pending_phase_routes_to_wait_clarification(self) -> None:
        state = {
            "phase": RunPhase.WAITING_CLARIFICATION.value,
            "pending_clarification": {"clarification_id": "abc"},
        }
        assert route_after_executing(state) == "wait_clarification"  # type: ignore[arg-type]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestSystemPromptIntentHint:
    """``_build_system_prompt`` 接受 IntentClassification 后追加 per-turn hint。"""

    @pytest.fixture(autouse=True)
    def _force_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        disabled = ",".join([
            "chat.system.developer",
            "chat.strategy.default",
            "chat.coding_guidance",
        ])
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", disabled)

    async def test_coding_request_appends_per_turn_hint(self) -> None:
        classification = IntentClassification(
            is_coding_request=True,
            matched_verbs=("修复", "重构"),
            confidence="high",
        )
        prompt = await _build_system_prompt(
            "P", "proj-1", role="developer",
            intent_classification=classification,
        )
        assert "本轮检测到编码请求" in prompt
        assert "必须先调用 analyze_repository_relevance" in prompt
        assert "修复" in prompt
        assert "重构" in prompt

    async def test_non_coding_does_not_append_hint(self) -> None:
        classification = IntentClassification(
            is_coding_request=False,
            matched_verbs=(),
            confidence="low_signal",
        )
        prompt = await _build_system_prompt(
            "P", "proj-1", role="developer",
            intent_classification=classification,
        )
        assert "本轮检测到编码请求" not in prompt

    async def test_default_none_byte_level_compatible(self) -> None:
        """默认 None → 与历史版本字节级一致（既有 65+ 测试 0 回归契约）。"""
        prompt_with_none = await _build_system_prompt(
            "P", "proj-1", role="developer",
        )
        prompt_explicit_none = await _build_system_prompt(
            "P", "proj-1", role="developer",
            intent_classification=None,
        )
        assert prompt_with_none == prompt_explicit_none
        assert "本轮检测到编码请求" not in prompt_with_none


class TestExtractPendingClarificationPriority:
    """LLM 主动调 ``ask_clarification`` 时 ``_extract_pending_clarification`` 命中。

    即便同一轮里还有 analyze_repository_relevance 的低置信结果，编排层也不再
    据此自动澄清 —— 是否澄清完全由 LLM 决定。
    """

    def test_explicit_ask_clarification_takes_priority(self) -> None:
        """LLM 主动调 ask_clarification 时 _extract_pending_clarification 命中。"""
        tool_calls = {
            "tool-clar": {
                "id": "tool-clar",
                "name": "ask_clarification",
                "input": {},
                "result": {
                    "clarification_id": "explicit-1",
                    "pending": True,
                    "marker": "ask_clarification",
                    "question": "选 A 还是 B？",
                    "options": [
                        {"id": "opt-A", "label": "A"},
                        {"id": "opt-B", "label": "B"},
                    ],
                    "allow_freeform": True,
                },
                "status": "done",
            },
            "tool-relev": _relev_tool_call(_low_confidence_relev()),
        }
        # _extract_pending_clarification 优先识别 LLM 主动调 → 拿到 explicit-1
        explicit = _extract_pending_clarification(tool_calls)
        assert explicit is not None
        assert explicit["clarification_id"] == "explicit-1"
