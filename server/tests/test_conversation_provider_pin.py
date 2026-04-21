"""Phase Wave — stub 测试文件。Plan 的 task 02-01 将把真实 assertion 填入。
Scope: 对话 Provider pin 冻结契约。覆盖 验收项：
 对话 status ∈ {completed, stopped, error} 时 API 拒绝修改 provider_credential_id
 （HTTP 400 + code=conversation_frozen 结构化错误）。
Consumer: Plan Wave Task 02-01。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 02-01)：填入以下用例
# - test_active_conversation_can_pin_provider_credential
# - test_completed_conversation_rejects_repin_with_400
# - test_stopped_conversation_rejects_repin_with_400
# - test_error_conversation_rejects_repin_with_400
# - test_error_code_is_conversation_frozen
# - test_non_owner_cannot_pin_provider_credential (ownership 校验)
# - test_pin_to_credential_from_other_project_rejected (跨项目隔离)
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
