"""runner 派发 durable 任务体测试（31u）。

覆盖 ``durable.tasks_impl.run_runner_dispatch`` 与派发链周边：

- 幂等守卫：终态 / active assignment / 查无 → no-op（防重复容器 / 重复 commit 的核心断言）
- 无匹配 runner → re-defer backoff（attempt+1 + run_at 退避曲线 + lock/queue 形参）
- 有在线 runner → ``_try_assign`` 成功链（assignment / current_tasks / TASK_ASSIGN 消息）
- 快照凭证 redact / rehydrate / USER_TOKEN 重铸（fail-soft）
- ``arecover_stranded_dispatch_sessions`` 保险丝扫描判据
- rejected 重派链（退避递增 / 上限落终态 + 告警事件）

任务体直接在测试事件循环内调用（不经 in-process 后端的 background 线程），
re-defer / 重派入队一律 monkeypatch ``DurableTaskService.defer`` 捕获形参断言。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from channels.layers import get_channel_layer
from django.utils import timezone

from agents.models import AgentSession
from durable.service import DurableTaskService
from durable.tasks_impl import run_runner_dispatch
from runners.dispatcher import (
    arebuild_dispatch_task_from_session,
    arecover_stranded_dispatch_sessions,
)
from runners.models import Runner, RunnerTaskAssignment
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


_SNAPSHOT = {
    "task_type": "coding",
    "tags": ["x"],
    "repo_url": "https://example.com/r.git",
    "branch": "main",
    "target_branch": "main",
    "prompt": "执行编码",
    "timeout": 3600,
    "node_execution_id": "",
    "metadata": {"repository_id": "repo-1"},
}


async def _make_session(
    session_id: str,
    *,
    status: str = SubAgentSession.Status.PENDING,
    snapshot: dict | None = _SNAPSHOT,
    task_type: str = SubAgentSession.TaskType.CODING,
) -> SubAgentSession:
    agent = await AgentSession.objects.acreate(
        session_id=f"agent-{session_id}",
        space=None,
        status=AgentSession.Status.RUNNING,
    )
    last_output: dict = {"task_type": "coding"}
    if snapshot is not None:
        last_output["dispatch"] = dict(snapshot)
    return await SubAgentSession.objects.acreate(
        session_id=session_id,
        main_session=agent,
        task_type=task_type,
        status=status,
        repo_url="https://example.com/r.git",
        last_output=last_output,
    )


async def _make_runner(*, concurrent: int = 1, channel_name: str = "disp.test.chan") -> Runner:
    return await Runner.objects.acreate(
        name=f"dispatch-runner-{channel_name}",
        token_hash=uuid.uuid4().hex.ljust(64, "a"),
        status=Runner.Status.ONLINE,
        is_active=True,
        is_paused=False,
        channel_name=channel_name,
        tags=["x"],
        concurrent=concurrent,
        current_tasks=0,
        last_heartbeat=timezone.now(),
    )


def _capture_defer(monkeypatch) -> list[dict]:
    deferred: list[dict] = []

    async def _capture(task_name, payload, **kwargs):
        deferred.append({"task": task_name, "payload": payload, **kwargs})
        return "job-x"

    monkeypatch.setattr(DurableTaskService, "defer", AsyncMock(side_effect=_capture))
    return deferred


# ── 任务体幂等守卫 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_body_skips_when_session_not_found() -> None:
    result = await run_runner_dispatch(session_id="ghost-session")
    assert result == {"status": "skipped", "reason": "not_found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        SubAgentSession.Status.COMPLETED,
        SubAgentSession.Status.ERROR,
        SubAgentSession.Status.TIMEOUT,
        SubAgentSession.Status.CANCELLED,
    ],
)
async def test_task_body_skips_terminal_session(status: str) -> None:
    """终态守卫：链条由它终结（re-defer 链在 session 终态后下一跳 no-op）。"""
    await _make_session(f"term-{status}", status=status)
    result = await run_runner_dispatch(session_id=f"term-{status}")
    assert result == {"status": "skipped", "reason": "terminal"}


@pytest.mark.asyncio
async def test_task_body_skips_active_assignment() -> None:
    """已派出 / 在跑 → 绝不起第二个容器（防重复 push commit 的核心断言）。"""
    session = await _make_session("active-assign")
    runner = await _make_runner(channel_name="active.chan")
    await RunnerTaskAssignment.objects.acreate(
        runner=runner, session=session, status=RunnerTaskAssignment.Status.RUNNING
    )
    result = await run_runner_dispatch(session_id="active-assign")
    assert result == {"status": "skipped", "reason": "active_assignment"}


@pytest.mark.asyncio
async def test_task_body_skips_when_snapshot_missing() -> None:
    """快照缺失（理论不可达：dispatch() 先持久化后入队）→ no-op + warning，不抛。"""
    await _make_session("no-snap", snapshot=None)
    result = await run_runner_dispatch(session_id="no-snap")
    assert result == {"status": "skipped", "reason": "no_snapshot"}


# ── re-defer backoff（无匹配 runner） ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_body_requeues_with_backoff_when_no_runner(monkeypatch) -> None:
    """无 runner → re-defer：attempt+1、run_at 按 5*2**attempt 退避、lock/queue 形参正确。"""
    await _make_session("no-runner")
    deferred = _capture_defer(monkeypatch)

    before = timezone.now()
    result = await run_runner_dispatch(session_id="no-runner", attempt=0)

    assert result == {"status": "requeued", "attempt": 1}
    assert len(deferred) == 1
    call = deferred[0]
    assert call["task"] == "durable_runner_dispatch"
    assert call["payload"] == {"session_id": "no-runner", "attempt": 1}
    assert call["queue"] == "dispatch"
    assert call["lock"] == "dispatch-no-runner"
    assert call.get("idempotency_key") is None
    delta = (call["run_at"] - before).total_seconds()
    assert 4 <= delta <= 7  # attempt=0 → 5s（容差）


@pytest.mark.asyncio
async def test_task_body_backoff_curve_caps_at_300s(monkeypatch) -> None:
    """退避曲线：attempt=3 → 40s；attempt=10 → 封顶 300s。"""
    await _make_session("backoff-curve")
    deferred = _capture_defer(monkeypatch)

    before = timezone.now()
    result = await run_runner_dispatch(session_id="backoff-curve", attempt=3)
    assert result == {"status": "requeued", "attempt": 4}
    delta = (deferred[0]["run_at"] - before).total_seconds()
    assert 39 <= delta <= 42  # 5 * 2**3 = 40

    result = await run_runner_dispatch(session_id="backoff-curve", attempt=10)
    delta = (deferred[1]["run_at"] - before).total_seconds()
    assert 299 <= delta <= 302  # 封顶 300


# ── 成功派发链 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_body_dispatches_to_online_runner() -> None:
    """有匹配 runner + 空槽 → assignment 建立、current_tasks +1、channel 收到 TASK_ASSIGN。"""
    await _make_session("happy-dispatch")
    runner = await _make_runner(channel_name="happy.chan")

    with patch(
        "tools.registry.RemoteToolRegistry.aget_tools_payload",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_runner_dispatch(session_id="happy-dispatch")

    assert result == {"status": "dispatched"}
    await runner.arefresh_from_db()
    assert runner.current_tasks == 1
    assert await RunnerTaskAssignment.objects.filter(
        session__session_id="happy-dispatch", status="assigned"
    ).aexists()
    message = await asyncio.wait_for(get_channel_layer().receive("happy.chan"), timeout=2)
    assert message["message"]["type"] == "task.assign"
    assert message["message"]["payload"]["session_id"] == "happy-dispatch"


# ── 快照凭证 rehydrate / USER_TOKEN 重铸 ──────────────────────────────────────


async def _make_redacted_session(session_id: str, *, task_token_user_id: str | None) -> Any:
    metadata: dict = {
        "repository_id": "",  # git 分支不触发（本组用例聚焦 USER_TOKEN）
        "_redacted_env_keys": [
            "env_FRIDAY_TASK_GIT_ACCESS_TOKEN",
            "env_FRIDAY_TASK_USER_TOKEN",
        ],
    }
    if task_token_user_id is not None:
        metadata["task_token_user_id"] = task_token_user_id
    snapshot = {**_SNAPSHOT, "metadata": metadata}
    return await _make_session(session_id, snapshot=snapshot)


@pytest.mark.asyncio
async def test_rebuild_rehydrates_git_token_and_remints_user_token() -> None:
    """rehydrate：Git token 从权威源补回；有 task_token_user_id → USER_TOKEN 重铸。"""
    from django.contrib.auth import get_user_model

    from repositories.models import Repository

    user = await get_user_model().objects.acreate(username="remint-user")
    repo = await Repository.objects.acreate(
        name="remint-repo",
        git_url="https://gitlab.example.com/t/remint.git",
        git_platform="gitlab",
        default_branch="main",
    )
    metadata = {
        "repository_id": str(repo.id),
        "task_token_user_id": str(user.id),
        "_redacted_env_keys": [
            "env_FRIDAY_TASK_GIT_ACCESS_TOKEN",
            "env_FRIDAY_TASK_USER_TOKEN",
        ],
    }
    session = await _make_session("remint-ok", snapshot={**_SNAPSHOT, "metadata": metadata})

    with (
        patch(
            "services.git_credentials.aresolve_git_token",
            new_callable=AsyncMock,
            return_value="glpat-REHYDRATED",
        ),
        patch(
            "access_tokens.services.mint_task_token",
            new_callable=AsyncMock,
            return_value="friday_pat_REMINTED",
        ) as mint,
    ):
        task = await arebuild_dispatch_task_from_session(session)

    assert task is not None
    assert task.metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "glpat-REHYDRATED"
    assert task.metadata["env_FRIDAY_TASK_USER_TOKEN"] == "friday_pat_REMINTED"
    assert "_redacted_env_keys" not in task.metadata
    mint.assert_awaited_once()
    args = mint.await_args.args
    assert str(args[0].id) == str(user.id)
    assert args[1] == "remint-ok"


@pytest.mark.asyncio
async def test_rebuild_skips_user_token_without_marker_key() -> None:
    """metadata 无 task_token_user_id（历史行 / 无触发用户降级链）→ 不重铸（fail-soft）。"""
    session = await _make_redacted_session("remint-nokey", task_token_user_id=None)

    with patch("access_tokens.services.mint_task_token", new_callable=AsyncMock) as mint:
        task = await arebuild_dispatch_task_from_session(session)

    assert task is not None
    assert "env_FRIDAY_TASK_USER_TOKEN" not in task.metadata
    mint.assert_not_awaited()


@pytest.mark.asyncio
async def test_rebuild_user_token_mint_failure_degrades() -> None:
    """重铸失败（mint 抛）→ fail-soft 跳过该键，不阻断重建。"""
    from django.contrib.auth import get_user_model

    user = await get_user_model().objects.acreate(username="remint-boom")
    session = await _make_redacted_session("remint-fail", task_token_user_id=str(user.id))

    with patch(
        "access_tokens.services.mint_task_token",
        new_callable=AsyncMock,
        side_effect=RuntimeError("mint boom"),
    ):
        task = await arebuild_dispatch_task_from_session(session)

    assert task is not None, "重铸失败绝不阻断重建"
    assert "env_FRIDAY_TASK_USER_TOKEN" not in task.metadata


# ── stranded 派发恢复扫描（apscheduler 保险丝） ────────────────────────────────


async def _backdate(session: SubAgentSession, minutes: int) -> None:
    await SubAgentSession.objects.filter(pk=session.pk).aupdate(
        updated_at=timezone.now() - timedelta(minutes=minutes)
    )


@pytest.mark.asyncio
async def test_recover_stranded_requeues_pending_with_snapshot(monkeypatch) -> None:
    """滞留 PENDING + 有快照 → defer 被调（编码任务也纳入，幂等由任务体守卫承担）。"""
    session = await _make_session("stranded-1")
    await _backdate(session, 20)
    deferred = _capture_defer(monkeypatch)

    counts = await arecover_stranded_dispatch_sessions()

    assert counts == {"scanned": 1, "skipped_active": 0, "requeued": 1, "failed": 0}
    assert deferred[0]["payload"] == {"session_id": "stranded-1", "attempt": 0}
    assert deferred[0]["lock"] == "dispatch-stranded-1"


@pytest.mark.asyncio
async def test_recover_stranded_skips_active_terminal_fresh_and_snapshotless(
    monkeypatch,
) -> None:
    """跳过判据：active assignment / 终态 / 无快照 / 未过窗口；计数键恒定四键。"""
    # active assignment → skipped_active
    active = await _make_session("stranded-active")
    await _backdate(active, 20)
    runner = await _make_runner(channel_name="stranded.chan")
    await RunnerTaskAssignment.objects.acreate(
        runner=runner, session=active, status=RunnerTaskAssignment.Status.ASSIGNED
    )
    # 终态 → 不进扫描面（PENDING 过滤）
    terminal = await _make_session("stranded-term", status=SubAgentSession.Status.COMPLETED)
    await _backdate(terminal, 20)
    # 无快照 → 不进扫描面（has_key 过滤）
    nosnap = await _make_session("stranded-nosnap", snapshot=None)
    await _backdate(nosnap, 20)
    # 未过窗口 → 不进扫描面
    await _make_session("stranded-fresh")

    deferred = _capture_defer(monkeypatch)
    counts = await arecover_stranded_dispatch_sessions()

    assert set(counts) == {"scanned", "skipped_active", "requeued", "failed"}
    assert counts["scanned"] == 1
    assert counts["skipped_active"] == 1
    assert counts["requeued"] == 0
    assert deferred == []


# ── rejected 重派链（consumers._handle_task_rejected） ────────────────────────


async def _make_rejected_fixture(
    session_id: str, *, prior_rejects: int
) -> tuple[Any, SubAgentSession]:
    """runner + session + 1 条 active assignment + N 条历史 rejected assignment。"""
    from runners.consumers import RunnerConsumer

    session = await _make_session(session_id)
    runner = await _make_runner(channel_name=f"rej.{session_id}")
    await RunnerTaskAssignment.objects.acreate(
        runner=runner, session=session, status=RunnerTaskAssignment.Status.ASSIGNED
    )
    for _ in range(prior_rejects):
        await RunnerTaskAssignment.objects.acreate(
            runner=runner, session=session, status="rejected"
        )

    consumer = RunnerConsumer()
    consumer.runner = runner
    return consumer, session


@pytest.mark.asyncio
async def test_rejected_requeues_with_growing_backoff(monkeypatch) -> None:
    """拒绝重派：defer 带 run_at 退避；reject_count 递增 → 退避秒数按曲线增长。"""
    deferred = _capture_defer(monkeypatch)

    # 第 1 次拒绝：reject_count=1 → delay = 5*2**1 = 10s
    consumer, _ = await _make_rejected_fixture("rej-a", prior_rejects=0)
    before = timezone.now()
    await consumer._handle_task_rejected({"payload": {"task_id": "rej-a", "reason": "busy"}})
    assert deferred[0]["task"] == "durable_runner_dispatch"
    assert deferred[0]["payload"] == {"session_id": "rej-a", "attempt": 0}
    assert deferred[0]["lock"] == "dispatch-rej-a"
    delta1 = (deferred[0]["run_at"] - before).total_seconds()
    assert 9 <= delta1 <= 12

    # 第 4 次拒绝：reject_count=4 → delay = 5*2**4 = 80s（同曲线、递增）
    consumer_b, _ = await _make_rejected_fixture("rej-b", prior_rejects=3)
    before = timezone.now()
    await consumer_b._handle_task_rejected({"payload": {"task_id": "rej-b", "reason": "busy"}})
    delta2 = (deferred[1]["run_at"] - before).total_seconds()
    assert 79 <= delta2 <= 82
    assert delta2 > delta1


@pytest.mark.asyncio
async def test_rejected_exhausted_fails_session_and_stops_requeue(monkeypatch) -> None:
    """reject_count 达上限（8）→ 不再 defer、session 落终态 error、发结构化告警事件。"""
    deferred = _capture_defer(monkeypatch)
    consumer, session = await _make_rejected_fixture("rej-max", prior_rejects=7)

    events: list[tuple] = []

    class _SpyLogger:
        def __getattr__(self, level):
            def _log(event, **kw):
                events.append((level, event, kw))

            return _log

    monkeypatch.setattr("runners.consumers.logger", _SpyLogger())

    await consumer._handle_task_rejected(
        {"payload": {"task_id": "rej-max", "reason": "always busy"}}
    )

    assert deferred == [], "达上限后不得再重派"
    await session.arefresh_from_db()
    assert session.status == SubAgentSession.Status.ERROR
    assert "连续拒绝" in (session.last_error or "")
    exhausted = [e for e in events if e[1] == "runner_dispatch_rejected_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0][2]["reject_count"] == 8
