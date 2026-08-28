"""``get_session_capture`` 独立 schema RED 快照（Phase 144 Wave 0）。

该文件刻意不改 Phase 144 Plan 04 消费的 52 工具全字典；Plan 05 注册生产 schema 后转绿。
"""

from __future__ import annotations

from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT


def test_get_session_capture_schema_pending() -> None:
    assert TOOL_SCHEMA_SNAPSHOT["get_session_capture"] == {
        "request": ["capture_id"],
        "response": [
            "capture_id",
            "question",
            "answer",
            "response_model",
            "provider",
            "input_tokens",
            "output_tokens",
            "session_id",
            "branch_name",
            "repository_id",
            "project_id",
            "link_reason",
            "value_tier",
            "status",
            "created_at",
            "updated_at",
            "evaluated_at",
            "ingested_at",
            "run_id",
        ],
    }
