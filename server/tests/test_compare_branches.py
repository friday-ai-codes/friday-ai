"""compare_branches 双平台单元测试 + diff 解析测试。
覆盖:
- CompareFileEntry / BranchCompareResult 数据模型
- _parse_diff_stats 函数的各种 diff 文本场景
- GitHub compare_branches: 成功/失败/截断/冲突检测
- GitLab compare_branches: 成功/失败/diff 解析/behind_by 计算
"""
from typing import Any
from unittest.mock import MagicMock, patch
import pytest
from services.git_platform.models import BranchCompareResult, CompareFileEntry
# ── 数据模型测试 ──────────────────────────────────────────────
class TestCompareFileEntry:
 def test_fields(self) -> None:
 entry = CompareFileEntry(path="src/main.py", change_type="modified", additions=10, deletions=3)
 assert entry.path == "src/main.py"
 assert entry.change_type == "modified"
 assert entry.additions == 10
 assert entry.deletions == 3
 assert entry.old_path == ""
 def test_old_path_for_rename(self) -> None:
 entry = CompareFileEntry(path="new.py", change_type="renamed", old_path="old.py")
 assert entry.old_path == "old.py"
class TestBranchCompareResult:
 def test_default_fields(self) -> None:
 result = BranchCompareResult(success=True)
 assert result.success is True
 assert result.ahead_by == 0
 assert result.behind_by == 0
 assert result.files ==
 assert result.total_additions == 0
 assert result.total_deletions == 0
 assert result.truncated is False
 assert result.has_potential_conflicts is False
 assert result.conflicting_files ==
 assert result.error == ""
 def test_failure_defaults(self) -> None:
 result = BranchCompareResult(success=False, error="not found")
 assert result.success is False
 assert result.error == "not found"
 assert result.files ==
 assert result.has_potential_conflicts is False
# ── diff 解析测试 ──────────────────────────────────────────────
class TestDiffParsing:
 """测试 GitLab 客户端的 _parse_diff_stats 函数。"""
 def test_simple_diff(self) -> None:
 from services.git_platform.gitlab_client import _parse_diff_stats
 diff_text = "+line1\n-line2\n+line3\n context"
 additions, deletions = _parse_diff_stats(diff_text)
 assert additions == 2
 assert deletions == 1
 def test_ignores_file_headers(self) -> None:
 from services.git_platform.gitlab_client import _parse_diff_stats
 diff_text = "---a/file.py\n+++b/file.py\n+real addition"
 additions, deletions = _parse_diff_stats(diff_text)
 assert additions == 1
 assert deletions == 0
 def test_empty_diff(self) -> None:
 from services.git_platform.gitlab_client import _parse_diff_stats
 additions, deletions = _parse_diff_stats("")
 assert additions == 0
 assert deletions == 0
 def test_context_only_diff(self) -> None:
 from services.git_platform.gitlab_client import _parse_diff_stats
 diff_text = " context line 1\n context line 2"
 additions, deletions = _parse_diff_stats(diff_text)
 assert additions == 0
 assert deletions == 0
 def test_mixed_diff_with_headers(self) -> None:
 from services.git_platform.gitlab_client import _parse_diff_stats
 diff_text = "--- a/old.py\n+++ b/new.py\n-old line\n+new line\n context\n+added"
 additions, deletions = _parse_diff_stats(diff_text)
 assert additions == 2
 assert deletions == 1
# ── GitHub compare_branches 测试 ──────────────────────────────
def _make_github_file_mock(
 filename: str = "src/main.py",
 status: str = "modified",
 additions: int = 5,
 deletions: int = 2,
 previous_filename: str | None = None,
) -> MagicMock:
 f = MagicMock
 f.filename = filename
 f.status = status
 f.additions = additions
 f.deletions = deletions
 f.previous_filename = previous_filename
 return f
class TestGitHubCompare:
 """mock PyGithub 的 repo.compare 测试 GitHub compare_branches。"""
 def _make_client(self) -> Any:
 from services.git_platform.github_client import GitHubClient
 client = GitHubClient(token="test-token", owner="owner", repo="repo")
 return client
 @pytest.mark.asyncio
 async def test_success(self) -> None:
 client = self._make_client
 file_mock = _make_github_file_mock
 comparison = MagicMock
 comparison.ahead_by = 3
 comparison.behind_by = 0
 comparison.files = [file_mock]
 repo_mock = MagicMock
 repo_mock.compare.return_value = comparison
 with patch.object(client, "_get_repo", return_value=repo_mock):
 result = await client.compare_branches("feature", "main")
 assert result.success is True
 assert result.ahead_by == 3
 assert result.behind_by == 0
 assert len(result.files) == 1
 assert result.files[0].path == "src/main.py"
 assert result.files[0].change_type == "modified"
 assert result.total_additions == 5
 assert result.total_deletions == 2
 assert result.has_potential_conflicts is False
 @pytest.mark.asyncio
 async def test_conflict_detection_when_behind(self) -> None:
 """behind_by > 0 时执行反向 compare 并检测文件路径交集。"""
 client = self._make_client
 # 正向 compare: feature vs main
 forward_file = _make_github_file_mock(filename="shared.py")
 forward_comparison = MagicMock
 forward_comparison.ahead_by = 2
 forward_comparison.behind_by = 1
 forward_comparison.files = [forward_file]
 # 反向 compare: main vs feature
 reverse_file = _make_github_file_mock(filename="shared.py")
 reverse_comparison = MagicMock
 reverse_comparison.files = [reverse_file]
 repo_mock = MagicMock
 repo_mock.compare.side_effect = [forward_comparison, reverse_comparison]
 with patch.object(client, "_get_repo", return_value=repo_mock):
 result = await client.compare_branches("feature", "main")
 assert result.has_potential_conflicts is True
 assert "shared.py" in result.conflicting_files
 # 验证调用了两次 compare（正向 + 反向）
 assert repo_mock.compare.call_count == 2
 @pytest.mark.asyncio
 async def test_no_conflict_when_behind_zero(self) -> None:
 """behind_by == 0 时不执行反向 compare。"""
 client = self._make_client
 comparison = MagicMock
 comparison.ahead_by = 1
 comparison.behind_by = 0
 comparison.files = [_make_github_file_mock]
 repo_mock = MagicMock
 repo_mock.compare.return_value = comparison
 with patch.object(client, "_get_repo", return_value=repo_mock):
 result = await client.compare_branches("feature", "main")
 assert result.has_potential_conflicts is False
 assert repo_mock.compare.call_count == 1
 @pytest.mark.asyncio
 async def test_truncation(self) -> None:
 """超过 max_files 时 truncated=True 且只返回 max_files 个文件。"""
 client = self._make_client
 files = [_make_github_file_mock(filename=f"file{i}.py") for i in range(5)]
 comparison = MagicMock
 comparison.ahead_by = 1
 comparison.behind_by = 0
 comparison.files = files
 repo_mock = MagicMock
 repo_mock.compare.return_value = comparison
 with patch.object(client, "_get_repo", return_value=repo_mock):
 result = await client.compare_branches("feature", "main", max_files=3)
 assert result.truncated is True
 assert len(result.files) == 3
 @pytest.mark.asyncio
 async def test_exception_handling(self) -> None:
 """异常时返回 BranchCompareResult(success=False, error=...)。"""
 client = self._make_client
 repo_mock = MagicMock
 repo_mock.compare.side_effect = Exception("API error")
 with patch.object(client, "_get_repo", return_value=repo_mock):
 result = await client.compare_branches("feature", "main")
 assert result.success is False
 assert "API error" in result.error
# ── GitLab compare_branches 测试 ──────────────────────────────
class TestGitLabCompare:
 """mock python-gitlab 的 project.repository_compare 测试 GitLab compare_branches。"""
 def _make_client(self) -> Any:
 from services.git_platform.gitlab_client import GitLabClient
 client = GitLabClient(base_url="https://gitlab.com", token="test-token", project_path="ns/repo")
 return client
 @pytest.mark.asyncio
 async def test_success_with_diff_parsing(self) -> None:
 """成功时从 diff 文本解析 additions/deletions。"""
 client = self._make_client
 # 正向 compare 结果
 forward_result = {
 "commits": [{"id": "a"}, {"id": "b"}],
 "diffs": [
 {
 "old_path": "src/main.py",
 "new_path": "src/main.py",
 "diff": "+added\n-removed\n context",
 "new_file": False,
 "deleted_file": False,
 "renamed_file": False,
 }
 ],
 }
 # 反向 compare 结果（behind_by = 0）
 reverse_result = {
 "commits":,
 "diffs":,
 }
 project_mock = MagicMock
 project_mock.repository_compare.side_effect = [forward_result, reverse_result]
 with patch.object(client, "_get_project", return_value=project_mock):
 result = await client.compare_branches("feature", "main")
 assert result.success is True
 assert result.ahead_by == 2
 assert result.behind_by == 0
 assert len(result.files) == 1
 assert result.files[0].path == "src/main.py"
 assert result.files[0].additions == 1
 assert result.files[0].deletions == 1
 assert result.total_additions == 1
 assert result.total_deletions == 1
 assert result.has_potential_conflicts is False
 @pytest.mark.asyncio
 async def test_behind_by_from_reverse_compare(self) -> None:
 """反向 compare 获取 behind_by（commits 列表长度）。"""
 client = self._make_client
 forward_result = {
 "commits": [{"id": "a"}],
 "diffs": [
 {
 "old_path": "shared.py",
 "new_path": "shared.py",
 "diff": "+line",
 "new_file": False,
 "deleted_file": False,
 "renamed_file": False,
 }
 ],
 }
 reverse_result = {
 "commits": [{"id": "x"}, {"id": "y"}],
 "diffs": [
 {
 "old_path": "shared.py",
 "new_path": "shared.py",
 "diff": "-line",
 "new_file": False,
 "deleted_file": False,
 "renamed_file": False,
 }
 ],
 }
 project_mock = MagicMock
 project_mock.repository_compare.side_effect = [forward_result, reverse_result]
 with patch.object(client, "_get_project", return_value=project_mock):
 result = await client.compare_branches("feature", "main")
 assert result.behind_by == 2
 assert result.has_potential_conflicts is True
 assert "shared.py" in result.conflicting_files
 @pytest.mark.asyncio
 async def test_exception_handling(self) -> None:
 """异常时返回 BranchCompareResult(success=False, error=...)。"""
 client = self._make_client
 project_mock = MagicMock
 project_mock.repository_compare.side_effect = Exception("GitLab API error")
 with patch.object(client, "_get_project", return_value=project_mock):
 result = await client.compare_branches("feature", "main")
 assert result.success is False
 assert "GitLab API error" in result.error
 @pytest.mark.asyncio
 async def test_file_type_detection(self) -> None:
 """测试不同文件变更类型的检测。"""
 client = self._make_client
 forward_result = {
 "commits": [{"id": "a"}],
 "diffs": [
 {
 "old_path": "",
 "new_path": "new_file.py",
 "diff": "+content",
 "new_file": True,
 "deleted_file": False,
 "renamed_file": False,
 },
 {
 "old_path": "deleted.py",
 "new_path": "deleted.py",
 "diff": "-content",
 "new_file": False,
 "deleted_file": True,
 "renamed_file": False,
 },
 {
 "old_path": "old_name.py",
 "new_path": "new_name.py",
 "diff": "",
 "new_file": False,
 "deleted_file": False,
 "renamed_file": True,
 },
 ],
 }
 reverse_result = {"commits":, "diffs": }
 project_mock = MagicMock
 project_mock.repository_compare.side_effect = [forward_result, reverse_result]
 with patch.object(client, "_get_project", return_value=project_mock):
 result = await client.compare_branches("feature", "main")
 assert result.files[0].change_type == "added"
 assert result.files[1].change_type == "deleted"
 assert result.files[2].change_type == "renamed"
 assert result.files[2].old_path == "old_name.py"
