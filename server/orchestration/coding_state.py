"""CodingSession graph state -- authoritative source。
所有字段为 JSON 可序列化类型，支持 checkpoint 持久化。
CodingSession Django 模型是此 state 的投影。
"""
from __future__ import annotations
from typing import Any, TypedDict
class CodingSessionState(TypedDict, total=False):
 """CodingSession 编排 graph state。
 所有字段为 JSON 可序列化类型，支持 checkpoint 持久化。
 CodingSession Django 模型是此 state 的投影。
 """
 # 标识
 coding_session_id: str
 conversation_id: str
 repository_id: str
 # 编排语义
 phase: str # coding / waiting_coding / awaiting_commit_confirm / committing / waiting_commit / pr_pending / awaiting_pr_confirm / creating_pr / skipping_pr / completed / failed
 error: str
 # Phase 结果
 phase1_session_id: str
 suggested_commit_message: str
 # Phase 配置
 confirmed_commit_message: str
 phase2_session_id: str
 # dispatch 共享配置（避免每次 dispatch 重新查询）
 dispatch_config: dict[str, Any]
 # Phase: PR 确认 (Phase)
 suggested_pr_title: str
 suggested_pr_description: str
 confirmed_pr_title: str
 confirmed_pr_description: str
 target_branch: str
 skip_pr: bool
 # 最终结果
 branch_url: str
 pr_url: str
