"""Progress payload 公共解析函数（implementation G4）。

目的: 让 server/subagent/api/callbacks.py:_handle_progress (HTTP) 与
server/runners/consumers.py:RunnerConsumer._handle_progress (WebSocket)
两条 progress 路径解析逻辑完全一致，避免再次分叉（regression）。

放置位置理由: 新建 orchestration 顶层模块，避免以下两条循环依赖风险:
  - 若放 subagent/api/callbacks.py，runners/consumers.py 需反向 import callbacks
  - 若放 runners/，callbacks.py 需反向 import runners
orchestration package 当前不 import subagent 与 runners，安全。
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

# 保留字段黑名单: details 中的这些 key 不透传，防止覆盖顶层 output["progress"] (nested dict)
# 与 output["coding_progress"] (nested dict) — 会产生类型冲突 (float vs dict)。
_RESERVED_OUTPUT_KEYS: frozenset[str] = frozenset({"progress", "coding_progress"})


def parse_progress_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """把 progress 回调 payload 规范化为 session.last_output 的增量更新字典。

    规范化输出 shape::

        {
            "progress": {
                "phase": str,
                "progress": float,
                "message": str,
                "updated_at": iso_str,
            },
            "coding_progress": {...},  # 仅当 payload["coding_progress"] 为非空 dict
            "suggested_commit_message": str,  # 仅当 payload["details"]["suggested_commit_message"] 存在
            # 其他 details 中的 scalar 字段也透传（排除保留字段黑名单）
        }

    Args:
        payload: 容器侧 ``report_status(status="progress", ...)`` 发送的 payload dict
            （可来自 DRF ``validated_data`` 或 WebSocket 原始 dict）。

    Returns:
        适合 merge 进 ``session.last_output`` 的增量 dict。
    """
    now_iso = timezone.now().isoformat()

    output: dict[str, Any] = {
        "progress": {
            "phase": payload.get("phase", ""),
            "progress": payload.get("progress", 0.0),
            "message": payload.get("message", ""),
            "updated_at": now_iso,
        },
    }

    coding_progress = payload.get("coding_progress")
    if coding_progress and isinstance(coding_progress, dict):
        output["coding_progress"] = {
            "modified_files": coding_progress.get("modified_files", []),
            "recent_tool_calls": coding_progress.get("recent_tool_calls", []),
            "updated_at": now_iso,
        }

    details = payload.get("details")
    if isinstance(details, dict):
        for key, value in details.items():
            if key in _RESERVED_OUTPUT_KEYS:
                # 保留字段黑名单：防止 details.progress/coding_progress scalar 覆盖顶层 nested dict
                continue
            # 只透传 scalar/基础类型 — 嵌套 dict/list 不透传（避免跨字段语义耦合）
            if value is None or isinstance(value, (str, int, float, bool)):
                output[key] = value

    return output
