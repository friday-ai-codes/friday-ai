"""chat 会话实时同步广播（WebSocket）。

把会话级事件（新建 / 状态变更 / 新消息）通过 channel layer ``group_send`` 推给所有
**有权可见**该会话的在线客户端，使「项目共享对话」在多用户间实时同步：
别人发起/排队中(running)/完成的会话与新消息，参与者无需刷新即可看到。

分组策略（``_target_groups``）：
- ``chat_conv_{id}``：正在查看该会话的客户端（按需订阅，预留）。
- ``chat_user_{owner_id}``：会话创建者本人（其个人/共享会话在任意页签实时一致）。
- ``chat_project_{project_id}``：仅当 ``visibility=shared`` 且绑定项目时——项目成员可见。

约定：
- best-effort，**绝不反噬主流程**（异常吞掉，仅采样日志）。
- 必须从 **async 主事件循环** 调用（与 ``NotificationService`` 同款），保证 in-memory
  channel layer 在开发态也能正确投递（worker 线程经 async_to_sync 会跨 loop 丢消息）。
- 广播负载由 ``ConversationListSerializer`` 产出，与 REST 列表同构；为避免 async 上下文
  触发同步 ORM，统一在本模块内用 ``select_related("created_by")`` 重新取一次会话。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from channels.layers import get_channel_layer

from chat.models import Conversation

logger = structlog.get_logger(__name__)


def chat_user_group(user_id: Any) -> str:
    """会话创建者专属分组（个人 + 自建共享会话事件）。"""
    return f"chat_user_{user_id}"


def chat_project_group(project_id: Any) -> str:
    """项目共享分组（shared 会话事件按项目广播给成员）。"""
    return f"chat_project_{project_id}"


def chat_conv_group(conversation_id: Any) -> str:
    """单会话分组（正在查看该会话的客户端按需订阅）。"""
    return f"chat_conv_{conversation_id}"


def _target_groups(conversation: Conversation) -> list[str]:
    groups: list[str] = [chat_conv_group(conversation.id)]
    owner_id = getattr(conversation, "created_by_id", None)
    if owner_id:
        groups.append(chat_user_group(owner_id))
    if (
        getattr(conversation, "visibility", Conversation.Visibility.PERSONAL)
        == Conversation.Visibility.SHARED
        and getattr(conversation, "bound_project_id", None)
    ):
        groups.append(chat_project_group(conversation.bound_project_id))
    return groups


async def _aget(conversation_id: Any) -> Conversation | None:
    # select_related("created_by") 预取创建者，避免序列化时在 async 上下文触发同步 ORM。
    return (
        await Conversation.objects.select_related("created_by")
        .filter(id=conversation_id)
        .afirst()
    )


async def abroadcast_conversation(conversation_id: Any, *, event: str = "upserted") -> None:
    """广播会话 upsert（含最新 status/title），让其他参与者列表实时刷新。"""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    started = time.perf_counter()
    try:
        conv = await _aget(conversation_id)
        if conv is None:
            return
        from chat.serializers import ConversationListSerializer

        payload = dict(ConversationListSerializer(conv).data)
        message = {"type": "chat.conversation", "event": event, "conversation": payload}
        for group in _target_groups(conv):
            await channel_layer.group_send(group, message)
        logger.info(
            "chat_realtime_conversation_broadcast",
            conversation_id=str(conversation_id),
            event=event,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component="chat_realtime",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬主流程
        logger.warning(
            "chat_realtime_conversation_broadcast_failed",
            conversation_id=str(conversation_id),
            error=str(exc),
            category="sampling",
            component="chat_realtime",
        )


async def abroadcast_stream(conversation: Conversation, sse_payload: dict) -> None:
    """把一条 SSE 流事件镜像广播给旁观者（逐 token 打字机）。

    仅 ``visibility=shared`` 的会话才镜像（个人会话无旁观者，省带宽）。负载与 REST/SSE
    完全同构（``{"type": ..., **event.data}``），前端旁观者直接喂给同一套 ``handleSSEEvent``
    渲染，与发起者所见一致。只投递到会话/项目分组（发起者本人靠 SSE，前端按 abortController 去回声）。
    """
    if getattr(conversation, "visibility", None) != Conversation.Visibility.SHARED:
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        groups = [chat_conv_group(conversation.id)]
        if getattr(conversation, "bound_project_id", None):
            groups.append(chat_project_group(conversation.bound_project_id))
        evt = {
            "type": "chat.stream",
            "conversation_id": str(conversation.id),
            "payload": sse_payload,
        }
        for group in groups:
            await channel_layer.group_send(group, evt)
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬主流程
        logger.warning(
            "chat_realtime_stream_broadcast_failed",
            conversation_id=str(getattr(conversation, "id", "")),
            error=str(exc),
            category="sampling",
            component="chat_realtime",
        )


async def abroadcast_message(conversation_id: Any, message: dict) -> None:
    """广播一条新消息（用户提问 / AI 回复），并带上会话最新状态。"""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        conv = await _aget(conversation_id)
        if conv is None:
            return
        evt = {
            "type": "chat.message",
            "conversation_id": str(conversation_id),
            "conversation_status": conv.status,
            "message": message,
        }
        for group in _target_groups(conv):
            await channel_layer.group_send(group, evt)
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬主流程
        logger.warning(
            "chat_realtime_message_broadcast_failed",
            conversation_id=str(conversation_id),
            error=str(exc),
            category="sampling",
            component="chat_realtime",
        )
