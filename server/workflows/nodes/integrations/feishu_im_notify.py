"""飞书 IM 通知节点（Open Platform）。

区别于基于 webhook 的 `notify_feishu`：本节点走项目飞书 App 的 IM 能力
（`FeishuIMClient`），可显式选择**通知群聊**或**通知个人**（open_id / user_id），
支持纯文本或交互卡片。用于把方案/编码结果等推送给指定对象，便于与生成/编码节点解耦。
"""

from typing import Any

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
class NotifyFeishuIMNode(BaseNode):
    """飞书通知 (IM) 节点

    通过项目飞书 App 向群聊或个人发送消息（文本 / 卡片）。
    """

    node_type = "notify_feishu_im"
    display_name = "飞书通知(IM)"
    description = "通过飞书 App 向群聊或个人发送通知"
    icon = "send"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "receive_id_type": {
                "type": "string",
                "title": "接收方类型",
                "enum": ["chat_id", "open_id", "user_id"],
                "default": "chat_id",
                "description": "chat_id=群聊；open_id/user_id=个人",
            },
            "receive_id": {
                "type": "string",
                "title": "接收方 ID",
                "description": "群聊 ID 或用户 open_id/user_id，支持模板变量",
            },
            "message_type": {
                "type": "string",
                "title": "消息形式",
                "enum": ["text", "card"],
                "default": "text",
            },
            "title": {
                "type": "string",
                "title": "卡片标题",
                "description": "仅卡片形式生效",
                "default": "通知",
            },
            "content": {
                "type": "string",
                "title": "消息内容",
                "description": "文本或卡片正文（卡片支持 Markdown），支持模板变量",
            },
        },
        "required": ["receive_id", "content"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        receive_id_type = config.get("receive_id_type", "chat_id")
        receive_id = context.render_template(config.get("receive_id", "")).strip()
        message_type = config.get("message_type", "text")
        title = context.render_template(config.get("title", "通知")).strip() or "通知"
        content = context.render_template(config.get("content", ""))

        if not receive_id or not content:
            return NodeResult(
                status="failed",
                error="接收方 ID 和消息内容不能为空",
                next_handle="error",
            )
        if receive_id_type not in ("chat_id", "open_id", "user_id"):
            return NodeResult(
                status="failed",
                error="接收方类型必须是 chat_id / open_id / user_id",
                next_handle="error",
            )

        project = await self._resolve_project(context)

        try:
            from services.feishu_im import create_feishu_im_client_for_project

            client = await create_feishu_im_client_for_project(project)

            # 群聊场景：发送前确保 Bot 已在群内。飞书要求机器人必须是群成员才能发消息，
            # 否则返回 "Bot/User can NOT be out of the chat"。原生自动建群（group_type=auto）
            # 不保证把插件机器人拉进群，这里幂等补一次加入（已在群内则直接通过）。
            if receive_id_type == "chat_id":
                join = await client.ensure_bot_in_chat(receive_id)
                if not join.get("success"):
                    return NodeResult(
                        status="failed",
                        error=(
                            "飞书 IM 通知失败: Bot 不在群聊中且自动加入失败"
                            f"（{join.get('error') or '未知原因'}）"
                        ),
                        next_handle="error",
                    )

            if message_type == "card":
                card = self._build_card(title, content)
                message_id = await client.send_card(
                    receive_id=receive_id,
                    receive_id_type=receive_id_type,
                    card=card,
                )
            else:
                result = await client.send_message(
                    receive_id=receive_id,
                    receive_id_type=receive_id_type,
                    msg_type="text",
                    content={"text": content},
                )
                message_id = (
                    result.get("data", {}).get("message_id", "")
                    if isinstance(result, dict)
                    else ""
                )

            return NodeResult(
                status="completed",
                output={
                    "success": True,
                    "message_id": message_id,
                    "receive_id": receive_id,
                    "receive_id_type": receive_id_type,
                },
                next_handle="default",
            )
        except Exception as e:
            return NodeResult(
                status="failed",
                error=f"飞书 IM 通知失败: {e}",
                next_handle="error",
            )

    def _build_card(self, title: str, content: str) -> dict[str, Any]:
        """构建最小交互卡片（lark_md 正文）。"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            ],
        }

    async def _resolve_project(self, context: ExecutionContext) -> Any:
        if not context.workflow_execution:
            return None
        try:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related("workflow__space").aget(
                id=context.workflow_execution.id
            )
            return we.workflow.space if we.workflow else None
        except Exception:
            return None
