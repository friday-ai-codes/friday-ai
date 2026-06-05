"""orchestration._StreamingSnapshot 单元测试 + flush/clear 集成测试。

覆盖目标（per "刷新空气泡" 修复）：
- ingest 各事件类型后 snapshot_payload 与前端 streaming state 字段一致
- 同 batch_id 在 tool_calls / timeline 上保留
- 节流：should_flush 在普通事件下按 0.5s 间隔放行，关键事件立即放行
- flush / _clear_streaming_snapshot 正确读写 OrchestrationRun.metadata
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from agents.core.events import (
    MESSAGE_COMPLETE,
    PHASE_TRANSITION,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)
from orchestration.graph import _StreamingSnapshot, _clear_streaming_snapshot


def _ingest(snapshot: _StreamingSnapshot, events: list[tuple[str, dict[str, Any]]]) -> None:
    for event_type, data in events:
        snapshot.ingest(event_type, data)


class TestStreamingSnapshotIngest:
    def test_text_delta_accumulates_into_pending_text(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(TEXT_DELTA, {"text": "Hello"})
        snap.ingest(TEXT_DELTA, {"text": ", world"})

        payload = snap.snapshot_payload()
        assert payload["pending_text"] == "Hello, world"
        assert payload["thinking"] == ""
        assert payload["tool_calls"] == []
        assert payload["timeline"] == []
        assert payload["narrations"] == []

    def test_thinking_merges_into_single_timeline_node(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(THINKING, {"thinking": "Let me think..."})
        snap.ingest(THINKING, {"thinking": " more"})

        payload = snap.snapshot_payload()
        assert payload["thinking"] == "Let me think... more"
        assert len(payload["timeline"]) == 1
        assert payload["timeline"][0]["kind"] == "thinking"
        assert payload["timeline"][0]["text"] == "Let me think... more"

    def test_tool_start_flushes_pending_text_to_narration(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        _ingest(
            snap,
            [
                (TEXT_DELTA, {"text": "我来搜一下"}),
                (
                    TOOL_USE_START,
                    {
                        "tool_call_id": "t1",
                        "tool_name": "search_repository_code",
                        "input": {"query": "foo"},
                        "batch_id": "batch_a",
                    },
                ),
            ],
        )

        payload = snap.snapshot_payload()
        assert payload["pending_text"] == ""
        assert payload["narrations"] == ["我来搜一下"]
        assert [item["kind"] for item in payload["timeline"]] == ["narration", "tool"]
        narr, tool = payload["timeline"]
        assert narr["text"] == "我来搜一下"
        assert tool["id"] == "t1"
        assert tool["status"] == "running"
        assert tool["batch_id"] == "batch_a"
        assert payload["tool_calls"] == [
            {
                "id": "t1",
                "name": "search_repository_code",
                "input": {"query": "foo"},
                "result": None,
                "status": "running",
                "batch_id": "batch_a",
            }
        ]

    def test_tool_result_updates_status_and_keeps_batch_id(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        _ingest(
            snap,
            [
                (
                    TOOL_USE_START,
                    {
                        "tool_call_id": "t1",
                        "tool_name": "search_repository_code",
                        "input": {"query": "foo"},
                        "batch_id": "batch_a",
                    },
                ),
                (
                    TOOL_USE_RESULT,
                    {
                        "tool_call_id": "t1",
                        "tool_name": "search_repository_code",
                        "result": "found 3 matches",
                        "batch_id": "batch_a",
                    },
                ),
            ],
        )
        payload = snap.snapshot_payload()
        assert payload["tool_calls"][0]["status"] == "done"
        assert payload["tool_calls"][0]["result"] == "found 3 matches"
        assert payload["tool_calls"][0]["batch_id"] == "batch_a"
        assert payload["timeline"][-1]["status"] == "done"
        assert payload["timeline"][-1]["result"] == "found 3 matches"

    def test_dict_result_serialized_to_json_string(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(TOOL_USE_START, {"tool_call_id": "t1", "tool_name": "x"})
        snap.ingest(
            TOOL_USE_RESULT,
            {"tool_call_id": "t1", "result": {"data": {"count": 3}}},
        )
        payload = snap.snapshot_payload()
        assert payload["tool_calls"][0]["result"] == '{"data": {"count": 3}}'

    def test_same_batch_id_shared_across_tools(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        _ingest(
            snap,
            [
                (TOOL_USE_START, {"tool_call_id": "t1", "tool_name": "a", "batch_id": "B"}),
                (TOOL_USE_START, {"tool_call_id": "t2", "tool_name": "b", "batch_id": "B"}),
            ],
        )
        payload = snap.snapshot_payload()
        assert [tc["batch_id"] for tc in payload["tool_calls"]] == ["B", "B"]

    def test_message_complete_does_not_clear_pending_text(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(TEXT_DELTA, {"text": "hi"})
        snap.ingest(MESSAGE_COMPLETE, {"final_answer": "hi"})
        payload = snap.snapshot_payload()
        # 前端 message_complete 才会把 pending_text 转 final + 清空，
        # snapshot 维持 pending_text 直到 stream 结束（snapshot 被 clear）。
        assert payload["pending_text"] == "hi"


class TestShouldFlushThrottle:
    def test_no_flush_when_not_dirty(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        assert snap.should_flush(TEXT_DELTA) is False

    def test_important_events_force_flush(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(TEXT_DELTA, {"text": "x"})
        for checkpoint in (
            TOOL_USE_START,
            TOOL_USE_RESULT,
            MESSAGE_COMPLETE,
            PHASE_TRANSITION,
        ):
            assert snap.should_flush(checkpoint) is True, checkpoint

    def test_regular_events_throttled_to_half_second(self) -> None:
        snap = _StreamingSnapshot(run_id="run-1")
        snap.ingest(TEXT_DELTA, {"text": "x"})
        snap._last_flush_ts = time.monotonic() - 0.1
        assert snap.should_flush(TEXT_DELTA) is False
        snap._last_flush_ts = time.monotonic() - 1.0
        assert snap.should_flush(TEXT_DELTA) is True


class _AsyncIterator:
    """辅助 async iterator，复用 test_conversation_runtime 里同名的小工具。"""

    def __init__(self, items: list[Any]) -> None:
        self._items = iter(items)

    def __aiter__(self) -> _AsyncIterator:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_run(
    *,
    status: str = "running",
    phase: str = "executing",
    metadata: dict[str, Any] | None = None,
) -> Any:
    from unittest.mock import MagicMock

    from django.utils import timezone

    from orchestration.models import OrchestrationRun

    mock = MagicMock(spec=OrchestrationRun)
    mock.status = status
    mock.phase = phase
    mock.run_id = "test-run-id"
    mock.metadata = metadata or {}
    mock.created_at = timezone.now()
    mock.id = 1
    return mock


def _patch_orch_session(mock_run: Any) -> Any:
    """复用 test_conversation_runtime 的 patch 套路：OrchestrationRun + SubAgentSession 全 mock。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from orchestration.models import OrchestrationRun

    orch_patcher = patch("chat.conversation_service.OrchestrationRun")
    sess_patcher = patch("subagent.models.SubAgentSession")
    mock_orch_cls = orch_patcher.start()
    mock_sess_cls = sess_patcher.start()
    mock_orch_cls.Status = OrchestrationRun.Status
    mock_orch_cls.Phase = OrchestrationRun.Phase
    mock_orch_cls.objects.filter.return_value.order_by.return_value.afirst = AsyncMock(
        return_value=mock_run,
    )
    mock_sess_cls.TaskType.EXPLORE = "explore"
    mock_sess_cls.Status.PENDING = "pending"
    mock_sess_cls.Status.RUNNING = "running"
    qs = MagicMock()
    qs.order_by.return_value = _AsyncIterator([])
    mock_sess_cls.objects.filter.return_value = qs
    return orch_patcher, sess_patcher


@pytest.mark.django_db(transaction=True)
class TestGetConversationRuntimeExposesSnapshot:
    """get_conversation_runtime 把 metadata['streaming_snapshot'] 透传给前端。"""

    @pytest.mark.asyncio
    async def test_active_runtime_returns_snapshot(self) -> None:
        from chat.conversation_service import ConversationService

        snapshot = {
            "pending_text": "正在思考",
            "thinking": "",
            "tool_calls": [
                {
                    "id": "t1",
                    "name": "search",
                    "input": {"q": "x"},
                    "result": None,
                    "status": "running",
                    "batch_id": None,
                }
            ],
            "narrations": [],
            "timeline": [
                {
                    "id": "t1",
                    "kind": "tool",
                    "name": "search",
                    "input": {"q": "x"},
                    "result": None,
                    "status": "running",
                    "batch_id": None,
                }
            ],
        }
        mock_run = _make_mock_run(metadata={"streaming_snapshot": snapshot})
        orch_p, sess_p = _patch_orch_session(mock_run)
        try:
            runtime = await ConversationService.get_conversation_runtime(
                "11111111-1111-1111-1111-111111111111"
            )
        finally:
            orch_p.stop()
            sess_p.stop()

        assert runtime["active"] is True
        assert runtime["streaming_snapshot"] == snapshot

    @pytest.mark.asyncio
    async def test_inactive_runtime_omits_snapshot(self) -> None:
        from chat.conversation_service import ConversationService

        mock_run = _make_mock_run(
            status="completed",
            phase="completed",
            metadata={"streaming_snapshot": {"pending_text": "stale"}},
        )
        orch_p, sess_p = _patch_orch_session(mock_run)
        try:
            runtime = await ConversationService.get_conversation_runtime(
                "22222222-2222-2222-2222-222222222222"
            )
        finally:
            orch_p.stop()
            sess_p.stop()

        assert runtime["active"] is False
        # 完成态不返回 snapshot，避免前端 bubble 重影
        assert runtime["streaming_snapshot"] is None


class TestPersistenceHelpers:
    """flush / _clear_streaming_snapshot 行为：mock OrchestrationRun ORM。"""

    @pytest.mark.asyncio
    async def test_flush_writes_snapshot_into_metadata(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        run = MagicMock()
        run.metadata = {"foo": "bar"}

        snap = _StreamingSnapshot(run_id="run-x")
        snap.ingest(TEXT_DELTA, {"text": "hello"})

        with patch("orchestration.models.OrchestrationRun") as mock_cls:
            mock_qs = MagicMock()
            mock_qs.afirst = AsyncMock(return_value=run)
            mock_qs.aupdate = AsyncMock()
            mock_cls.objects.filter.return_value = mock_qs

            await snap.flush()

        kwargs = mock_qs.aupdate.await_args.kwargs
        new_md = kwargs["metadata"]
        assert new_md["foo"] == "bar"
        assert new_md["streaming_snapshot"]["pending_text"] == "hello"
        # flush 完应把 dirty 置 False，避免被再次 flush 同一份数据
        assert snap._dirty is False

    @pytest.mark.asyncio
    async def test_clear_pops_snapshot_keeps_other_metadata(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        run = MagicMock()
        run.metadata = {"foo": "bar", "streaming_snapshot": {"pending_text": "x"}}

        with patch("orchestration.models.OrchestrationRun") as mock_cls:
            mock_qs = MagicMock()
            mock_qs.afirst = AsyncMock(return_value=run)
            mock_qs.aupdate = AsyncMock()
            mock_cls.objects.filter.return_value = mock_qs

            await _clear_streaming_snapshot("run-x")

        kwargs = mock_qs.aupdate.await_args.kwargs
        assert "streaming_snapshot" not in kwargs["metadata"]
        assert kwargs["metadata"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_clear_noop_when_run_id_empty(self) -> None:
        from unittest.mock import patch

        with patch("orchestration.models.OrchestrationRun") as mock_cls:
            await _clear_streaming_snapshot("")
            mock_cls.objects.filter.assert_not_called()
