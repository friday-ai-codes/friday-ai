"""Phase: Git Diff 增量索引测试
测试覆盖：
-: git diff 获取变更文件列表 + last_indexed_commit_sha 更新
-: 按变更类型分发处理 + fallback
-: 差异摘要生成
"""
from unittest.mock import AsyncMock, patch
import pytest
from services.indexer import (
 DiffAction,
 FileDiff,
 GitDiffError,
 IndexerService,
 _build_summary_text,
 _get_head_sha,
 _parse_git_diff_output,
)
# SQLite 内存数据库 + async 需要 transaction=True 避免跨线程锁冲突
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
# ============================================================================
# DiffAction 枚举扩展
# ============================================================================
class TestDiffActionEnum:
 """DiffAction 枚举扩展验证。"""
 def test_rename_action_exists(self) -> None:
 assert DiffAction.RENAME.value == "rename"
 def test_all_actions(self) -> None:
 actions = {a.value for a in DiffAction}
 assert actions == {"add", "update", "delete", "skip", "rename"}
# ============================================================================
# FileDiff 数据类扩展
# ============================================================================
class TestFileDiffDataclass:
 """FileDiff 数据类扩展验证。"""
 def test_old_path_default_none(self) -> None:
 diff = FileDiff("new.py", DiffAction.ADD)
 assert diff.old_path is None
 def test_old_path_for_rename(self) -> None:
 diff = FileDiff("new.py", DiffAction.RENAME, old_path="old.py")
 assert diff.old_path == "old.py"
# ============================================================================
# IndexHistory.summary_text 字段
# ============================================================================
class TestIndexHistorySummaryText:
 """IndexHistory.summary_text 字段验证。"""
 def test_summary_text_field_exists(self) -> None:
 from repositories.models import IndexHistory
 field = IndexHistory._meta.get_field("summary_text")
 assert field.null is True
 assert field.blank is True
# ============================================================================
# git diff 输出解析
# ============================================================================
class TestGitDiffParsing:
 """git diff --name-status 输出解析。"""
 def test_parse_add(self) -> None:
 output = "A\tnew_file.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 1
 assert diffs[0].action == DiffAction.ADD
 assert diffs[0].file_path == "new_file.py"
 def test_parse_modify(self) -> None:
 output = "M\texisting.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 1
 assert diffs[0].action == DiffAction.UPDATE
 def test_parse_delete(self) -> None:
 output = "D\tremoved.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 1
 assert diffs[0].action == DiffAction.DELETE
 def test_parse_rename_100_percent(self) -> None:
 output = "R100\told_name.py\tnew_name.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 1
 assert diffs[0].action == DiffAction.RENAME
 assert diffs[0].file_path == "new_name.py"
 assert diffs[0].old_path == "old_name.py"
 def test_parse_rename_partial_similarity(self) -> None:
 """非完全相似度的 rename 拆为 DELETE + ADD"""
 output = "R075\told.py\tnew.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 2
 assert diffs[0].action == DiffAction.DELETE
 assert diffs[0].file_path == "old.py"
 assert diffs[1].action == DiffAction.ADD
 assert diffs[1].file_path == "new.py"
 def test_parse_empty_output(self) -> None:
 diffs = _parse_git_diff_output("")
 assert diffs ==
 def test_parse_mixed_changes(self) -> None:
 output = "A\tnew.py\nM\tchanged.py\nD\tgone.py\nR100\told.py\trenamed.py\n"
 diffs = _parse_git_diff_output(output)
 assert len(diffs) == 4
 actions = [d.action for d in diffs]
 assert DiffAction.ADD in actions
 assert DiffAction.UPDATE in actions
 assert DiffAction.DELETE in actions
 assert DiffAction.RENAME in actions
# ============================================================================
# _get_head_sha 单元测试
# ============================================================================
class TestGetHeadSha:
 """_get_head_sha 单元测试。"""
 async def test_returns_sha(self) -> None:
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"abc123def456\n", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 return_value=(b"abc123def456\n", b""),
 ),
 ):
 sha = await _get_head_sha("/fake/repo")
 assert sha == "abc123def456"
 async def test_raises_on_failure(self) -> None:
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
 mock_proc.returncode = 1
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 return_value=(b"", b"error"),
 ),
 ):
 with pytest.raises(GitDiffError):
 await _get_head_sha("/fake/repo")
# ============================================================================
# run_git_diff_index 核心逻辑
# ============================================================================
class TestGitDiffIndex:
 """IndexerService.run_git_diff_index 核心逻辑。"""
 async def test_no_changes_returns_success(self) -> None:
 """diff 为空时直接返回成功"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 ):
 indexer = IndexerService("test-repo-id")
 result = await indexer.run_git_diff_index("/fake/repo", "old_sha", "new_sha")
 assert result["status"] == "success"
 assert result["added"] == 0
# ============================================================================
# 按变更类型分发
# ============================================================================
class TestDiffDispatch:
 """按变更类型分发处理。"""
 async def test_delete_calls_qdrant_delete(self) -> None:
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"D\tremoved.py\n", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 return_value=(b"D\tremoved.py\n", b""),
 ),
 patch(
 "services.indexer.qdrant_delete_by_file_path",
 new_callable=AsyncMock,
 ) as mock_delete,
 ):
 indexer = IndexerService("test-repo-id")
 result = await indexer.run_git_diff_index("/fake/repo", "old", "new")
 mock_delete.assert_called_once_with("test-repo-id", "removed.py")
 assert result["deleted"] == 1
# ============================================================================
# Rename 处理
# ============================================================================
class TestRenameHandling:
 """Rename 处理逻辑验证。"""
 async def test_rename_100_updates_metadata(self) -> None:
 """R100 rename 只更新路径元数据，不重新索引"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(
 return_value=(b"R100\told.py\tnew.py\n", b"")
 )
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch(
 "services.indexer.asyncio.wait_for",
 return_value=(b"R100\told.py\tnew.py\n", b""),
 ),
 patch(
 "services.indexer.qdrant_update_file_path",
 new_callable=AsyncMock,
 ) as mock_update,
 ):
 indexer = IndexerService("test-repo-id")
 result = await indexer.run_git_diff_index("/fake/repo", "old", "new")
 mock_update.assert_called_once_with("test-repo-id", "old.py", "new.py")
 assert result["renamed"] == 1
# ============================================================================
# clone_and_index_repository git diff 路径
# ============================================================================
class TestCloneAndIndexGitDiffPath:
 """clone_and_index_repository git diff 路径测试。"""
 async def test_uses_git_diff_when_last_sha_exists(self, repository) -> None:
 """有 last_indexed_commit_sha 时走 git diff 路径"""
 repository.last_indexed_commit_sha = "abc123"
 await repository.asave(update_fields=["last_indexed_commit_sha"])
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="def456",
 ),
 patch(
 "services.indexer._fetch_commit",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "services.indexer.IndexerService.run_git_diff_index",
 new_callable=AsyncMock,
 return_value={
 "status": "success",
 "added": 0,
 "updated": 0,
 "deleted": 0,
 "renamed": 0,
 },
 ) as mock_diff_index,
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 mock_diff_index.assert_called_once
 async def test_updates_last_indexed_commit_sha(self, repository) -> None: """索引完成后 last_indexed_commit_sha 更新为 HEAD SHA"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="new_head_sha",
 ),
 patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
 patch(
 "services.indexer.IndexerService.run_full_index",
 new_callable=AsyncMock,
 return_value={"status": "success"},
 ),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 await repository.arefresh_from_db
 assert repository.last_indexed_commit_sha == "new_head_sha"
# ============================================================================
# 差异摘要生成
# ============================================================================
class TestDiffSummary:
 """差异摘要生成。"""
 def test_all_types(self) -> None:
 text = _build_summary_text(3, 2, 1)
 assert text == "本次增量：新增 3 文件、修改 2 文件、删除 1 文件"
 def test_add_only(self) -> None:
 text = _build_summary_text(5, 0, 0)
 assert text == "本次增量：新增 5 文件"
 def test_no_changes(self) -> None:
 text = _build_summary_text(0, 0, 0)
 assert text == "无变更"
 def test_modify_and_delete(self) -> None:
 text = _build_summary_text(0, 3, 2)
 assert text == "本次增量：修改 3 文件、删除 2 文件"
# ============================================================================
# Fallback 行为
# ============================================================================
class TestFallback:
 """Git diff 不可用时的 fallback 行为。"""
 async def test_fetch_failure_falls_back_to_hash(self, repository) -> None: """fetch 旧 commit 失败时自动 fallback 到文件哈希比较"""
 repository.last_indexed_commit_sha = "nonexistent_sha"
 await repository.asave(update_fields=["last_indexed_commit_sha"])
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="def456",
 ),
 patch(
 "services.indexer._fetch_commit",
 new_callable=AsyncMock,
 return_value=False,
 ),
 patch(
 "services.indexer.IndexerService.run_incremental_index",
 new_callable=AsyncMock,
 return_value={
 "status": "success",
 "added": 0,
 "updated": 0,
 "deleted": 0,
 "skipped": 0,
 },
 ) as mock_incr,
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 mock_incr.assert_called_once
 async def test_git_diff_error_falls_back_to_hash(self, repository) -> None: """git diff 命令失败时自动 fallback 到文件哈希比较"""
 repository.last_indexed_commit_sha = "old_sha"
 await repository.asave(update_fields=["last_indexed_commit_sha"])
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="def456",
 ),
 patch(
 "services.indexer._fetch_commit",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "services.indexer.IndexerService.run_git_diff_index",
 new_callable=AsyncMock,
 side_effect=GitDiffError("diff failed"),
 ),
 patch(
 "services.indexer.IndexerService.run_incremental_index",
 new_callable=AsyncMock,
 return_value={
 "status": "success",
 "added": 0,
 "updated": 0,
 "deleted": 0,
 "skipped": 0,
 },
 ) as mock_incr,
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 mock_incr.assert_called_once
 async def test_no_last_sha_uses_original_logic(self, repository) -> None: """无 last_indexed_commit_sha 时走原有逻辑"""
 assert repository.last_indexed_commit_sha is None
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="head123",
 ),
 patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
 patch(
 "services.indexer.IndexerService.run_full_index",
 new_callable=AsyncMock,
 return_value={"status": "success"},
 ) as mock_full,
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 mock_full.assert_called_once
# ============================================================================
# IndexHistory 字段填充
# ============================================================================
class TestIndexHistoryPopulation:
 """IndexHistory 字段在索引完成后正确填充。"""
 async def test_history_fields_populated_after_git_diff_index(self, repository) -> None: """git diff 索引后 IndexHistory 填充所有统计字段"""
 from django.utils import timezone
 from repositories.models import IndexHistory, IndexHistoryStatus, TriggerType
 repository.last_indexed_commit_sha = "old_sha_123"
 await repository.asave(update_fields=["last_indexed_commit_sha"])
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="new_sha_456",
 ),
 patch(
 "services.indexer._fetch_commit",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "services.indexer.IndexerService.run_git_diff_index",
 new_callable=AsyncMock,
 return_value={
 "status": "success",
 "added": 3,
 "updated": 2,
 "deleted": 1,
 "renamed": 0,
 },
 ),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(
 str(repository.id), history_id=str(history.id)
 )
 await history.arefresh_from_db
 assert history.status == IndexHistoryStatus.COMPLETED
 assert history.from_sha == "old_sha_123"
 assert history.to_sha == "new_sha_456"
 assert history.files_added == 3
 assert history.files_modified == 2
 assert history.files_deleted == 1
 assert history.summary_text == "本次增量：新增 3 文件、修改 2 文件、删除 1 文件"
 async def test_fallback_records_reason_in_history(self, repository) -> None: """fallback 时 IndexHistory 记录 fallback 原因"""
 from django.utils import timezone
 from repositories.models import IndexHistory, IndexHistoryStatus, TriggerType
 repository.last_indexed_commit_sha = "bad_sha"
 await repository.asave(update_fields=["last_indexed_commit_sha"])
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch(
 "services.indexer._get_head_sha",
 new_callable=AsyncMock,
 return_value="head_sha",
 ),
 patch(
 "services.indexer._fetch_commit",
 new_callable=AsyncMock,
 return_value=False,
 ),
 patch(
 "services.indexer.IndexerService.run_incremental_index",
 new_callable=AsyncMock,
 return_value={
 "status": "success",
 "added": 0,
 "updated": 0,
 "deleted": 0,
 "skipped": 0,
 },
 ),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(
 str(repository.id), history_id=str(history.id)
 )
 await history.arefresh_from_db
 assert history.status == IndexHistoryStatus.COMPLETED
 assert history.error_message is not None
 assert "[fallback]" in history.error_message
