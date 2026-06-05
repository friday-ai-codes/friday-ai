"""Webhook trigger node."""

import structlog

from workflows.nodes.base import ExecutionContext, NodePort, PortType
from workflows.nodes.registry import register_node
from workflows.nodes.triggers.base import BaseTriggerNode

logger = structlog.get_logger()


@register_node
class WebhookTriggerNode(BaseTriggerNode):
    """Webhook 触发节点

    通过 HTTP Webhook 触发工作流执行。
    """

    node_type = "webhook_trigger"
    display_name = "Webhook 触发"
    description = "通过 HTTP Webhook 触发工作流"
    icon = "webhook"

    config_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "title": "Webhook 路径",
                "description": "自定义的 webhook 路径后缀",
                "default": "",
            },
            "method": {
                "type": "string",
                "title": "HTTP 方法",
                "enum": ["POST", "GET", "PUT"],
                "default": "POST",
            },
            "secret": {
                "type": "string",
                "title": "验证密钥",
                "description": "用于验证 webhook 请求的密钥",
                "default": "",
            },
            "response_mode": {
                "type": "string",
                "title": "响应模式",
                "enum": ["immediate", "wait"],
                "default": "immediate",
                "description": "immediate: 立即响应; wait: 等待工作流完成后响应",
            },
        },
    }

    outputs = [
        NodePort(name="default", label="Payload", port_type=PortType.OBJECT),
        NodePort(name="headers", label="Headers", port_type=PortType.OBJECT),
        NodePort(name="query", label="Query Params", port_type=PortType.OBJECT),
    ]

    async def parse_payload(self, context: ExecutionContext) -> dict:
        """Extract HTTP request info: path, method, headers, body.

        Webhook payload structure from handler:
        - body: Request body (JSON parsed)
        - headers: HTTP headers dict
        - query: Query string parameters
        - webhook_path: The matched webhook path
        """
        raw_payload = context.input_data.get("raw_payload", context.input_data)

        # Extract HTTP request components
        body = raw_payload.get("body", {}) if isinstance(raw_payload, dict) else raw_payload
        headers = context.input_data.get("headers", {})
        query = context.input_data.get("query", {})
        webhook_path = context.input_data.get("webhook_path", "")

        return {
            "data": {
                "path": webhook_path,
                "method": context.node_config.get("method", "POST"),
                "headers": headers,
                "query": query,
                "body": body,
            },
            # Backward compatibility: keep existing flat structure
            "body": body,
            "headers": headers,
            "query": query,
        }
