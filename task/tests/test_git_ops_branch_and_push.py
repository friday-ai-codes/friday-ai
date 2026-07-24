"""GitOperations setup_task_branch / push_branch bug fix 回归测试。

覆盖两处历史 bug（详见 ``git_ops/operations.py:setup_task_branch`` /
``push_branch`` 的 docstring）：

- **Bug X**：``setup_task_branch`` 原本对所有分支名强制拼 ``friday/`` 前缀，
  与 implementation 引入的模板分支名（``feat20260519.xxx`` / ``fix20260519.xxx``）
  冲突。修复后应严格尊重显式传入的 ``branch_strategy``。
- **Bug Y**：``push_branch`` 原本只 try/except ``GitCommandError``，未检查
  GitPython ``origin.push()`` 返回的 ``PushInfo.flags``；push 被远端拒绝时
  静默上报 success，容器关闭后代码丢失。修复后应把错误位翻成 ``GitCommandError``
  抛出，让上层 retry 机制和异常处理路径正常工作。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from git import PushInfo
from git.exc import GitCommandError

from git_ops import GitOperations


class TestSetupTaskBranchNoFridayPrefix:
    """Bug X 回归：setup_task_branch 不再强制 friday/ 前缀。"""

    @pytest.fixture
    def git_ops_with_mock_repo(self, mock_config):
        """构造一个绕过 explore 守卫、注入 mock Repo 的 GitOperations 实例。"""
        mock_config.task_mode = "execute"
        ops = GitOperations(mock_config)
        ops.repo = MagicMock()
        # fetch 默认抛 GitCommandError，让 setup_task_branch 走"新建分支"分支
        ops.repo.git.fetch = MagicMock(
            side_effect=GitCommandError("fetch", 128, b"branch not found")
        )
        new_branch = MagicMock()
        ops.repo.create_head = MagicMock(return_value=new_branch)
        return ops

    @pytest.mark.asyncio
    async def test_explicit_template_branch_name_preserved(
        self, git_ops_with_mock_repo
    ):
        """显式传入模板分支名 fix20260519.xxx 时应原样保留，不应加 friday/ 前缀。"""
        ops = git_ops_with_mock_repo
        result = await ops.setup_task_branch(
            branch_strategy="fix20260519.example-app-page-apps-favorites",
            task_id="task-001",
        )
        assert result == "fix20260519.example-app-page-apps-favorites"
        ops.repo.create_head.assert_called_once_with(
            "fix20260519.example-app-page-apps-favorites"
        )

    @pytest.mark.asyncio
    async def test_explicit_feature_branch_name_preserved(
        self, git_ops_with_mock_repo
    ):
        """显式 feat20260519.xxx 分支名同样原样保留。"""
        ops = git_ops_with_mock_repo
        result = await ops.setup_task_branch(
            branch_strategy="feat20260519.new-thing",
            task_id="task-001",
        )
        assert result == "feat20260519.new-thing"

    @pytest.mark.asyncio
    async def test_branch_strategy_with_friday_prefix_unchanged(
        self, git_ops_with_mock_repo
    ):
        """显式包含 friday/ 前缀的分支名同样原样保留，不双加。"""
        ops = git_ops_with_mock_repo
        result = await ops.setup_task_branch(
            branch_strategy="friday/legacy-name",
            task_id="task-001",
        )
        assert result == "friday/legacy-name"

    @pytest.mark.asyncio
    async def test_none_branch_strategy_falls_back_to_default(
        self, git_ops_with_mock_repo
    ):
        """branch_strategy=None 时 fallback 到 friday/task-{task_id} 默认值。"""
        ops = git_ops_with_mock_repo
        result = await ops.setup_task_branch(
            branch_strategy=None,
            task_id="task-001",
        )
        assert result == "friday/task-task-001"

    @pytest.mark.asyncio
    async def test_task_id_placeholder_substituted(self, git_ops_with_mock_repo):
        """branch_strategy 内 {task_id} 占位符仍正常替换。"""
        ops = git_ops_with_mock_repo
        result = await ops.setup_task_branch(
            branch_strategy="custom-{task_id}-branch",
            task_id="task-XYZ",
        )
        assert result == "custom-task-XYZ-branch"

    @pytest.mark.asyncio
    async def test_existing_remote_branch_checked_out_from_origin(
        self, git_ops_with_mock_repo
    ):
        """远端分支已存在时，新 clone 应基于 origin/<branch> 建立本地工作分支。"""
        ops = git_ops_with_mock_repo
        ops.repo.git.fetch = MagicMock(return_value="")

        result = await ops.setup_task_branch(
            branch_strategy="feature/existing-branch",
            task_id="task-001",
        )

        assert result == "feature/existing-branch"
        ops.repo.git.checkout.assert_called_once_with(
            "-B",
            "feature/existing-branch",
            "origin/feature/existing-branch",
        )


class TestPushBranchDetectsRemoteRejection:
    """Bug Y 回归：push_branch 必须把 PushInfo.flags 错误位翻成 GitCommandError。"""

    @pytest.fixture
    def git_ops_with_mock_remote(self, mock_config):
        """构造可控的 mock remote 的 GitOperations。"""
        mock_config.task_mode = "execute"
        ops = GitOperations(mock_config)
        ops.repo = MagicMock()
        ops.remotes_push_mock = MagicMock()
        ops.repo.remotes.origin.push = ops.remotes_push_mock
        return ops

    def _push_info(self, flags: int, summary: str = "") -> MagicMock:
        """构造模拟的 PushInfo 对象（仅供位掩码测试用，不依赖真实 git）。"""
        info = MagicMock(spec=PushInfo)
        info.flags = flags
        info.summary = summary
        return info

    @pytest.mark.asyncio
    async def test_rejected_push_raises_git_command_error(
        self, git_ops_with_mock_remote
    ):
        """PushInfo.flags 含 REJECTED 时应抛 GitCommandError，不再 silent success。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.REJECTED, "[rejected] non-fast-forward")
        ]
        with pytest.raises(GitCommandError):
            await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_remote_rejected_push_raises(self, git_ops_with_mock_remote):
        """REMOTE_REJECTED（hook 拒绝 / 保护分支等）同样要抛。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(
                PushInfo.REMOTE_REJECTED, "remote rejected: pre-receive hook declined"
            )
        ]
        with pytest.raises(GitCommandError):
            await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_error_flag_raises(self, git_ops_with_mock_remote):
        """ERROR 位（通用错误，含网络/认证类失败）必须抛。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.ERROR, "fatal: Authentication failed")
        ]
        with pytest.raises(GitCommandError):
            await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_remote_failure_raises(self, git_ops_with_mock_remote):
        """REMOTE_FAILURE 同样要抛。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.REMOTE_FAILURE, "remote failure")
        ]
        with pytest.raises(GitCommandError):
            await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_new_head_push_succeeds_silently(self, git_ops_with_mock_remote):
        """NEW_HEAD（首次 push 新分支）属于成功，不应抛异常。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.NEW_HEAD, "new branch")
        ]
        # 不应 raise
        await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_fast_forward_push_succeeds(self, git_ops_with_mock_remote):
        """FAST_FORWARD（已有分支 ff 推进）也是成功路径。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.FAST_FORWARD, "fast-forward")
        ]
        await ops.push_branch("fix20260519.test-branch")

    @pytest.mark.asyncio
    async def test_mixed_results_with_one_failure_raises(
        self, git_ops_with_mock_remote
    ):
        """多个 ref push 时只要有一个失败就应抛（半推半就的数据一致性灾难）。"""
        ops = git_ops_with_mock_remote
        ops.remotes_push_mock.return_value = [
            self._push_info(PushInfo.NEW_HEAD, "new branch"),
            self._push_info(PushInfo.REJECTED, "[rejected]"),
        ]
        with pytest.raises(GitCommandError):
            await ops.push_branch("fix20260519.test-branch")
