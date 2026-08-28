"""Phase 143 Wave 0：Session Capture durable 双任务与恢复契约（RED）。"""

from __future__ import annotations

import ast
import datetime
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.asyncio

_EVAL_TASK = "durable_session_capture_eval"
_INGEST_TASK = "durable_session_capture_ingest"
_FORBIDDEN_PAYLOAD_KEYS = {
    "question",
    "answer",
    "distilled_essence",
    "transcript",
}


def _source(relative: str) -> str:
    return (SERVER_DIR / relative).read_text(encoding="utf-8")


def _function_source(relative: str, function_name: str) -> str:
    tree = ast.parse(_source(relative))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            return ast.get_source_segment(_source(relative), node) or ""
    pytest.fail(f"{relative} 缺少 {function_name}")


async def test_queue_knowledge_in_all_queues() -> None:
    from durable.queues import ALL_QUEUES, QUEUE_KNOWLEDGE

    assert QUEUE_KNOWLEDGE == "knowledge"
    assert QUEUE_KNOWLEDGE in ALL_QUEUES


async def test_procrastinate_wrappers_are_keyword_only_and_aligned() -> None:
    from durable import tasks
    from durable.tasks_impl import run_session_capture_eval, run_session_capture_ingest

    for wrapper, implementation in (
        (tasks.durable_session_capture_eval, run_session_capture_eval),
        (tasks.durable_session_capture_ingest, run_session_capture_ingest),
    ):
        wrapper_params = inspect.signature(wrapper).parameters
        implementation_params = inspect.signature(implementation).parameters
        assert wrapper_params == implementation_params
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in wrapper_params.values()
        )
        assert set(wrapper_params) == {"capture_id", "attempt", "initiated_by_user_id"}


async def test_inprocess_adapters_splat_payload() -> None:
    text = _source("durable/handlers.py")
    assert "run_session_capture_eval(**payload)" in text
    assert "run_session_capture_ingest(**payload)" in text
    assert f'register_handler("{_EVAL_TASK}"' in text
    assert f'register_handler("{_INGEST_TASK}"' in text


async def test_payload_has_only_scalar_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from initiatives.services.session_capture_enqueue import (
        enqueue_session_capture_eval,
        enqueue_session_capture_ingest,
    )

    calls: list[tuple[str, dict, dict]] = []

    async def fake_defer(task: str, payload: dict, **kwargs):
        calls.append((task, payload, kwargs))
        return f"job-{len(calls)}"

    captures = [
        SimpleNamespace(status="pending_eval", eval_attempts=0, initiated_by_user_id="user-1"),
        SimpleNamespace(status="ingest_pending", ingest_attempts=0, initiated_by_user_id="user-1"),
    ]
    monkeypatch.setattr(
        "initiatives.services.session_capture_enqueue.CaptureService.get_capture",
        AsyncMock(side_effect=captures),
    )
    monkeypatch.setattr("durable.service.DurableTaskService.defer", fake_defer)
    await enqueue_session_capture_eval("capture-1", initiated_by_user_id="user-1")
    await enqueue_session_capture_ingest("capture-1", initiated_by_user_id="user-1")

    assert [call[0] for call in calls] == [_EVAL_TASK, _INGEST_TASK]
    for _task, payload, kwargs in calls:
        assert set(payload) == {"capture_id", "attempt"}
        assert payload == {"capture_id": "capture-1", "attempt": 0}
        assert not (_FORBIDDEN_PAYLOAD_KEYS & set(payload))
        assert kwargs["initiated_by_user_id"] == "user-1"


@pytest.mark.parametrize("tier", ["medium", "high"])
async def test_medium_high_defers_ingest(
    monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    import durable.tasks_impl as task_impl

    capture = SimpleNamespace(
        id="capture-1",
        initiated_by_user_id="user-1",
        status="evaluating",
    )
    service = MagicMock()
    service.claim_evaluation = AsyncMock(return_value=capture)
    service.record_evaluation = AsyncMock(return_value=SimpleNamespace(status="ingest_pending"))
    evaluator = AsyncMock(
        return_value=SimpleNamespace(value_tier=tier, distilled_essence="可独立召回的精华")
    )
    enqueue = AsyncMock(return_value="job-ingest")
    monkeypatch.setattr(task_impl, "CaptureService", lambda: service, raising=False)
    monkeypatch.setattr(task_impl, "evaluate_session_capture", evaluator, raising=False)
    monkeypatch.setattr(task_impl, "enqueue_session_capture_ingest", enqueue, raising=False)

    result = await task_impl.run_session_capture_eval(
        capture_id="capture-1", attempt=0, initiated_by_user_id="user-1"
    )

    assert result["status"] == "ingest_pending"
    evaluator.assert_awaited_once()
    service.record_evaluation.assert_awaited_once()
    enqueue.assert_awaited_once_with("capture-1", initiated_by_user_id="user-1")


async def test_low_skips_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    import durable.tasks_impl as task_impl

    capture = SimpleNamespace(id="capture-1", status="evaluating")
    service = MagicMock()
    service.claim_evaluation = AsyncMock(return_value=capture)
    service.record_evaluation = AsyncMock(return_value=SimpleNamespace(status="evaluated_low"))
    monkeypatch.setattr(task_impl, "CaptureService", lambda: service, raising=False)
    monkeypatch.setattr(
        task_impl,
        "evaluate_session_capture",
        AsyncMock(
            return_value=SimpleNamespace(value_tier="low", distilled_essence="低价值精华")
        ),
        raising=False,
    )
    enqueue = AsyncMock()
    ingest = AsyncMock()
    monkeypatch.setattr(task_impl, "enqueue_session_capture_ingest", enqueue, raising=False)
    monkeypatch.setattr("knowledge.ingestion.ingest", ingest)

    result = await task_impl.run_session_capture_eval(capture_id="capture-1")

    assert result["status"] == "evaluated_low"
    enqueue.assert_not_awaited()
    ingest.assert_not_awaited()


async def test_ingest_worker_uses_unified_ingest_only() -> None:
    source = _function_source("durable/tasks_impl.py", "run_session_capture_ingest")
    assert "await ingest(" in source
    assert 'IngestionRequest("session_capture"' in source
    assert "evaluate_session_capture" not in source
    assert "aschedule_ingestion" not in source


async def test_replay_skips_llm_when_not_claimable(monkeypatch: pytest.MonkeyPatch) -> None:
    import durable.tasks_impl as task_impl

    service = MagicMock()
    service.claim_evaluation = AsyncMock(return_value=None)
    evaluator = AsyncMock()
    monkeypatch.setattr(task_impl, "CaptureService", lambda: service, raising=False)
    monkeypatch.setattr(task_impl, "evaluate_session_capture", evaluator, raising=False)

    result = await task_impl.run_session_capture_eval(capture_id="capture-terminal")

    assert result == {
        "status": "skipped",
        "reason": "not_claimable",
        "capture_id": "capture-terminal",
    }
    evaluator.assert_not_awaited()


async def test_ingested_replay_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    import durable.tasks_impl as task_impl

    service = MagicMock()
    service.claim_ingestion = AsyncMock(return_value=None)
    ingest = AsyncMock()
    monkeypatch.setattr(task_impl, "CaptureService", lambda: service, raising=False)
    monkeypatch.setattr("knowledge.ingestion.ingest", ingest)

    result = await task_impl.run_session_capture_ingest(capture_id="capture-ingested")

    assert result["status"] == "skipped"
    assert result["reason"] == "not_claimable"
    ingest.assert_not_awaited()


async def test_ingest_replay_does_not_call_evaluator() -> None:
    source = _function_source("durable/tasks_impl.py", "run_session_capture_ingest")
    assert "evaluate_session_capture(" not in source
    assert "SessionCaptureEvaluator" not in source


async def test_ingest_failure_does_not_reenter_eval() -> None:
    source = _function_source("durable/tasks_impl.py", "run_session_capture_ingest")
    assert "record_ingest_failure" in source
    assert "record_eval_failure" not in source
    assert "pending_eval" not in source


async def test_initial_and_recovery_use_stable_idempotency_key() -> None:
    source = _source("initiatives/services/session_capture_enqueue.py")
    assert 'f"capture-eval:{capture_id}"' in source
    assert 'f"capture-ingest:{capture_id}"' in source
    assert "has_active_by_key" in source


async def test_backoff_redefer_omits_stable_idempotency_key() -> None:
    for function_name, stable_prefix in (
        ("run_session_capture_eval", "capture-eval:{capture_id}"),
        ("run_session_capture_ingest", "capture-ingest:{capture_id}"),
    ):
        source = _function_source("durable/tasks_impl.py", function_name)
        assert f'idempotency_key=f"{stable_prefix}"' not in source


async def test_backoff_schedules_new_job_with_lock_and_run_at() -> None:
    for function_name, lock_prefix in (
        ("run_session_capture_eval", "capture-eval:"),
        ("run_session_capture_ingest", "capture-ingest:"),
    ):
        source = _function_source("durable/tasks_impl.py", function_name)
        assert "DurableTaskService.defer(" in source
        assert "run_at=run_at" in source
        assert "lock=" in source
        assert lock_prefix in source


async def test_backoff_dual_backend_parity_lock_run_at_without_same_key() -> None:
    service_source = _source("durable/service.py")
    backend_source = _source("durable/backends.py")
    for source in (service_source, backend_source):
        assert "run_at" in source
        assert "lock" in source
        assert "idempotency_key" in source


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 5), (1, 10), (2, 20), (5, 160), (6, 300), (99, 300), (-1, 5)],
)
async def test_backoff_is_bounded(attempt: int, expected: int) -> None:
    from durable.tasks_impl import _session_capture_backoff_seconds

    assert _session_capture_backoff_seconds(attempt) == expected


async def test_automatic_attempt_limit_is_six() -> None:
    import durable.tasks_impl as task_impl

    assert task_impl._SESSION_CAPTURE_MAX_ATTEMPTS == 6


async def _exercise_recovery(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str,
    active: bool = False,
) -> list[tuple[str, dict, dict]]:
    import initiatives.services.session_capture_enqueue as enqueue_module

    capture = SimpleNamespace(
        id=f"capture-{status}",
        status=status,
        initiated_by_user_id="actor-1",
        updated_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
        next_retry_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1),
    )
    monkeypatch.setattr(
        enqueue_module,
        "_list_recoverable_captures",
        AsyncMock(return_value=[capture]),
        raising=False,
    )
    monkeypatch.setattr(
        "durable.service.DurableTaskService.has_active_by_key",
        AsyncMock(return_value=active),
    )
    calls: list[tuple[str, dict, dict]] = []

    async def fake_defer(task: str, payload: dict, **kwargs):
        calls.append((task, payload, kwargs))
        return "job-recovered"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", fake_defer)
    await enqueue_module.recover_session_capture_tasks()
    return calls


async def test_recovery_redefers_pending_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = await _exercise_recovery(monkeypatch, status="pending_eval")
    assert calls[0][0] == _EVAL_TASK
    assert calls[0][2]["idempotency_key"] == "capture-eval:capture-pending_eval"


async def test_recovery_redefers_stale_evaluating(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = await _exercise_recovery(monkeypatch, status="evaluating")
    assert calls[0][0] == _EVAL_TASK


async def test_recovery_redefers_stale_ingesting(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = await _exercise_recovery(monkeypatch, status="ingesting")
    assert calls[0][0] == _INGEST_TASK


@pytest.mark.parametrize("status", ["evaluated_low", "ingested", "evaluated"])
async def test_recovery_skips_active_fresh_and_terminal(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    calls = await _exercise_recovery(monkeypatch, status=status)
    assert calls == []
    active_calls = await _exercise_recovery(monkeypatch, status="pending_eval", active=True)
    assert active_calls == []


async def test_recovery_isolates_single_failure() -> None:
    source = _function_source(
        "initiatives/services/session_capture_enqueue.py",
        "recover_session_capture_tasks",
    )
    assert "for " in source
    assert "except Exception" in source


async def test_eval_resume_when_evaluating_still_runs_llm() -> None:
    source = _function_source("initiatives/services/capture_service.py", "_claim_evaluation")
    assert "SessionCaptureStatus.EVALUATING" in source
    assert "eval_attempts" in source
    worker = _function_source("durable/tasks_impl.py", "run_session_capture_eval")
    assert "evaluate_session_capture" in worker


@pytest.mark.parametrize("actor", ["user-42", None])
async def test_worker_rebinds_initiated_by_user_id(actor: str | None) -> None:
    expected = actor or "system"
    for function_name in ("run_session_capture_eval", "run_session_capture_ingest"):
        source = _function_source("durable/tasks_impl.py", function_name)
        assert "bind_task_context(" in source
        assert 'source="durable"' in source
        assert 'component="knowledge"' in source
        assert 'initiated_by_user_id or "system"' in source
        assert expected
