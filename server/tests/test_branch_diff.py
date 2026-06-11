"""get_branch_diff 双平台单元测试（mock SDK，零网络）。

覆盖:
- GitLab get_branch_diff: 正常路径 / max_files 截断 / max_diff_lines 截断 / SDK 异常
- （Task 2 追加）GitHub get_branch_diff: 正常路径 / patch 缺失降级 / 截断 / SDK 异常
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
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
