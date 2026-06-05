"""编码会话事件 -- 将编码结果写入消息 metadata 供前端恢复。

编码结果不通过实时 SSE 推送（因为编码执行在 Runner 容器，回调时 SSE 流已关闭），
而是写入关联 Message.metadata.codingResult / codingError，前端通过消息历史恢复。
前端通过 ConversationRuntime 轮询检测编码完成。

implementation 决策 (gap closure for checkpoint audit G3):
正式锁定 ConversationRuntime 快照轮询为 work item 编码中间产出的投递路径,
不做 AgentEvent SSE push 升级 —— 理由即本模块顶部论证 (Runner 容器生命周期
与 SSE 流不兼容)。详见 project docs
与 server/agents/core/events.py 中 CODING_PROGRESS / AWAITING_PR_REVIEW /
CONFLICT_CHECK 三常量上方的 implementation 决策注释块 (Task 5 产出)。
"""

from __future__ import annotations

import structlog

from chat.models import CodingSession, Message

logger = structlog.get_logger(__name__)


async def store_coding_complete_to_message(
    coding_session: CodingSession, branch_url: str = "",
) -> None:
    """编码完成时，将 PR 结果写入关联 Message.metadata。

    Args:
        coding_session: CodingSession 实例。
        branch_url: 分支 URL（skip PR 场景下提供，per contract）。
    """
    if not coding_session.message_id:
        logger.warning("coding_complete_no_message", session_id=str(coding_session.id))
        return

    msg = await Message.objects.filter(id=coding_session.message_id).afirst()
    if msg is None:
        return

    metadata = msg.metadata or {}
    metadata["codingResult"] = {
        "sessionId": str(coding_session.id),
        "status": "completed",
        "prUrl": coding_session.pr_url,
        "branchUrl": branch_url,
        "branchName": coding_session.branch_name,
        "modifiedFilesCount": len(coding_session.affected_files) if coding_session.affected_files else 0,
    }
    msg.metadata = metadata
    await msg.asave(update_fields=["metadata"])
    logger.info("coding_complete_stored", session_id=str(coding_session.id))


async def store_coding_failed_to_message(coding_session: CodingSession) -> None:
    """编码失败时，将错误信息写入关联 Message.metadata。"""
    if not coding_session.message_id:
        logger.warning("coding_failed_no_message", session_id=str(coding_session.id))
        return

    msg = await Message.objects.filter(id=coding_session.message_id).afirst()
    if msg is None:
        return

    metadata = msg.metadata or {}
    metadata["codingError"] = {
        "sessionId": str(coding_session.id),
        "status": "failed",
        "errorMessage": coding_session.error_message,
    }
    msg.metadata = metadata
    await msg.asave(update_fields=["metadata"])
    logger.info("coding_failed_stored", session_id=str(coding_session.id))
