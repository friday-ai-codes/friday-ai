"""更新索引时进度残留 bug 回归测试。

场景：
- 上一轮索引成功，DB 里 4 个进度计数器是 N/N（满）。
- 用户点"更新索引"，后端切到 INDEXING 状态。
- 此时 IndexStatusView 不应再读到上一轮的 N/N → 误显示 100% / "完成"。
- 期望：触发索引时清零 4 个进度字段；status view 在 0/0 状态下应给出 0%
  与 "解析文件中..." 阶段文案。
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from repositories.models import IndexHistory, IndexStatus, Repository

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture
def stale_indexed_repo(db) -> Repository:
    """模拟"上一轮索引已完成"的仓库：4 个进度字段都是 100/100。"""
    return Repository.objects.create(
        name="stale-progress-repo",
        git_url="https://github.com/example/stale.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        index_total_chunks=100,
        index_processed_chunks=100,
        index_write_total=100,
        index_write_processed=100,
    )


# ---------------------------------------------------------------------------
# Test A：触发更新索引后，DB 中 4 个进度字段必须被重置为 0
# ---------------------------------------------------------------------------


async def test_trigger_index_resets_progress_counters(stale_indexed_repo: Repository) -> None:
    """点"更新索引"后，DB 里上一轮的进度残留（100/100）必须被清零。"""
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from repositories.index_views import IndexTriggerView

    async def fake_index(repo_id: str, *, history_id: str | None = None, branch: str | None = None) -> dict:
        return {"status": "success"}

    # 迁移后入队改走 durable（in-process 后端执行 durable_index → run_index →
    # services.indexer.clone_and_index_repository），patch seam 随之从
    # repositories.index_views 上移到 services.indexer。
    with (
        patch("services.indexer.clone_and_index_repository", side_effect=fake_index),
        patch(
            "repositories.index_views._acquire_index_lock_async",
            return_value=stale_indexed_repo,
        ),
    ):
        factory = APIRequestFactory()
        wsgi_request = factory.post(
            f"/api/repositories/{stale_indexed_repo.id}/index/", format="json",
        )
        wsgi_request.user = MagicMock()
        wsgi_request.auth = None
        request = Request(wsgi_request, parsers=[JSONParser()])  # type: ignore[call-arg]

        response = await IndexTriggerView().post(request, stale_indexed_repo.id)
        assert response.status_code == 202

    await stale_indexed_repo.arefresh_from_db()
    assert stale_indexed_repo.index_total_chunks == 0
    assert stale_indexed_repo.index_processed_chunks == 0
    assert stale_indexed_repo.index_write_total == 0
    assert stale_indexed_repo.index_write_processed == 0


# ---------------------------------------------------------------------------
# Test B：INDEXING 状态 + 进度字段为 0 时，view 不应返回 100% / "完成"
# ---------------------------------------------------------------------------


async def test_status_view_during_indexing_with_reset_counters_shows_initial_stage(
    stale_indexed_repo: Repository,
) -> None:
    """切到 INDEXING 且进度字段为 0 时，view 应显示 0% 与"解析文件中..."。"""
    from rest_framework.test import APIRequestFactory

    from repositories.index_views import IndexStatusView

    stale_indexed_repo.index_status = IndexStatus.INDEXING
    stale_indexed_repo.index_total_chunks = 0
    stale_indexed_repo.index_processed_chunks = 0
    stale_indexed_repo.index_write_total = 0
    stale_indexed_repo.index_write_processed = 0
    await stale_indexed_repo.asave()

    factory = APIRequestFactory()
    request = factory.get(f"/api/repositories/{stale_indexed_repo.id}/index/status/")
    request.user = MagicMock()

    response = await IndexStatusView().get(request, stale_indexed_repo.id)
    assert response.status_code == 200
    data = response.data

    assert data["index_status"] == IndexStatus.INDEXING
    assert data["overall_progress"] == 0
    assert data["overall_stage"] == "解析文件中..."


async def test_chunk_progress_takes_precedence_over_completed_file_counter(
    stale_indexed_repo: Repository,
) -> None:
    """文件 parse 计数到 100% 时，不能覆盖真实 chunk embedding/upsert 进度。"""
    from repositories.index_views import _compute_index_progress
    from services.indexer import IndexStage

    stale_indexed_repo.index_status = IndexStatus.INDEXING
    stale_indexed_repo.index_stage = IndexStage.INDEXING_FILES
    stale_indexed_repo.index_total_chunks = 100
    stale_indexed_repo.index_processed_chunks = 50
    stale_indexed_repo.index_write_total = 100
    stale_indexed_repo.index_write_processed = 50
    stale_indexed_repo.indexed_files_total = 10
    stale_indexed_repo.indexed_files_processed = 10

    progress = _compute_index_progress(stale_indexed_repo)

    assert progress["indexed_files_processed"] == 10
    assert progress["indexed_files_total"] == 10
    # PROG-01 单调阶段进度：chunk 阶段 embed 50/100 + write 50/100 → combined 0.5，
    # 映射到 [20,100] → 20 + 0.5*80 = 60（解析完成不掩盖 chunk 进度）。
    assert progress["overall_progress"] == 60


# ---------------------------------------------------------------------------
# 清理 IndexHistory（避免 fixture 残留影响其他测试）
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_history(db) -> Generator[None, None, None]:
    yield
    IndexHistory.objects.all().delete()
