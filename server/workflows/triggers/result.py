"""P9「工作流即端点」结果协议接缝：输出投影 + 同步等结果 + 回调投递桩。

本期只预留接缝 + 最小桩：
- ``project_output`` / ``build_tool_result``：**已完整实现**的纯函数，把
  ``WorkflowExecution.output_data`` 按 ``Workflow.output_schema`` 投影成稳定结果结构。
- ``await_execution_result``：**最小实现**——轮询执行终态 + timeout（无现成同步等待 API）。
- ``deliver_callback_result``：**桩（TODO）**——仅预留 callback_url 投递形状与日志，
  **不**实现真实 HTTP 投递 / 重试 / 签名。完整闭环留给未来 Workflow Agent Gateway。
"""

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from workflows.models.execution import ExecutionStatus

if TYPE_CHECKING:
    from workflows.models import WorkflowExecution

logger = structlog.get_logger(__name__)

# 执行终态集合：到达任一即视为可取结果（不再轮询）。
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMEOUT,
    }
)


def project_output(output_data: dict | None, output_schema: dict | None) -> dict:
    """把执行 ``output_data`` 按 ``output_schema``（JSON Schema）投影成稳定输出结构。

    纯函数，无 IO，无副作用：
    - ``output_schema`` 为空 / 无 ``properties`` → 原样返回 ``output_data`` 的浅拷贝
      （未声明 schema 时向后兼容，不裁剪）。
    - 否则仅保留 schema ``properties`` 声明的键；缺失键若 schema 提供 ``default``
      则填入，否则忽略（保证字段集稳定、可预期）。

    Args:
        output_data: 终端节点汇总输出（引擎 ``amark_completed`` 写入的扁平 dict）。
        output_schema: 工作流声明的输出 JSON Schema。

    Returns:
        投影后的稳定输出 dict。
    """
    data = dict(output_data or {})
    properties = (output_schema or {}).get("properties")
    if not isinstance(properties, dict) or not properties:
        return data

    projected: dict[str, Any] = {}
    for key, spec in properties.items():
        if key in data:
            projected[key] = data[key]
        elif isinstance(spec, dict) and "default" in spec:
            projected[key] = spec["default"]
    return projected


def build_tool_result(
    execution: "WorkflowExecution",
    output_schema: dict | None,
) -> dict:
    """把一次执行包装成稳定的工具返回结构（供未来 tool / 端点返回）。

    形状（接缝契约）::

        {
            "execution_id": str,
            "status": str,              # ExecutionStatus 值
            "succeeded": bool,          # status == completed
            "output": dict,             # project_output 投影结果
            "error": str,               # 失败时的 error_message，否则空串
        }
    """
    succeeded = execution.status == ExecutionStatus.COMPLETED
    return {
        "execution_id": str(execution.id),
        "status": execution.status,
        "succeeded": succeeded,
        "output": project_output(execution.output_data, output_schema),
        "error": "" if succeeded else (execution.error_message or ""),
    }


async def await_execution_result(
    execution_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> "WorkflowExecution | None":
    """轮询等待执行到达终态后返回该执行；超时返回 None（最小同步等结果实现）。

    引擎在独立线程跑 DAG，无现成「等完成拿 output」API，本函数以最小代价补齐：
    周期性查库直到 ``status`` ∈ :data:`TERMINAL_STATUSES` 或超时。

    Args:
        execution_id: 目标执行 ID。
        timeout: 最长等待秒数。
        poll_interval: 轮询间隔秒数。

    Returns:
        到达终态的 ``WorkflowExecution``；超时或不存在返回 None。
    """
    from workflows.models import WorkflowExecution

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    while True:
        execution = (
            await WorkflowExecution.objects.filter(id=execution_id)
            .only("id", "status", "output_data", "error_message")
            .afirst()
        )
        if execution is None:
            return None
        if execution.status in TERMINAL_STATUSES:
            return execution
        if loop.time() >= deadline:
            logger.info(
                "await_execution_result_timeout",
                category="sampling",
                component="workflow_endpoint",
                execution_id=str(execution_id),
                last_status=execution.status,
                timeout=timeout,
            )
            return None
        await asyncio.sleep(poll_interval)


async def deliver_callback_result(
    callback_url: str,
    result: dict,
    *,
    initiated_by_user_id: str | int | None = None,
) -> None:
    """回调投递桩（TODO，未完整实现）。

    预留「执行完成后向 callback_url POST 结构化结果」的接缝形状。本期**不**实现
    真实 HTTP 投递、重试、签名与失败处理——仅记录一条结构化日志占位，供未来
    Workflow Agent Gateway / 执行完成 hook 接入时替换为真实投递。

    Args:
        callback_url: 调用方预留的结果回调地址（来自 trigger_data/metadata）。
        result: ``build_tool_result`` 产出的结构化结果。
        initiated_by_user_id: 触发用户（无则记 ``system``）。
    """
    # TODO(P9-followup): 实现真实回调投递（httpx POST + tenacity 重试 + 签名 +
    #   失败落 SystemLogEntry），并由执行完成 hook 调用。当前仅占位日志，绝不阻塞主流程。
    logger.info(
        "tool_callback_delivery_stub",
        category="caller",
        component="workflow_endpoint",
        callback_url=callback_url,
        execution_id=result.get("execution_id"),
        status=result.get("status"),
        initiated_by_user_id=str(initiated_by_user_id) if initiated_by_user_id else "system",
        note="stub_not_implemented",
    )
