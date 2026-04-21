"""Phase Wave — stub 测试文件。Plan 的 task 07-01 将把真实 assertion 填入。
Scope: 上下文窗口超限 SSE ERROR 结构化 payload 契约。覆盖 验收项：
 SSE ERROR 事件 {code:"context_window_exceeded", data:{estimated_tokens,
 max_tokens, exceeded_by, model, recommended_actions}} 统一结构。
Consumer: Plan Wave Task 07-01。
"""
from __future__ import annotations
import pytest
# TODO(Plan Task 07-01)：填入以下用例
# - test_context_exceeded_emits_sse_error_event
# - test_payload_code_is_context_window_exceeded
# - test_payload_includes_estimated_tokens_max_tokens_exceeded_by
# - test_payload_includes_model_name
# - test_payload_recommended_actions_has_three_entries
# - test_exceeded_by_equals_estimated_minus_max
# - test_non_context_errors_use_different_code
def test_placeholder -> None:
 """Phase Wave stub — Plan fill real assertion."""
 pytest.skip("Phase Wave stub — Plan fill real assertion")
