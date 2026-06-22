"""``list_endpoints`` agent tool —— per implementation work item。

列出指定仓库的所有 API 端点，按 HTTP 方法 + URL 路径排序。

实现要点：
- 查询：``Endpoint.objects.filter(repository_id=repo_id).order_by('http_method', 'url_path')``
- **limit 参数**：default=200，max=1000（避超大仓库爆 output）。
- **total 回传**：同时返回仓库总端点数（不受 limit 截断），让 Agent 知道是否被截断。
- **轻量字典**：``.values()`` 避免全 ORM 实例化，减少内存占用。
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
    EndpointSummary,
    ListEndpointsInput,
    ListEndpointsOutput,
)
from codegraph.models import Endpoint, Symbol

logger = structlog.get_logger(__name__)


_TOOL_DESCRIPTION = (
    "List all API endpoints in a repository, sorted by HTTP method then URL path.\n"
    "\n"
    "USE WHEN you want to explore what APIs a backend repository exposes:\n"
    "  - 'what endpoints does the study-course repo have?' → list_endpoints(repository_id='...')\n"
    "  - 'show me all POST endpoints' → list_endpoints(...) then filter client-side\n"
    "\n"
    "Returns up to `limit` endpoints (default 200, max 1000) with total count.\n"
    "Each result includes: http_method, url_path, handler_name, file_path, line_number.\n"
    "\n"
    "DO NOT USE FOR finding a specific endpoint — use `find_api_handler` instead."
)

_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 后端仓库 UUID（需已完成 codegraph 索引，Endpoint 表有数据）",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "返回端点数量上限（默认 200，最大 1000）",
        },
    },
    "required": ["repository_id"],
}


@tool(
    name="list_endpoints",
    description=_TOOL_DESCRIPTION,
    category="PROJECT",
    parameters=_TOOL_PARAMETERS,
)
async def list_endpoints(
    repository_id: str | None = None,
    limit: int = 200,
) -> ToolResult:
    """列出仓库所有 API 端点（按 method + path 排序）。

    Args:
        repository_id: 后端仓库 UUID（必填）。
        limit: 返回端点数量上限（ge=1, le=1000，默认 200）。

    Returns:
        ``ToolResult``：成功时包含 EndpointSummary 列表 + total 数；
        失败时 ``success=False`` + ``error``。永不冒泡异常。
    """
    logger.info(
        "list_endpoints_called",
        repository_id=repository_id,
        limit=limit,
    )

    try:
        return await _list_endpoints_impl(
            repository_id=repository_id,
            limit=limit,
        )
    except (ValueError, TypeError, DjangoValidationError) as exc:
        logger.warning(
            "list_endpoints_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return ToolResult(
            success=False,
            error=f"invalid input or downstream failure: {exc}",
        )
    except ValidationError as exc:
        logger.warning(
            "list_endpoints_failed",
            error_type="ValidationError",
            error=str(exc),
        )
        return ToolResult(success=False, error=str(exc))


async def _list_endpoints_impl(
    *,
    repository_id: str | None,
    limit: int,
) -> ToolResult:
    """list_endpoints 函数体实现。"""
    try:
        validated = ListEndpointsInput(
            repository_id=repository_id or "",
            limit=limit,
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=str(exc))

    if not validated.repository_id:
        return ToolResult(
            success=False,
            error="repository_id is required (per work item implementation)",
        )

    repo_id = validated.repository_id
    effective_limit = validated.limit

    # 总数（不受 limit 截断）
    total = await Endpoint.objects.filter(repository_id=repo_id).acount()

    # 端点列表（按 method + path 排序，values() 轻量）
    endpoints: list[EndpointSummary] = []
    async for ep in (
        Endpoint.objects.filter(repository_id=repo_id)
        .order_by("http_method", "url_path")
        .values("http_method", "url_path", "handler_name", "file_path", "line_number")[
            :effective_limit
        ]
    ):
        endpoints.append(
            EndpointSummary(
                http_method=ep["http_method"],
                url_path=ep["url_path"],
                handler_name=ep["handler_name"],
                file_path=ep["file_path"],
                line_number=ep["line_number"],
            )
        )

    # 端点为空 ≠ codegraph 未构建：codegraph 可能已建（符号/调用/导入齐全），
    # 只是该仓库未提取到 HTTP 端点（非 Web 服务，或其路由注册写法尚未被端点
    # 提取器支持）。用 Symbol 表实际判断，避免给上层 Agent "codegraph 未跑" 的
    # 误导性结论。
    codegraph_built = True
    symbol_count = 0
    if endpoints:
        message = ""
    else:
        symbol_count = await Symbol.objects.filter(repository_id=repo_id).acount()
        codegraph_built = symbol_count > 0
        if codegraph_built:
            message = (
                f"该仓库 codegraph 已构建（符号 {symbol_count} 个），但未提取到任何 HTTP 端点。"
                "这不代表 codegraph 未跑：可能该仓库不是 Web 服务，或其路由注册写法尚未被"
                "端点提取器支持（符号 / 调用 / 导入关系仍可正常查询）。"
            )
        else:
            message = "该仓库 codegraph 索引尚未构建（Endpoint 与 Symbol 均为空），请先运行 codegraph 索引。"
    output = ListEndpointsOutput(endpoints=endpoints, total=total, message=message)

    logger.info(
        "list_endpoints_success",
        repository_id=repo_id,
        returned=len(endpoints),
        total=total,
        truncated=total > effective_limit,
        codegraph_built=codegraph_built,
        symbol_count=symbol_count,
    )

    return ToolResult(
        success=True,
        output={
            "data": output.model_dump(),
            "metadata": {
                "repository_id": repo_id,
                "returned": len(endpoints),
                "total": total,
                "truncated": total > effective_limit,
                # 让 Agent 拿到结构化信号，区分"无端点"与"codegraph 未构建"
                "codegraph_built": codegraph_built,
                "symbol_count": symbol_count,
            },
        },
    )


__all__ = ["list_endpoints"]
