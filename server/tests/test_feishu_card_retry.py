"""Tests for Feishu card send retry mechanism."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.hooks.feishu_sync import BASE_DELAY, MAX_RETRIES, FeishuSyncHook


@pytest.fixture
def hook():
    return FeishuSyncHook()


@pytest.fixture
def mock_execution():
    """模拟工作流执行对象。"""
    execution = MagicMock()
    execution.id = "test-execution-001"
    execution.context = {"chat_id": "oc_test_chat_id"}
    execution.input_data = {}
    execution.error_message = ""
    execution.workflow = MagicMock()
    execution.workflow.space = None
    return execution


class TestRetryConstants:
    """测试重试配置常量。"""

    def test_max_retries(self):
        assert MAX_RETRIES == 3

    def test_base_delay(self):
        assert BASE_DELAY == 1.0


class TestBuildStatusCard:
    """测试卡片构建。"""

    def test_build_status_card_default_color(self, hook):
        card = hook._build_status_card("测试内容")
        assert card["header"]["template"] == "blue"
        assert card["elements"][0]["content"] == "测试内容"

    def test_build_status_card_custom_color(self, hook):
        card = hook._build_status_card("错误信息", color="red")
        assert card["header"]["template"] == "red"


class TestGetChatId:
    """测试 chat_id 提取。"""

    def test_from_context(self, hook):
        execution = MagicMock()
        execution.context = {"chat_id": "oc_123"}
        execution.input_data = {}
        assert hook._get_chat_id(execution) == "oc_123"

    def test_from_input_data(self, hook):
        execution = MagicMock()
        execution.context = {}
        execution.input_data = {"chat_id": "oc_456"}
        assert hook._get_chat_id(execution) == "oc_456"

    def test_not_found(self, hook):
        execution = MagicMock()
        execution.context = {}
        execution.input_data = {}
        assert hook._get_chat_id(execution) is None


@pytest.mark.asyncio
class TestSendNotification:
    """测试通知发送重试和降级。"""

    async def test_first_send_success(self, hook, mock_execution):
        """首次发送成功时不重试。"""
        mock_service = AsyncMock()
        mock_service.send_card = AsyncMock(return_value="msg_001")

        with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock, return_value=mock_service):
            with patch("workflows.hooks.feishu_sync.feature_flags") as mock_flags:
                mock_flags.sync_workflow_to_feishu = True

                await hook._send_notification(mock_execution, content="测试通知")

        mock_service.send_card.assert_called_once()

    async def test_retry_on_failure_then_success(self, hook, mock_execution):
        """首次失败后重试成功。"""
        mock_service = AsyncMock()
        # 首次失败，第二次成功
        mock_service.send_card = AsyncMock(
            side_effect=[Exception("网络错误"), "msg_002"]
        )

        with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock, return_value=mock_service):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await hook._send_notification(mock_execution, content="重试测试")

        assert mock_service.send_card.call_count == 2

    async def test_all_retries_fail_gracefully(self, hook, mock_execution):
        """3 次全部失败后降级，不抛异常。"""
        mock_service = AsyncMock()
        mock_service.send_card = AsyncMock(
            side_effect=Exception("持续失败")
        )

        with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock, return_value=mock_service):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # 不应抛出异常
                await hook._send_notification(mock_execution, content="降级测试")

        assert mock_service.send_card.call_count == MAX_RETRIES

    async def test_no_chat_id_skips_silently(self, hook):
        """没有 chat_id 时静默跳过。"""
        execution = MagicMock()
        execution.id = "no-chat"
        execution.context = {}
        execution.input_data = {}

        # 不应抛出异常，也不应尝试发送
        await hook._send_notification(execution, content="无 chat_id")


@pytest.mark.asyncio
class TestHookHandlers:
    """测试 hook 事件处理器。"""

    async def test_on_execution_completed_calls_send(self, hook, mock_execution):
        """完成事件应调用 _send_notification。"""
        with patch.object(hook, "_send_notification", new_callable=AsyncMock) as mock_send:
            with patch("workflows.hooks.feishu_sync.feature_flags") as mock_flags:
                mock_flags.sync_workflow_to_feishu = True
                await hook.on_execution_completed(execution=mock_execution)

        mock_send.assert_called_once()

    async def test_feature_flag_disabled_skips(self, hook, mock_execution):
        """feature flag 关闭时跳过。"""
        with patch.object(hook, "_send_notification", new_callable=AsyncMock) as mock_send:
            with patch("workflows.hooks.feishu_sync.feature_flags") as mock_flags:
                mock_flags.sync_workflow_to_feishu = False
                await hook.on_execution_completed(execution=mock_execution)

        mock_send.assert_not_called()
