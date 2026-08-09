"""durable_charter_draft 任务注册、payload 契约、跳过语义与幂等键。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from django.core.exceptions import ObjectDoesNotExist

from durable.handlers import register_business_handlers
from durable.queues import ALL_QUEUES, QUEUE_CHARTER
from durable.service import DurableTaskService
from durable.tasks_impl import run_charter_draft
from repositories.services.charter_service import CharterPersistError
from services import background_runner

pytestmark = [pytest.mark.asyncio]


async def test_charter_queue_in_all_queues() -> None:
    assert QUEUE_CHARTER == "charter"
    assert QUEUE_CHARTER in ALL_QUEUES


async def test_charter_adapter_calls_task_with_expanded_kwargs(settings, monkeypatch) -> None:
    """in-process adapter 以 **payload 展开调 run_charter_draft。"""
    settings.DURABLE_TASK_BACKEND = "inprocess"
    monkeypatch.setattr("durable.service.use_procrastinate_backend", lambda: False)
    register_business_handlers()

    captured = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("durable.tasks_impl.run_charter_draft", captured)

    payload = {"repository_id": "R", "initiated_by_user_id": "u1"}
    await DurableTaskService.defer(
        "durable_charter_draft",
        payload,
        queue=QUEUE_CHARTER,
        idempotency_key="charter:R",
    )
    background_runner.wait_for_pending(timeout=5.0)

    captured.assert_awaited_once()
    assert captured.await_args.args == ()
    assert set(captured.await_args.kwargs) >= {"repository_id"}
    assert captured.await_args.kwargs["repository_id"] == "R"


async def test_run_charter_draft_success(monkeypatch) -> None:
    import repositories.services.charter_service as cs

    charter = MagicMock()
    charter.source = "ai_draft"
    monkeypatch.setattr(cs, "adraft_charter", AsyncMock(return_value=charter))

    result = await run_charter_draft(repository_id="repo-1", initiated_by_user_id="42")
    assert result["status"] == "ok"
    assert result["repository_id"] == "repo-1"


async def test_run_charter_draft_llm_unavailable_skipped(monkeypatch) -> None:
    import repositories.services.charter_service as cs

    monkeypatch.setattr(cs, "adraft_charter", AsyncMock(return_value=None))
    result = await run_charter_draft(repository_id="repo-1")
    assert result == {
        "status": "skipped",
        "reason": "llm_unavailable",
        "repository_id": "repo-1",
    }


async def test_run_charter_draft_not_found_skipped(monkeypatch) -> None:
    import repositories.services.charter_service as cs

    async def _raise(*_a, **_k):
        raise ObjectDoesNotExist("Repository matching query does not exist.")

    monkeypatch.setattr(cs, "adraft_charter", _raise)
    result = await run_charter_draft(repository_id="missing")
    assert result["status"] == "skipped"
    assert result["reason"] == "not_found"


async def test_run_charter_draft_persist_error_reraises(monkeypatch) -> None:
    import repositories.services.charter_service as cs

    async def _raise(*_a, **_k):
        raise CharterPersistError("章程草案落库失败")

    monkeypatch.setattr(cs, "adraft_charter", _raise)
    with pytest.raises(CharterPersistError):
        await run_charter_draft(repository_id="repo-1")


async def test_run_charter_draft_unexpected_reraises(monkeypatch) -> None:
    import repositories.services.charter_service as cs

    async def _raise(*_a, **_k):
        raise RuntimeError("sk-ant-secret-should-not-leak")

    monkeypatch.setattr(cs, "adraft_charter", _raise)
    with pytest.raises(RuntimeError):
        await run_charter_draft(repository_id="repo-1")


async def test_enqueue_charter_draft_idempotency_and_lock(monkeypatch) -> None:
    from repositories.charter_enqueue import enqueue_charter_draft

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-charter"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.acharacter_lock",
        AsyncMock(return_value="charter-slot-1"),
    )

    job = await enqueue_charter_draft("repo-x", initiated_by_user_id="7")
    assert job == "job-charter"
    assert captured["task"] == "durable_charter_draft"
    assert captured["kwargs"]["queue"] == QUEUE_CHARTER
    assert captured["kwargs"]["idempotency_key"] == "charter:repo-x"
    assert captured["kwargs"]["lock"] == "charter-slot-1"
    assert captured["kwargs"]["initiated_by_user_id"] == "7"
