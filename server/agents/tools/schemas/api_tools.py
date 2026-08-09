"""API 相关 MCP tool 输入/输出契约 —— per implementation。

三个 tool 的 schema 集中维护，防止字段漂移：

- ``FindApiHandlerInput / Output``：给定 URL + method 找后端 handler symbol（work item）
- ``FindApiCallersInput / Output``：给定 handler 名找所有前端调用方（work item）
- ``ListEndpointsInput / Output``：列仓库所有 API 端点（work item）

规范同 implementation find_related_code：
- ``ConfigDict(strict=True, extra='forbid', frozen=True)`` 三重防漂移
- 字段 description 含中文语义说明，LLM 读即感知参数意图
- Literal / 约束类型不 import Django ORM（避 app loading 顺序耦合）
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# find_api_handler
# ---------------------------------------------------------------------------


class FindApiHandlerInput(BaseModel):
    """``find_api_handler`` tool 输入契约。

    给定 HTTP method + URL 路径，在指定仓库的 Endpoint 表中查找匹配的后端 handler。
    URL 在查找前会经过 normalize_url_path 归一化（:param 风格）。
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    url: str = Field(
        description=(
            "目标 URL 路径（可包含任意 placeholder 风格：{id} / :id / <int:pk> / ${userId} 等）。"
            "查找时自动归一化为 :param 风格对比后端路由。示例：'/api/v1/users/:id' 或 '/api/v1/users/123'"
        ),
    )
    method: str = Field(
        description=(
            "HTTP 请求方法（GET / POST / PUT / DELETE / PATCH 等，大小写均可，内部统一转大写）。"
        ),
    )
    repository_id: str = Field(
        description=(
            "**REQUIRED.** 后端仓库的 UUID（存储 API Endpoint 的仓库，通常是 Go/Python 后端仓库）。"
        ),
    )


class HandlerResult(BaseModel):
    """单个 handler 匹配结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handler_name: str = Field(description="处理函数名（如 'GetUserHandler' / 'UserView.get'）")
    url_path: str = Field(description="Endpoint 记录的原始 URL 路径（未归一化）")
    http_method: str = Field(description="HTTP 方法（大写）")
    file_path: str = Field(description="handler 所在文件路径（相对仓库根）")
    line_number: int = Field(description="handler 定义所在行号")
    view_type: str = Field(description="视图类型（FUNCTION_VIEW / CLASS_VIEW / VIEWSET）")


class FindApiHandlerOutput(BaseModel):
    """``find_api_handler`` tool 输出契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handlers: list[HandlerResult] = Field(
        description="匹配的 handler 列表（归一化路径相同的全部返回）",
        default_factory=list,
    )
    message: str = Field(
        description="无匹配时的说明文字（'未找到匹配的 API handler'）；有匹配时为空字符串",
        default="",
    )
    normalized_url: str = Field(
        description="查询 URL 归一化后的形式（:param 风格），用于调试 / 确认归一化结果",
    )


# ---------------------------------------------------------------------------
# find_api_callers
# ---------------------------------------------------------------------------


class FindApiCallersInput(BaseModel):
    """``find_api_callers`` tool 输入契约。

    给定后端 handler 函数名，通过 CrossRepoApiCall 表追溯到所有前端业务调用方。
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    handler_name: str = Field(
        description=(
            "后端 handler 函数名（如 'GetUserHandler'），需与 Endpoint.handler_name 字段精确匹配。"
            "大小写敏感。"
        ),
    )
    repository_id: str = Field(
        description=(
            "**REQUIRED.** 后端仓库的 UUID（handler 所在仓库，通常是 Go/Python 后端仓库）。"
        ),
    )


class CallerResult(BaseModel):
    """单个前端调用方结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caller_file: str = Field(description="调用方文件路径（前端仓库相对路径）")
    caller_function: str = Field(description="调用所在函数/方法名")
    line_number: int = Field(description="调用点行号")
    api_wrapper_symbol: str = Field(
        description="中间 ApiWrapper 函数名（业务层调用的前端封装函数）"
    )
    match_confidence: float = Field(
        description="跨仓匹配可信度（1.0=完全匹配 / 0.7=path-only / 0.4=部分匹配）"
    )


class FindApiCallersOutput(BaseModel):
    """``find_api_callers`` tool 输出契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    callers: list[CallerResult] = Field(
        description="所有前端业务调用方列表（按 caller_file 排序）",
        default_factory=list,
    )
    message: str = Field(
        description="无调用方时的说明文字；有调用方时为空字符串",
        default="",
    )


# ---------------------------------------------------------------------------
# list_endpoints
# ---------------------------------------------------------------------------


class ListEndpointsInput(BaseModel):
    """``list_endpoints`` tool 输入契约。

    列出指定仓库的所有 API 端点，按 HTTP 方法 + URL 路径排序。
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    repository_id: str = Field(
        description="**REQUIRED.** 后端仓库的 UUID（存储 API Endpoint 的仓库）。",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=1000,
        description=(
            "返回端点数量上限（默认 200，最大 1000）。超大仓库建议分批按前缀筛选。"
        ),
    )


class EndpointSummary(BaseModel):
    """单个端点摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    http_method: str = Field(description="HTTP 方法（大写，如 GET / POST）")
    url_path: str = Field(description="端点 URL 路径（原始，未归一化）")
    handler_name: str = Field(description="处理函数名")
    file_path: str = Field(description="handler 所在文件路径（相对仓库根）")
    line_number: int = Field(description="handler 定义所在行号")


class ListEndpointsOutput(BaseModel):
    """``list_endpoints`` tool 输出契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoints: list[EndpointSummary] = Field(
        description="端点列表（按 http_method ASC + url_path ASC 排序）",
        default_factory=list,
    )
    total: int = Field(description="仓库中端点总数（不受 limit 截断）")
    message: str = Field(
        description="无端点时的说明；有端点时为空字符串",
        default="",
    )


__all__ = [
    "FindApiHandlerInput",
    "HandlerResult",
    "FindApiHandlerOutput",
    "FindApiCallersInput",
    "CallerResult",
    "FindApiCallersOutput",
    "ListEndpointsInput",
    "EndpointSummary",
    "ListEndpointsOutput",
]
