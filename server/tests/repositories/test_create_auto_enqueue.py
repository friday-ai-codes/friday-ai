"""建仓自动入队：index + summary 归因、幂等键、失败不阻塞、禁止 durable_graph。"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from projects.models import Space
from repositories.models import IndexHistory, IndexHistoryStatus, IndexStatus, Repository
from repositories.views import _acreate_repository_core

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _auth_headers(user: User) -> dict[str, str]:
    refresh = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {refresh.access_token}"}


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(username="creator", email="c@e.com", password="x")


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="create-space")


async def test_acreate_enqueues_index_and_summary_with_actor(user: User, space: Space) -> None:
    """建仓后入队 durable_index + durable_repo_summary，带创建者归因，从不入队 durable_graph。"""
    captured: list[tuple[str, dict, dict]] = []

    async def _fake_defer(task, payload, **kwargs):
        captured.append((task, dict(payload), dict(kwargs)))
        return f"job-{task}-{payload.get('repository_id')}"

    with (
        patch("durable.service.DurableTaskService.defer", side_effect=_fake_defer),
        patch("durable.concurrency.aindex_lock", AsyncMock(return_value="index-slot-0")),
        patch("durable.concurrency.asummary_lock", AsyncMock(return_value="summary-slot-0")),
    ):
        repo = await _acreate_repository_core(
            {
                "name": "auto-enq",
                "git_url": "https://github.com/t/auto.git",
                "git_platform": "github",
                "access_token": "tok",
                "space_ids": [space.id],
            },
            actor=user,
        )

    tasks = [t for t, _, _ in captured]
    assert "durable_index" in tasks
    assert "durable_repo_summary" in tasks
    assert "durable_graph" not in tasks

    actor_id = str(user.id)
    for task, payload, kwargs in captured:
        assert kwargs.get("initiated_by_user_id") == actor_id
        if task == "durable_index":
            assert kwargs.get("idempotency_key") == f"index:{repo.id}"
            assert payload.get("trigger") == "create"
            assert payload.get("repository_id") == str(repo.id)
        if task == "durable_repo_summary":
            assert kwargs.get("idempotency_key") == f"summary:{repo.id}"

    # 返回实例应已反映入队后的 DB 状态（勿仍为 not_indexed）
    assert repo.index_status == IndexStatus.INDEXING
    hist = await IndexHistory.objects.filter(repository=repo).afirst()
    assert hist is not None
    assert hist.status == IndexHistoryStatus.RUNNING


async def test_create_api_response_index_status_indexing(user: User, space: Space) -> None:
    """API 201 响应体 index_status 应为 indexing（入队成功后）。"""

    async def _fake_defer(task, payload, **kwargs):
        return f"job-{task}"

    with (
        patch("durable.service.DurableTaskService.defer", side_effect=_fake_defer),
        patch("durable.concurrency.aindex_lock", AsyncMock(return_value="index-slot-0")),
        patch("durable.concurrency.asummary_lock", AsyncMock(return_value="summary-slot-0")),
    ):
        client = AsyncClient()
        resp = await client.post(
            "/api/repositories/",
            data={
                "name": "resp-idx",
                "git_url": "https://github.com/t/resp.git",
                "git_platform": "github",
                "access_token": "tok",
                "space_ids": [str(space.id)],
            },
            content_type="application/json",
            headers=await _auth_headers(user),
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body.get("index_status") == IndexStatus.INDEXING


async def test_enqueue_repo_index_concurrent_single_running_history() -> None:
    """并发两次 enqueue 只产生一条 RUNNING IndexHistory。"""
    import asyncio

    from repositories.index_enqueue import enqueue_repo_index

    repo = await Repository.objects.acreate(
        name="conc-idx",
        git_url="https://github.com/t/conc.git",
        git_platform="github",
        index_status=IndexStatus.NOT_INDEXED,
    )

    async def _fake_defer(task, payload, **kwargs):
        await asyncio.sleep(0.05)  # 拉长 defer 窗口，放大竞态
        return f"job-{payload.get('history_id')}"

    with (
        patch("durable.service.DurableTaskService.defer", side_effect=_fake_defer),
        patch("durable.concurrency.aindex_lock", AsyncMock(return_value="index-slot-0")),
    ):
        results = await asyncio.gather(
            enqueue_repo_index(str(repo.id), trigger="create"),
            enqueue_repo_index(str(repo.id), trigger="create"),
        )

    assert sum(1 for r in results if r is not None) == 1
    running = await IndexHistory.objects.filter(
        repository=repo, status=IndexHistoryStatus.RUNNING
    ).acount()
    assert running == 1
    await repo.arefresh_from_db()
    assert repo.index_status == IndexStatus.INDEXING


async def test_enqueue_repo_index_idempotent_key(user: User) -> None:
    """同仓二次 enqueue 使用相同 index:{id} 幂等键。"""
    from repositories.index_enqueue import enqueue_repo_index

    repo = await Repository.objects.acreate(
        name="idem-idx",
        git_url="https://github.com/t/idem.git",
        git_platform="github",
        index_status=IndexStatus.NOT_INDEXED,
    )
    keys: list[str] = []

    async def _fake_defer(task, payload, **kwargs):
        keys.append(kwargs.get("idempotency_key", ""))
        # 模拟成功后仓库仍 INDEXING；第二次应因 already_indexing 跳过
        return "job-1"

    with (
        patch("durable.service.DurableTaskService.defer", side_effect=_fake_defer),
        patch("durable.concurrency.aindex_lock", AsyncMock(return_value="index-slot-0")),
    ):
        first = await enqueue_repo_index(str(repo.id), initiated_by_user_id=str(user.id))
        second = await enqueue_repo_index(str(repo.id), initiated_by_user_id=str(user.id))

    assert first == "job-1"
    assert second is None  # already INDEXING
    assert keys == [f"index:{repo.id}"]


async def test_create_enqueue_failures_do_not_block_create(user: User, space: Space) -> None:
    """enqueue 返回 None（内部失败）时建仓仍 201。"""
    with (
        patch(
            "repositories.index_enqueue.enqueue_repo_index",
            AsyncMock(return_value=None),
        ),
        patch(
            "repositories.summary_service.enqueue_repo_summary",
            AsyncMock(return_value=None),
        ),
    ):
        client = AsyncClient()
        resp = await client.post(
            "/api/repositories/",
            data={
                "name": "fail-enq",
                "git_url": "https://github.com/t/fail.git",
                "git_platform": "github",
                "access_token": "tok",
                "space_ids": [str(space.id)],
            },
            content_type="application/json",
            headers=await _auth_headers(user),
        )

    assert resp.status_code == 201
    repo = await Repository.objects.aget(name="fail-enq")
    assert repo is not None


async def test_enqueue_repo_index_rolls_back_on_defer_failure() -> None:
    """defer 失败不得留下 INDEXING 或 RUNNING history。"""
    from repositories.index_enqueue import enqueue_repo_index

    repo = await Repository.objects.acreate(
        name="rollback-idx",
        git_url="https://github.com/t/rb.git",
        git_platform="github",
        index_status=IndexStatus.NOT_INDEXED,
    )

    with (
        patch(
            "durable.service.DurableTaskService.defer",
            AsyncMock(side_effect=RuntimeError("defer-down")),
        ),
        patch("durable.concurrency.aindex_lock", AsyncMock(return_value="index-slot-0")),
    ):
        result = await enqueue_repo_index(str(repo.id), trigger="create")

    assert result is None
    await repo.arefresh_from_db()
    assert repo.index_status == IndexStatus.NOT_INDEXED
    hist = await IndexHistory.objects.filter(repository=repo).afirst()
    assert hist is not None
    assert hist.status == IndexHistoryStatus.FAILED


def test_acreate_repository_core_source_has_no_durable_graph() -> None:
    """源码守护：建仓核心不得 defer 独立图谱任务名。"""
    src = inspect.getsource(_acreate_repository_core)
    assert '"durable_graph"' not in src
    assert "'durable_graph'" not in src
