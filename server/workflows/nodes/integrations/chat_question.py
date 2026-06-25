"""群聊提问节点。

GroupChatQuestionNode: 发送提问卡片到群聊并挂起工作流等待回答。
卡片回调由 chat_question_callback.py 处理。
"""

from datetime import timedelta
from typing import Any, ClassVar

import structlog
from django.utils import timezone

from feishu.cards.chat_question_card import build_chat_question_card
from services.feishu_im import FeishuIMClient, create_feishu_im_client_for_project
from workflows.models.execution import WorkflowEventSubscription
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


async def _get_feishu_credentials(context: ExecutionContext) -> tuple[str, str]:
    """从工作流执行上下文获取飞书凭证。

    Args:
        context: 执行上下文

    Returns:
        (app_id, app_secret) 元组

    Raises:
        ValueError: 无法获取凭证
    """
    project = None
    if context.workflow_execution:
        from workflows.models import WorkflowExecution

        we = await WorkflowExecution.objects.select_related(
            "workflow__space"
        ).aget(id=context.workflow_execution.id)
        project = we.workflow.space if we.workflow else None

    client = await create_feishu_im_client_for_project(project)
    return (client.app_id, client.app_secret)


@register_node
class GroupChatQuestionNode(BaseNode):
    """群聊提问节点。

    向指定群聊发送提问卡片，然后进入 waiting_event 状态。
    当用户通过卡片回答后，回调处理器恢复工作流。

    Flow:
    1. 从 config 提取 question、options、chat_id
    2. 构建提问卡片
    3. 通过 FeishuIMClient 发送到群聊
    4. 返回 waiting_event（工作流挂起）
    5. 用户回答后，chat_question_callback 恢复工作流
    """

    node_type: ClassVar[str] = "group_chat_question"
    display_name: ClassVar[str] = "群聊提问"
    description: ClassVar[str] = "向群聊发送提问卡片，等待用户回答后继续"
    icon: ClassVar[str] = "help-circle"
    category: ClassVar[NodeCategory] = NodeCategory.INTEGRATION
    execution_mode: ClassVar[str] = "server_local"
    is_blocking: ClassVar[bool] = True

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "title": "群聊 ID",
                "description": "目标群聊 ID（支持模板变量）",
            },
            "question": {
                "type": "string",
                "title": "问题",
                "description": "提问内容文本",
            },
            "options": {
                "type": "array",
                "title": "选项",
                "description": "可选的快捷回答选项",
                "items": {"type": "string"},
            },
            "work_item_name": {
                "type": "string",
                "title": "工作项名称",
                "description": "显示在卡片标题中的工作项名称",
                "default": "",
            },
            "mention_user_id": {
                "type": "string",
                "title": "@mention 用户 ID",
                "description": "要 @mention 的飞书用户 open_id（可选）",
            },
            "max_rounds": {
                "type": "integer",
                "title": "最大追问轮次",
                "description": "多轮追问的最大轮次（1 表示单轮，最多 5 轮）",
                "default": 1,
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": ["chat_id", "question"],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="输入",
            port_type=PortType.OBJECT,
            required=True,
            description="上游节点输出",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="answered",
            label="已回复",
            port_type=PortType.OBJECT,
            description="用户回复成功后的输出",
        ),
        NodePort(
            name="timeout",
            label="超时",
            port_type=PortType.OBJECT,
            description="等待超时的输出",
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="发送失败的输出",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行群聊提问节点。

        1. 提取配置
        2. 构建并发送提问卡片
        3. 返回 waiting_event
        """
        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
        )

        config = context.node_config

        # 提取配置（支持模板变量）
        chat_id = context.render_template(config.get("chat_id", "")).strip()
        question = context.render_template(config.get("question", "")).strip()
        options: list[str] = config.get("options") or []
        work_item_name = context.render_template(
            config.get("work_item_name", "")
        ).strip()
        mention_user_id: str | None = config.get("mention_user_id") or None
        max_rounds: int = min(max(int(config.get("max_rounds", 1)), 1), 5)

        if not chat_id:
            return NodeResult(
                status="failed",
                error="缺少 chat_id 配置",
                next_handle="error",
            )

        if not question:
            return NodeResult(
                status="failed",
                error="缺少 question 配置",
                next_handle="error",
            )

        log.info(
            "chat_question_start",
            chat_id=chat_id,
            question_preview=question[:50],
            options_count=len(options),
        )

        # 构建提问卡片
        card = build_chat_question_card(
            question=question,
            execution_id=context.execution_id,
            node_id=context.node_id,
            options=options if options else None,
            work_item_name=work_item_name,
            mention_user_id=mention_user_id,
        )

        # 发送卡片到群聊
        try:
            app_id, app_secret = await _get_feishu_credentials(context)
            im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)

            message_id = await im_client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

            log.info(
                "chat_question_card_sent",
                chat_id=chat_id,
                message_id=message_id,
            )

        except Exception as e:
            log.exception("chat_question_send_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=f"发送提问卡片失败: {e}",
                next_handle="error",
            )

        # 创建事件订阅记录（用于超时检查）
        if context.workflow_execution and context.node_execution:
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type="ChatQuestionCallback",
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(minutes=30),
                timeout_action="fail",
            )

        # 返回 waiting_event，等待回调恢复
        return NodeResult(
            status="waiting_event",
            output={
                "message_id": message_id,
                "question": question,
                "chat_id": chat_id,
                "options": options,
                "work_item_name": work_item_name,
                "mention_user_id": mention_user_id or "",
                "max_rounds": max_rounds,
                "current_round": 1,
                "rounds": [],
            },
        )
