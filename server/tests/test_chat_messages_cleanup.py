"""Phase Wave — stub 测试文件。Plan 的 task 07-02 将把真实 assertion 填入。
Scope: 对话历史清理 DELETE 端点契约。覆盖 验收项：
 DELETE /api/chat/conversations/{id}/messages/?before_id=X 带 ownership
 校验 + 幂等删除（重复调用不报 404）。
Consumer: Plan Wave Task 07-02。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 07-02)：填入以下用例
# - test_delete_before_id_removes_older_messages
# - test_delete_keeps_message_with_given_id_and_newer
# - test_delete_is_idempotent
# - test_delete_rejects_non_owner (ownership 校验)
# - test_delete_rejects_cross_project_conversation_id
# - test_delete_without_before_id_returns_400
# - test_delete_returns_deleted_count
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
