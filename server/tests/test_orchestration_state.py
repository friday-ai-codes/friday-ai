"""WorkflowState 和 RunPhase 类型定义单元测试。"""

from __future__ import annotations

from typing import get_type_hints

from orchestration.state import RunPhase, WorkflowState


class TestRunPhase:
    def test_has_seven_phases(self) -> None:
        # implementation 新增 WAITING_CLARIFICATION，从 6 个升到 7 个
        assert len(RunPhase) == 7

    def test_values(self) -> None:
        expected = {
            "planning",
            "executing",
            "waiting",
            "waiting_clarification",  # implementation
            "finalizing",
            "completed",
            "error",
        }
        assert {p.value for p in RunPhase} == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(RunPhase.PLANNING, str)
        assert RunPhase.PLANNING == "planning"

    def test_members(self) -> None:
        assert RunPhase.PLANNING.value == "planning"
        assert RunPhase.EXECUTING.value == "executing"
        assert RunPhase.WAITING.value == "waiting"
        assert RunPhase.WAITING_CLARIFICATION.value == "waiting_clarification"
        assert RunPhase.FINALIZING.value == "finalizing"
        assert RunPhase.COMPLETED.value == "completed"
        assert RunPhase.ERROR.value == "error"


class TestWorkflowState:
    def test_fields(self) -> None:
        hints = get_type_hints(WorkflowState)
        expected_fields = {
            "run_id", "phase", "blocking_tasks", "user_message", "final_answer",
            "blocking_results", "wait_execute_loops",
            "accumulated_thinking", "tool_calls", "parts", "user_parts", "result_metadata",
            "agent_session_id",
            # 协商暂停 payload
            "pending_clarification",
        }
        assert set(hints.keys()) == expected_fields

    def test_total_false(self) -> None:
        state: WorkflowState = {}  # type: ignore[typeddict-item]
        assert isinstance(state, dict)

    def test_can_construct_partial(self) -> None:
        state: WorkflowState = {"run_id": "abc-123", "phase": RunPhase.PLANNING}
        assert state["run_id"] == "abc-123"
        assert state["phase"] == "planning"

    def test_can_construct_full(self) -> None:
        state: WorkflowState = {
            "run_id": "run-001",
            "phase": RunPhase.EXECUTING,
            "blocking_tasks": [{"task_id": "t1"}],
            "user_message": "hello",
            "final_answer": "done",
        }
        assert len(state) == 5
