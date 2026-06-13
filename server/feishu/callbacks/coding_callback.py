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
    """在后台线程中完成分支确认流程，收敛到统一续跑入口。

    18-04：删除手工迷你调度器（手动重置 NE / 手工构建 ExecutionContext / 手工 execute /
    手工复刻 _next_handle / SUSPENDED→RUNNING 翻转）。改为只把确认的分支名 + 恢复标记
    写入 NodeExecution.output_data（数据准备），再调统一入口
    ``engine._continue_after_node``——节点重跑（消费 ``_confirmed_branch_name``）、
    路由、互斥抢锁全部由统一入口完成（与容器回调 / agent_tasks 范式同源，第三套
    迷你调度器漂移源根除）。

    使用 _run_in_thread 避免阻塞飞书回调响应（必须 3 秒内）。

    Args:
        execution_id: 工作流执行 ID
        node_id: 节点 ID
        branch_name: 确认的分支名
    """
    # 延迟导入防循环引用（agent_tasks / dispatcher 同模式）
    from workflows.engine.scheduler import _run_in_thread

    async def _do_confirmation() -> None:
        from workflows.engine.scheduler import WorkflowEngine

        try:
            node_execution = (
                await NodeExecution.objects.filter(
                    workflow_execution_id=execution_id,
                    node_id=node_id,
                    status__in=[
                        NodeExecutionStatus.WAITING_EVENT,
                        NodeExecutionStatus.WAITING_APPROVAL,
                    ],
                )
                .select_related("workflow_execution")
                .afirst()
            )

            if not node_execution:
                logger.warning(
                    "branch_confirm_node_not_found",
                    execution_id=execution_id,
                    node_id=node_id,
                )
                return

            # 写入分支选择结果 + 恢复标记到 output_data（数据准备，不做手工路由）。
            # 统一入口检测仍 WAITING_* + 恢复标记 → 经 _execute_node 重跑该节点（节点
            # 内部消费 _confirmed_branch_name）；SUSPENDED→RUNNING 抢锁由统一入口负责。
            output_data = node_execution.output_data or {}
            output_data["_confirmed_branch_name"] = branch_name
            output_data["_resume_from_callback"] = True
            node_execution.output_data = output_data
            await node_execution.asave(update_fields=["output_data"])

            engine = WorkflowEngine()
            await engine._continue_after_node(
                node_execution.workflow_execution,
                node_execution,
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
