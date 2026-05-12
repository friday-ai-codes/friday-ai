"""IndexerService.run_git_diff_index 拿到 git diff 后立刻把 stats / changed_files / from_sha / to_sha 写入 IndexHistory。
目的：让"索引历史"列表中的 RUNNING 行能立即看到本次增量索引的文件增/改/删数量与
变更文件路径列表，而不必等到索引完成。
测试不验证 embedding / qdrant 写入，仅断言 partial-update 这一步。
"""
from __future__ import annotations
import tempfile
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from django.utils import timezone
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 Repository,
 TriggerType,
)
from services.indexer import IndexerService
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
@pytest.fixture(autouse=True)
def _stub_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
 """stub Qdrant + 图谱写入，专注 partial-update 行为。"""
 from services import indexer as ix
 monkeypatch.setattr(ix, "qdrant_create_collection", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "qdrant_delete_by_file_path", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "qdrant_upsert_vectors", AsyncMock(return_value=True))
 monkeypatch.setattr(ix, "qdrant_update_file_path", AsyncMock(return_value=True))
 async def _noop_ensure(self: object, *a: object, **kw: object) -> None:
 return None
 async def _noop_graph(self: object, *a: object, **kw: object) -> None:
 return None
 async def _noop_branch_record(self: object, *a: object, **kw: object) -> None:
 return None
 monkeypatch.setattr(ix.IndexerService, "_ensure_collection", _noop_ensure)
 monkeypatch.setattr(ix.IndexerService, "_extract_and_write_graph", _noop_graph)
 monkeypatch.setattr(
 ix.IndexerService, "_update_branch_index_record", _noop_branch_record
 )
def _mk_diff_subprocess(diff_output: bytes) -> AsyncMock:
 """构造一个返回指定 git diff --name-status 输出的 subprocess mock。"""
 proc = AsyncMock
 proc.communicate = AsyncMock(return_value=(diff_output, b""))
 proc.returncode = 0
 return proc
@pytest.fixture
async def repository -> Repository:
 return await Repository.objects.acreate(
 name="partial-update-repo",
 git_url="https://github.com/test/partial.git",
 git_platform="github",
 default_branch="main",
 )
@pytest.fixture
async def running_history(repository: Repository) -> IndexHistory:
 return await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
class TestRunGitDiffIndexPartialUpdate:
 async def test_pure_delete_partial_update_runs_before_completion(
 self,
 repository: Repository,
 running_history: IndexHistory,
 ) -> None:
 """纯删除 diff：拿到 diff 后立即把 deleted=2 + changed_files 写入 IndexHistory。"""
 with tempfile.TemporaryDirectory as tmpdir:
 indexer = IndexerService(str(repository.id))
 diff_output = b"D\told_a.py\nD\told_b.py\n"
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_mk_diff_subprocess(diff_output),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 new_callable=AsyncMock,
 return_value=(diff_output, b""),
 ),
 ):
 await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from_abc",
 to_sha="to_xyz",
 history_id=str(running_history.id),
 )
 await running_history.arefresh_from_db
 assert running_history.from_sha == "from_abc"
 assert running_history.to_sha == "to_xyz"
 assert running_history.files_added == 0
 assert running_history.files_modified == 0
 assert running_history.files_deleted == 2
 assert running_history.changed_files == {
 "added":,
 "modified":,
 "deleted": ["old_a.py", "old_b.py"],
 }
 # summary_text 应当人可读
 assert running_history.summary_text is not None
 assert "删除 2" in running_history.summary_text
 # status 仍是 RUNNING — partial-update 不应改写 status / finished_at
 assert running_history.status == IndexHistoryStatus.RUNNING
 assert running_history.finished_at is None
 async def test_mixed_diff_partial_update_counts_and_paths(
 self,
 repository: Repository,
 running_history: IndexHistory,
 ) -> None:
 """混合 diff（A/M/D）：counts + 文件路径分组都被 partial-update 写入。"""
 # 让所有 add/update 文件都"不存在"，从而跳过 parse_file → 不进入 embedding 路径
 with tempfile.TemporaryDirectory as tmpdir:
 indexer = IndexerService(str(repository.id))
 diff_output = b"A\tnew_x.py\nA\tnew_y.py\nM\tchanged.py\nD\tgone.py\n"
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_mk_diff_subprocess(diff_output),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 new_callable=AsyncMock,
 return_value=(diff_output, b""),
 ),
 patch("services.indexer.os.path.exists", return_value=False),
 ):
 await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from_abc",
 to_sha="to_xyz",
 history_id=str(running_history.id),
 )
 await running_history.arefresh_from_db
 assert running_history.files_added == 2
 assert running_history.files_modified == 1
 assert running_history.files_deleted == 1
 assert running_history.changed_files == {
 "added": ["new_x.py", "new_y.py"],
 "modified": ["changed.py"],
 "deleted": ["gone.py"],
 }
 assert running_history.from_sha == "from_abc"
 assert running_history.to_sha == "to_xyz"
 assert running_history.summary_text is not None
 assert "新增 2" in running_history.summary_text
 assert running_history.status == IndexHistoryStatus.RUNNING
 async def test_no_history_id_does_not_touch_db(
 self,
 repository: Repository,
 running_history: IndexHistory,
 ) -> None:
 """history_id 不传则不应误改其他 IndexHistory 记录。"""
 with tempfile.TemporaryDirectory as tmpdir:
 indexer = IndexerService(str(repository.id))
 diff_output = b"D\tx.py\n"
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_mk_diff_subprocess(diff_output),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 new_callable=AsyncMock,
 return_value=(diff_output, b""),
 ),
 ):
 await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from_abc",
 to_sha="to_xyz",
 )
 await running_history.arefresh_from_db
 assert running_history.files_deleted == 0
 assert running_history.changed_files in ({}, None)
 assert running_history.from_sha is None
 async def test_partial_update_visible_to_concurrent_reader(
 self,
 repository: Repository,
 running_history: IndexHistory,
 ) -> None:
 """partial-update 写入后，其他 ORM 读者立刻能看到新值（无未提交事务残留）。"""
 captured: dict[str, Any] = {}
 async def capture_after_subprocess(*args: Any, **kwargs: Any) -> Any:
 # asyncio.wait_for 被调用 = subprocess 已 communicate 完毕
 # 此时还在 indexer 内部、尚未结束；模拟"前端在索引中查询"
 return (b"D\tx.py\n", b"")
 with tempfile.TemporaryDirectory as tmpdir:
 indexer = IndexerService(str(repository.id))
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=_mk_diff_subprocess(b"D\tx.py\n"),
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 side_effect=capture_after_subprocess,
 ),
 ):
 await indexer.run_git_diff_index(
 repo_path=tmpdir,
 from_sha="from_abc",
 to_sha="to_xyz",
 history_id=str(running_history.id),
 )
 # 用全新查询验证 partial-update 落库（不依赖 fixture 实例缓存）
 fresh = await IndexHistory.objects.aget(id=running_history.id)
 assert fresh.files_deleted == 1
 assert fresh.from_sha == "from_abc"
 assert fresh.changed_files.get("deleted") == ["x.py"]
 assert captured == {} # 仅占位
