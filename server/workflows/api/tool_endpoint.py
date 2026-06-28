"""P9「工作流即端点」接缝 API：把一次工具调用 POST 映射到工作流执行。

本期只预留接缝 + 最小桩，**不**建完整 Workflow Agent Gateway / OpenAI / MCP 网关：
- 路由：``POST /api/workflows/tools/<tool_name>/invoke/``
- ``tool_name`` 最小实现 = ``WorkflowTrigger.token``（token 既是路由标识又是鉴权凭证，
  复用既有飞书专属端点口径），故权限沿用 webhook 触发端点的 ``AllowAny``。
- 经 ``TriggerDispatcher`` 走统一 ``tool_invoke`` handler（input_schema 校验在 handler 内）。
- 默认同步等结果（``await_execution_result``）并按 ``Workflow.output_schema`` 投影返回；
  ``wait=false`` 时立即返回 execution_id（异步）。
- ``callback_url`` 为**桩**：仅在同步路径占位调用 ``deliver_callback_result``（TODO 未实现真实投递）。
"""

import uuid

import structlog
from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from workflows.triggers import (
    TriggerContext,
    TriggerDispatcher,
    await_execution_result,
    build_tool_result,
    deliver_callback_result,
)

logger = structlog.get_logger(__name__)

# 同步等结果默认 / 上限超时（秒）：防止端点请求被长执行无限挂住。
_DEFAULT_WAIT_TIMEOUT = 30.0
_MAX_WAIT_TIMEOUT = 120.0


class ToolInvokeView(APIView):
    """工作流即端点：工具调用入口（P9 接缝）。"""

    # tool_name == WorkflowTrigger.token 即凭证（mirror WebhookTriggerView）。
    permission_classes = [AllowAny]

    async def post(self, request: Request, tool_name: str) -> Response:
        """处理一次工具调用：dispatch → （可选）同步等结果 → 投影返回。"""
        trace_id = str(uuid.uuid4())
        log = logger.bind(trace_id=trace_id, tool_name=tool_name)

        body = request.data if isinstance(request.data, dict) else {}
        # 入参：优先 body["arguments"]，否则把整个 body 当作 arguments。
        raw_arguments = body.get("arguments")
        arguments = raw_arguments if isinstance(raw_arguments, dict) else body
        callback_url = body.get("callback_url") or request.query_params.get("callback_url") or ""

        # wait 默认 True（工具语义偏同步）；timeout 受上限保护。
        wait = _coerce_bool(body.get("wait", request.query_params.get("wait", True)))
        timeout = _coerce_timeout(body.get("timeout", request.query_params.get("timeout")))

        triggered_by = getattr(request, "user", None)
        if triggered_by is not None and not getattr(triggered_by, "is_authenticated", False):
            triggered_by = None

        context = TriggerContext(
            trigger_type="tool_invoke",
            raw_payload=arguments,
            triggered_by=triggered_by,
            metadata={
                "trace_id": trace_id,
                "tool_name": tool_name,
                "arguments": arguments,
                # callback_url 预留接缝（执行完成 hook 投递结构化结果的桩，本期 TODO）。
                "callback_url": callback_url,
            },
        )

        log.info("tool_invoke_start", category="caller", component="workflow_endpoint", wait=wait)

        dispatcher = TriggerDispatcher()
        try:
            executions = await dispatcher.dispatch(context)
        except Exception as e:  # noqa: BLE001 — 不泄露 payload/凭证，结构化错误响应
            log.error("tool_invoke_dispatch_failed", error=str(e)[:2000])
            return Response(
                {"status": "error", "message": str(e)[:2000]},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not executions:
            # 无匹配触发器 / 校验失败 → 404（区别于分发异常的 500）。
            return Response(
                {
                    "status": "not_found",
                    "message": f"No active workflow tool found for: {tool_name}",
                    "reason": "no_matching_tool_or_invalid_input",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        execution = executions[0]
        workflow = execution.workflow
        output_schema = getattr(workflow, "output_schema", {}) or {}

        if not wait:
            log.info("tool_invoke_accepted_async", execution_id=str(execution.id))
            return Response(
                {
                    "status": "accepted",
                    "execution_id": str(execution.id),
                    "workflow_id": str(workflow.id),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # 同步等结果（最小实现：轮询终态 + timeout）。
        finished = await await_execution_result(str(execution.id), timeout=timeout)
        if finished is None:
            # 超时未达终态：返回 202 + execution_id 供调用方后续查询（不算失败）。
            return Response(
                {
                    "status": "pending",
                    "execution_id": str(execution.id),
                    "workflow_id": str(workflow.id),
                    "reason": "result_wait_timeout",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        result = build_tool_result(finished, output_schema)

        # callback_url 投递桩（TODO 未实现真实投递；占位演示接缝形状）。
        if callback_url:
            await deliver_callback_result(
                callback_url,
                result,
                initiated_by_user_id=getattr(triggered_by, "id", None),
            )

        log.info(
            "tool_invoke_complete",
            execution_id=str(execution.id),
            result_status=result["status"],
        )
        return Response(result, status=status.HTTP_200_OK)


def _coerce_bool(value: object) -> bool:
    """把 body/query 的 wait 值统一成 bool（兼容 "false"/"0"/"no" 字符串）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _coerce_timeout(value: object) -> float:
    """把 timeout 值钳制到 (0, _MAX_WAIT_TIMEOUT]，非法值回退默认。"""
    try:
        if value is None or value == "":
            return _DEFAULT_WAIT_TIMEOUT
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_WAIT_TIMEOUT
    if seconds <= 0:
        return _DEFAULT_WAIT_TIMEOUT
    return min(seconds, _MAX_WAIT_TIMEOUT)
