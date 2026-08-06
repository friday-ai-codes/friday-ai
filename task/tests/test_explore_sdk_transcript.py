"""explore 模式 completed 帧携带 SDK 会话（quick 260807-1s3）。

蓝图调研/拟方案容器全部跑 explore 模式：completed 帧不带 ``sdk_session_id`` /
``sdk_transcript`` 的话，server 侧 ``SubAgentSession`` 留痕恒空、``_aresume_env``
永远查不到可续会话 ⇒ 同仓重派只能全新执行。正反并列：

1. result 带 ``session_id`` ⇒ ``read_transcript`` 被调、completed 帧两个字段齐全；
2. result 无 ``session_id`` ⇒ 两个字段为空串、``read_transcript`` 不被调（行为与现状一致）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runner import TaskRunner


@pytest.fixture
def explore_runner(mock_explore_config):
    """explore 模式 TaskRunner（工作区恒 clean，聚焦 completed 帧的形状）。"""
    with (
        patch("core.runner.GitOperations") as mock_git_cls,
        patch("core.runner.CallbackClient") as mock_cb_cls,
    ):
        mock_git = MagicMock()
        mock_git.repo = MagicMock()
        mock_git.repo.git.status.return_value = ""
        mock_git.get_workspace_path.return_value = "/app/workspace"
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


@pytest.mark.asyncio
async def test_explore_completed_carries_sdk_session(explore_runner):
    """① result 带 session_id ⇒ completed 帧携带 sdk_session_id + transcript。"""
    explore_runner.claude = MagicMock()
    explore_runner.claude.run_explore_mode = AsyncMock(
        return_value={"success": True, "output": "分析产物", "session_id": "sess-1"}
    )

    with patch("core.sdk_sessions.read_transcript", return_value='{"jsonl":1}') as mock_read:
        result = await explore_runner._run_explore_mode(MagicMock())

    assert result == 0
    mock_read.assert_called_once_with("sess-1", "/app/workspace")
    explore_runner.callback.report_completed.assert_awaited_once()
    kwargs = explore_runner.callback.report_completed.await_args.kwargs
    assert kwargs["sdk_session_id"] == "sess-1"
    assert kwargs["sdk_transcript"] == '{"jsonl":1}'
    assert kwargs["output"] == {"text": "分析产物", "task_type": "explore"}


@pytest.mark.asyncio
async def test_explore_completed_without_session_id_sends_empty_fields(explore_runner):
    """② result 无 session_id ⇒ 两字段空串、不读 transcript（与现状逐字一致）。"""
    explore_runner.claude = MagicMock()
    explore_runner.claude.run_explore_mode = AsyncMock(
        return_value={"success": True, "output": "分析产物"}
    )

    with patch("core.sdk_sessions.read_transcript") as mock_read:
        result = await explore_runner._run_explore_mode(MagicMock())

    assert result == 0
    mock_read.assert_not_called()
    kwargs = explore_runner.callback.report_completed.await_args.kwargs
    assert kwargs["sdk_session_id"] == ""
    assert kwargs["sdk_transcript"] == ""
