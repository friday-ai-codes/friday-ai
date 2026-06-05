"""MCP 命令白名单校验测试。

验证只有 MCP_ALLOWED_COMMANDS 中的命令才能通过 MCP 工具执行，
未授权命令在启动子进程前就被拒绝。
"""

from unittest.mock import AsyncMock, patch

import pytest
from django.test import override_settings
from structlog.testing import capture_logs

from tools.models import RemoteTool
from tools.sources.mcp_source import CommandNotAllowedError, execute_mcp


@pytest.mark.asyncio
@pytest.mark.django_db
class TestMcpWhitelist:
    """MCP 白名单校验测试套件。"""

    def _make_tool(self, *, server_command: str = "npx", tool_name: str = "test") -> RemoteTool:
        """构造 MCP 类型的 RemoteTool 实例（不入库）。"""
        tool = RemoteTool(
            name=f"test-{server_command}",
            description="test tool",
            source=RemoteTool.Source.MCP,
            input_schema={},
            config={"server_command": server_command, "tool_name": tool_name},
        )
        return tool

    @override_settings(MCP_ALLOWED_COMMANDS=["npx"])
    @patch("tools.sources.mcp_source.stdio_client")
    @patch("tools.sources.mcp_source.ClientSession")
    async def test_allowed_command(self, mock_session_cls: AsyncMock, mock_stdio: AsyncMock) -> None:
        """白名单内命令正常调用 StdioServerParameters，不抛异常。"""
        # 模拟 stdio_client 上下文管理器
        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

        # 模拟 ClientSession 上下文管理器
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=AsyncMock(content=[]))
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        tool = self._make_tool(server_command="npx")
        _ = await execute_mcp(tool, {"arg": "value"})

        # 白名单内的命令应该正常调用 stdio_client
        mock_stdio.assert_called_once()

    @override_settings(MCP_ALLOWED_COMMANDS=["npx"])
    @patch("tools.sources.mcp_source.stdio_client")
    async def test_blocked_command(self, mock_stdio: AsyncMock) -> None:
        """白名单外命令抛出 CommandNotAllowedError，不调用 stdio_client。"""
        tool = self._make_tool(server_command="rm")

        with pytest.raises(CommandNotAllowedError) as exc_info:
            await execute_mcp(tool, {})

        assert exc_info.value.command == "rm"
        # 关键验证：被拒绝命令不启动子进程
        mock_stdio.assert_not_called()

    @override_settings(MCP_ALLOWED_COMMANDS=["npx"])
    async def test_error_format(self) -> None:
        """execute_tool 捕获 CommandNotAllowedError 后返回 command_not_allowed 错误码。"""
        from tools.executor import execute_tool

        mock_tool = self._make_tool(server_command="rm")

        with patch("tools.executor.RemoteToolRegistry.aget_tool", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_tool
            result = await execute_tool("test-rm", {})

        assert result["ok"] is False
        assert result["error"]["code"] == "command_not_allowed"
        assert "rm" in result["error"]["message"]

    @override_settings(MCP_ALLOWED_COMMANDS=["npx"])
    async def test_blocked_command_logged(self) -> None:
        """被拒绝命令触发 structlog warning 日志（mcp_command_blocked event）。"""
        tool = self._make_tool(server_command="rm")

        with capture_logs() as cap_logs:
            with pytest.raises(CommandNotAllowedError):
                await execute_mcp(tool, {})

        # 验证产生了 mcp_command_blocked 事件
        blocked_events = [e for e in cap_logs if e.get("event") == "mcp_command_blocked"]
        assert len(blocked_events) == 1
        assert blocked_events[0]["command"] == "rm"
        assert blocked_events[0]["log_level"] == "warning"
