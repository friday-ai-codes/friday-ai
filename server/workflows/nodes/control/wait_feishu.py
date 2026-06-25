"""等待飞书字段变更节点"""

from django.utils import timezone

from workflows.conditions import evaluate_condition
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


@register_node
class WaitForFeishuFieldNode(BaseNode):
    """等待飞书字段变更节点

    暂停工作流执行，等待飞书工作项字段变更为期望值后继续。
    """

    node_type = "wait_feishu_field"
    display_name = "等待飞书字段"
    description = "暂停执行，等待飞书工作项字段变更为期望值后继续"
    icon = "clock"
    category = NodeCategory.CONTROL
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "支持变量引用，如 {{trigger.work_item_id}}",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "default": "story",
            },
            "project_key": {
                "type": "string",
                "title": "空间标识",
                "description": "飞书项目 Key，支持变量引用",
            },
            "condition": {
                "type": "object",
                "title": "等待条件",
                "description": "字段条件表达式（JSON 格式）",
            },
            "timeout_seconds": {
                "type": "integer",
                "title": "超时时间(秒)",
                "description": "0 表示使用默认值(7天)，-1 表示不超时",
                "default": 0,
            },
            "timeout_action": {
                "type": "string",
                "title": "超时动作",
                "enum": ["fail", "skip", "retry"],
                "default": "fail",
            },
        },
        "required": ["work_item_id", "condition"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="matched", label="条件匹配", port_type=PortType.OBJECT),
        NodePort(name="timeout", label="超时", port_type=PortType.OBJECT),
        NodePort(name="skipped", label="跳过", port_type=PortType.OBJECT),
    ]

    is_blocking = True

    # 默认超时 7 天
    DEFAULT_TIMEOUT_SECONDS = 7 * 24 * 60 * 60

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        # 解析配置（支持变量引用）
        work_item_id = context.render_template(config.get("work_item_id", ""))
        work_item_type = config.get("work_item_type", "story")
        project_key = context.render_template(config.get("project_key", ""))
        condition = config.get("condition", {})
        timeout_seconds = config.get("timeout_seconds", 0)
        timeout_action = config.get("timeout_action", "fail")

        if not work_item_id:
            return NodeResult(
                status="failed",
                error="work_item_id 不能为空",
            )

        if not project_key:
            # 尝试从上下文获取
            project_key = context.workflow_context.get("project_key", "")
            if not project_key:
                return NodeResult(
                    status="failed",
                    error="project_key 不能为空",
                )

        # 检查当前字段值是否已满足条件（可能条件已经满足）
        current_value = await self._fetch_current_field_value(
            context, project_key, work_item_id, work_item_type
        )

        if current_value and evaluate_condition(condition, current_value):
            return NodeResult(
                status="completed",
                output={
                    "matched": True,
                    "field_value": current_value,
                    "wait_duration": 0,
                },
                next_handle="matched",
            )

        # 计算超时时间
        timeout_at = None
        if timeout_seconds == -1:
            timeout_at = None
        elif timeout_seconds == 0:
            timeout_at = timezone.now() + timezone.timedelta(
                seconds=self.DEFAULT_TIMEOUT_SECONDS
            )
        else:
            timeout_at = timezone.now() + timezone.timedelta(seconds=timeout_seconds)

        # 创建事件订阅
        subscription_data = {
            "work_item_id": work_item_id,
            "work_item_type": work_item_type,
            "project_key": project_key,
            "condition": condition,
            "timeout_seconds": timeout_seconds,
            "timeout_action": timeout_action,
            "created_at": timezone.now().isoformat(),
        }

        # 创建订阅记录
        await WorkflowEventSubscription.objects.acreate(
            workflow_execution=context.workflow_execution,
            node_execution=context.node_execution,
            event_type="WorkitemUpdateEvent",  # 主要监听字段更新事件
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
            condition_expression=condition,
            timeout_at=timeout_at,
            timeout_action=timeout_action,
        )

        # 返回等待事件状态
        return NodeResult(
            status="waiting_event",
            output=subscription_data,
        )

    async def _fetch_current_field_value(
        self,
        context: ExecutionContext,
        project_key: str,
        work_item_id: str,
        work_item_type: str,
    ) -> dict | None:
        """获取当前字段值（用于检查条件是否已满足）"""
        try:
            from feishu.client import create_feishu_client_for_project
            from projects.models import Space

            # 获取空间
            project = await Space.objects.filter(feishu_project_key=project_key).afirst()

            if not project:
                return None

            # 获取工作项详情
            client = create_feishu_client_for_project(project)
            work_item = await client.get_work_item(
                project_key=project_key,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
            )

            return work_item.fields if work_item else None

        except Exception as e:
            import structlog

            logger = structlog.get_logger()
            logger.warning("fetch_field_value_error", error=str(e))
            return None
