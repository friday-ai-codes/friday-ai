"""SSE 事件类型契约测试。

验证后端 events.py 的事件类型常量定义完整、正确，
确保前后端 SSE 事件类型始终保持一致。

前端 SSEEvent.type 联合类型应与 ALL_EVENT_TYPES 一一对应：
  'text_delta' | 'tool_use_start' | 'tool_use_result' | 'message_complete'
  | 'title_generated' | 'error' | 'thinking' | 'budget_warning'
"""

from __future__ import annotations

from agents.core.events import (
    ALL_EVENT_TYPES,
    AWAITING_PR_REVIEW,
    BUDGET_WARNING,
    CODING_COMPLETE,
    CODING_FAILED,
    CODING_PROGRESS,
    CONFLICT_CHECK,
    KEEPALIVE,
    PHASE_TRANSITION,
    PROCESS_EVENT,
    TASK_PROGRESS,
)


class TestSSEEventTypeContract:
    """SSE 事件类型契约：后端常量必须覆盖所有前端已知事件类型。"""

    EXPECTED_EVENT_TYPES: frozenset[str] = frozenset({
        "text_delta",
        "tool_use_start",
        "tool_use_result",
        "message_complete",
        "thinking",
        "error",
        "title_generated",
        "budget_warning",
        "deep_analysis_progress",
        "phase_transition",
        "task_progress",
        "doc_summary",
        "doc_error",
        "coding_progress",
        "coding_complete",
        "coding_failed",
        "awaiting_pr_review",
        "conflict_check",
        # parts contract：parts 双轨期新事件（与旧事件共存）
        "part_started",
        "part_delta",
        "part_completed",
        # Phase 110-01：编排过程事件（ConvergenceSessionEvent 统一信封）。
        # 前端那半边（web/src/types/chat.ts 的 SSEEvent.type 联合类型）由 110-03 与消费
        # 同批落地——本契约测试只比对后端常量集，不会因前端未同步而变红。
        "process_event",
    })

    def test_all_event_types_contains_expected(self) -> None:
        """ALL_EVENT_TYPES 恰好包含 22 种预期事件类型（18 legacy + 3 parts + 1 编排过程事件）。"""
        assert ALL_EVENT_TYPES == self.EXPECTED_EVENT_TYPES, (
            f"ALL_EVENT_TYPES 与预期不符。\n"
            f"  多余: {ALL_EVENT_TYPES - self.EXPECTED_EVENT_TYPES}\n"
            f"  缺少: {self.EXPECTED_EVENT_TYPES - ALL_EVENT_TYPES}"
        )

    def test_all_event_types_count(self) -> None:
        """ALL_EVENT_TYPES 应恰好包含 22 种类型（18 legacy + 3 parts + 1 编排过程事件）。"""
        assert len(ALL_EVENT_TYPES) == 22, (
            f"期望 22 种事件类型，实际 {len(ALL_EVENT_TYPES)}: {ALL_EVENT_TYPES}"
        )

    def test_budget_warning_constant(self) -> None:
        """BUDGET_WARNING 常量值为 'budget_warning'。"""
        assert BUDGET_WARNING == "budget_warning"

    def test_phase_transition_constant(self) -> None:
        """PHASE_TRANSITION 常量值为 'phase_transition'。"""
        assert PHASE_TRANSITION == "phase_transition"

    def test_task_progress_constant(self) -> None:
        """TASK_PROGRESS 常量值为 'task_progress'。"""
        assert TASK_PROGRESS == "task_progress"

    def test_keepalive_constant(self) -> None:
        """KEEPALIVE 常量值为 'keepalive'。"""
        assert KEEPALIVE == "keepalive"

    def test_coding_progress_constant(self) -> None:
        """CODING_PROGRESS 常量值为 'coding_progress'。"""
        assert CODING_PROGRESS == "coding_progress"

    def test_coding_complete_constant(self) -> None:
        """CODING_COMPLETE 常量值为 'coding_complete'。"""
        assert CODING_COMPLETE == "coding_complete"

    def test_coding_failed_constant(self) -> None:
        """CODING_FAILED 常量值为 'coding_failed'。"""
        assert CODING_FAILED == "coding_failed"

    def test_awaiting_pr_review_constant(self) -> None:
        """AWAITING_PR_REVIEW 常量值为 'awaiting_pr_review'。"""
        assert AWAITING_PR_REVIEW == "awaiting_pr_review"

    def test_process_event_constant(self) -> None:
        """PROCESS_EVENT 常量值为 'process_event'。"""
        assert PROCESS_EVENT == "process_event"

    def test_conflict_check_constant(self) -> None:
        """CONFLICT_CHECK 常量值为 'conflict_check'。"""
        assert CONFLICT_CHECK == "conflict_check"

    def test_keepalive_not_in_all_event_types(self) -> None:
        """KEEPALIVE 不应在 ALL_EVENT_TYPES 中（它是连接级事件，不走 SSE data 行）。"""
        assert KEEPALIVE not in ALL_EVENT_TYPES, (
            "keepalive 是连接级事件，不应被包含在 SSE data 事件类型集合中"
        )

    def test_heartbeat_default_interval(self) -> None:
        """Keepalive 心跳间隔默认值为 15.0 秒。"""
        from agents.sdk.runner import SdkRunnerConfig

        config = SdkRunnerConfig(
            system_prompt="test",
            model="test",
            space_id="test",
            session_id="test",
        )
        assert config.heartbeat_timeout == 15.0, (
            f"期望心跳间隔 15.0 秒，实际 {config.heartbeat_timeout}"
        )
