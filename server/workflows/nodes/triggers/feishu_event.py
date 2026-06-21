"""Feishu event trigger node."""

import structlog

from workflows.nodes.base import ExecutionContext, NodePort, PortType
from workflows.nodes.registry import register_node
from workflows.nodes.triggers.base import BaseTriggerNode

logger = structlog.get_logger()


@register_node
class FeishuEventTriggerNode(BaseTriggerNode):
    """飞书事件触发节点

    纯 Webhook 入口：保存工作流后，节点会获得一个专属端点
    ``/api/feishu/webhook/<token>/``。在飞书项目的自动化规则里，把"何时触发"
    （工作项类型、状态流转、空间等条件）配好后，将 Webhook 动作指向该端点即可
    直达本工作流。

    触发时机与过滤完全由飞书侧自动化规则决定，本节点不再重复配置工作项类型、
    状态过滤、监听/排除空间等条件。
    """

    node_type = "feishu_event_trigger"
    display_name = "飞书事件触发"
    description = "通过飞书 Webhook 专属端点触发工作流"
    icon = "webhook"

    config_schema = {
        "type": "object",
        "properties": {
            # 服务端在保存工作流时回填的专属端点 token（只读展示，前端据此拼出完整 URL）。
            # 客户端传入值会在同步时被服务端权威 token 覆盖。
            "endpoint_token": {
                "type": "string",
                "title": "端点 Token",
                "description": "服务端自动生成，对应专属 Webhook 端点路径，无需手动填写",
                "default": "",
                "readOnly": True,
            },
            # 节点专属校验 token：拖入时客户端生成。飞书自动化规则的 Webhook 动作里需把
            # 该 token 放进请求（payload header.token），webhook 命中端点后还会比对此值，
            # 不匹配则拒绝——即使端点 URL 泄露，没有该 token 也无法触发（纵深防御）。
            # 留空（旧节点）则跳过校验，仅靠端点 URL 密钥。
            "verification_token": {
                "type": "string",
                "title": "校验 Token",
                "description": "节点专属校验凭证，需在飞书自动化规则里随请求发送（header.token），不匹配则拒绝触发",
                "default": "",
                "readOnly": True,
            },
        },
    }

    outputs = [
        NodePort(
            name="default",
            label="事件数据",
            port_type=PortType.OBJECT,
            description="包含 event_type, work_item_id, project_key, payload",
            schema={
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "事件类型"},
                    "work_item_id": {"type": "string", "description": "工作项 ID"},
                    "project_key": {"type": "string", "description": "飞书项目 Key"},
                    "work_item_type": {"type": "string", "description": "工作项类型"},
                    "work_item_name": {"type": "string", "description": "工作项名称"},
                    "current_status": {"type": "string", "description": "当前状态 Key"},
                    "current_status_name": {"type": "string", "description": "当前状态名称"},
                    "previous_status": {"type": "string", "description": "原状态 Key"},
                    "previous_status_name": {"type": "string", "description": "原状态名称"},
                    "payload": {"type": "object", "description": "原始事件 payload"},
                    "data": {
                        "type": "object",
                        "description": "结构化事件数据",
                        "properties": {
                            "event_type": {"type": "string"},
                            "work_item_id": {"type": "string"},
                            "project_key": {"type": "string"},
                            "work_item_type": {"type": "string"},
                            "work_item_name": {"type": "string"},
                            "current_status": {"type": "string"},
                            "current_status_name": {"type": "string"},
                            "previous_status": {"type": "string"},
                            "previous_status_name": {"type": "string"},
                        },
                    },
                },
            },
        ),
    ]

    async def parse_payload(self, context: ExecutionContext) -> dict:
        """Extract Feishu event data with flattening.

        Feishu payload: transparent passthrough with flattening.
        Critical fields: work_item_id (from id field)
        Optional fields: project_key, work_item_type, name, status info
        """
        raw_payload = context.input_data.get("raw_payload", context.input_data)
        input_data = context.input_data

        # Get event_type from multiple sources
        event_type = input_data.get("event_type") or context.trigger_data.get("event_type", "")

        # Critical: work_item_id
        work_item_id = (
            input_data.get("work_item_id")
            or context.trigger_data.get("work_item_id")
            or raw_payload.get("id")
        )
        if work_item_id:
            work_item_id = str(work_item_id)

        # Optional: project_key
        project_key = (
            input_data.get("project_key")
            or context.trigger_data.get("project_key")
            or raw_payload.get("project_key")
            or raw_payload.get("project_simple_name", "")
        )
        if not project_key:
            logger.debug("optional_field_missing", field="project_key", trigger_type=self.node_type)

        # Optional: work item details
        work_item_type = raw_payload.get("work_item_type_key", "")
        work_item_name = raw_payload.get("name", "")

        # Optional: status info (for status change events)
        cur_status = raw_payload.get("cur_work_item_status", {})
        prev_status = raw_payload.get("pre_work_item_status", {})

        current_status = cur_status.get("state_key", "")
        current_status_name = cur_status.get("name", "")
        previous_status = prev_status.get("state_key", "")
        previous_status_name = prev_status.get("name", "")

        return {
            "data": {
                "event_type": event_type,
                "work_item_id": work_item_id,
                "project_key": project_key,
                "work_item_type": work_item_type,
                "work_item_name": work_item_name,
                "current_status": current_status,
                "current_status_name": current_status_name,
                "previous_status": previous_status,
                "previous_status_name": previous_status_name,
            },
            # Backward compatibility: flat fields at root
            "event_type": event_type,
            "work_item_id": work_item_id,
            "project_key": project_key,
            "work_item_type": work_item_type,
            "work_item_name": work_item_name,
            "current_status": current_status,
            "current_status_name": current_status_name,
            "previous_status": previous_status,
            "previous_status_name": previous_status_name,
            "payload": raw_payload,  # Legacy compatibility
        }
