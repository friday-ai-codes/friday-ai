"""Semgrep enqueue / QUEUE_SCAN 验收（D-02/D-04；归属 127-03）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_enqueue_uses_queue_scan_and_slot_lock(monkeypatch) -> None:
    """QUEUE_SCAN；idempotency_key=semgrep:{repo}:{mr_key}；scan-slot-*；N=2。

    （决策: D-02/D-04）
    """
    from durable.concurrency import DEFAULT_SCAN_CONCURRENCY, scan_slot_lock
    from durable.queues import ALL_QUEUES, QUEUE_SCAN
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

    assert QUEUE_SCAN == "scan"
    assert QUEUE_SCAN in ALL_QUEUES
    assert DEFAULT_SCAN_CONCURRENCY == 2
    assert scan_slot_lock("repo-x", 2).startswith("scan-slot-")

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-scan"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-1"),
    )

    job = await enqueue_semgrep_scan(
        "repo-x",
        mr_key="mr-9",
        source_sha="a" * 40,
        target_sha="b" * 40,
        initiated_by_user_id="42",
    )
    assert job == "job-scan"
    assert captured["task"] == "durable_semgrep_scan"
    assert captured["kwargs"]["queue"] == QUEUE_SCAN
    assert captured["kwargs"]["idempotency_key"] == "semgrep:repo-x:mr-9"
    assert captured["kwargs"]["lock"] == "scan-slot-1"
    assert captured["payload"]["repository_id"] == "repo-x"
    assert captured["payload"]["mr_key"] == "mr-9"
    assert captured["payload"]["source_sha"] == "a" * 40
    assert captured["payload"]["target_sha"] == "b" * 40


@pytest.mark.asyncio
async def test_enqueue_passes_initiated_by_user_id(monkeypatch) -> None:
    """enqueue 透传 initiated_by_user_id（可观测绑定触发用户）。

    （决策: D-04）
    """
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["kwargs"] = kwargs
        captured["payload"] = payload
        return "job-2"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )

    await enqueue_semgrep_scan(
        "repo-y",
        mr_key="!12",
        source_sha="c" * 40,
        target_sha="d" * 40,
        initiated_by_user_id="user-7",
    )
    assert captured["kwargs"]["initiated_by_user_id"] == "user-7"
    assert captured["payload"].get("initiated_by_user_id") == "user-7"


@pytest.mark.asyncio
async def test_enqueue_failure_returns_none_not_raise(monkeypatch) -> None:
    """enqueue 失败返回 None，不 raise 到建 MR。

    （决策: D-04；威胁: T-127-02）
    """
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

    async def _boom(*_a, **_k):
        raise RuntimeError("defer exploded")

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _boom)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )

    job = await enqueue_semgrep_scan(
        "repo-z",
        mr_key="mr-0",
        source_sha="e" * 40,
        target_sha="f" * 40,
    )
    assert job is None
