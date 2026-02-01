"""FeishuEventHandler for Feishu project event triggering."""
from typing import TYPE_CHECKING, ClassVar
import structlog
from asgiref.sync import sync_to_async
from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.registry import register_handler
if TYPE_CHECKING:
 from workflows.models import Workflow
logger = structlog.get_logger
@register_handler
class FeishuEventHandler(TriggerHandler):
 """飞书项目事件触发处理器
 处理来自飞书项目 Webhook 的事件，匹配 WorkflowTrigger 配置。
 TriggerContext 需要:
 - raw_payload: 飞书 Webhook 原始 payload
 - event_type: 飞书事件类型 (如 "WorkitemCreateEvent")
 - project: 关联的 Project 实例
 - metadata["token"]: 飞书 Webhook token (可选，用于验证)
 """
 trigger_type: ClassVar[str] = "feishu"
 display_name: ClassVar[str] = "飞书事件"
 description: ClassVar[str] = "飞书项目 Webhook 事件触发"
 async def validate(self, context: TriggerContext) -> list[str]:
 """验证飞书事件触发上下文
 检查:
 1. 必须有 event_type
 2. 必须有 project
 3. 验证 webhook token (如果项目配置了)
 """
 errors =
 if not context.event_type:
 errors.append("缺少必需字段: event_type")
 if not context.project:
 errors.append("缺少必需字段: project")
 return errors
 # 验证 webhook token
 received_token = context.metadata.get("token", "")
 expected_token = getattr(context.project, "feishu_webhook_token", None)
 if expected_token:
 from feishu.client import verify_webhook_token
 if not verify_webhook_token(received_token, expected_token):
 errors.append("飞书 Webhook Token 验证失败")
 logger.warning(
 "feishu_token_invalid",
 project_id=str(context.project.id),
 )
 return errors
 async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
 """查找匹配飞书事件的工作流
 通过 WorkflowTrigger 配置匹配事件类型和过滤条件。
 支持一对多：一个事件可触发多个工作流。
 """
 if not context.event_type or not context.project:
 return
 from workflows.models import WorkflowTrigger
 # 查找该项目下所有匹配事件类型的活跃触发器
 triggers = await sync_to_async(
 lambda: list(
 WorkflowTrigger.objects.filter(
 event_type=context.event_type,
 is_active=True,
 workflow__is_active=True,
 workflow__project=context.project,
 ).select_related("workflow")
 )
 )
 # 使用 matches_event 进行详细过滤
 workflows =
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
 project_id=str(context.project.id),
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
 "project_id": str(context.project.id) if context.project else None,
 }
