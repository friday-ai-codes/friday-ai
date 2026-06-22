"""索引失败后的续跑语义回归测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.models import FileIndex, IndexStatus, Repository
from services.indexer import clone_and_index_repository

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def _successful_clone_proc() -> AsyncMock:
    proc = AsyncMock()
    stderr = AsyncMock()
    stderr.read = AsyncMock(return_value=b"")
    proc.stderr = stderr
    proc.wait = AsyncMock(return_value=0)
    # 子进程现统一走 communicate()（git clone / git log 等），返回 (stdout, stderr) 二元组。
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.returncode = 0
    proc.kill = MagicMock()
    return proc


async def test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental() -> None:
    """失败半成品有 FileIndex checkpoint 时，应续跑 full index，而不是走 diff 增量。"""
    repo = await Repository.objects.acreate(
        name="partial-resume-repo",
        git_url="https://github.com/example/partial-resume.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.FAILED,
        index_error="[Errno 9] Bad file descriptor",
        last_indexed_commit_sha="",
    )
    await FileIndex.objects.acreate(
        repository=repo,
        file_path="src/done.py",
        file_hash="hash-done",
    )

    full_result = {
        "status": "success",
        "files_processed": 2,
        "chunks_indexed": 1,
        "added": 2,
    }

    with (
        patch("services.indexer.tempfile.mkdtemp", return_value="/tmp/fake_resume_clone"),
        patch("services.indexer.shutil.rmtree"),
        patch("services.indexer.os.path.exists", return_value=True),
        patch(
            "services.indexer.asyncio.create_subprocess_exec",
            return_value=_successful_clone_proc(),
        ),
        patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="b" * 40),
        patch(
            "services.indexer.qdrant_get_stored_file_hashes",
            new_callable=AsyncMock,
            return_value={"src/done.py": "hash-done"},
        ),
        patch(
            "services.indexer.IndexerService.run_full_index",
            new_callable=AsyncMock,
            return_value=full_result,
        ) as full_index,
        patch(
            "services.indexer.IndexerService.run_incremental_index",
            new_callable=AsyncMock,
        ) as incremental_index,
        patch(
            "services.indexer.IndexerService.run_git_diff_index",
            new_callable=AsyncMock,
        ) as git_diff_index,
    ):
        result = await clone_and_index_repository(str(repo.id))

    assert result["status"] == "success"
    full_index.assert_awaited_once()
    incremental_index.assert_not_awaited()
    git_diff_index.assert_not_awaited()
