"""``find_api_callers`` agent tool —— per implementation work item。

给定后端 handler 函数名，通过 CrossRepoApiCall 表追溯所有前端业务调用方（call site）。

查询链（per implementation 数据模型）：
  handler_name → Endpoint(repo) → CrossRepoApiCall(endpoint) → ApiCallSite → {file:line}

实现要点：
- **select_related**：``CrossRepoApiCall.objects.filter(endpoint__in=...).select_related('call_site')``
  避 N+1 查询。
- **结构化错误**：handler_name 找不到 endpoint / 无跨仓调用 → 空列表 + message 说明。
- **match_confidence 透传**：1.0/0.7/0.4 三档可信度让 Agent 知道匹配质量。
- 永不冒泡异常（per implementation 双层防御）。

**注册路径**：通过 ``agents/tools/__init__.py`` 顶层 import 触发 ``@tool`` 注册。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError

from agents.tools.base import ToolResult, tool
from agents.tools.schemas.api_tools import (
    CallerResult,
    FindApiCallersInput,
    FindApiCallersOutput,
)
from codegraph.models import CrossRepoApiCall, Endpoint

logger = structlog.get_logger(__name__)


_TOOL_DESCRIPTION = (
    "Given a backend handler function name, find all frontend business call sites "
    "that ultimately invoke that backend API endpoint.\n"
    "\n"
    "USE WHEN you know the backend handler and want to trace who calls it from the frontend:\n"
    "  - 'who calls GetUserHandler from the frontend?' → find_api_callers(handler_name='GetUserHandler', ...)\n"
    "  - 'find all frontend pages that use the login endpoint' → find_api_callers(handler_name='LoginHandler', ...)\n"
    "\n"
    "Returns frontend business call sites (ApiCallSite) with file path + line number, "
    "NOT the low-level axios helpers.\n"
    "\n"
    "Requires cross-repo API call data (implementation offline join) to be populated.\n"
    "DO NOT USE FOR finding the handler by URL — use `find_api_handler` instead."
)

_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "handler_name": {
            "type": "string",
            "description": (
                "后端 handler 函数名（与 Endpoint.handler_name 字段精确匹配，大小写敏感）。"
                "示例：'GetUserHandler' / 'UserView.get' / 'handleCreateOrder'"
            ),
        },
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 后端仓库 UUID（handler 所在的 Go/Python 后端仓库）",
        },
    },
    "required": ["handler_name", "repository_id"],
}


@tool(
    name="find_api_callers",
    description=_TOOL_DESCRIPTION,
    category="PROJECT",
    parameters=_TOOL_PARAMETERS,
)
async def find_api_callers(
    handler_name: str | None = None,
    repository_id: str | None = None,
) -> ToolResult:
    """查找前端对指定后端 handler 的所有业务调用点。

    Args:
        handler_name: 后端 handler 函数名（精确匹配 Endpoint.handler_name）。
        repository_id: 后端仓库 UUID（必填）。

    Returns:
        ``ToolResult``：成功时包含 CallerResult 列表；失败时 ``success=False`` + ``error``。
        永不冒泡异常。
    """
    logger.info(
        "find_api_callers_called",
        handler_name=handler_name,
        repository_id=repository_id,
    )

    try:
        return await _find_api_callers_impl(
            handler_name=handler_name,
            repository_id=repository_id,
        )
    except (ValueError, TypeError, DjangoValidationError) as exc:
        logger.warning(
            "find_api_callers_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return ToolResult(
            success=False,
            error=f"invalid input or downstream failure: {exc}",
        )
    except ValidationError as exc:
        logger.warning(
            "find_api_callers_failed",
            error_type="ValidationError",
            error=str(exc),
        )
        return ToolResult(success=False, error=str(exc))


async def _find_api_callers_impl(
    *,
    handler_name: str | None,
    repository_id: str | None,
) -> ToolResult:
    """find_api_callers 函数体实现。"""
    try:
        validated = FindApiCallersInput(
            handler_name=handler_name or "",
            repository_id=repository_id or "",
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=str(exc))

    if not validated.repository_id:
        return ToolResult(
            success=False,
            error="repository_id is required (per work item implementation)",
        )

    if not validated.handler_name:
        return ToolResult(success=False, error="handler_name is required")

    repo_id = validated.repository_id

    # 步骤1：找对应的 endpoint(s)（同名 handler 可能有多个 endpoint）
    endpoint_ids = [
        ep_id
        async for ep_id in Endpoint.objects.filter(
            repository_id=repo_id,
            handler_name=validated.handler_name,
        ).values_list("id", flat=True)
    ]

    if not endpoint_ids:
        logger.info(
            "find_api_callers_no_endpoint",
            handler_name=validated.handler_name,
            repository_id=repo_id,
        )
        output = FindApiCallersOutput(
            callers=[],
            message=f"未找到 handler_name='{validated.handler_name}' 对应的 Endpoint 记录",
        )
        return ToolResult(
            success=True,
            output={"data": output.model_dump(), "metadata": {"repository_id": repo_id}},
        )

    # 步骤2：CrossRepoApiCall → ApiCallSite（select_related 避 N+1）
    callers: list[CallerResult] = []
    async for cross_call in CrossRepoApiCall.objects.filter(
        endpoint_id__in=endpoint_ids,
    ).select_related("call_site", "call_site__api_wrapper"):
        cs = cross_call.call_site
        callers.append(
            CallerResult(
                caller_file=cs.caller_file,
                caller_function=cs.caller_function,
                line_number=cs.line_number,
                api_wrapper_symbol=cs.api_wrapper.function_symbol,
                match_confidence=cross_call.match_confidence,
            )
        )

    # 按 caller_file + line_number 排序，让结果稳定可读
    callers.sort(key=lambda c: (c.caller_file, c.line_number))

    message = "" if callers else f"handler '{validated.handler_name}' 暂无跨仓前端调用记录（需先运行 cross-repo offline join）"
    output = FindApiCallersOutput(callers=callers, message=message)

    logger.info(
        "find_api_callers_success",
        handler_name=validated.handler_name,
        endpoint_count=len(endpoint_ids),
        caller_count=len(callers),
    )

    return ToolResult(
        success=True,
        output={
            "data": output.model_dump(),
            "metadata": {
                "repository_id": repo_id,
                "handler_name": validated.handler_name,
                "endpoint_count": len(endpoint_ids),
                "caller_count": len(callers),
            },
        },
    )


__all__ = ["find_api_callers"]
