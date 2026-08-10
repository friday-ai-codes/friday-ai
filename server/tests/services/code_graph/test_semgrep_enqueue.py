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


@pytest.mark.asyncio
async def test_enqueue_emits_started_completed_lifecycle(monkeypatch) -> None:
    """入队生命周期须有 started/completed（带 duration_ms）。

    包内内核只许 ``category="sampling"``（观测契约；调用类归因在外层壳层），
    「谁触发的」由 ``initiated_by_user_id`` 保住。

    （决策: 可观测规范；review: MN-03）
    """
    import structlog

    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan

    async def _fake_defer(task, payload, **kwargs):
        return "job-obs"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )

    with structlog.testing.capture_logs() as logs:
        await enqueue_semgrep_scan(
            "repo-obs",
            mr_key="mr-obs",
            source_sha="a" * 40,
            target_sha="b" * 40,
            initiated_by_user_id="user-1",
        )

    events = {entry["event"]: entry for entry in logs}
    assert "code_graph_enqueue_semgrep_scan_started" in events
    assert "code_graph_enqueue_semgrep_scan_completed" in events
    started_entry = events["code_graph_enqueue_semgrep_scan_started"]
    assert started_entry["category"] == "sampling"
    assert started_entry["component"] == "code_graph"
    assert started_entry["initiated_by_user_id"] == "user-1"
    assert "duration_ms" in events["code_graph_enqueue_semgrep_scan_completed"]


@pytest.mark.asyncio
async def test_enqueue_for_branches_resolves_both_shas(monkeypatch) -> None:
    """挂点 helper 经 client 解析两端 sha 后入队，payload 两端均非空。

    （Req: TAINT-01；决策: D-04）
    """
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan_for_branches

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["payload"] = payload
        return "job-branches"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )

    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(
        side_effect=lambda branch: ("a" * 40) if branch == "feat/x" else ("b" * 40)
    )

    job = await enqueue_semgrep_scan_for_branches(
        "repo-b",
        mr_key="mr-1",
        source_branch="feat/x",
        target_branch="main",
        client=client,
    )
    assert job == "job-branches"
    assert captured["payload"]["source_sha"] == "a" * 40
    assert captured["payload"]["target_sha"] == "b" * 40
    assert captured["payload"]["branch_name"] == "feat/x"


@pytest.mark.asyncio
async def test_enqueue_for_branches_skips_when_target_unresolvable(monkeypatch) -> None:
    """任一端 sha 解析不到 → 返回 None 且完全不 defer（⛔ 不入队恒 unavailable 任务）。

    （Req: TAINT-01；决策: D-04）
    """
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan_for_branches

    deferred: list = []

    async def _fake_defer(task, payload, **kwargs):
        deferred.append(payload)
        return "job-should-not-happen"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )
    monkeypatch.setattr(
        "services.repo_mirror.ensure_mirror_commit",
        AsyncMock(side_effect=RuntimeError("mirror down")),
    )

    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(
        side_effect=lambda branch: ("a" * 40) if branch == "feat/x" else ""
    )

    job = await enqueue_semgrep_scan_for_branches(
        "repo-c",
        mr_key="mr-2",
        source_branch="feat/x",
        target_branch="main",
        client=client,
    )
    assert job is None
    assert deferred == []


@pytest.mark.asyncio
async def test_enqueue_for_branches_falls_back_to_mirror(monkeypatch) -> None:
    """client 解析不到时回退本地 bare 镜像 ``ensure_mirror_commit``。

    （Req: TAINT-01；决策: D-02/D-04）
    """
    from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan_for_branches

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["payload"] = payload
        return "job-mirror"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)
    monkeypatch.setattr(
        "durable.concurrency.ascan_lock",
        AsyncMock(return_value="scan-slot-0"),
    )

    class _Snapshot:
        def __init__(self, sha: str) -> None:
            self.commit_sha = sha

    async def _fake_mirror(repository_id, branch=None):
        return _Snapshot(("a" * 40) if branch == "feat/y" else ("b" * 40))

    monkeypatch.setattr("services.repo_mirror.ensure_mirror_commit", _fake_mirror)

    job = await enqueue_semgrep_scan_for_branches(
        "repo-d",
        mr_key="mr-3",
        source_branch="feat/y",
        target_branch="main",
        client=None,
    )
    assert job == "job-mirror"
    assert captured["payload"]["source_sha"] == "a" * 40
    assert captured["payload"]["target_sha"] == "b" * 40
