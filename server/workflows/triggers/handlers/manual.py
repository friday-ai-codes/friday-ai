"""ManualHandler for manual workflow triggering."""
from typing import TYPE_CHECKING, ClassVar
from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.registry import register_handler
if TYPE_CHECKING:
 from workflows.models import Workflow
@register_handler
class ManualHandler(TriggerHandler):
 """手动触发处理器
 用于用户通过 UI 或 API 手动启动工作流。
 workflow 必须在 context 中直接指定。
 """
 trigger_type: ClassVar[str] = "manual"
 display_name: ClassVar[str] = "手动触发"
 description: ClassVar[str] = "用户手动启动工作流"
 async def validate(self, context: TriggerContext) -> list[str]:
 """验证手动触发上下文
 检查:
 1. context.workflow 必须存在
 2. workflow.is_active 必须为 True
 """
 errors =
 if not context.workflow:
 errors.append("缺少必需字段: workflow")
 return errors
 if not context.workflow.is_active:
 errors.append(f"工作流 '{context.workflow.name}' 未激活")
 return errors
 async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
 """返回手动指定的工作流
 手动触发时 workflow 已在 context 中指定，直接返回。
 """
 if context.workflow and context.workflow.is_active:
 return [context.workflow]
 return
 async def prepare_input(
 self,
 context: TriggerContext,
 workflow: "Workflow",
 ) -> dict:
 """准备手动触发的输入数据"""
 return {
 "trigger_type": context.trigger_type,
 "raw_payload": context.raw_payload,
 "event_type": context.event_type,
 }
