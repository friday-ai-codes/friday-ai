"""Branch confirmation callback handler for AI coding workflow node.

Handles branch_confirm and branch_modify callbacks from branch
confirmation cards. Updates NodeExecution with the confirmed branch
name and resumes the workflow.
"""

import json
from typing import Any

import structlog

from feishu.cards.coding_result_card import build_branch_confirmed_card
from feishu.views import CardCallback, register_card_callback
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import NodeExecution, NodeExecutionStatus

logger = structlog.get_logger(__name__)


@register_card_callback("branch_confirm")
def handle_branch_confirm(callback: CardCallback) -> dict[str, Any] | None:
    """处理分支确认按钮点击。

    从 action_value 提取 branch_name，写入 NodeExecution 并恢复工作流。

    Args:
        callback: 卡片回调数据

    Returns:
        更新后的卡片 JSON（已确认状态），或 None
    """
    data = _extract_callback_data(callback)
    if not data:
        return None

    execution_id: str = data.get("execution_id", "")
    node_id: str = data.get("node_id", "")
    branch_name: str = data.get("branch_name", "")

    if not execution_id or not node_id or not branch_name:
        logger.warning(
            "branch_confirm_missing_data",
            execution_id=execution_id,
            node_id=node_id,
            has_branch=bool(branch_name),
        )
        return None

    logger.info(
        "branch_confirmed",
        execution_id=execution_id,
        node_id=node_id,
        branch_name=branch_name,
    )

    # 在后台线程中完成确认流程（飞书回调必须 3 秒内响应）
    _schedule_branch_confirmation(
        execution_id=execution_id,
        node_id=node_id,
        branch_name=branch_name,
    )

    # 获取 plan_title 用于返回卡片
    plan_title = _get_plan_title(execution_id, node_id)

    return build_branch_confirmed_card(
        branch_name=branch_name,
        plan_title=plan_title,
    )


@register_card_callback("branch_modify")
def handle_branch_modify(callback: CardCallback) -> dict[str, Any] | None:
    """处理分支修改表单提交。

    从 form_data 提取用户输入的自定义分支名。

    Args:
        callback: 卡片回调数据

    Returns:
        更新后的卡片 JSON（已确认状态），或 None
    """
    data = _extract_callback_data(callback)
    if not data:
        return None

    execution_id: str = data.get("execution_id", "")
    node_id: str = data.get("node_id", "")

    # 从表单数据中提取用户输入的分支名
    branch_name = _extract_form_branch_name(callback)

    if not execution_id or not node_id or not branch_name:
        logger.warning(
            "branch_modify_missing_data",
            execution_id=execution_id,
            node_id=node_id,
            has_branch=bool(branch_name),
        )
        return None

    logger.info(
        "branch_modified",
        execution_id=execution_id,
        node_id=node_id,
        branch_name=branch_name,
    )

    _schedule_branch_confirmation(
        execution_id=execution_id,
        node_id=node_id,
        branch_name=branch_name,
    )

    plan_title = _get_plan_title(execution_id, node_id)

    return build_branch_confirmed_card(
        branch_name=branch_name,
        plan_title=plan_title,
    )


def _extract_callback_data(callback: CardCallback) -> dict[str, Any]:
    """从回调中提取数据字典。

    action_value 可能是 dict（CardCallbackView 已解析）或 str。

    Args:
        callback: 卡片回调数据

    Returns:
        解析后的数据字典，或空字典
    """
    action_value = callback.action_value
    if isinstance(action_value, dict):
        return action_value
    elif isinstance(action_value, str):
        try:
            data = json.loads(action_value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_form_branch_name(callback: CardCallback) -> str:
    """从表单提交中提取用户输入的分支名。

    表单值可能在 action_value 的多个位置。

    Args:
        callback: 卡片回调数据

    Returns:
        用户输入的分支名，或空字符串
    """
    action_value = callback.action_value
    if isinstance(action_value, dict):
        # 直接从 action_value 查找
        branch: str = action_value.get("branch_name", "")
        if not branch:
            # 回退：从 form_value 查找
            form_value = action_value.get("form_value", {})
            if isinstance(form_value, dict):
                branch = form_value.get("branch_name", "")
        return branch
    return ""


def _get_plan_title(execution_id: str, node_id: str) -> str:
    """从 NodeExecution 获取方案标题。

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID

    Returns:
        方案标题字符串
    """
    try:
        node_execution = NodeExecution.objects.filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
        ).first()

        if not node_execution:
            return "技术方案"

        output_data = node_execution.output_data or {}
        plan_data = output_data.get("plan_data", {})
        if isinstance(plan_data, dict):
            title: str = plan_data.get("title", "技术方案")
            return title

        return "技术方案"
    except Exception as e:
        logger.warning("get_plan_title_failed", error=str(e))
        return "技术方案"


def _schedule_branch_confirmation(
    execution_id: str,
    node_id: str,
    branch_name: str,
) -> None:
    """在后台线程中完成分支确认流程。

    1. 找到 WAITING_EVENT 状态的 NodeExecution
    2. 将确认的 branch_name 写入 output_data
    3. 恢复工作流执行

    使用 _run_in_thread 避免阻塞飞书回调响应（必须 3 秒内）。

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID
        branch_name: 确认的分支名
    """

    async def _do_confirmation() -> None:
        from workflows.models.execution import ExecutionStatus

        try:
            node_execution = await NodeExecution.objects.filter(
                workflow_execution_id=execution_id,
                node_id=node_id,
                status__in=[
                    NodeExecutionStatus.WAITING_EVENT,
                    NodeExecutionStatus.WAITING_APPROVAL,
                ],
            ).select_related("workflow_execution").afirst()

            if not node_execution:
                logger.warning(
                    "branch_confirm_node_not_found",
                    execution_id=execution_id,
                    node_id=node_id,
                )
                return

            # 将确认的分支名写入 output_data
            output_data = node_execution.output_data or {}
            output_data["_confirmed_branch_name"] = branch_name
            node_execution.output_data = output_data
            await node_execution.asave(update_fields=["output_data"])

            # select_related 已预加载 workflow_execution
            workflow_execution = node_execution.workflow_execution
            if workflow_execution.status == ExecutionStatus.SUSPENDED:
                workflow_execution.status = ExecutionStatus.RUNNING
                await workflow_execution.asave(update_fields=["status"])

            # 重新执行该节点（节点内部会检测 _confirmed_branch_name）
            # 直接实例化节点并执行，而非通过 engine._execute_node
            # （因为 _execute_node 需要 dag_node 参数）
            from workflows.nodes.base import ExecutionContext, NodeResult
            from workflows.nodes.registry import NodeRegistry

            workflow_node = await NodeExecution.objects.select_related("node").aget(
                pk=node_execution.pk
            )
            workflow_node = workflow_node.node

            node_class = NodeRegistry.get(workflow_node.node_type)
            if not node_class:
                logger.error(
                    "branch_confirm_unknown_node_type",
                    node_type=workflow_node.node_type,
                )
                return

            # 重置节点状态为 running
            node_execution.status = NodeExecutionStatus.RUNNING
            await node_execution.asave(update_fields=["status"])

            # 构建执行上下文
            context = ExecutionContext(
                execution_id=str(workflow_execution.id),
                node_id=str(workflow_node.id),
                node_config=workflow_node.config,
                input_data=node_execution.input_data or {},
                workflow_context=workflow_execution.context or {},
                previous_outputs={},
                workflow_execution=workflow_execution,
                node_execution=node_execution,
            )

            node_instance = node_class()
            result: NodeResult = await node_instance.execute(context)

            # 处理执行结果
            if result.status == "completed":
                output_with_handle = {**(result.output or {})}
                if result.next_handle and result.next_handle != "default":
                    output_with_handle["_next_handle"] = result.next_handle
                await node_execution.amark_completed(
                    output_with_handle
                )
                engine = WorkflowEngine()
                await engine._continue_after_node(
                    workflow_execution, node_execution
                )
            elif result.status == "failed":
                await node_execution.amark_failed(
                    result.error or "编码执行失败"
                )

            logger.info(
                "branch_confirmation_complete",
                execution_id=execution_id,
                node_id=node_id,
                branch_name=branch_name,
            )

        except Exception as e:
            logger.exception(
                "branch_confirmation_error",
                execution_id=execution_id,
                node_id=node_id,
                error=str(e),
            )

    _run_in_thread(_do_confirmation())
