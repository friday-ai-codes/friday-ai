"""ToolInvokeHandler —— P9「工作流即端点」接缝：把一次工具调用映射到工作流执行。

本期只预留接缝 + 最小桩，**不**建完整的 Workflow Agent Gateway / OpenAI / MCP 网关。

最小可用查找（least-invasive）：``metadata["tool_name"]`` 直接当作 ``WorkflowTrigger.token``
定位唯一触发器（token 既是路由标识又是鉴权凭证，复用既有飞书专属端点口径），命中即返回
其工作流。``metadata["arguments"]`` 为工具入参，经 ``WorkflowTrigger.validate_input`` 做
JSON Schema 校验后包装为 ``{trigger_type, raw_payload: arguments}`` 交给引擎。
"""

from typing import TYPE_CHECKING, ClassVar

import structlog

from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.base import TriggerHandler
from workflows.triggers.registry import register_handler

if TYPE_CHECKING:
    from workflows.models import Workflow, WorkflowTrigger

logger = structlog.get_logger(__name__)


@register_handler
class ToolInvokeHandler(TriggerHandler):
    """工具调用触发处理器（P9 接缝）。

    TriggerContext 需要:
    - metadata["tool_name"]: 工具名（最小实现 = ``WorkflowTrigger.token``）
    - metadata["arguments"]: 工具入参 dict（用于 input_schema 校验 + 透传引擎）

    一次 dispatch 内 validate / find_workflows / prepare_input 共享同一 handler 实例，
    故把命中的 WorkflowTrigger 缓存到 ``self`` 避免重复查库。
    """

    trigger_type: ClassVar[str] = "tool_invoke"
    display_name: ClassVar[str] = "工具调用触发"
    description: ClassVar[str] = "把一次工具调用（tool_name + arguments）映射到工作流执行"

    def __init__(self) -> None:
        # 单次 dispatch 内复用，避免 validate / find_workflows 重复查库。
        self._trigger: "WorkflowTrigger | None" = None

    @staticmethod
    def get_arguments(context: TriggerContext) -> dict:
        """提取工具入参：优先 ``metadata["arguments"]``，回退到 ``raw_payload``。"""
        arguments = context.metadata.get("arguments")
        if isinstance(arguments, dict):
            return arguments
        return context.raw_payload or {}

    async def _resolve_trigger(self, context: TriggerContext) -> "WorkflowTrigger | None":
        """按 ``tool_name`` == ``WorkflowTrigger.token`` 定位启用中的触发器（带缓存）。"""
        if self._trigger is not None:
            return self._trigger

        tool_name = context.metadata.get("tool_name")
        if not tool_name:
            return None

        from workflows.models import WorkflowTrigger

        self._trigger = (
            await WorkflowTrigger.objects.filter(
                token=tool_name,
                is_active=True,
                workflow__is_active=True,
            )
            .select_related("workflow")
            .afirst()
        )
        return self._trigger

    async def validate(self, context: TriggerContext) -> list[str]:
        """校验工具调用上下文。

        1. ``metadata.tool_name`` 必填；
        2. 能按 tool_name 定位到启用中的触发器；
        3. 命中触发器若声明了 ``input_schema``，对 arguments 跑 JSON Schema 校验
           （接线既有但此前未被 dispatch 调用的 ``WorkflowTrigger.validate_input``）。
        """
        errors: list[str] = []

        tool_name = context.metadata.get("tool_name")
        if not tool_name:
            errors.append("缺少必需字段: metadata.tool_name")
            return errors

        trigger = await self._resolve_trigger(context)
        if trigger is None:
            errors.append(f"未找到启用中的工具触发器: {tool_name}")
            return errors

        # 接线 input_schema 校验（trigger.validate_input 为纯计算，无 IO）。
        schema_errors = trigger.validate_input(self.get_arguments(context))
        if schema_errors:
            logger.info(
                "tool_invoke_input_invalid",
                category="caller",
                component="workflow_trigger",
                tool_name=tool_name,
                trigger_id=str(trigger.id),
                error_count=len(schema_errors),
            )
            errors.extend(schema_errors)

        return errors

    async def find_workflows(self, context: TriggerContext) -> list["Workflow"]:
        """返回命中触发器关联的工作流（命中缓存，单工作流语义）。"""
        trigger = await self._resolve_trigger(context)
        if trigger is None:
            return []
        return [trigger.workflow]

    async def prepare_input(
        self,
        context: TriggerContext,
        workflow: "Workflow",
    ) -> dict:
        """包装工具入参为引擎 input_data：``{trigger_type, raw_payload: arguments}``。"""
        return {
            "trigger_type": context.trigger_type,
            "raw_payload": self.get_arguments(context),
            "tool_name": context.metadata.get("tool_name"),
        }
