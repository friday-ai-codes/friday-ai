"""Phase Wave — stub 测试文件。Plan 的 task 03-01 将把真实 assertion 填入。
Scope: 凭证缺失降级 preflight 端点契约。覆盖 验收项：
 GET /api/chat/conversations/{id}/preflight/ 返回结构化错误
 {code:"provider_credential_missing", data:{provider_type, recommended_actions}}。
Consumer: Plan Wave Task 03-01。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 03-01)：填入以下用例
# - test_preflight_returns_ok_when_credential_exists
# - test_preflight_returns_provider_credential_missing_code
# - test_preflight_payload_includes_recommended_actions
# - test_preflight_payload_includes_provider_type
# - test_preflight_rejects_non_member (权限矩阵)
# - test_preflight_handles_inactive_credential
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
