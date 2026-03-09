"""子步骤 WebSocket 广播 handler。
接收 sub_step_updated signal，通过 channel_layer 广播到 MONITOR_GROUP，
前端 MonitorConsumer 转发给客户端。
"""
from __future__ import annotations
import uuid
from typing import Any
import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
logger = structlog.get_logger
# 与 runners/consumers.py 中的 MONITOR_GROUP 保持一致
MONITOR_GROUP = "monitor"
def handle_sub_step_updated(
 sender: type,
 sub_step: Any,
 node_execution_id: uuid.UUID,
 **kwargs: Any,
) -> None:
 """广播子步骤状态变更事件到 MONITOR_GROUP。
 通过 channel_layer.group_send 发送 monitor.event 类型消息，
 MonitorConsumer 接收后转发给前端。
 """
 channel_layer = get_channel_layer
 if channel_layer is None:
 # 测试环境或未配置 channel layer 时静默跳过
 return
 # 从关联的 NodeExecution 获取进度数据
 from workflows.models.execution import NodeExecution
 try:
 node_exec = NodeExecution.objects.filter(id=node_execution_id).values(
 "sub_step_completed_count", "sub_step_total_count"
 ).first
 progress = {
 "completed": node_exec["sub_step_completed_count"] if node_exec else 0,
 "total": node_exec["sub_step_total_count"] if node_exec else 0,
 }
 except Exception:
 progress = {"completed": 0, "total": 0}
 data = {
 "id": str(sub_step.id),
 "step_type": sub_step.step_type,
 "name": sub_step.name,
 "step_order": sub_step.step_order,
 "status": sub_step.status,
 "started_at": sub_step.started_at.isoformat if sub_step.started_at else None,
 "completed_at": sub_step.completed_at.isoformat if sub_step.completed_at else None,
 "progress": progress,
 }
 try:
 async_to_sync(channel_layer.group_send)(
 MONITOR_GROUP,
 {
 "type": "monitor.event",
 "data": {
 "event": "sub_step.update",
 "node_execution_id": str(node_execution_id),
 "data": data,
 },
 },
 )
 except Exception:
 logger.warning(
 "sub_step_broadcast_failed",
 node_execution_id=str(node_execution_id),
 step_type=sub_step.step_type,
 )
