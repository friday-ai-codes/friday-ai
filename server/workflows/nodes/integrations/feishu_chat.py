"""飞书群聊操作节点。

FetchGroupChatNode: 获取群聊 ID（从配置或工作项 API）
JoinGroupChatNode: 将 Bot 加入指定群聊（幂等）
"""

import structlog

from services.feishu_im import FeishuIMService
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


@register_node
class FetchGroupChatNode(BaseNode):
    """获取群聊 ID 节点。

    优先从配置读取 chat_id，若未配置则通过工作项 API 自动获取。
    """

    node_type = "fetch_group_chat"
    display_name = "获取群聊"
    description = "获取群聊 ID，支持手动配置或从工作项自动获取"
    icon = "message-circle"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "手动指定群聊 ID，留空则从工作项自动获取",
                "default": "",
            },
            "project_key": {
                "type": "string",
                "title": "空间 Key",
                "description": "飞书项目空间 Key（自动获取时需要）",
                "default": "",
            },
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "工作项 ID（自动获取时需要）",
                "default": "",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "工作项类型（story, task, bug 等）",
                "default": "story",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 优先从配置读取 chat_id（支持模板变量）
        chat_id = context.render_template(config.get("chat_id", "")).strip()

        if chat_id:
            log.info("chat_id_from_config", chat_id=chat_id)
            return NodeResult(
                status="completed",
                output={"chat_id": chat_id, "source": "config"},
                next_handle="default",
            )

        # 从工作项 API 获取
        project_key = context.render_template(config.get("project_key", "")).strip()
        work_item_id_str = context.render_template(config.get("work_item_id", "")).strip()
        work_item_type = config.get("work_item_type", "story")

        if not project_key or not work_item_id_str:
            log.warning("missing_work_item_params")
            return NodeResult(
                status="failed",
                error="无法获取群聊 ID：未配置 chat_id，且缺少 project_key 或 work_item_id",
                next_handle="error",
            )

        # 获取 FeishuIMService 实例
        project = None
        if context.workflow_execution:
            project = context.workflow_execution.workflow.project

        im_service = await FeishuIMService.create(project)

        try:
            work_item_id = int(work_item_id_str)
        except ValueError:
            return NodeResult(
                status="failed",
                error=f"work_item_id 格式错误: {work_item_id_str}",
                next_handle="error",
            )

        chat_info = await im_service.get_chat_id_for_work_item(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )

        if chat_info is None:
            log.warning("no_chat_found_for_work_item")
            return NodeResult(
                status="failed",
                error="无法获取群聊 ID：工作项无关联群聊",
                next_handle="error",
            )

        log.info("chat_id_from_work_item", chat_id=chat_info["chat_id"])
        return NodeResult(
            status="completed",
            output=chat_info,
            next_handle="default",
        )


@register_node
class JoinGroupChatNode(BaseNode):
    """加入群聊节点。

    调用 ensure_bot_in_chat 将 Bot 加入指定群聊，幂等操作。
    """

    node_type = "join_group_chat"
    display_name = "加入群聊"
    description = "将 Bot 加入指定群聊，已在群内时幂等成功"
    icon = "user-plus"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "目标群聊 ID，支持模板变量",
            },
        },
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 优先从配置获取 chat_id，其次从 input_data
        chat_id = context.render_template(config.get("chat_id", "")).strip()
        if not chat_id:
            chat_id = str(context.input_data.get("chat_id", "")).strip()

        if not chat_id:
            return NodeResult(
                status="failed",
                error="未提供 chat_id",
                next_handle="error",
            )

        # 获取 FeishuIMService 实例
        project = None
        if context.workflow_execution:
            project = context.workflow_execution.workflow.project

        im_service = await FeishuIMService.create(project)

        result = await im_service.ensure_bot_in_chat(chat_id)

        if result["success"]:
            log.info(
                "join_group_chat_success",
                chat_id=chat_id,
                already_member=result["already_member"],
            )
            return NodeResult(
                status="completed",
                output={
                    "chat_id": chat_id,
                    "already_member": result["already_member"],
                },
                next_handle="default",
            )

        log.warning("join_group_chat_failed", chat_id=chat_id, error=result.get("error"))
        return NodeResult(
            status="failed",
            error=result.get("error", "加入群聊失败"),
            next_handle="error",
        )
