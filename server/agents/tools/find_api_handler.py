"""``find_api_handler`` agent tool —— per implementation work item。

给定 HTTP URL + method，在指定仓库的 Endpoint 表中查找匹配的后端 handler symbol。

实现要点：
- **URL 归一化**：复用 implementation ``path_normalizer.normalize_url_path``，将查询 URL 与
  Endpoint.url_path 统一归一化为 :param 风格再对比。
- **查询策略**：先按 ``http_method + repository_id`` 过滤 Endpoint，再 Python 侧逐条
  normalize(url_path) 对比——单仓 endpoint 数量有限（implementation 实测 285+），Python 侧对比可接受。
- **method 大小写**：输入统一转大写对比（get → GET）。
- **结构化错误**：repository_id 缺失 / Pydantic ValidationError / 内部异常均走
  ``ToolResult(success=False, error=...)``，永不冒泡。

**注册路径**：通过 ``agents/tools/__init__.py`` 顶层 import 触发 ``@tool`` 注册。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError

from agents.tools.base import ToolResult, tool
from agents.tools.schemas.api_tools import (
    FindApiHandlerInput,
    FindApiHandlerOutput,
    HandlerResult,
)
from codegraph.cross_repo.path_normalizer import normalize_url_path
from codegraph.models import Endpoint

logger = structlog.get_logger(__name__)


_TOOL_DESCRIPTION = (
    "Given a URL path and HTTP method, find the backend handler function(s) "
    "that process that API endpoint.\n"
    "\n"
    "USE WHEN you know the API URL and want to find which backend function handles it:\n"
    "  - 'who handles GET /api/v1/users/:id?' → find_api_handler(url='/api/v1/users/:id', method='GET', ...)\n"
    "  - 'find the handler for POST /api/auth/login' → find_api_handler(url='/api/auth/login', method='POST', ...)\n"
    "\n"
    "URL is normalized automatically — all of these match the same endpoint:\n"
    "  '/api/v1/users/123', '/api/v1/users/{id}', '/api/v1/users/:id'\n"
    "\n"
    "DO NOT USE FOR listing all endpoints — use `list_endpoints` instead.\n"
    "DO NOT USE FOR finding who calls a handler — use `find_api_callers` instead."
)

_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "目标 URL 路径（支持任意 placeholder 风格，自动归一化）。"
                "示例：'/api/v1/users/123' 或 '/api/v1/users/{id}' 或 '/api/v1/users/:id'"
            ),
        },
        "method": {
            "type": "string",
            "description": "HTTP 请求方法（GET/POST/PUT/DELETE/PATCH，大小写均可）",
        },
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 后端仓库 UUID（存储 Endpoint 数据的仓库）",
        },
    },
    "required": ["url", "method", "repository_id"],
}


@tool(
    name="find_api_handler",
    description=_TOOL_DESCRIPTION,
    category="PROJECT",
    parameters=_TOOL_PARAMETERS,
)
async def find_api_handler(
    url: str | None = None,
    method: str | None = None,
    repository_id: str | None = None,
) -> ToolResult:
    """查找处理指定 URL + method 的后端 handler symbol。

    Args:
        url: 目标 URL 路径（任意 placeholder 风格，内部统一归一化）。
        method: HTTP 方法（大小写均可，内部转大写）。
        repository_id: 后端仓库 UUID（必填）。

    Returns:
        ``ToolResult``：成功时 ``output={"data": FindApiHandlerOutput, ...}``；
        失败时 ``success=False`` + ``error`` 字符串。永不冒泡异常。
    """
    logger.info(
        "find_api_handler_called",
        url=url,
        method=method,
        repository_id=repository_id,
    )

    try:
        return await _find_api_handler_impl(
            url=url,
            method=method,
            repository_id=repository_id,
        )
    except (ValueError, TypeError, DjangoValidationError) as exc:
        logger.warning(
            "find_api_handler_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return ToolResult(
            success=False,
            error=f"invalid input or downstream failure: {exc}",
        )
    except ValidationError as exc:
        logger.warning(
            "find_api_handler_failed",
            error_type="ValidationError",
            error=str(exc),
        )
        return ToolResult(success=False, error=str(exc))


async def _find_api_handler_impl(
    *,
    url: str | None,
    method: str | None,
    repository_id: str | None,
) -> ToolResult:
    """find_api_handler 函数体实现（抽内层承接外层 try/except）。"""
    try:
        validated = FindApiHandlerInput(
            url=url or "",
            method=method or "",
            repository_id=repository_id or "",
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=str(exc))

    if not validated.repository_id:
        return ToolResult(
            success=False,
            error="repository_id is required (per work item implementation)",
        )

    if not validated.url:
        return ToolResult(success=False, error="url is required")

    if not validated.method:
        return ToolResult(success=False, error="method is required")

    normalized_query = normalize_url_path(validated.url)
    method_upper = validated.method.upper()
    repo_id = validated.repository_id

    logger.info(
        "find_api_handler_normalized",
        original_url=validated.url,
        normalized_url=normalized_query,
        method=method_upper,
    )

    # 先按 method + repo 过滤，Python 侧 normalize 对比
    # Django async queryset：values() → 轻量字典列表
    endpoints_qs = Endpoint.objects.filter(
        repository_id=repo_id,
        http_method=method_upper,
    ).values(
        "handler_name",
        "url_path",
        "http_method",
        "file_path",
        "line_number",
        "view_type",
    )

    matched: list[HandlerResult] = []
    async for ep in endpoints_qs:
        if normalize_url_path(ep["url_path"]) == normalized_query:
            matched.append(
                HandlerResult(
                    handler_name=ep["handler_name"],
                    url_path=ep["url_path"],
                    http_method=ep["http_method"],
                    file_path=ep["file_path"],
                    line_number=ep["line_number"],
                    view_type=ep["view_type"],
                )
            )

    message = "" if matched else f"未找到匹配 {method_upper} {normalized_query} 的 API handler"
    output_model = FindApiHandlerOutput(
        handlers=matched,
        message=message,
        normalized_url=normalized_query,
    )

    logger.info(
        "find_api_handler_success",
        normalized_url=normalized_query,
        method=method_upper,
        match_count=len(matched),
    )

    return ToolResult(
        success=True,
        output={
            "data": output_model.model_dump(),
            "metadata": {
                "repository_id": repo_id,
                "normalized_url": normalized_query,
                "method": method_upper,
                "match_count": len(matched),
            },
        },
    )


__all__ = ["find_api_handler"]
