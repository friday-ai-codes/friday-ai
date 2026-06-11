"""get_branch_diff 双平台单元测试（mock SDK，零网络）。

覆盖:
- GitLab get_branch_diff: 正常路径 / max_files 截断 / max_diff_lines 截断 / SDK 异常
- GitHub get_branch_diff: 正常路径 / patch 缺失降级（A1）/ 截断 / SDK 异常
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException
from gitlab.exceptions import GitlabError

# ── GitLab get_branch_diff 测试 ──────────────────────────────


def _make_gitlab_diff_entry(
    old_path: str = "src/main.py",
    new_path: str = "src/main.py",
    diff: str = "+added\n-removed\n context",
    new_file: bool = False,
    deleted_file: bool = False,
    renamed_file: bool = False,
) -> dict[str, Any]:
    return {
        "old_path": old_path,
        "new_path": new_path,
        "diff": diff,
        "new_file": new_file,
        "deleted_file": deleted_file,
        "renamed_file": renamed_file,
    }


class TestGitlabBranchDiff:
    """mock python-gitlab 的 project.repository_compare() 测试 GitLab get_branch_diff。"""

    def _make_client(self) -> Any:
        from services.git_platform.gitlab_client import GitLabClient

        return GitLabClient(
            base_url="https://gitlab.com", token="test-token", project_path="ns/repo"
        )

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """正常路径: 2 个 diffs 项 → success=True、files 长度 2、diff 文本一致、truncated=False。"""
        client = self._make_client()

        diff_a = "+line a1\n-line a2\n context"
        diff_b = "+new content"
        compare_result = {
            "diffs": [
                _make_gitlab_diff_entry(old_path="src/a.py", new_path="src/a.py", diff=diff_a),
                _make_gitlab_diff_entry(
                    old_path="", new_path="src/b.py", diff=diff_b, new_file=True
                ),
            ],
        }

        project_mock = MagicMock()
        project_mock.repository_compare.return_value = compare_result

        with patch.object(client, "_get_project", return_value=project_mock):
            result = await client.get_branch_diff("feature", "main")

        assert result.success is True
        assert result.truncated is False
        assert len(result.files) == 2
        assert result.files[0].old_path == "src/a.py"
        assert result.files[0].new_path == "src/a.py"
        assert result.files[0].diff == diff_a
        assert result.files[0].new_file is False
        assert result.files[1].new_path == "src/b.py"
        assert result.files[1].diff == diff_b
        assert result.files[1].new_file is True

    @pytest.mark.asyncio
    async def test_max_files_truncation(self) -> None:
        """max_files 截断: 3 个 diffs + max_files=2 → files 长度 2、truncated=True。"""
        client = self._make_client()

        compare_result = {
            "diffs": [_make_gitlab_diff_entry(new_path=f"src/file{i}.py") for i in range(3)],
        }

        project_mock = MagicMock()
        project_mock.repository_compare.return_value = compare_result

        with patch.object(client, "_get_project", return_value=project_mock):
            result = await client.get_branch_diff("feature", "main", max_files=2)

        assert result.success is True
        assert len(result.files) == 2
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_max_diff_lines_truncation(self) -> None:
        """max_diff_lines 截断: 单文件超行数 → diff 尾部追加 "[diff truncated]"、truncated=True。"""
        client = self._make_client()

        long_diff = "\n".join(f"+line {i}" for i in range(20))
        compare_result = {
            "diffs": [_make_gitlab_diff_entry(diff=long_diff)],
        }

        project_mock = MagicMock()
        project_mock.repository_compare.return_value = compare_result

        with patch.object(client, "_get_project", return_value=project_mock):
            result = await client.get_branch_diff("feature", "main", max_diff_lines=10)

        assert result.success is True
        assert result.truncated is True
        assert result.files[0].diff.endswith("[diff truncated]")
        # 截断后行数 = max_diff_lines + 1 行截断标记
        assert len(result.files[0].diff.split("\n")) == 11

    @pytest.mark.asyncio
    async def test_sdk_exception(self) -> None:
        """SDK 异常: repository_compare 抛 GitlabError → success=False、error 非空、不上抛。"""
        client = self._make_client()

        project_mock = MagicMock()
        project_mock.repository_compare.side_effect = GitlabError("GitLab API error")

        with patch.object(client, "_get_project", return_value=project_mock):
            result = await client.get_branch_diff("feature", "main")

        assert result.success is False
        assert result.error
        assert "GitLab API error" in result.error


# ── GitHub get_branch_diff 测试 ──────────────────────────────


def _make_github_compare_file(
    filename: str = "src/main.py",
    status: str = "modified",
    patch_text: str | None = "+added\n-removed\n context",
    previous_filename: str | None = None,
) -> MagicMock:
    f = MagicMock()
    f.filename = filename
    f.status = status
    f.patch = patch_text
    f.previous_filename = previous_filename
    return f


class TestGithubBranchDiff:
    """mock PyGithub 的 repo.compare() 测试 GitHub get_branch_diff。"""

    def _make_client(self) -> Any:
        from services.git_platform.github_client import GitHubClient

        return GitHubClient(token="test-token", owner="owner", repo="repo")

    def _make_repo_mock(self, files: list[MagicMock]) -> MagicMock:
        comparison = MagicMock()
        comparison.files = files
        repo_mock = MagicMock()
        repo_mock.compare.return_value = comparison
        return repo_mock

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """正常路径: 2 个 file 对象 → success=True、diff 取自 file.patch、status 映射布尔位。"""
        client = self._make_client()

        added_patch = "+new file content"
        renamed_patch = "+renamed line"
        repo_mock = self._make_repo_mock(
            [
                _make_github_compare_file(
                    filename="src/new.py", status="added", patch_text=added_patch
                ),
                _make_github_compare_file(
                    filename="src/renamed.py",
                    status="renamed",
                    patch_text=renamed_patch,
                    previous_filename="src/old.py",
                ),
            ]
        )

        with patch.object(client, "_get_repo", return_value=repo_mock):
            result = await client.get_branch_diff("feature", "main")

        assert result.success is True
        assert result.truncated is False
        assert len(result.files) == 2
        assert result.files[0].new_path == "src/new.py"
        assert result.files[0].diff == added_patch
        assert result.files[0].new_file is True
        assert result.files[0].deleted_file is False
        assert result.files[1].renamed_file is True
        assert result.files[1].old_path == "src/old.py"
        assert result.files[1].new_path == "src/renamed.py"
        assert result.files[1].diff == renamed_patch
        # compare(base=target, head=source)，与 compare_branches 既有调用同序
        repo_mock.compare.assert_called_once_with("main", "feature")

    @pytest.mark.asyncio
    async def test_missing_patch_degrades(self) -> None:
        """patch 缺失降级（A1）: 某 file patch=None → 该文件 diff==""、truncated=True、其余正常。"""
        client = self._make_client()

        normal_patch = "+normal change"
        repo_mock = self._make_repo_mock(
            [
                _make_github_compare_file(filename="huge.bin", patch_text=None),
                _make_github_compare_file(filename="src/ok.py", patch_text=normal_patch),
            ]
        )

        with patch.object(client, "_get_repo", return_value=repo_mock):
            result = await client.get_branch_diff("feature", "main")

        assert result.success is True
        assert result.truncated is True
        assert result.files[0].new_path == "huge.bin"
        assert result.files[0].diff == ""
        assert result.files[1].diff == normal_patch

    @pytest.mark.asyncio
    async def test_max_files_truncation(self) -> None:
        """max_files 截断: 3 个文件 + max_files=2 → files 长度 2、truncated=True。"""
        client = self._make_client()

        repo_mock = self._make_repo_mock(
            [_make_github_compare_file(filename=f"src/file{i}.py") for i in range(3)]
        )

        with patch.object(client, "_get_repo", return_value=repo_mock):
            result = await client.get_branch_diff("feature", "main", max_files=2)

        assert result.success is True
        assert len(result.files) == 2
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_max_diff_lines_truncation(self) -> None:
        """max_diff_lines 截断: 单文件超行数 → 尾部追加 "[diff truncated]"、truncated=True。"""
        client = self._make_client()

        long_patch = "\n".join(f"+line {i}" for i in range(20))
        repo_mock = self._make_repo_mock(
            [_make_github_compare_file(patch_text=long_patch)]
        )

        with patch.object(client, "_get_repo", return_value=repo_mock):
            result = await client.get_branch_diff("feature", "main", max_diff_lines=10)

        assert result.success is True
        assert result.truncated is True
        assert result.files[0].diff.endswith("[diff truncated]")

    @pytest.mark.asyncio
    async def test_sdk_exception(self) -> None:
        """SDK 异常: compare 抛 GithubException → success=False、error 非空、不上抛。"""
        client = self._make_client()

        repo_mock = MagicMock()
        repo_mock.compare.side_effect = GithubException(500, "GitHub API error", None)

        with patch.object(client, "_get_repo", return_value=repo_mock):
            result = await client.get_branch_diff("feature", "main")

        assert result.success is False
        assert result.error
        assert "GitHub API error" in result.error
