"""分支生命周期自动化测试（work item ~ work item）。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.models import (
    BranchIndexStatus,
    IndexStatus,
    Repository,
    RepositoryBranchIndex,
)
from tasks.index_trigger_tasks import (
    _check_and_upgrade_overlay,
    _rebuild_branch_overlay,
    cleanup_branch_index,
    cleanup_stale_branch_indexes,
    clear_dedup_cache,
    parse_push_event,
    trigger_auto_index,
    trigger_branch_rebuild,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def branch_index_factory():
    """创建 RepositoryBranchIndex 的工厂。"""

    async def _make(
        repository: Repository,
        branch_name: str,
        *,
        is_base_branch: bool = False,
        status: str = BranchIndexStatus.INDEXED,
        is_stale: bool = False,
        effective_chunks_count: int = 0,
        collection_name: str | None = None,
    ) -> RepositoryBranchIndex:
        return await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name=branch_name,
            is_base_branch=is_base_branch,
            status=status,
            is_stale=is_stale,
            effective_chunks_count=effective_chunks_count,
            collection_name=collection_name,
        )

    return _make


@pytest.fixture(autouse=True)
def _clear_dedup_each():
    clear_dedup_cache()
    yield


def test_parse_push_event_branch_name() -> None:
    gh = parse_push_event(
        "github",
        {"ref": "refs/heads/feature/foo", "after": "abc123"},
    )
    assert gh["branch_name"] == "feature/foo"
    assert gh["is_delete"] is False

    gl = parse_push_event(
        "gitlab",
        {"ref": "refs/heads/main", "after": "def456"},
    )
    assert gl["branch_name"] == "main"
    assert gl["is_delete"] is False

    gt = parse_push_event(
        "gitea",
        {"ref": "refs/heads/hotfix/bar", "after": "ghi789"},
    )
    assert gt["branch_name"] == "hotfix/bar"
    assert gt["is_delete"] is False


def test_delete_detection_all_platforms() -> None:
    gh = parse_push_event(
        "github",
        {
            "ref": "refs/heads/old-branch",
            "after": "0" * 40,
            "deleted": True,
        },
    )
    assert gh["is_delete"] is True

    gl = parse_push_event(
        "gitlab",
        {"ref": "refs/heads/old-branch", "after": "0" * 40},
    )
    assert gl["is_delete"] is True

    gt = parse_push_event(
        "gitea",
        {
            "ref": "refs/heads/old-branch",
            "after": "0" * 40,
            "deleted": True,
        },
    )
    assert gt["is_delete"] is True

    normal = parse_push_event(
        "github",
        {"ref": "refs/heads/main", "after": "abc123"},
    )
    assert normal["is_delete"] is False


@pytest.mark.asyncio
async def test_feature_push_triggers_rebuild(
    repository: Repository,
    branch_index_factory,
) -> None:
    import asyncio

    repository.auto_index_enabled = True
    repository.index_status = IndexStatus.INDEXED
    repository.base_branch = "main"
    await repository.asave()

    await branch_index_factory(repository, "main", is_base_branch=True)
    await branch_index_factory(repository, "feature/x", is_base_branch=False)

    with patch(
        "tasks.index_trigger_tasks.clone_and_index_repository",
        new_callable=AsyncMock,
        return_value={"status": "success"},
    ):
        result = await trigger_branch_rebuild(repository, "feature/x", "sha123")
        assert result["status"] == "triggered"
        await asyncio.sleep(0.15)


@pytest.mark.asyncio
async def test_concurrent_rebuild_soft_lock(
    repository: Repository,
    branch_index_factory,
) -> None:
    repository.auto_index_enabled = True
    repository.index_status = IndexStatus.INDEXED
    repository.base_branch = "main"
    await repository.asave()

    await branch_index_factory(
        repository,
        "feature/x",
        status=BranchIndexStatus.INDEXING,
        is_base_branch=False,
    )

    result = await trigger_branch_rebuild(repository, "feature/x", "sha123")
    assert result["status"] == "skipped"
    assert result["reason"] == "already_indexing"


@pytest.mark.asyncio
async def test_rebuild_retry_backoff(repository: Repository, branch_index_factory) -> None:
    repository.auto_index_enabled = True
    repository.index_status = IndexStatus.INDEXED
    repository.base_branch = "main"
    await repository.asave()

    row = await branch_index_factory(
        repository,
        "feature/x",
        status=BranchIndexStatus.INDEXED,
        is_base_branch=False,
    )

    mock_clone = AsyncMock(side_effect=RuntimeError("fail"))
    with (
        patch(
            "tasks.index_trigger_tasks.clone_and_index_repository",
            mock_clone,
        ),
        patch("tasks.index_trigger_tasks.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _rebuild_branch_overlay(repository, "feature/x", "sha")

    assert mock_clone.call_count == 3
    await row.arefresh_from_db()
    assert row.status == BranchIndexStatus.FAILED


@pytest.mark.asyncio
async def test_branch_delete_cleanup(repository: Repository, branch_index_factory) -> None:
    await branch_index_factory(
        repository,
        "feature/x",
        is_base_branch=False,
        collection_name="code_index_xxx_br_feature",
    )

    with patch(
        "tasks.index_trigger_tasks.QdrantService.delete_collection_by_name",
        return_value=True,
    ) as mock_del:
        result = await cleanup_branch_index(repository, "feature/x")
        assert result["status"] == "cleaned"
        mock_del.assert_called_once_with("code_index_xxx_br_feature")

    assert (
        not await RepositoryBranchIndex.objects.filter(
            repository=repository,
            branch_name="feature/x",
        ).aexists()
    )


@pytest.mark.asyncio
async def test_scheduled_cleanup_orphans(
    repository: Repository,
    branch_index_factory,
) -> None:
    repository.auto_index_enabled = True
    repository.git_url = "https://github.com/x/y.git"
    await repository.asave()

    await branch_index_factory(repository, "main", is_base_branch=True)
    fa = await branch_index_factory(repository, "feature/a", is_base_branch=False)
    fb = await branch_index_factory(repository, "feature/b", is_base_branch=False)

    with (
        patch(
            "tasks.index_trigger_tasks._get_remote_branches",
            new_callable=AsyncMock,
            return_value={"main", "feature/a"},
        ),
        patch(
            "tasks.index_trigger_tasks.QdrantService.delete_collection_by_name",
            return_value=True,
        ),
    ):
        result = await cleanup_stale_branch_indexes()
        assert result["cleaned"] >= 1

    assert await RepositoryBranchIndex.objects.filter(pk=fa.pk).aexists()
    assert not await RepositoryBranchIndex.objects.filter(pk=fb.pk).aexists()


@pytest.mark.asyncio
async def test_cleanup_skips_on_network_error(
    repository: Repository,
    branch_index_factory,
) -> None:
    repository.auto_index_enabled = True
    repository.git_url = "https://github.com/x/y.git"
    await repository.asave()

    row = await branch_index_factory(repository, "orphan", is_base_branch=False)

    with patch(
        "tasks.index_trigger_tasks._get_remote_branches",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network"),
    ):
        result = await cleanup_stale_branch_indexes()
        assert result["cleaned"] == 0

    assert await RepositoryBranchIndex.objects.filter(pk=row.pk).aexists()


@pytest.mark.asyncio
async def test_overlay_upgrade_triggered(
    repository: Repository,
    branch_index_factory,
) -> None:
    await branch_index_factory(
        repository,
        "main",
        is_base_branch=True,
        effective_chunks_count=100,
    )
    await branch_index_factory(
        repository,
        "feature/x",
        is_base_branch=False,
        effective_chunks_count=60,
        collection_name="old_overlay",
    )

    with (
        patch(
            "tasks.index_trigger_tasks.QdrantService.check_collection_health",
            return_value={"points_count": 100},
        ),
        patch(
            "tasks.index_trigger_tasks.clone_and_index_repository",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ) as mock_clone,
        patch(
            "tasks.index_trigger_tasks.QdrantService.delete_collection_by_name",
            return_value=True,
        ) as mock_del,
    ):
        ok = await _check_and_upgrade_overlay(repository, "feature/x")
        assert ok is True
        mock_clone.assert_awaited()
        mock_del.assert_called_once_with("old_overlay")


@pytest.mark.asyncio
async def test_overlay_upgrade_not_triggered_below_threshold(
    repository: Repository,
    branch_index_factory,
) -> None:
    await branch_index_factory(
        repository,
        "main",
        is_base_branch=True,
        effective_chunks_count=100,
    )
    await branch_index_factory(
        repository,
        "feature/x",
        is_base_branch=False,
        effective_chunks_count=10,
    )

    with (
        patch(
            "tasks.index_trigger_tasks.QdrantService.check_collection_health",
            return_value={"points_count": 100},
        ),
        patch(
            "tasks.index_trigger_tasks.clone_and_index_repository",
            new_callable=AsyncMock,
        ) as mock_clone,
    ):
        ok = await _check_and_upgrade_overlay(repository, "feature/x")
        assert ok is False
        mock_clone.assert_not_called()


@pytest.mark.asyncio
@patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="headsha")
async def test_base_push_marks_overlays_stale(
    mock_head: MagicMock,
    repository: Repository,
    branch_index_factory,
) -> None:
    repository.auto_index_enabled = True
    repository.index_status = IndexStatus.INDEXED
    repository.base_branch = "main"
    await repository.asave()

    await branch_index_factory(
        repository,
        "main",
        is_base_branch=True,
        status=BranchIndexStatus.INDEXED,
    )
    o1 = await branch_index_factory(
        repository,
        "feature/a",
        is_base_branch=False,
        is_stale=False,
    )
    o2 = await branch_index_factory(
        repository,
        "feature/b",
        is_base_branch=False,
        is_stale=False,
    )

    async def _fake_clone(repository_id: str, *, history_id: str | None = None, branch=None):
        from services.indexer import IndexerService

        indexer = IndexerService(repository_id)
        await indexer._update_branch_index_record(
            repo_path="/tmp/fake",
            branch_name="main",
            is_base_branch=True,
            points_count=50,
        )
        return {"status": "success"}

    # 迁移后 trigger_auto_index 改走 durable（in-process 后端执行 durable_index →
    # run_index → services.indexer.clone_and_index_repository），patch seam 上移到
    # services.indexer 才能拦截后台续跑路径。
    with patch(
        "services.indexer.clone_and_index_repository",
        side_effect=_fake_clone,
    ):
        result = await trigger_auto_index(
            repository,
            "webhook",
            "sha123",
            dedup_branch_name="main",
        )
        assert result["status"] == "triggered"
        # 后台 task 现在跑在 services.background_runner 的独立 worker loop —
        # 改用 wait_for_pending 等所有 in-flight Future 落地。
        from services import background_runner

        await asyncio.get_event_loop().run_in_executor(
            None, background_runner.wait_for_pending, 5.0,
        )

    await o1.arefresh_from_db()
    await o2.arefresh_from_db()
    assert o1.is_stale is True
    assert o2.is_stale is True
