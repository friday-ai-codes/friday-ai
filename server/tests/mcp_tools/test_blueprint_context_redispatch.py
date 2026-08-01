"""SC2 路径 1/2 端到端测试（BUS-02，Phase 113-04）—— **触发点必须是真实端点**。

本文件守 ROADMAP SC2 的前两条路径，全部用例**真打 URL**：

- 路径 1（短等待增量命中）：`POST /api/mcp/tools/read_blueprint_context/` 两次，中间由另一个容器
  `POST /api/mcp/tools/report_blueprint_context/` 写入 —— 断言两次返回条目集合**无重叠**且第二次
  命中目标 key 且 seq 严格大于前次 max_seq（容器侧的「命中即停轮询」由
  `task/tests/test_blueprint_context_wait.py` 覆盖，此处不重复）。
- 路径 2（长等待退出后自动重派）：⭐ 触发点固定为真打 `report_blueprint_context` 端点。
  **绝不**用「直接调 service / 直接调 `aredispatch_waiting_repos`」替代 —— 绕过端点等于
  SC-2 第二条路径的运行时触发点从未被测（B2）。断言：恰好重派 1 次、prompt 带
  `partial_plan_id` 续作引用、waiter 置 `superseded`、二次写入幂等不再重派、重派失败不反噬 200。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from agents.models import AgentSession
from delivery.models import (
    BlueprintContextEntry,
    ContextEntryStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services.blueprint_context_service import BlueprintContextService
from repositories.models import Repository
from runners.models import Runner
from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)

# 真打 URL（与 mcp_tools/urls.py 逐字一致）。
_READ_URL = "/api/mcp/tools/read_blueprint_context/"
_REPORT_URL = "/api/mcp/tools/report_blueprint_context/"

_RUNTIME_CFG = "services.provider_config.aget_claude_code_runtime_config"
_GIT_TOKEN = "services.git_credentials.aresolve_git_token"


# ---------------------------------------------------------------------------
# 工厂与替身
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    """容器派发替身：记录每次 DispatchTask（与 113-03 编排面测试同形）。"""

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


async def _make_user(username: str):
    from django.contrib.auth import get_user_model

    return await sync_to_async(get_user_model().objects.create_user)(
        username=username, password="x"
    )


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


async def _make_online_runner() -> Runner:
    from django.utils import timezone

    return await Runner.objects.acreate(
        name=f"runner-{uuid.uuid4().hex[:6]}",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=Runner.Status.ONLINE,
        last_heartbeat=timezone.now(),
    )


async def _make_blueprint_session(*, created_by=None) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="repo_plan",
        created_by=created_by,
    )


async def _make_container_session(
    blueprint_session: ConvergenceSession, *, owner, repository: Repository
) -> SubAgentSession:
    """派发链上的容器会话（`AgentSession.user` 是 113-02 归属校验的唯一数据来源）。

    `RepoResearchTask.subagent_session` 绑定模拟 `mark_running` 的服务端回填 —— 它是
    仓归属（CR-01）的唯一权威链，没有它容器写不了任何 `repo:` 前缀 key。
    """
    sid = f"bp-plan-{uuid.uuid4().hex[:12]}"
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{sid}",
        status=AgentSession.Status.RUNNING,
        user=owner,
        metadata={"source": "blueprint_repo_plan"},
    )
    sub = await SubAgentSession.objects.acreate(
        session_id=sid,
        main_session=agent_session,
        repo_url="https://example.com/x.git",
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": "blueprint_repo_plan",
            "blueprint_session_id": str(blueprint_session.id),
            "repository_id": str(repository.id),
        },
    )
    task, _ = await sync_to_async(RepoResearchTask.objects.get_or_create)(
        session=blueprint_session,
        repository=repository,
        defaults={"status": RepoResearchTaskStatus.RUNNING},
    )
    task.subagent_session = sub
    await sync_to_async(task.save)(update_fields=["subagent_session", "updated_at"])
    return sub


async def _make_partial_plan(session: ConvergenceSession, repo: Repository) -> PartialPlan:
    """A 仓上一轮的部分产物（长等待退出时已保存），重派时作续作引用。"""
    task, _ = await sync_to_async(RepoResearchTask.objects.get_or_create)(
        session=session, repository=repo, defaults={"status": RepoResearchTaskStatus.DONE}
    )
    return await PartialPlan.objects.acreate(
        research_task=task,
        content={"repository_id": str(repo.id), "current_state": [{"summary": "看过了"}]},
        content_hash="h" * 8,
        valid=True,
    )


def _headers(sub: SubAgentSession) -> dict:
    return {"HTTP_X_FRIDAY_SESSION_ID": sub.session_id}


@sync_to_async
def _entry_status(entry_id) -> str:
    row = BlueprintContextEntry.objects.filter(id=entry_id).first()
    return getattr(row, "status", "")


# ===========================================================================
# 路径 1 — 短等待增量命中（真打 read 端点）
# ===========================================================================


async def test_incremental_poll_sees_only_new_entry_after_report(mcp_client, access_user) -> None:
    """A 轮询 read（空）→ B report → A 带 max_seq 再 read：只拿到新增条目。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session(created_by=access_user)
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    waiter_container = await _make_container_session(cs, owner=access_user, repository=repo_a)
    provider_container = await _make_container_session(cs, owner=access_user, repository=repo_b)

    # 先写一条无关条目，使「第一次 read 非空」也成立（否则空集合无重叠是平凡真）。
    seed = await sync_to_async(client.post)(
        _REPORT_URL,
        {"key": "contract:unrelated", "kind": "contract", "content": {"note": "x"}},
        format="json",
        **_headers(provider_container),
    )
    assert seed.status_code == 200, seed.content

    first = await sync_to_async(client.post)(
        _READ_URL, {"since_seq": 0}, format="json", **_headers(waiter_container)
    )
    assert first.status_code == 200
    first_body = first.json()
    assert [entry["key"] for entry in first_body["entries"]] == ["contract:unrelated"]
    cursor = first_body["max_seq"]
    assert cursor == 1

    report = await sync_to_async(client.post)(
        _REPORT_URL,
        {
            "key": f"repo:{repo_b.id}.api_surface",
            "kind": "api_surface",
            "content": {"name": "listX", "method": "GET", "path": "/x"},
        },
        format="json",
        **_headers(provider_container),
    )
    assert report.status_code == 200
    assert report.json()["applied"] is True

    second = await sync_to_async(client.post)(
        _READ_URL, {"since_seq": cursor}, format="json", **_headers(waiter_container)
    )
    assert second.status_code == 200
    second_body = second.json()

    first_ids = {entry["id"] for entry in first_body["entries"]}
    second_ids = {entry["id"] for entry in second_body["entries"]}
    # ⭐ 增量语义成立：两次返回条目集合无重叠（不重复拉全量）。
    assert first_ids and second_ids
    assert first_ids.isdisjoint(second_ids)
    assert [entry["key"] for entry in second_body["entries"]] == [f"repo:{repo_b.id}.api_surface"]
    assert second_body["entries"][0]["seq"] > cursor
    assert second_body["max_seq"] > cursor


# ===========================================================================
# 路径 2 — 长等待退出后经**真打 report 端点**自动重派
# ===========================================================================


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_report_endpoint_redispatches_waiting_repo_with_partial_reference(
    mcp_client, access_user, monkeypatch
) -> None:
    """⭐ 触发点是真打 `report_blueprint_context`：waiter 满足 → 恰好重派 1 次 + 带 partial 引用。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session(created_by=access_user)
    repo_a = await _make_repo()  # consumer：在等 B 的契约
    repo_b = await _make_repo()  # provider：本次写入方
    partial = await _make_partial_plan(cs, repo_a)
    await _make_online_runner()
    provider_container = await _make_container_session(cs, owner=access_user, repository=repo_b)

    wait_key = f"repo:{repo_b.id}.api_surface"
    waiter = await BlueprintContextService().register_waiter(
        session=cs,
        from_repository_id=str(repo_a.id),
        wait_key_pattern=wait_key,
        partial_plan_id=str(partial.id),
        reason="需要 B 的接口契约",
    )
    assert waiter["cycle_detected"] is False

    dispatcher = _FakeDispatcher()
    monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: dispatcher)
    cfg, git = _stub_runtime()

    with cfg, git:
        resp = await sync_to_async(client.post)(
            _REPORT_URL,
            {
                "key": wait_key,
                "kind": "api_surface",
                "repository_id": str(repo_b.id),
                "content": {"name": "listX", "method": "GET", "path": "/x"},
            },
            format="json",
            **_headers(provider_container),
        )

    # ⭐断言 a：响应体同时回报满足数与重派数
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["applied"] is True
    assert body["satisfied_waiters"] == 1
    assert body["redispatched"] == 1

    # ⭐断言 b：waiter 已置 superseded（DB 重读）+ 恰好 1 次新派发，且指向 A 仓
    assert await _entry_status(waiter["entry_id"]) == ContextEntryStatus.SUPERSEDED
    assert dispatcher.await_count == 1
    task = dispatcher.tasks[0]
    assert task.task_id.startswith("bp-plan-")
    sub = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
    assert sub is not None
    assert sub.last_output["repository_id"] == str(repo_a.id)
    assert sub.last_output["source"] == "blueprint_repo_plan"
    # 续作引用注入生效：prompt 带上一轮 partial 产物 id（不是从零重做）
    assert "partial_plan_id" in task.prompt
    assert str(partial.id) in task.prompt
    # 方案正文不进 prompt 的续作段（只带段名）
    assert "看过了" not in task.prompt

    # ⭐断言 c：幂等 —— 同 key 再写一次，满足数 0 且 dispatcher 不再增加
    with _stub_runtime()[0], _stub_runtime()[1]:
        again = await sync_to_async(client.post)(
            _REPORT_URL,
            {
                "key": wait_key,
                "kind": "api_surface",
                "repository_id": str(repo_b.id),
                "content": {"name": "listX", "method": "GET", "path": "/x"},
            },
            format="json",
            **_headers(provider_container),
        )
    assert again.status_code == 200
    assert again.json()["satisfied_waiters"] == 0
    assert again.json()["redispatched"] == 0
    assert dispatcher.await_count == 1, "同事务置 superseded 杜绝重复重派"


@override_settings(FRIDAY_BASE_URL="https://friday.example.com")
async def test_redispatch_failure_never_breaks_report_response(
    mcp_client, access_user, monkeypatch
) -> None:
    """⭐断言 d：重派抛异常 → report 仍 200 且 applied=True（best-effort，绝不反噬写入）。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session(created_by=access_user)
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    provider_container = await _make_container_session(cs, owner=access_user, repository=repo_b)

    wait_key = f"repo:{repo_b.id}.api_surface"
    waiter = await BlueprintContextService().register_waiter(
        session=cs,
        from_repository_id=str(repo_a.id),
        wait_key_pattern=wait_key,
        reason="需要 B 的接口契约",
    )

    async def _boom(self, session, repository_ids):
        raise RuntimeError("redispatch exploded friday_pat_abcdefghij1234567890")

    monkeypatch.setattr(BlueprintRepoPlanAdapter, "aredispatch_waiting_repos", _boom)

    resp = await sync_to_async(client.post)(
        _REPORT_URL,
        {
            "key": wait_key,
            "kind": "api_surface",
            "repository_id": str(repo_b.id),
            "content": {"name": "listX"},
        },
        format="json",
        **_headers(provider_container),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True  # 写入语义不变
    assert body["satisfied_waiters"] == 1  # 置位也已发生
    assert body["redispatched"] == 0  # 只有重派计数降级为 0
    # 置 superseded 与写入同事务，不受重派失败影响
    assert await _entry_status(waiter["entry_id"]) == ContextEntryStatus.SUPERSEDED


async def test_report_without_waiter_reports_zero_redispatch(mcp_client, access_user) -> None:
    """无 waiter 时不触碰派发面：`redispatched == 0`（键恒在，下游无需判空）。"""
    client, _ = mcp_client
    cs = await _make_blueprint_session(created_by=access_user)
    repo_b = await _make_repo()
    container = await _make_container_session(cs, owner=access_user, repository=repo_b)

    resp = await sync_to_async(client.post)(
        _REPORT_URL,
        {
            "key": f"repo:{repo_b.id}.api_surface",
            "kind": "api_surface",
            "content": {"name": "x"},
        },
        format="json",
        **_headers(container),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["satisfied_waiters"] == 0
    assert body["redispatched"] == 0
