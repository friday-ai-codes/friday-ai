"""失败 ToolResult 的定位键出网链（110-HI-01）。

评审发现的缺口是一个**形状**问题，不是取值问题：两个编排工具的失败终态返回的
`ToolResult(success=False, error=…)` 结构上不含任何 id，而 `_normalize_tool_result`
把它固化成 `{"error": …, "is_error": true}`——前端气泡因此能 JSON.parse 却取不到
`session_id`，只能回退 store 的全局活跃会话。同一对话里「失败后重跑」时，失败那条
气泡就改显示新一轮的实时时间线。

原有用例只覆盖「在途、根本没有 result」这一种绑不到会话的形态（那正是兜底**应该**
生效的一种），没有任何一条覆盖「终态、result 可解析但缺 session_id」——这里补上。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from agents.chat_runner import _normalize_tool_result
from agents.tools.base import ToolResult


class TestNormalizeToolResultFailureBody:
    def test_metadata_is_merged_into_the_failure_body(self) -> None:
        """失败体带上工具显式给出的定位键（气泡靠它绑回自己那次编排）。"""
        sid = str(uuid.uuid4())

        body = _normalize_tool_result(
            ToolResult(success=False, error="boom", metadata={"session_id": sid})
        )

        assert body["session_id"] == sid
        assert body["error"] == "boom"
        assert body["is_error"] is True

    def test_metadata_cannot_override_the_error_flags(self) -> None:
        """🔴 固定两键必须在最后展开——否则一个工具就能把 is_error 翻成 false。

        与上一条分开写：合成一条时第一个断言先红，会把这条的覆盖面整个遮住。
        """
        body = _normalize_tool_result(
            ToolResult(
                success=False,
                error="真实错误",
                metadata={"is_error": False, "error": "伪造的成功"},
            )
        )

        assert body["is_error"] is True
        assert body["error"] == "真实错误"

    def test_empty_metadata_keeps_the_legacy_two_key_shape(self) -> None:
        """无 metadata 的工具（绝大多数）出网形状逐字不变。"""
        assert _normalize_tool_result(ToolResult(success=False, error="x")) == {
            "error": "x",
            "is_error": True,
        }

    def test_success_path_still_returns_output_verbatim(self) -> None:
        """成功分支不受影响：metadata 不并进 output（suspension 等既有 metadata 不出网）。"""
        out = {"session_id": "s-1", "status": "done"}

        assert (
            _normalize_tool_result(
                ToolResult(success=True, output=out, metadata={"suspension": True})
            )
            is out
        )


class TestPlanResearchTerminalFailureCarriesSessionId:
    def test_failed_terminal_result_has_session_id_in_metadata(self) -> None:
        from agents.tools.plan_research_tools import _map_terminal
        from delivery.models import ConvergenceSessionStatus

        sid = uuid.uuid4()
        session = SimpleNamespace(
            id=sid,
            status=ConvergenceSessionStatus.FAILED,
            error={"message": "上游 500：<html>boom</html>"},
        )

        result = _map_terminal(session)

        assert result.success is False
        assert result.metadata == {"session_id": str(sid)}

    def test_failure_body_end_to_end_is_bindable(self) -> None:
        """🔴 端到端形状：出网体既是失败态、又带得回会话——这正是评审缺的那条形状。"""
        from agents.tools.plan_research_tools import _map_terminal
        from delivery.models import ConvergenceSessionStatus

        sid = uuid.uuid4()
        body = _normalize_tool_result(
            _map_terminal(
                SimpleNamespace(
                    id=sid,
                    status=ConvergenceSessionStatus.FAILED,
                    error={"reason": "merge_validation_exhausted"},
                )
            )
        )

        assert body["is_error"] is True
        assert body["session_id"] == str(sid)
