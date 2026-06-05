"""Feishu notification node."""

import httpx

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node


@register_node
class NotifyFeishuNode(BaseNode):
    """飞书通知节点

    发送消息到飞书机器人或用户。
    """

    node_type = "notify_feishu"
    display_name = "飞书通知"
    description = "发送消息到飞书"
    icon = "message-square"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "title": "Webhook URL",
                "description": "飞书机器人 Webhook 地址",
            },
            "message_type": {
                "type": "string",
                "title": "消息类型",
                "enum": ["text", "post", "interactive"],
                "default": "text",
            },
            "content": {
                "type": "string",
                "title": "消息内容",
                "description": "文本消息内容，支持模板变量",
            },
            "title": {
                "type": "string",
                "title": "标题",
                "description": "富文本消息标题（仅 post 类型）",
                "default": "",
            },
            "at_all": {
                "type": "boolean",
                "title": "@所有人",
                "default": False,
            },
            "at_users": {
                "type": "array",
                "title": "@指定用户",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["webhook_url", "content"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        webhook_url = context.render_template(config.get("webhook_url", ""))
        message_type = config.get("message_type", "text")
        content = context.render_template(config.get("content", ""))
        title = context.render_template(config.get("title", ""))
        at_all = config.get("at_all", False)

        if not webhook_url or not content:
            return NodeResult(
                status="failed",
                error="Webhook URL 和消息内容不能为空",
                next_handle="error",
            )

        try:
            payload = self._build_message_payload(message_type, content, title, at_all)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    timeout=30,
                )

                response_data = response.json()

                if response_data.get("code") == 0:
                    return NodeResult(
                        status="completed",
                        output={
                            "success": True,
                            "message_type": message_type,
                            "response": response_data,
                        },
                        next_handle="default",
                    )
                else:
                    return NodeResult(
                        status="failed",
                        error=f"飞书 API 错误: {response_data.get('msg', 'Unknown error')}",
                        next_handle="error",
                    )

        except Exception as e:
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )

    def _build_message_payload(
        self,
        message_type: str,
        content: str,
        title: str,
        at_all: bool,
    ) -> dict:
        """构建飞书消息体"""
        if message_type == "text":
            text = content
            if at_all:
                text = f'<at user_id="all">所有人</at> {text}'
            return {
                "msg_type": "text",
                "content": {"text": text},
            }

        elif message_type == "post":
            return {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": title,
                            "content": [[{"tag": "text", "text": content}]],
                        }
                    }
                },
            }

        elif message_type == "interactive":
            return {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": title or "通知"},
                    },
                    "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": content}}],
                },
            }

        return {"msg_type": "text", "content": {"text": content}}


class MCPDeployNode(BaseNode):
    """MCP 部署节点 [未实现]

    触发 MCP (Model Context Protocol) 服务部署。
    """

    node_type = "mcp_deploy"
    display_name = "MCP 部署"
    description = "触发 MCP 服务部署"
    icon = "cloud-upload"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "mcp_server_url": {
                "type": "string",
                "title": "MCP 服务地址",
                "description": "MCP 服务器的 API 地址",
            },
            "service_name": {
                "type": "string",
                "title": "服务名称",
                "description": "要部署的服务名称",
            },
            "environment": {
                "type": "string",
                "title": "环境",
                "enum": ["development", "staging", "production"],
                "default": "development",
            },
            "version": {
                "type": "string",
                "title": "版本",
                "description": "要部署的版本号，支持模板变量",
                "default": "latest",
            },
            "config_overrides": {
                "type": "object",
                "title": "配置覆盖",
                "description": "部署时的配置覆盖",
                "default": {},
            },
            "wait_for_completion": {
                "type": "boolean",
                "title": "等待完成",
                "description": "是否等待部署完成",
                "default": True,
            },
            "timeout": {
                "type": "integer",
                "title": "超时(秒)",
                "default": 300,
                "minimum": 30,
                "maximum": 1800,
            },
        },
        "required": ["mcp_server_url", "service_name"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        mcp_server_url = context.render_template(config.get("mcp_server_url", ""))
        service_name = context.render_template(config.get("service_name", ""))
        environment = config.get("environment", "development")
        version = context.render_template(config.get("version", "latest"))
        config_overrides = config.get("config_overrides", {})
        wait_for_completion = config.get("wait_for_completion", True)
        timeout = config.get("timeout", 300)

        if not mcp_server_url or not service_name:
            return NodeResult(
                status="failed",
                error="MCP 服务地址和服务名称不能为空",
                next_handle="error",
            )

        try:
            # Trigger deployment
            deploy_result = await self._trigger_deployment(
                mcp_server_url=mcp_server_url,
                service_name=service_name,
                environment=environment,
                version=version,
                config_overrides=config_overrides,
                wait_for_completion=wait_for_completion,
                timeout=timeout,
            )

            if deploy_result.get("success"):
                return NodeResult(
                    status="completed",
                    output=deploy_result,
                    next_handle="default",
                )
            else:
                return NodeResult(
                    status="failed",
                    error=deploy_result.get("error", "Deployment failed"),
                    next_handle="error",
                )

        except Exception as e:
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )

    async def _trigger_deployment(
        self,
        mcp_server_url: str,
        service_name: str,
        environment: str,
        version: str,
        config_overrides: dict,
        wait_for_completion: bool,
        timeout: int,
    ) -> dict:
        """触发 MCP 部署"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{mcp_server_url}/api/deploy",
                    json={
                        "service": service_name,
                        "environment": environment,
                        "version": version,
                        "config": config_overrides,
                    },
                    timeout=timeout,
                )

                if response.status_code == 200:
                    return {
                        "success": True,
                        "deployment_id": response.json().get("deployment_id"),
                        "service": service_name,
                        "environment": environment,
                        "version": version,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                    }

        except httpx.TimeoutException:
            return {"success": False, "error": f"Deployment timeout ({timeout}s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}
