"""长等待登记 / 互等环 / 波次驱动派发的可证伪断言（BUS-02，Phase 113-04）。

本文件守**回调侧与编排侧**（SC2 路径 2 的前半 + 路径 3）；路径 2 的**运行时触发点**
（`report_blueprint_context` 端点 → 自动重派）由 `tests/mcp_tools/test_blueprint_context_redispatch.py`
真打端点覆盖 —— 本文件刻意**不**直调重派方法，绕过端点的「证据」等于那条路径从未被测（B2）。

覆盖：

1. **waiting_context 登记不判完成**：plan 容器带 `waiting_context` 退出 → 落一条
   `dependency_claim(active)` waiter、`PartialPlan` **不含** `repo_plan` 段、task 置回可派发态
   （STALE）、**零派发**。
2. ⭐ **路径 3 互等环抛澄清**：A 等 B 后 B 等 A → 第二次 `register_waiter` 立即
   `cycle_detected is True` + 存在 `BlueprintThread(ai_clarification, blocking=True)` +
   **零 dispatch** + 该 waiter 置 `superseded`；线程问题文本含两个仓 id 但**不含 content 正文**。
   全用例**零 sleep**（环在登记瞬间被判定，不靠超时兜底）。
3. **波次预排驱动派发**：预排 `{1:[B], 2:[A]}` → 首次 `dispatch_plans` 只派 B；B 产出 repo_plan
   后再调才派 A。
4. **成环时开 blocking 澄清且不静默打平**：`aplan_waves` 命中环 → 线程带 `return_stage="repo_plan"`。
5. **expire_waiters 挂 barrier 续驱**：回拨 `created_at` 后 `aexpire_stale_waiters` 返回仓清单且
   waiter 置 `superseded`（**不新起定时任务**）。
6. **事件留痕**：`blueprint.context.waiter_registered` / `waiter_satisfied` 各 emit 一次，
   payload 只含标量与仓 id。
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings
from django.utils import timezone

from agents.models import AgentSession
from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintContextEntry,
    BlueprintThread,
    ContextEntryKind,
    ContextEntryStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
)
from delivery.services.blueprint_context_service import BlueprintContextService
from repositories.models import Repository
from runners.models import Runner
from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter
from subagent.models import SubAgentSession

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_RUNTIME_CFG = "services.provider_config.aget_claude_code_runtime_config"
_GIT_TOKEN = "services.git_credentials.aresolve_git_token"
_NO_BARRIER = patch(
    "subagent.api.callbacks._trigger_blueprint_repo_plan_barrier", new_callable=AsyncMock
)


# ── 工厂与替身 ────────────────────────────────────────────────────────────


class _FakeDispatcher:
    """容器派发替身：`await_count == 0` 即「没起任何容器」的硬证据。"""

    def __init__(self) -> None:
        self.tasks: list[Any] = []
        self.await_count = 0

    async def dispatch(self, task: Any) -> None:
        self.await_count += 1
        self.tasks.append(task)


def _stub_runtime():
    return (
        patch(_RUNTIME_CFG, new=AsyncMock(return_value={"api_key": "k", "default_model": "m"})),
        patch(_GIT_TOKEN, new=AsyncMock(return_value="")),
    )


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


async def _make_online_runner() -> Runner:
    return await Runner.objects.acreate(
        name=f"runner-{uuid.uuid4().hex[:6]}",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=Runner.Status.ONLINE,
        last_heartbeat=timezone.now(),
    )


def _association(repo: Repository, *, role: str = "direct", **extra) -> dict:
    item = {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role": role,
        "responsibility": [{"block_id": f"blk_{repo.name}", "type": "paragraph", "text": "职责"}],
        "fitness": {"verdict": "suitable", "reasons": [], "citations": []},
    }
    item.update(extra)
    return item


async def _make_locked_session(*associations: dict):
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={"repo_associations": list(associations)}
    )
    artifact.current_version = version
    await artifact.asave(update_fields=["current_version"])
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_plan",
        current_artifact_version_id=version.id,
    )
    return session, artifact


def _repo_plan_section(repository_id: str, **overrides) -> dict:
    section: dict[str, Any] = {
        "repository_id": repository_id,
        "role": "direct",
        "impl_items": [
            {"item_id": "it_1", "title": "改动", "change_type": "modify", "how": "改一处"}
        ],
    }
    section.update(overrides)
    return section


async def _record_repo_plan(session, repo: Repository, section: dict | None = None):
    task, _ = await sync_to_async(RepoResearchTask.objects.get_or_create)(
        session=session, repository=repo, defaults={"status": RepoResearchTaskStatus.DONE}
    )
    await PartialPlan.objects.acreate(
        research_task=task,
        content={
            "repository_id": str(repo.id),
            "repo_plan": section or _repo_plan_section(str(repo.id)),
        },
        content_hash="h" * 8,
        valid=True,
    )
    return task


async def _make_plan_container(session, repo: Repository, task):
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    return await SubAgentSession.objects.acreate(
        session_id=f"bp-plan-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": "blueprint_repo_plan",
            "blueprint_session_id": str(session.id),
            "research_task_id": str(task.id),
            "repository_id": str(repo.id),
        },
    )


@sync_to_async
def _claims(session_id, *, status: str = ContextEntryStatus.ACTIVE) -> list[BlueprintContextEntry]:
    return list(
        BlueprintContextEntry.objects.filter(
            convergence_session_id=session_id,
            kind=ContextEntryKind.DEPENDENCY_CLAIM,
            status=status,
        ).order_by("seq")
    )


@sync_to_async
def _threads(artifact_id=None) -> list[BlueprintThread]:
    query = BlueprintThread.objects.all()
    if artifact_id is not None:
        query = query.filter(artifact_id=artifact_id)
    return list(query)


@sync_to_async
def _thread_questions(thread_id) -> str:
    from delivery.models import BlueprintThreadMessage

    return "\n".join(
        BlueprintThreadMessage.objects.filter(thread_id=thread_id).values_list("body", flat=True)
    )


@sync_to_async
def _events(session_id, event: str) -> list[ConvergenceSessionEvent]:
    return list(
        ConvergenceSessionEvent.objects.filter(session_id=session_id, event=event).order_by("ts")
    )


# ===========================================================================
# 1. waiting_context 登记不判完成（路径 2 的前半）
# ===========================================================================


async def test_waiting_context_registers_waiter_without_completing() -> None:
    """带 waiting_context 的回调 → 登记 waiter、不落 repo_plan、task 置回可派发、零派发。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    task = await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_a, status=RepoResearchTaskStatus.RUNNING
    )
    # 上一轮的部分产物（长等待退出时容器已 report 过 partial）
    partial = await PartialPlan.objects.acreate(
        research_task=task,
        content={"repository_id": str(repo_a.id), "current_state": [{"summary": "看过了"}]},
        content_hash="h" * 8,
        valid=True,
    )
    sub = await _make_plan_container(session, repo_a, task)
    dispatcher = _FakeDispatcher()

    payload = {
        "output": {
            "waiting_context": {
                "keys": [f"repo:{repo_b.id}.api_surface"],
                "partial_plan_id": str(partial.id),
                "reason": "需要 B 的接口契约",
            }
        }
    }
    with patch("runners.dispatcher.get_dispatcher", lambda: dispatcher), _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    # 登记了一条 active waiter，且携带 partial 引用
    claims = await _claims(session.id)
    assert len(claims) == 1
    assert claims[0].content["from_repository_id"] == str(repo_a.id)
    assert claims[0].content["wait_key_pattern"] == f"repo:{repo_b.id}.api_surface"
    assert claims[0].content["partial_plan_id"] == str(partial.id)

    # **不判完成**：没有任何一行 content 带 repo_plan 段
    contents = [
        row
        async for row in PartialPlan.objects.filter(research_task=task).values_list(
            "content", flat=True
        )
    ]
    assert contents, "上一轮 partial 仍在"
    assert all("repo_plan" not in (content or {}) for content in contents)

    # task 被置回可派发态（STALE），等重派驱动续作
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    # 登记阶段绝不派发（重派由写入侧端点触发）
    assert dispatcher.await_count == 0


async def test_waiting_context_without_keys_falls_through_to_repo_plan_parsing() -> None:
    """`waiting_context` 没有 keys → 不当等待处理，仍走正常 repo_plan 解析（不吞产物）。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a))
    task = await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_a, status=RepoResearchTaskStatus.RUNNING
    )
    sub = await _make_plan_container(session, repo_a, task)

    payload = {
        "output": {
            "waiting_context": {"keys": []},
            "repo_plan": _repo_plan_section(str(repo_a.id)),
        }
    }
    with _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    assert await _claims(session.id) == []
    row = await PartialPlan.objects.filter(research_task=task).order_by("-created_at").afirst()
    assert row is not None
    assert row.content["repo_plan"]["impl_items"]


# ===========================================================================
# 2. ⭐ 路径 3 —— 互等环在登记瞬间抛澄清（零 sleep 依赖）
# ===========================================================================


async def test_mutual_wait_cycle_opens_blocking_clarification_without_dispatch() -> None:
    """A 等 B、B 等 A → 第二次登记立即判环、开 blocking 线程、零派发、该 waiter 置 superseded。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    service = BlueprintContextService()
    dispatcher = _FakeDispatcher()

    with patch("runners.dispatcher.get_dispatcher", lambda: dispatcher):
        first = await service.register_waiter(
            session=session,
            from_repository_id=str(repo_a.id),
            wait_key_pattern=f"repo:{repo_b.id}.api_surface",
            reason="A 等 B",
        )
        # 第一次不成环：不开线程
        assert first["cycle_detected"] is False
        assert await _threads(artifact.id) == []

        second = await service.register_waiter(
            session=session,
            from_repository_id=str(repo_b.id),
            wait_key_pattern=f"repo:{repo_a.id}.api_surface",
            reason="B 等 A",
        )

    # ⭐ 环在**登记瞬间**被判定（本用例零 sleep、零超时依赖）
    assert second["cycle_detected"] is True
    assert {frozenset(cycle) for cycle in second["cycle"]} == {
        frozenset({str(repo_a.id), str(repo_b.id)})
    }

    threads = await _threads(artifact.id)
    assert len(threads) == 1
    assert threads[0].kind == ThreadKind.AI_CLARIFICATION
    assert threads[0].blocking is True

    # ⭐ 命中环绝不 dispatch（交人裁决，不自作主张排序）
    assert dispatcher.await_count == 0

    # 命中环的 waiter 自身置 superseded（已交人裁决，不再等）
    superseded = await _claims(session.id, status=ContextEntryStatus.SUPERSEDED)
    assert [str(row.id) for row in superseded] == [second["entry_id"]]

    # 线程文本含两个仓 id，但不含任何 content 正文
    question = await _thread_questions(threads[0].id)
    assert str(repo_a.id) in question
    assert str(repo_b.id) in question
    assert "A 等 B" not in question


async def test_cycle_exit_lands_stale_task_and_stays_redispatchable() -> None:
    """⭐ MJ-02：成环退出后 task 落 **STALE**（可重派态），且澄清关闭后 `dispatch_plans` 能重派。

    原实现成环分支什么都不做 → task 停在 RUNNING → `mark_stale` 按 WR-01 只动终态 task 而
    跳过它 → 派发面的 DISPATCHABLE 白名单（pending/stale）也跳过该仓 ⇒ 人裁决完澄清后该仓
    **永远无法重派**，会话静默悬挂，只能改库恢复。
    """
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    await _make_online_runner()
    task_a = await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_a, status=RepoResearchTaskStatus.RUNNING
    )
    sub = await _make_plan_container(session, repo_a, task_a)

    # 先造对侧 waiter（B 等 A），本次 A 等 B 即成环。
    await BlueprintContextService().register_waiter(
        session=session,
        from_repository_id=str(repo_b.id),
        wait_key_pattern=f"repo:{repo_a.id}.api_surface",
        reason="B 等 A",
    )

    dispatcher = _FakeDispatcher()
    payload = {
        "output": {
            "waiting_context": {"keys": [f"repo:{repo_b.id}.api_surface"], "reason": "A 等 B"}
        }
    }
    with patch("runners.dispatcher.get_dispatcher", lambda: dispatcher), _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    # 环已抛澄清（service 侧），且**不派发**
    threads = await _threads(artifact.id)
    assert len(threads) == 1
    assert threads[0].blocking is True
    assert dispatcher.await_count == 0

    # ⭐ 关键断言：task 落 STALE 而不是卡在 RUNNING
    await task_a.arefresh_from_db()
    assert task_a.status == RepoResearchTaskStatus.STALE
    assert task_a.error["reason"] == "waiting_context_cycle"

    # ⭐ 反向断言：澄清关闭 + waiter 清空后，派发面能真的重派该仓（不是死仓）
    await BlueprintContextEntry.objects.filter(
        convergence_session_id=session.id, kind=ContextEntryKind.DEPENDENCY_CLAIM
    ).aupdate(status=ContextEntryStatus.SUPERSEDED)
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()
    with cfg, git, override_settings(FRIDAY_BASE_URL="https://friday.example.com"):
        result = await BlueprintRepoPlanAdapter(research_adapter=research).dispatch_plans(session)
    assert str(repo_a.id) in {
        row.last_output["repository_id"]
        async for row in SubAgentSession.objects.filter(
            session_id__in=[t.session_id for t in dispatcher.tasks]
        )
    }
    assert result["dispatched"] >= 1


async def test_active_waiter_blocks_redispatch_of_that_repo() -> None:
    """⭐ MJ-02 显式门控：仓仍有 active waiter 时 `dispatch_plans` **不重派**它（不烧额度）。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    await _make_online_runner()
    await BlueprintContextService().register_waiter(
        session=session,
        from_repository_id=str(repo_a.id),
        wait_key_pattern=f"repo:{repo_b.id}.api_surface",
        reason="A 等 B",
    )

    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()
    with cfg, git, override_settings(FRIDAY_BASE_URL="https://friday.example.com"):
        result = await BlueprintRepoPlanAdapter(research_adapter=research).dispatch_plans(session)

    dispatched_ids = {
        row.last_output["repository_id"]
        async for row in SubAgentSession.objects.filter(
            session_id__in=[t.session_id for t in dispatcher.tasks]
        )
    }
    # B（没在等）照常派；A（在等 B）本轮跳过 —— 证明门控不是「全都不派」
    assert dispatched_ids == {str(repo_b.id)}
    assert result["dispatched"] == 1


async def test_all_repos_waiting_opens_blocking_thread_instead_of_silent_hang() -> None:
    """⭐ MJ-03：两仓都以 `waiting_context` 退出且 key 永不出现 → 落 open blocking 线程。

    这条路径上**所有容器都已退出** ⇒ 不会再有回调 ⇒ engine 不会再 advance ⇒ 挂在
    `_h_bp_repo_plan` 里的超龄清理与 stuck 探测都不可达。原实现因此永久停在 `waiting_event`：
    无澄清线程、无失败、无任何用户可见信号。
    """
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    dispatcher = _FakeDispatcher()

    # 两仓分别等一个**永不出现**的 key（互不成环：等的是第三方 contract:）
    for repo, other in ((repo_a, "contract:never_a"), (repo_b, "contract:never_b")):
        task = await sync_to_async(RepoResearchTask.objects.create)(
            session=session, repository=repo, status=RepoResearchTaskStatus.RUNNING
        )
        sub = await _make_plan_container(session, repo, task)
        payload = {"output": {"waiting_context": {"keys": [other], "reason": "等第三方契约"}}}
        with patch("runners.dispatcher.get_dispatcher", lambda: dispatcher), _NO_BARRIER:
            await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    # ⭐ 死锁可见：一条 open blocking 澄清线程，带 return_stage="repo_plan"（B3）
    threads = await _threads(artifact.id)
    assert len(threads) == 1, "全员长等待必须留下用户可见的阻塞线程"
    assert threads[0].blocking is True
    assert threads[0].return_stage == "repo_plan"
    question = await _thread_questions(threads[0].id)
    assert str(repo_a.id) in question and str(repo_b.id) in question
    assert "等第三方契约" not in question, "澄清文本不得夹带容器上报的自由文本"
    # 判定过程零派发（不自作主张重派）
    assert dispatcher.await_count == 0


async def test_partial_waiting_does_not_open_deadlock_thread() -> None:
    """MJ-03 反向：只有一个仓在等、另一个仓的容器仍在途 → **不**开死锁线程（断言非恒真）。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    # B 的容器仍 RUNNING
    await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_b, status=RepoResearchTaskStatus.RUNNING
    )
    task_a = await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_a, status=RepoResearchTaskStatus.RUNNING
    )
    sub = await _make_plan_container(session, repo_a, task_a)

    payload = {"output": {"waiting_context": {"keys": [f"repo:{repo_b.id}.api_surface"]}}}
    with _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    assert await _threads(artifact.id) == []


async def test_waiting_exit_expires_overdue_waiters_and_redispatches() -> None:
    """⭐ MJ-03 自愈路径：容器退出瞬间清一次超龄 waiter 并重派（不新起定时任务）。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    await _make_online_runner()

    # A 的 waiter 早已超龄（回拨 created_at；auto_now_add 需显式 update）
    overdue = await BlueprintContextService().register_waiter(
        session=session,
        from_repository_id=str(repo_a.id),
        wait_key_pattern="contract:never",
        reason="等了很久",
    )
    await BlueprintContextEntry.objects.filter(id=overdue["entry_id"]).aupdate(
        created_at=timezone.now() - timezone.timedelta(seconds=7200)
    )

    task_b = await sync_to_async(RepoResearchTask.objects.create)(
        session=session, repository=repo_b, status=RepoResearchTaskStatus.RUNNING
    )
    sub = await _make_plan_container(session, repo_b, task_b)
    dispatcher = _FakeDispatcher()
    payload = {"output": {"waiting_context": {"keys": [f"repo:{repo_a.id}.api_surface"]}}}
    cfg, git = _stub_runtime()
    with (
        patch("runners.dispatcher.get_dispatcher", lambda: dispatcher),
        cfg,
        git,
        override_settings(FRIDAY_BASE_URL="https://friday.example.com"),
        _NO_BARRIER,
    ):
        await _handle_blueprint_repo_plan_completion(sub, payload, _log())

    # 超龄 waiter 被清（置 superseded）并触发 A 的重派
    assert overdue["entry_id"] not in {str(row.id) for row in await _claims(session.id)}
    dispatched_ids = {
        row.last_output["repository_id"]
        async for row in SubAgentSession.objects.filter(
            session_id__in=[t.session_id for t in dispatcher.tasks]
        )
    }
    assert str(repo_a.id) in dispatched_ids


async def test_wave_cycle_opens_clarification_with_return_stage() -> None:
    """`aplan_waves` 命中互等环 → blocking 澄清线程带 `return_stage="repo_plan"`（B3）。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, artifact = await _make_locked_session(
        _association(
            repo_a,
            apis_provided=[{"name": "a_api"}],
            apis_consumed=[{"name": "b_api"}],
        ),
        _association(
            repo_b,
            apis_provided=[{"name": "b_api"}],
            apis_consumed=[{"name": "a_api"}],
        ),
    )

    result = await BlueprintRepoPlanAdapter().aplan_waves(session)

    assert result["cycles"], "互等环必须如实上报"
    threads = await _threads(artifact.id)
    assert len(threads) == 1
    assert threads[0].blocking is True
    assert threads[0].return_stage == "repo_plan"
    # 成环仓不丢：仍出现在 waves 里
    assert {rid for ids in result["waves"].values() for rid in ids} == {
        str(repo_a.id),
        str(repo_b.id),
    }
    question = await _thread_questions(threads[0].id)
    assert str(repo_a.id) in question and str(repo_b.id) in question

    # 幂等：已有阻塞澄清线程时不再叠开（不刷 HITL 面板）
    await BlueprintRepoPlanAdapter().aplan_waves(session)
    assert len(await _threads(artifact.id)) == 1


# ===========================================================================
# 3. 波次预排驱动派发
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_dispatch_plans_only_dispatches_current_wave() -> None:
    """预排 {1:[B], 2:[A]} → 首轮只派 provider 仓 B；B 产出后再调才派 consumer 仓 A。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(
        _association(repo_a, apis_consumed=[{"name": "b_api"}]),
        _association(repo_b, apis_provided=[{"name": "b_api"}]),
    )
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    adapter = BlueprintRepoPlanAdapter(research_adapter=research)
    cfg, git = _stub_runtime()

    prearrange = await adapter.aplan_waves(session)
    assert prearrange["waves"] == {1: [str(repo_b.id)], 2: [str(repo_a.id)]}

    with cfg, git:
        first = await adapter.dispatch_plans(session)

    assert first["dispatched"] == 1
    assert dispatcher.await_count == 1
    dispatched_sub = await SubAgentSession.objects.filter(
        session_id=dispatcher.tasks[0].session_id
    ).afirst()
    assert dispatched_sub is not None
    assert dispatched_sub.last_output["repository_id"] == str(repo_b.id)
    # ⭐ A 本轮**没起容器**（等 B 的契约先上总线）；两仓都在 pending（B 在途、A 待下一波）
    assert first["pending"] == 2
    assert first["completed"] == []
    dispatched_repository_ids = [
        row.last_output["repository_id"]
        async for row in SubAgentSession.objects.filter(
            session_id__in=[task.session_id for task in dispatcher.tasks]
        )
    ]
    assert dispatched_repository_ids == [str(repo_b.id)]

    # B 产出 repo_plan → 下一波变成当前波次
    await _record_repo_plan(session, repo_b)
    cfg2, git2 = _stub_runtime()
    with cfg2, git2:
        second = await adapter.dispatch_plans(session)

    assert second["dispatched"] == 1
    assert dispatcher.await_count == 2
    second_sub = await SubAgentSession.objects.filter(
        session_id=dispatcher.tasks[1].session_id
    ).afirst()
    assert second_sub is not None
    assert second_sub.last_output["repository_id"] == str(repo_a.id)


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_no_api_info_keeps_full_parallel_dispatch() -> None:
    """无接口信息（首轮常态）→ 全部在 wave 1，两仓同轮派发（预排前行为零回归）。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    await _make_online_runner()
    dispatcher = _FakeDispatcher()
    research = BlueprintResearchAdapter(
        dispatcher_factory=lambda: dispatcher, charters_loader=AsyncMock(return_value={})
    )
    cfg, git = _stub_runtime()

    with cfg, git:
        result = await BlueprintRepoPlanAdapter(research_adapter=research).dispatch_plans(session)

    assert result["dispatched"] == 2
    assert dispatcher.await_count == 2


async def test_build_stage_state_carries_wave_summary() -> None:
    """`build_stage_state(waves=…)` 只写 id 与计数摘要（正文绝不进 stage_state）。"""
    state = BlueprintRepoPlanAdapter().build_stage_state(
        plans={"a": {"impl_items": []}},
        dispatched=["b"],
        pending=["b"],
        waves={"waves": {1: ["b"], 2: ["a"]}, "cycle_count": 0, "unresolved_count": 1},
    )
    assert state["waves"] == {
        "waves": {"1": ["b"], "2": ["a"]},
        "cycle_count": 0,
        "unresolved_count": 1,
    }
    assert len(json.dumps(state)) < 2048
    # 不传 waves 时不写该键（波次是可选摘要）
    assert "waves" not in BlueprintRepoPlanAdapter().build_stage_state(
        plans={}, dispatched=[], pending=[]
    )


# ===========================================================================
# 5. expire_waiters 挂 barrier 续驱（不新起定时任务）
# ===========================================================================


async def test_expire_stale_waiters_returns_repository_ids() -> None:
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    waiter = await BlueprintContextService().register_waiter(
        session=session,
        from_repository_id=str(repo_a.id),
        wait_key_pattern=f"repo:{repo_b.id}.api_surface",
    )

    # 回拨 created_at 造「超龄」（auto_now_add 需显式 update）
    await BlueprintContextEntry.objects.filter(id=waiter["entry_id"]).aupdate(
        created_at=timezone.now() - timezone.timedelta(seconds=3600)
    )

    expired = await BlueprintRepoPlanAdapter().aexpire_stale_waiters(session, max_age_seconds=60)
    assert expired == [str(repo_a.id)]
    assert await _claims(session.id) == []
    assert len(await _claims(session.id, status=ContextEntryStatus.SUPERSEDED)) == 1

    # 幂等：二次清理无可清对象
    assert await BlueprintRepoPlanAdapter().aexpire_stale_waiters(session) == []


# ===========================================================================
# 6. 事件留痕
# ===========================================================================


async def test_waiter_events_emitted_with_scalar_payload_only() -> None:
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session, _artifact = await _make_locked_session(_association(repo_a), _association(repo_b))
    service = BlueprintContextService()

    await service.register_waiter(
        session=session,
        from_repository_id=str(repo_a.id),
        wait_key_pattern=f"repo:{repo_b.id}.api_surface",
        reason="需要 B 的接口契约",
    )
    await service.append_entry(
        session=session,
        key=f"repo:{repo_b.id}.api_surface",
        kind=ContextEntryKind.API_SURFACE,
        content={"name": "listX", "secret_note": "机密正文"},
        repository_id=str(repo_b.id),
    )
    satisfied = await service.satisfy_waiters(
        session=session, key=f"repo:{repo_b.id}.api_surface", repository_id=str(repo_b.id)
    )
    assert satisfied == [str(repo_a.id)]

    registered_events = await _events(session.id, "blueprint.context.waiter_registered")
    satisfied_events = await _events(session.id, "blueprint.context.waiter_satisfied")
    assert len(registered_events) == 1
    assert len(satisfied_events) == 1
    assert registered_events[0].payload["from_repository_id"] == str(repo_a.id)
    assert satisfied_events[0].payload["redispatch_repository_ids"] == [str(repo_a.id)]
    # payload 只含标量与仓 id：条目正文绝不进事件
    dumped = json.dumps(
        [registered_events[0].payload, satisfied_events[0].payload], ensure_ascii=False
    )
    assert "机密正文" not in dumped
