"""initial implementation plan — `services.indexer.update_graph_progress` 实装 + Repository 入口/出口 reset/terminal 集成测试。

测试覆盖（work item-02）：

1. 字段写入正确性（4 入参 → 4 字段）：
   - test_update_graph_progress_writes_stage：调用后 graph_stage 字段被写
   - test_update_graph_progress_writes_current_file：current_graph_file 被写
   - test_update_graph_progress_writes_counters：processed / total 被写
   - test_update_graph_progress_writes_all_four_fields_each_call：CONTEXT
     决议口径锁定——helper 一律全写 4 字段（per-call strong consistency，
     避免"上次的 stage 残留"bug；与 update_index_stage 仅写 index_stage 不同）

2. 节流验证（ROADMAP success criterion 关键）：
   - test_update_graph_progress_called_40_times_for_1000_files：callsite 循环
     `if i % 25 == 0: await update_graph_progress(...)` 调 1000 次 → mock
     aupdate.await_count == 40（精确 1000 // 25）
   - test_update_graph_progress_helper_does_not_self_throttle：连续直调 helper
     100 次 → aupdate 调用 100 次（helper 不二次节流，节流责任在 callsite）

3. 容错（与 update_index_stage 同模板）：
   - test_update_graph_progress_swallows_db_error：mock aupdate raise →
     helper 不抛，仅 structlog warning 包含 update_graph_progress_failed

4. build_graph_for_repository 入口/成功出口 reset+terminal（集成）：
   - test_build_graph_resets_repository_fields_on_entry：入口把 Repository
     graph_build_status 从 completed 重置为 running + 计数归零
   - test_build_graph_marks_completed_terminal：成功后 graph_build_status =
     completed + counts + graph_last_built_at 非 None

5. build_graph_for_repository 异常出口 terminal：
   - test_build_graph_marks_failed_terminal：异常后 graph_build_status =
     failed + graph_last_built_at 非 None；current_graph_file 保留最后写入值
     不清空（CONTEXT 失败路径决议）
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from repositories.models import Repository, RepositoryGraphStatus


# initial implementation-01 起 build_graph_for_repository 会 git clone 仓库到临时目录。
# 本模块全部 mock 了 `_extract_and_write_graph`，clone 步骤必须 stub 以避免
# 走真实 git clone 拉 fake URL 超时。
@pytest.fixture(autouse=True)
def _stub_prepare_repo_workdir() -> Any:
    @contextlib.asynccontextmanager
    async def _fake_workdir(
        _repository_id: str, **_kwargs: Any
    ) -> AsyncIterator[str]:
        yield "/tmp/fake-graph-build-workdir"

    with patch(
        "services.graph_builder.prepare_repo_workdir_async",
        new=_fake_workdir,
    ):
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_progress_repo(db) -> Repository:
    """新建一个空 Repository fixture（默认 graph_build_status='idle'）。"""
    return Repository.objects.create(
        name="graph-progress-helper-repo",
        git_url="https://example.com/graph-progress-helper.git",
        default_branch="main",
    )


# ---------------------------------------------------------------------------
# 1. 字段写入正确性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_writes_stage(
    graph_progress_repo: Repository,
) -> None:
    """传 stage='building_graph' 后 Repository.graph_stage 字段被写。"""
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)
    await update_graph_progress(repo_id, stage="building_graph")

    refreshed = await Repository.objects.aget(id=repo_id)
    assert refreshed.graph_stage == "building_graph"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_writes_current_file(
    graph_progress_repo: Repository,
) -> None:
    """传 current_file='src/x.py' 后 current_graph_file 字段被写。"""
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)
    await update_graph_progress(repo_id, current_file="src/x.py")

    refreshed = await Repository.objects.aget(id=repo_id)
    assert refreshed.current_graph_file == "src/x.py"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_writes_counters(
    graph_progress_repo: Repository,
) -> None:
    """传 processed=42 / total=100 后两个 IntegerField 被写。"""
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)
    await update_graph_progress(repo_id, processed=42, total=100)

    refreshed = await Repository.objects.aget(id=repo_id)
    assert refreshed.graph_files_processed == 42
    assert refreshed.graph_files_total == 100


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_writes_all_four_fields_each_call(
    graph_progress_repo: Repository,
) -> None:
    """CONTEXT 决议口径：helper 每次调用一律全写 4 字段（per-call strong consistency）。

    保 update_kwargs 包含 graph_stage / current_graph_file / graph_files_processed /
    graph_files_total 4 个 key（与 update_index_stage 仅写 index_stage 不同——
    本 helper 是 5 字段聚合更新，per-call 全写避免"上次的 stage 残留"bug）。
    """
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)

    mock_aupdate = AsyncMock(return_value=1)
    mock_filter_result = MagicMock()
    mock_filter_result.aupdate = mock_aupdate

    with patch.object(
        Repository.objects,
        "filter",
        return_value=mock_filter_result,
    ):
        await update_graph_progress(
            repo_id,
            stage="building_graph",
            current_file="src/x.py",
            processed=10,
            total=50,
        )

    assert mock_aupdate.await_count == 1
    kwargs = mock_aupdate.await_args.kwargs
    # 一律全写 4 字段：4 个 key 都必须出现在 aupdate kwargs 中
    assert set(kwargs.keys()) == {
        "graph_stage",
        "current_graph_file",
        "graph_files_processed",
        "graph_files_total",
    }
    assert kwargs["graph_stage"] == "building_graph"
    assert kwargs["current_graph_file"] == "src/x.py"
    assert kwargs["graph_files_processed"] == 10
    assert kwargs["graph_files_total"] == 50


# ---------------------------------------------------------------------------
# 2. 节流验证（ROADMAP success criterion）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_called_40_times_for_1000_files(
    graph_progress_repo: Repository,
) -> None:
    """模拟 callsite 节流：1000 文件 + GRAPH_YIELD_EVERY=25 → DB 写入 40 次。

    1000 // 25 == 40（i=0,25,50,...,975 共 40 个命中点）；helper 函数体每次
    调用即写库，节流责任在 callsite——`_extract_and_write_graph` 内沿用
    `if index % GRAPH_YIELD_EVERY == 0` 判断。
    """
    from services.indexer import GRAPH_YIELD_EVERY, update_graph_progress

    assert GRAPH_YIELD_EVERY == 25, "节流常量必须固定为 25（CONTEXT 决议）"

    repo_id = str(graph_progress_repo.id)
    mock_aupdate = AsyncMock(return_value=1)
    mock_filter_result = MagicMock()
    mock_filter_result.aupdate = mock_aupdate

    with patch.object(
        Repository.objects,
        "filter",
        return_value=mock_filter_result,
    ):
        for i in range(1000):
            if i % GRAPH_YIELD_EVERY == 0:
                await update_graph_progress(repo_id, processed=i, total=1000)

    assert mock_aupdate.await_count == 40, (
        f"期望 1000//25 == 40 次 DB 写，实际 {mock_aupdate.await_count}"
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_helper_does_not_self_throttle(
    graph_progress_repo: Repository,
) -> None:
    """直接连续调 helper 100 次 → DB 写入 100 次（helper 函数体内不二次节流）。"""
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)
    mock_aupdate = AsyncMock(return_value=1)
    mock_filter_result = MagicMock()
    mock_filter_result.aupdate = mock_aupdate

    with patch.object(
        Repository.objects,
        "filter",
        return_value=mock_filter_result,
    ):
        for _ in range(100):
            await update_graph_progress(repo_id, stage="x")

    assert mock_aupdate.await_count == 100


# ---------------------------------------------------------------------------
# 3. 容错（DB 错误不抛）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_update_graph_progress_swallows_db_error(
    graph_progress_repo: Repository,
) -> None:
    """mock aupdate raise → helper 不抛，仅 structlog warning 含事件名。"""
    from services.indexer import update_graph_progress

    repo_id = str(graph_progress_repo.id)
    mock_aupdate = AsyncMock(side_effect=Exception("conn lost"))
    mock_filter_result = MagicMock()
    mock_filter_result.aupdate = mock_aupdate

    with structlog.testing.capture_logs() as captured:
        with patch.object(
            Repository.objects,
            "filter",
            return_value=mock_filter_result,
        ):
            # 关键断言：调用本身不应抛异常
            await update_graph_progress(repo_id, stage="x")

    warning_events = [
        e
        for e in captured
        if e.get("event") == "update_graph_progress_failed"
        and e.get("log_level") == "warning"
    ]
    assert len(warning_events) == 1, (
        f"期望 1 条 update_graph_progress_failed warning，实际 captured={captured}"
    )


# ---------------------------------------------------------------------------
# 4. build_graph_for_repository 入口/成功出口 reset+terminal
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_extract_stats() -> dict[str, Any]:
    return {
        "files_processed": 0,
        "files_failed": 0,
        "total_symbols": 3,
        "total_imports": 2,
        "total_calls": 1,
        "total_endpoints": 0,
    }


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_build_graph_resets_repository_fields_on_entry(
    graph_progress_repo: Repository,
    fake_extract_stats: dict[str, Any],
) -> None:
    """入口必须把 Repository graph_build_status 从 completed 重置为 running + 计数归零。

    设计：build_graph_for_repository 入口的 `_reset_repository_graph_progress`
    需要把 graph_build_status / graph_stage / current_graph_file /
    graph_files_processed / graph_files_total 5 字段归位。
    """
    from services.graph_builder import build_graph_for_repository
    from services.indexer import IndexerService

    # 预设旧的"已完成"态——验证入口 reset 能覆盖
    old_built_at = timezone.now()
    await Repository.objects.filter(id=graph_progress_repo.id).aupdate(
        graph_build_status=RepositoryGraphStatus.COMPLETED,
        graph_stage="完成",
        current_graph_file="src/old_file.py",
        graph_files_processed=100,
        graph_files_total=100,
        graph_last_built_at=old_built_at,
    )

    repo_id = str(graph_progress_repo.id)

    # 捕获 reset 时刻的快照：在 _extract_and_write_graph 内观察 Repository 状态
    captured_state: dict[str, Any] = {}

    async def _extract_capturing_state(
        self: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        repo = await Repository.objects.aget(id=repo_id)
        captured_state["status"] = repo.graph_build_status
        captured_state["stage"] = repo.graph_stage
        captured_state["files_processed"] = repo.graph_files_processed
        captured_state["files_total"] = repo.graph_files_total
        captured_state["current_file"] = repo.current_graph_file
        return fake_extract_stats

    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new=_extract_capturing_state,
    ):
        await build_graph_for_repository(repo_id, trigger="manual")

    assert captured_state["status"] == RepositoryGraphStatus.RUNNING, (
        f"入口 reset 后期望 graph_build_status=running，实际 {captured_state}"
    )
    assert captured_state["files_processed"] == 0
    assert captured_state["files_total"] == 0
    assert captured_state["current_file"] == ""
    assert captured_state["stage"], "入口 reset 后 graph_stage 不应为空（应含'前置清理'类文案）"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_build_graph_marks_completed_terminal(
    graph_progress_repo: Repository,
    fake_extract_stats: dict[str, Any],
) -> None:
    """成功路径终态：graph_build_status=completed + graph_last_built_at 非 None。"""
    from services.graph_builder import build_graph_for_repository
    from services.indexer import IndexerService

    repo_id = str(graph_progress_repo.id)
    start_ts = timezone.now()

    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new_callable=AsyncMock,
        return_value=fake_extract_stats,
    ):
        await build_graph_for_repository(repo_id, trigger="manual")

    refreshed = await Repository.objects.aget(id=repo_id)
    assert refreshed.graph_build_status == RepositoryGraphStatus.COMPLETED
    assert refreshed.graph_stage == "完成"
    assert refreshed.current_graph_file == ""
    assert refreshed.graph_last_built_at is not None
    assert refreshed.graph_last_built_at >= start_ts


# ---------------------------------------------------------------------------
# 5. build_graph_for_repository 异常出口 terminal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_build_graph_marks_failed_terminal(
    graph_progress_repo: Repository,
) -> None:
    """异常路径终态：graph_build_status=failed + graph_last_built_at 非 None。

    CONTEXT 决议（失败路径）：current_graph_file 不清空，保留最后写入值以便
    排查"卡在哪个文件"。本测试通过预先写入 current_graph_file 模拟构建过程中
    helper 已写入的状态，然后异常时验证字段保留。
    """
    from services.graph_builder import build_graph_for_repository
    from services.indexer import IndexerService

    repo_id = str(graph_progress_repo.id)
    start_ts = timezone.now()

    # 模拟构建中 helper 已写过 current_graph_file，然后下一个文件抛异常
    async def _extract_writing_then_raising(
        self: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        await Repository.objects.filter(id=repo_id).aupdate(
            current_graph_file="src/last_seen.py",
            graph_files_processed=42,
        )
        raise RuntimeError("extract boom")

    with patch.object(
        IndexerService,
        "_extract_and_write_graph",
        new=_extract_writing_then_raising,
    ):
        with pytest.raises(RuntimeError):
            await build_graph_for_repository(repo_id, trigger="manual")

    refreshed = await Repository.objects.aget(id=repo_id)
    assert refreshed.graph_build_status == RepositoryGraphStatus.FAILED
    assert refreshed.graph_last_built_at is not None
    assert refreshed.graph_last_built_at >= start_ts
    # CONTEXT 失败路径决议：current_graph_file 保留最后写入值，便于排查
    assert refreshed.current_graph_file == "src/last_seen.py", (
        "失败路径必须保留最后写入的 current_graph_file（CONTEXT Grey Area 1 决议）"
    )
