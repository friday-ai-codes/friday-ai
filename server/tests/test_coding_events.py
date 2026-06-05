"""编码事件存储逻辑测试。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStoreCodingCompleteToMessage:
    """store_coding_complete_to_message 测试。"""

    @pytest.mark.asyncio
    async def test_no_message_id_skips(self) -> None:
        """没有关联 message 时跳过。"""
        from chat.coding_events import store_coding_complete_to_message

        session = MagicMock()
        session.message_id = None
        session.id = uuid.uuid4()
        await store_coding_complete_to_message(session)
        # 不报错即可

    @pytest.mark.asyncio
    async def test_stores_result_to_metadata(self) -> None:
        """编码完成结果写入消息 metadata。"""
        from chat.coding_events import store_coding_complete_to_message

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()

        mock_msg = MagicMock()
        mock_msg.metadata = {}
        mock_msg.asave = AsyncMock()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.message_id = message_id
        mock_session.pr_url = "https://github.com/org/repo/pull/42"
        mock_session.branch_name = "coding-abc12345"
        mock_session.affected_files = [{"path": "a.py", "change_type": "modify"}]

        with patch("chat.coding_events.Message") as MockMessage:
            MockMessage.objects.filter.return_value.afirst = AsyncMock(return_value=mock_msg)
            await store_coding_complete_to_message(mock_session)

        assert mock_msg.metadata["codingResult"]["prUrl"] == "https://github.com/org/repo/pull/42"
        assert mock_msg.metadata["codingResult"]["status"] == "completed"
        assert mock_msg.metadata["codingResult"]["sessionId"] == str(session_id)
        assert mock_msg.metadata["codingResult"]["branchName"] == "coding-abc12345"
        assert mock_msg.metadata["codingResult"]["modifiedFilesCount"] == 1
        mock_msg.asave.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_not_found_skips(self) -> None:
        """消息不存在时跳过。"""
        from chat.coding_events import store_coding_complete_to_message

        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()
        mock_session.message_id = uuid.uuid4()

        with patch("chat.coding_events.Message") as MockMessage:
            MockMessage.objects.filter.return_value.afirst = AsyncMock(return_value=None)
            await store_coding_complete_to_message(mock_session)
        # 不报错即可


class TestStoreCodingFailedToMessage:
    """store_coding_failed_to_message 测试。"""

    @pytest.mark.asyncio
    async def test_stores_error_to_metadata(self) -> None:
        """编码失败错误写入消息 metadata。"""
        from chat.coding_events import store_coding_failed_to_message

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()

        mock_msg = MagicMock()
        mock_msg.metadata = {}
        mock_msg.asave = AsyncMock()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.message_id = message_id
        mock_session.error_message = "Docker container OOMKilled"

        with patch("chat.coding_events.Message") as MockMessage:
            MockMessage.objects.filter.return_value.afirst = AsyncMock(return_value=mock_msg)
            await store_coding_failed_to_message(mock_session)

        assert mock_msg.metadata["codingError"]["errorMessage"] == "Docker container OOMKilled"
        assert mock_msg.metadata["codingError"]["status"] == "failed"
        assert mock_msg.metadata["codingError"]["sessionId"] == str(session_id)
        mock_msg.asave.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_message_id_skips(self) -> None:
        """没有关联 message 时跳过。"""
        from chat.coding_events import store_coding_failed_to_message

        session = MagicMock()
        session.message_id = None
        session.id = uuid.uuid4()
        await store_coding_failed_to_message(session)
        # 不报错即可


class TestStoreCodingCompleteWithBranchUrl:
    """store_coding_complete_to_message 支持 branch_url 参数。"""

    @pytest.mark.asyncio
    async def test_store_coding_complete_with_branch_url(self) -> None:
        """传入 branch_url 后 Message.metadata.codingResult 包含 branchUrl 字段。"""
        from chat.coding_events import store_coding_complete_to_message

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()

        mock_msg = MagicMock()
        mock_msg.metadata = {}
        mock_msg.asave = AsyncMock()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.message_id = message_id
        mock_session.pr_url = ""
        mock_session.branch_name = "feat20260409.test-feature"
        mock_session.affected_files = [{"path": "a.py", "change_type": "modify"}]

        with patch("chat.coding_events.Message") as MockMessage:
            MockMessage.objects.filter.return_value.afirst = AsyncMock(return_value=mock_msg)
            await store_coding_complete_to_message(
                mock_session,
                branch_url="https://github.com/test/repo/tree/feat-branch",
            )

        assert mock_msg.metadata["codingResult"]["branchUrl"] == "https://github.com/test/repo/tree/feat-branch"
        assert mock_msg.metadata["codingResult"]["status"] == "completed"
        mock_msg.asave.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_coding_complete_without_branch_url(self) -> None:
        """不传 branch_url 时 branchUrl 为空字符串（向后兼容）。"""
        from chat.coding_events import store_coding_complete_to_message

        session_id = uuid.uuid4()
        message_id = uuid.uuid4()

        mock_msg = MagicMock()
        mock_msg.metadata = {}
        mock_msg.asave = AsyncMock()

        mock_session = MagicMock()
        mock_session.id = session_id
        mock_session.message_id = message_id
        mock_session.pr_url = "https://github.com/org/repo/pull/1"
        mock_session.branch_name = "coding-abc12345"
        mock_session.affected_files = []

        with patch("chat.coding_events.Message") as MockMessage:
            MockMessage.objects.filter.return_value.afirst = AsyncMock(return_value=mock_msg)
            await store_coding_complete_to_message(mock_session)

        assert mock_msg.metadata["codingResult"]["branchUrl"] == ""
        mock_msg.asave.assert_awaited_once()
