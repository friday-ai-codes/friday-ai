"""FeishuEventHandler for Feishu space event triggering."""

from typing import TYPE_CHECKING, ClassVar

import structlog

from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.registry import register_handler

if TYPE_CHECKING:
    from workflows.models import Workflow

logger = structlog.get_logger()


@register_handler
class FeishuEventHandler(TriggerHandler):
    """飞书项目事件触发处理器

    处理来自飞书项目 Webhook 的事件，匹配 WorkflowTrigger 配置。

    TriggerContext 需要:
    - raw_payload: 飞书 Webhook 原始 payload
    - event_type: 飞书事件类型 (如 "WorkitemCreateEvent")
    - project: 关联的 Space 实例
    - metadata["token"]: 飞书 Webhook token (可选，用于验证)
    """

    trigger_type: ClassVar[str] = "feishu"
    display_name: ClassVar[str] = "飞书事件"
    description: ClassVar[str] = "飞书项目 Webhook 事件触发"

    async def validate(self, context: TriggerContext) -> list[str]:
        """验证飞书事件触发上下文

        两种路由模式：
        - **专属端点模式**（``metadata["trigger_token"]`` 存在）：URL 中的 token 即路由
          标识 + 鉴权凭证，不再要求 event_type，也不再校验 header token。
        - **旧版共享端点模式**：保持原行为——要求 event_type + space，并按 project 的
          ``feishu_webhook_token`` 校验 header token（向后兼容）。
        """
        errors = []

        trigger_token = context.metadata.get("trigger_token")

        if not trigger_token and not context.event_type:
            errors.append("缺少必需字段: event_type")

        if not context.space:
            errors.append("缺少必需字段: space")
            return errors

        # 专属端点模式：token 本身就是凭证，跳过 header token 校验
        if trigger_token:
            return errors

        # 旧版共享端点：验证 webhook token
        received_token = context.metadata.get("token", "")
        expected_token = getattr(context.space, "feishu_webhook_token", None)

        if expected_token:
            from feishu.client import verify_webhook_token

            if not verify_webhook_token(received_token, expected_token):
                errors.append("飞书 Webhook Token 验证失败")
                logger.warning(
                    "feishu_token_invalid",
                    space_id=str(context.space.id),
                )

        return errors

    async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
        """查找要触发的工作流

        - **专属端点模式**：``metadata["trigger_token"]`` 直接定位唯一 WorkflowTrigger，
          命中即返回其工作流，不做任何 event_type / filter 匹配。
        - **旧版共享端点模式**：按 event_type + project 匹配 WorkflowTrigger，并用
          ``matches_event()`` 做过滤（仅对仍保留 event_type 的存量触发器生效）。
        """
        from workflows.models import WorkflowTrigger

        trigger_token = context.metadata.get("trigger_token")
        if trigger_token:
            trigger = (
                await WorkflowTrigger.objects.filter(
                    token=trigger_token,
                    is_active=True,
                    workflow__is_active=True,
                )
                .select_related("workflow")
                .afirst()
            )
            if trigger is None:
                logger.debug("feishu_trigger_token_unmatched")
                return []
            logger.debug(
                "feishu_trigger_token_matched",
                trigger_id=str(trigger.id),
                workflow_id=str(trigger.workflow.id),
            )
            return [trigger.workflow]

        # 旧版共享端点：按事件类型匹配
        if not context.event_type or not context.space:
            return []

        triggers = [
            t async for t in WorkflowTrigger.objects.filter(
                event_type=context.event_type,
                is_active=True,
                workflow__is_active=True,
                workflow__space=context.space,
            ).select_related("workflow")
        ]

        # 使用 matches_event() 进行详细过滤
        workflows = []
        for trigger in triggers:
            if trigger.matches_event(context.event_type, context.raw_payload):
                workflows.append(trigger.workflow)
                logger.debug(
                    "trigger_matched",
                    trigger_id=str(trigger.id),
                    workflow_id=str(trigger.workflow.id),
                    event_type=context.event_type,
                )

        if not workflows:
            logger.debug(
                "no_triggers_matched",
                event_type=context.event_type,
                space_id=str(context.space.id),
                trigger_count=len(triggers),
            )

        return workflows

    async def prepare_input(
        self,
        context: TriggerContext,
        workflow: "Workflow",
    ) -> dict:
        """准备飞书事件触发的输入数据"""
        return {
            "trigger_type": context.trigger_type,
            "raw_payload": context.raw_payload,
            "event_type": context.event_type,
            "space_id": str(context.space.id) if context.space else None,
        }
