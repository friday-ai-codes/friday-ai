"""Human approval node."""
import structlog
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger
@register_node
class HumanApprovalNode(BaseNode):
 """人工审批节点
 暂停工作流执行，等待人工审批。
 """
 node_type = "human_approval"
 display_name = "人工审批"
 description = "暂停执行，等待人工审批通过后继续"
 icon = "user-check"
 category = NodeCategory.CONTROL
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "title": {
 "type": "string",
 "title": "审批标题",
 "default": "请审批",
 },
 "description": {
 "type": "string",
 "title": "审批说明",
 "default": "",
 },
 "approvers": {
 "type": "array",
 "title": "审批人",
 "description": "指定审批人的用户 ID 列表，为空则项目成员均可审批",
 "items": {"type": "string"},
 "default":,
 },
 "require_all": {
 "type": "boolean",
 "title": "需要所有人审批",
 "description": "是否需要所有指定审批人都通过",
 "default": False,
 },
 "timeout_hours": {
 "type": "integer",
 "title": "超时时间(小时)",
 "description": "超时后自动拒绝，0 表示不超时",
 "default": 0,
 },
 "notification": {
 "type": "object",
 "title": "通知配置",
 "properties": {
 "enabled": {"type": "boolean", "default": True},
 "channels": {
 "type": "array",
 "items": {"type": "string", "enum": ["feishu", "email"]},
 "default": ["feishu"],
 },
 },
 },
 "show_data": {
 "type": "array",
 "title": "展示数据",
 "description": "在审批页面展示的输入数据字段",
 "items": {"type": "string"},
 "default":,
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="approved", label="通过", port_type=PortType.OBJECT),
 NodePort(name="rejected", label="拒绝", port_type=PortType.OBJECT),
 ]
 is_blocking = True
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 构建审批请求
 approval_request = {
 "title": context.render_template(config.get("title", "请审批")),
 "description": context.render_template(config.get("description", "")),
 "approvers": config.get("approvers", ),
 "require_all": config.get("require_all", False),
 "timeout_hours": config.get("timeout_hours", 0),
 "display_data": self._extract_display_data(
 context.input_data,
 config.get("show_data", ),
 ),
 "requested_at": context.workflow_context.get("started_at"),
 }
 # 发送通知
 notification_config = config.get("notification", {})
 if notification_config.get("enabled", True):
 await self._send_notifications(
 context,
 approval_request,
 notification_config.get("channels", ["feishu"]),
 )
 # 返回等待审批状态
 return NodeResult(
 status="waiting_approval",
 output=approval_request,
 )
 def _extract_display_data(self, input_data: dict, fields: list) -> dict:
 """提取要展示的数据"""
 if not fields:
 return input_data
 return {k: input_data.get(k) for k in fields if k in input_data}
 async def _send_notifications(
 self,
 context: ExecutionContext,
 approval_request: dict,
 channels: list[str],
 ) -> None:
 """发送审批通知"""
 logger.warning(
 "approval_notification_not_implemented",
 channels=channels,
 node_name=context.node_config.get("title", ""),
 )
