"""TriggerDispatcher for unified workflow triggering."""

from typing import TYPE_CHECKING

import structlog

from workflows.triggers.context import TriggerContext
from workflows.triggers.registry import TriggerHandlerRegistry

if TYPE_CHECKING:
    from workflows.engine.scheduler import WorkflowEngine
    from workflows.models import WorkflowExecution

logger = structlog.get_logger()


class TriggerDispatcher:
    """统一触发调度器

    所有触发方式（手动/Webhook/飞书）通过此类进入工作流执行。
    协调处理器查找、验证、工作流发现和执行启动。

    Attributes:
        engine: 工作流执行引擎实例
        _processed_keys: 已处理的幂等键集合，用于去重

    Examples:
        >>> dispatcher = TriggerDispatcher()
        >>> context = TriggerContext(trigger_type="manual", raw_payload={})
        >>> executions = await dispatcher.dispatch(context)
    """

    def __init__(self, engine: "WorkflowEngine | None" = None):
        """初始化调度器

        Args:
            engine: 可选的工作流引擎实例。未提供时延迟创建。
        """
        # 延迟导入避免循环引用
        from workflows.engine.scheduler import WorkflowEngine

        self.engine = engine or WorkflowEngine()
        self._processed_keys: set[str] = set()

    async def dispatch(self, context: TriggerContext) -> list["WorkflowExecution"]:
        """分发触发并启动工作流执行

        主调度流程：
        1. 检查幂等键防止重复处理
        2. 查找对应的处理器
        3. 验证触发上下文
        4. 查找匹配的工作流
        5. 启动工作流执行

        Args:
            context: 统一触发上下文

        Returns:
            已创建的 WorkflowExecution 实例列表
        """
        # 1. 幂等性检查
        if context.idempotency_key:
            if context.idempotency_key in self._processed_keys:
                logger.info(
                    "duplicate_trigger_skipped",
                    idempotency_key=context.idempotency_key,
                    trigger_type=context.trigger_type,
                )
                return []
            self._processed_keys.add(context.idempotency_key)

        # 2. 获取处理器
        handler_class = TriggerHandlerRegistry.get(context.trigger_type)
        if not handler_class:
            logger.error(
                "unknown_trigger_type",
                trigger_type=context.trigger_type,
            )
            return []

        handler = handler_class()

        # 3. 验证上下文
        errors = await handler.validate(context)
        if errors:
            logger.warning(
                "trigger_validation_failed",
                trigger_type=context.trigger_type,
                errors=errors,
            )
            return []

        # 4. 查找工作流
        workflows = await handler.find_workflows(context)
        if not workflows:
            logger.debug(
                "no_matching_workflows",
                trigger_type=context.trigger_type,
            )
            return []

        # 5. 启动执行
        executions: list["WorkflowExecution"] = []
        for workflow in workflows:
            try:
                input_data = await handler.prepare_input(context, workflow)
                execution = await self.engine.start_execution(
                    workflow=workflow,
                    input_data=input_data,
                    triggered_by=context.triggered_by,
                    trigger_type=context.trigger_type,
                    trigger_data={
                        "source": context.trigger_type,
                        "raw_payload": context.raw_payload,
                    },
                    debug_mode=context.debug_mode,
                    stop_before_node_id=context.stop_before_node_id,
                )
                executions.append(execution)
                logger.info(
                    "workflow_triggered",
                    execution_id=str(execution.id),
                    workflow_id=str(workflow.id),
                    trigger_type=context.trigger_type,
                )
            except Exception as e:
                logger.error(
                    "workflow_start_failed",
                    workflow_id=str(workflow.id),
                    trigger_type=context.trigger_type,
                    error=str(e),
                )

        return executions

    async def dispatch_single(self, context: TriggerContext) -> "WorkflowExecution | None":
        """单工作流触发的便捷方法

        适用于手动触发等已知目标工作流的场景。
        调用 dispatch() 并返回第一个执行实例。

        Args:
            context: 触发上下文，通常已设置 workflow 属性

        Returns:
            WorkflowExecution 实例，无执行时返回 None

        Examples:
            >>> context = TriggerContext(
            ...     trigger_type="manual",
            ...     raw_payload={},
            ...     workflow=my_workflow,
            ... )
            >>> execution = await dispatcher.dispatch_single(context)
        """
        executions = await self.dispatch(context)
        return executions[0] if executions else None
