"""TaskRunner 工作区干净度校验测试。

验证 explore 模式结束时自动检查工作区状态，
非 clean 则标记任务失败（返回非零退出码）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runner import TaskRunner


@pytest.fixture
def mock_task_runner(mock_explore_config):
    """创建用于测试的 TaskRunner 实例（explore 模式）。"""
    with patch("core.runner.GitOperations") as mock_git_cls, \
         patch("core.runner.CallbackClient") as mock_cb_cls:
        mock_git = MagicMock()
        mock_git.repo = MagicMock()
        mock_git.cleanup = MagicMock()
        mock_git_cls.return_value = mock_git

        mock_cb = MagicMock()
        mock_cb.report_error = AsyncMock()
        mock_cb.report_started = AsyncMock()
        mock_cb.report_completed = AsyncMock()
        mock_cb_cls.return_value = mock_cb

        runner = TaskRunner(mock_explore_config)
        runner.git_ops = mock_git
        runner.callback = mock_cb

        yield runner


@pytest.fixture
def mock_log():
    """创建模拟的 structlog bound logger。"""
    log = MagicMock()
    log.info = MagicMock()
    log.error = MagicMock()
    log.warning = MagicMock()
    log.exception = MagicMock()
    return log


class TestCheckWorkspaceClean:
    """_check_workspace_clean 方法测试。"""

    @pytest.mark.asyncio
    async def test_workspace_clean(self, mock_task_runner, mock_log):
        """Test 1: 工作区干净时返回 True。"""
        mock_task_runner.git_ops.repo.git.status.return_value = ""
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True
        mock_log.info.assert_called_with(
            "workspace_clean", task_id=mock_task_runner.config.task_id
        )

    @pytest.mark.asyncio
    async def test_workspace_has_uncommitted_changes(self, mock_task_runner, mock_log):
        """Test 2: 工作区有未提交修改时返回 False。"""
        mock_task_runner.git_ops.repo.git.status.return_value = " M src/main.py"
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is False
        mock_log.error.assert_called_once()
        call_args = mock_log.error.call_args
        assert call_args[0][0] == "workspace_not_clean"
        assert "M src/main.py" in call_args[1]["git_status"]

    @pytest.mark.asyncio
    async def test_workspace_has_untracked_files(self, mock_task_runner, mock_log):
        """Test 3: 工作区有 untracked 文件时返回 False。"""
        mock_task_runner.git_ops.repo.git.status.return_value = "?? new_file.py"
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is False

    @pytest.mark.asyncio
    async def test_workspace_dirty_logs_git_status(self, mock_task_runner, mock_log):
        """Test 4: 校验失败时 structlog 记录包含 git status 完整输出。"""
        status_output = " M file1.py\n?? file2.py"
        mock_task_runner.git_ops.repo.git.status.return_value = status_output
        await mock_task_runner._check_workspace_clean(mock_log)

        call_args = mock_log.error.call_args
        assert call_args[1]["git_status"] == status_output
        # 同时验证 callback.report_error 被调用
        mock_task_runner.callback.report_error.assert_called_once()
        error_msg = mock_task_runner.callback.report_error.call_args[0][0]
        assert status_output in error_msg

    @pytest.mark.asyncio
    async def test_only_friday_scratch_is_clean(self, mock_task_runner, mock_log):
        """仅有 Friday 自身的 .friday/ 暂存目录时应视为干净（返回 True）。

        复现并锁定线上报错「Explore 模式结束后工作区存在未提交变更: ?? .friday/」：
        Friday 会往 /workspace/.friday/ 写 usage.json，不应被当成用户未提交变更。
        """
        mock_task_runner.git_ops.repo.git.status.return_value = "?? .friday/"
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True
        mock_log.info.assert_called_with(
            "workspace_clean", task_id=mock_task_runner.config.task_id
        )

    @pytest.mark.asyncio
    async def test_friday_scratch_file_variants_are_clean(self, mock_task_runner, mock_log):
        """.friday/ 下具体文件（usage.json / answer.json）也应被剔除、视为干净。"""
        mock_task_runner.git_ops.repo.git.status.return_value = (
            "?? .friday/usage.json\n?? .friday/answer.json"
        )
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True

    @pytest.mark.asyncio
    async def test_only_claude_scratch_is_clean(self, mock_task_runner, mock_log):
        """⭐ 仅有 agent SDK 的 .claude/ 状态目录时应视为干净（返回 True）。

        复现线上事故：一整批调研容器报「Explore 模式结束后工作区存在未提交变更:
        ?? .claude/」全部失败，整条蓝图编排停在 repo_research 等不到回调。
        `.claude/` 是 agent SDK 自己写的，与 `.friday/` 同为工具产物。
        """
        mock_task_runner.git_ops.repo.git.status.return_value = "?? .claude/"
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True

    @pytest.mark.asyncio
    async def test_both_tool_scratch_dirs_are_clean(self, mock_task_runner, mock_log):
        """两个工具目录（含其下文件）同时出现也视为干净。"""
        mock_task_runner.git_ops.repo.git.status.return_value = (
            "?? .claude/settings.local.json\n?? .friday/usage.json"
        )
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True

    @pytest.mark.asyncio
    async def test_friday_scratch_mixed_with_real_change_is_dirty(
        self, mock_task_runner, mock_log
    ):
        """混入真实用户改动时仍判脏（返回 False），且报错里不含被过滤的工具目录。"""
        mock_task_runner.git_ops.repo.git.status.return_value = (
            "?? .friday/usage.json\n?? .claude/settings.local.json\n M src/main.py"
        )
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is False
        error_msg = mock_task_runner.callback.report_error.call_args[0][0]
        assert "src/main.py" in error_msg
        assert ".friday/" not in error_msg
        assert ".claude/" not in error_msg

    @pytest.mark.asyncio
    async def test_repo_none_returns_true(self, mock_task_runner, mock_log):
        """Test 5: repo 为 None 时返回 True（无法检查视为通过）。"""
        mock_task_runner.git_ops.repo = None
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is True

    @pytest.mark.asyncio
    async def test_git_status_exception_returns_false(self, mock_task_runner, mock_log):
        """Test 6: git status 命令异常时返回 False（保守策略）。"""
        mock_task_runner.git_ops.repo.git.status.side_effect = Exception("git error")
        result = await mock_task_runner._check_workspace_clean(mock_log)
        assert result is False
        mock_log.error.assert_called_once()


class TestRunExploreModeWorkspaceCheck:
    """_run_explore_mode 中工作区校验集成测试。"""

    @pytest.mark.asyncio
    async def test_explore_dirty_workspace_returns_1(self, mock_task_runner, mock_log):
        """Test 7: 工作区非 clean 时返回 1。"""
        mock_claude = MagicMock()
        mock_claude.run_explore_mode = AsyncMock(return_value={"success": True})
        mock_task_runner.claude = mock_claude

        # 工作区有未提交修改
        mock_task_runner.git_ops.repo.git.status.return_value = " M dirty_file.py"

        result = await mock_task_runner._run_explore_mode(mock_log)
        assert result == 1

    @pytest.mark.asyncio
    async def test_explore_clean_workspace_returns_0(self, mock_task_runner, mock_log):
        """Test 8: 工作区 clean 且 explore 成功时返回 0。"""
        mock_claude = MagicMock()
        mock_claude.run_explore_mode = AsyncMock(return_value={"success": True})
        mock_task_runner.claude = mock_claude

        # 工作区干净
        mock_task_runner.git_ops.repo.git.status.return_value = ""

        result = await mock_task_runner._run_explore_mode(mock_log)
        assert result == 0
