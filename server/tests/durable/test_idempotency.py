"""重复投递 / 重复执行 / page_index 幂等守护（IDEMP-01 / SC4）。

锁定三类 Pitfall：
- duplicate_dispatch（双跑 / 重复 IndexHistory RUNNING）：同 deterministic key 二次
  ``DurableTaskService.defer`` 不产生第二个在途标识——in-process 同名覆盖单条 job；
  procrastinate 分支（postgres_queue）经 ``queueing_lock`` 在 todo 唯一、返回既有 job id。
- duplicate_execution（重复索引产物 / 重复 History）：FileIndex/GraphFileIndex 的
  unique_together 约束令同 (repo,[branch,]file_path) 重复 upsert 去重；run_index 复用入参
  ``history_id``、不在执行期新建 RUNNING 行（History 仅在入队点创建，真相源不变）。
- page_index（IDEMP-01 基线）：占位任务体重复执行恒等返回、零副作用。

默认 SQLite / in-process 路径跑；procrastinate 专项用例带 postgres_queue 标记，
默认套件经 addopts 排除（需真实 Postgres）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from django.db import IntegrityError

from durable.handlers import register_business_handlers
from durable.queues import QUEUE_INDEX
from durable.service import DurableTaskService
from services import background_runner

_INDEX_PAYLOAD = {"repository_id": "R", "history_id": None, "branch": None, "trigger": "manual"}


# ---------------------------------------------------------------------------
# duplicate_dispatch：同 key 二次 defer 不产生重复在途 job
# ---------------------------------------------------------------------------


async def test_duplicate_dispatch_inprocess_single_inflight(settings, monkeypatch) -> None:
    """in-process：同 idempotency_key 二次 defer → 同名覆盖单条 job，不产生重复在途标识。"""
    settings.DURABLE_TASK_BACKEND = "auto"
    register_business_handlers()
    # 替换重活：仅验证投递去重语义，不触发真实 clone/embedding（pytest-socket 默认禁网）。
    monkeypatch.setattr("durable.tasks_impl.run_index", AsyncMock(return_value={"status": "ok"}))

    jid1 = await DurableTaskService.defer(
        "durable_index", _INDEX_PAYLOAD, queue=QUEUE_INDEX, idempotency_key="index:R"
    )
    jid2 = await DurableTaskService.defer(
        "durable_index", _INDEX_PAYLOAD, queue=QUEUE_INDEX, idempotency_key="index:R"
    )
    background_runner.wait_for_pending(timeout=5.0)

    # deterministic key 即 in-process job_id：两次投递返回同一标识、注册表仅一条该 key 项。
    assert jid1 == jid2 == "index:R"
    from durable import backends

    assert "index:R" in backends._jobs


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
@pytest.mark.django_db(transaction=True)
async def test_duplicate_dispatch_procrastinate_queueing_lock_unique(
    procrastinate_app, durable_service
) -> None:
    """procrastinate：同 queueing_lock 二次 defer 命中 AlreadyEnqueued，返回既有 job id（todo 唯一）。"""
    key = "index:repo-dup"
    jid1 = await durable_service.defer(
        "durable_index", _INDEX_PAYLOAD, queue=QUEUE_INDEX, idempotency_key=key
    )
    jid2 = await durable_service.defer(
        "durable_index", _INDEX_PAYLOAD, queue=QUEUE_INDEX, idempotency_key=key
    )
    # 第二次未新增 todo job：queueing_lock 命中 → 返回既有 job 标识。
    assert jid1 == jid2


# ---------------------------------------------------------------------------
# duplicate_execution：重复执行不产生重复数据 / 重复 History
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_duplicate_execution_fileindex_unique_constraint() -> None:
    """重复执行经 FileIndex.uq_repo_file_path 去重：同 (repo,file_path) 二次写入抛 IntegrityError。"""
    from repositories.models import FileIndex, Repository

    repo = await Repository.objects.acreate(
        name="idemp-fileindex-repo",
        git_url="https://github.com/example/idemp.git",
        git_platform="github",
        default_branch="main",
    )
    await FileIndex.objects.acreate(repository=repo, file_path="src/a.py", file_hash="h1")

    with pytest.raises(IntegrityError):
        await FileIndex.objects.acreate(repository=repo, file_path="src/a.py", file_hash="h2")


@pytest.mark.django_db(transaction=True)
async def test_duplicate_execution_graphfileindex_unique_constraint() -> None:
    """图谱轨 checkpoint：GraphFileIndex.uq_graph_repo_branch_file 令同 (repo,branch,file) 去重。"""
    from repositories.models import GraphFileIndex, Repository

    repo = await Repository.objects.acreate(
        name="idemp-graphindex-repo",
        git_url="https://github.com/example/idemp-graph.git",
        git_platform="github",
        default_branch="main",
    )
    await GraphFileIndex.objects.acreate(
        repository=repo, file_path="src/a.py", file_hash="h1", branch_name=""
    )

    with pytest.raises(IntegrityError):
        await GraphFileIndex.objects.acreate(
            repository=repo, file_path="src/a.py", file_hash="h2", branch_name=""
        )


async def test_run_index_reuses_history_id_no_new_running_row(monkeypatch) -> None:
    """run_index 复用入参 history_id（不在执行期新建 IndexHistory）：重复执行 history_id 恒等转发。

    History 仅在入队点创建（真相源），任务体只把 history_id 透传给 indexer——重复执行不会
    各自新增第二条 RUNNING 行。
    """
    from durable.tasks_impl import run_index

    captured: list[str | None] = []

    async def _stub_clone(repository_id: str, *, history_id: str | None = None, branch=None) -> dict:
        captured.append(history_id)
        return {"status": "success"}

    monkeypatch.setattr("services.indexer.clone_and_index_repository", _stub_clone)

    await run_index(repository_id="R", history_id="H", branch=None, trigger="manual")
    await run_index(repository_id="R", history_id="H", branch=None, trigger="manual")

    # 两次执行都复用入参 history_id "H"，任务体零自建 History。
    assert captured == ["H", "H"]


# ---------------------------------------------------------------------------
# page_index：占位任务体重复执行恒等、零副作用（IDEMP-01 基线）
# ---------------------------------------------------------------------------


async def test_page_index_idempotent_no_side_effect() -> None:
    """run_page_index 连续两次返回等值 dict，无任何写库 / 外部副作用。"""
    from durable.tasks_impl import run_page_index

    first = await run_page_index(target_id="page-1")
    second = await run_page_index(target_id="page-1")

    assert first == second == {"status": "noop", "target_id": "page-1"}
