"""子步骤 WebSocket 广播 handler。

接收 sub_step_updated signal，通过 channel_layer 广播到 execution_{workflow_execution_id} 组，
WorkflowExecutionConsumer 的 workflow_event handler 转发给前端。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = structlog.get_logger()


def handle_sub_step_updated(
    sender: type,
    sub_step: Any,
    node_execution_id: uuid.UUID,
    **kwargs: Any,
) -> None:
    """广播子步骤状态变更事件到 execution_{workflow_execution_id} 组。

    通过 channel_layer.group_send 发送 workflow.event 类型消息，
    WorkflowExecutionConsumer.workflow_event() 接收后 json.dumps 整个
    event dict 发送到前端。
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        # 测试环境或未配置 channel layer 时静默跳过
        return

    # 从关联的 NodeExecution 获取进度数据和 workflow_execution_id
    from workflows.models.execution import NodeExecution

    try:
        node_exec = NodeExecution.objects.filter(id=node_execution_id).values(
            "sub_step_completed_count", "sub_step_total_count", "workflow_execution_id"
        ).first()
        if not node_exec:
            logger.warning(
                "sub_step_broadcast_skipped_no_node_exec",
                node_execution_id=str(node_execution_id),
            )
            return
        progress = {
            "completed": node_exec["sub_step_completed_count"],
            "total": node_exec["sub_step_total_count"],
        }
        workflow_execution_id = str(node_exec["workflow_execution_id"])
    except Exception:
        logger.warning(
            "sub_step_broadcast_query_failed",
            node_execution_id=str(node_execution_id),
        )
        return

    data = {
        "id": str(sub_step.id),
        "step_type": sub_step.step_type,
        "name": sub_step.name,
        "step_order": sub_step.step_order,
        "status": sub_step.status,
        "started_at": sub_step.started_at.isoformat() if sub_step.started_at else None,
        "completed_at": sub_step.completed_at.isoformat() if sub_step.completed_at else None,
        "progress": progress,
    }

    try:
        async_to_sync(channel_layer.group_send)(
            f"execution_{workflow_execution_id}",
            {
                "type": "workflow.event",
                "event": "sub_step.update",
                "node_execution_id": str(node_execution_id),
                "data": data,
            },
        )
    except Exception:
        logger.warning(
            "sub_step_broadcast_failed",
            node_execution_id=str(node_execution_id),
            step_type=sub_step.step_type,
        )
