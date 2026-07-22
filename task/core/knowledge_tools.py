"""容器知识 MCP（AGENT-02）：7 个白名单只读知识工具的进程内 SDK MCP server。

镜像 ``remote_tools.py`` 全套约束，把服务端 ``/api/mcp/tools/<name>/`` HTTP 工具面
暴露给容器内编码代理——权限/排除/脱敏经服务端天然继承，容器不再是"知识贫民区"。

与 ``remote_tools.py`` 的关键差异（响应外形，见 103-02 PLAN 已核实坐标）：
- ``/api/tools/execute/`` 返回 ``{"ok", "result"|"error"}`` 信封；而
  ``/api/mcp/tools/<name>/`` 各视图 **200 直接返回业务 JSON dict**（含 run_id），
  错误经 ``mcp_tools/errors.py error_response`` 返回 ``{"error_code", "detail"}`` + 4xx/5xx。
- 请求 body **直接是业务参数 dict**（不是 ``{name, arguments}`` 信封）。

安全约束（T-103-05/06 脱敏 + 端点校验）：
- PAT（``user_token``）只进 ``Authorization`` header，绝不进 structlog/print/返回文本。
- 非 200 只回显 HTTP code，**不回显响应体**（防上游错误细节/token 泄漏）。
- 日志只记 ``tool``/``status``/``duration_ms``/``quota_used``，绝不记 token、
  endpoint 完整 URL、入参与响应明文。
- 端点校验镜像 ``_is_valid_tools_endpoint``：非法 scheme/host → 不挂 server，
  绝不向不可信端点注入 PAT。

容错约束（return-not-raise）：
- handler 全路径 return 结构化工具结果，绝不 raise——agent 收到错误继续跑，不崩容器。

配额守门（T-103-07 DoS）：
- per-task 闭包共享计数器，默认 200（``FRIDAY_TASK_KNOWLEDGE_QUOTA`` 可配）；
  用尽后返回 agent 可理解文案，不再发 HTTP。

向后兼容（三要素守门）：
- endpoint / user_token 任一为空 → 返回 None（不挂 MCP server，存量任务零回归）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

logger = structlog.get_logger(__name__)

KNOWLEDGE_MCP_SERVER_NAME = "friday-knowledge"

# 配额用尽文案：agent 可理解、可继续（不带 is_error，避免模型反复重试）。
QUOTA_EXHAUSTED_TEXT = "知识工具调用配额已用尽，请基于已有上下文继续完成任务"

# 7 工具白名单（task 侧硬编码，input_schema 逐一对照
# server/mcp_tools/serializers.py 对应 RequestSerializer 字段）。
# description 面向 agent 写清"何时用哪个"。
KNOWLEDGE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_rag_chunks",
        "description": (
            "语义检索代码库：用自然语言问题召回相关代码片段（RAG）。"
            "适合「某功能在哪实现」「某概念相关代码」类问题。"
            "必须提供 repository_id / repository_ids，或设 all_repositories=true 跨仓检索。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言检索问题（必填）"},
                "repository_id": {"type": "string", "description": "单仓 UUID"},
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多仓 UUID 列表",
                },
                "all_repositories": {
                    "type": "boolean",
                    "description": "显式跨全部已索引仓检索",
                },
                "branch": {"type": "string", "description": "分支名（仅单仓时可指定）"},
                "top_k": {"type": "integer", "description": "返回条数上限（默认 30，最大 50）"},
                "max_tokens": {"type": "integer", "description": "结果 token 预算（默认 8000）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "grep_repository",
        "description": (
            "在仓库中按关键词/正则精确匹配文本（git grep 语义）。"
            "适合找符号定义、字符串字面量、精确代码位置。"
            "必须提供 repository_id / repository_ids，或设 all_repositories=true。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "匹配模式（必填）"},
                "repository_id": {"type": "string", "description": "单仓 UUID"},
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多仓 UUID 列表",
                },
                "all_repositories": {"type": "boolean", "description": "跨全部已索引仓"},
                "branch": {"type": "string", "description": "分支名（仅单仓时可指定）"},
                "regex": {"type": "boolean", "description": "pattern 是否为正则（默认 false）"},
                "case_sensitive": {"type": "boolean", "description": "大小写敏感（默认 true）"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定搜索路径列表",
                },
                "context_lines": {"type": "integer", "description": "上下文行数（默认 0）"},
                "max_matches": {"type": "integer", "description": "最大命中数（默认 100）"},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_only", "count"],
                    "description": "输出模式（默认 content）",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_repository_file",
        "description": (
            "读取仓库中指定文件内容（可指定行区间）。适合已知文件路径、需要看具体实现细节时使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repository_id": {"type": "string", "description": "仓库 UUID（必填）"},
                "file_path": {"type": "string", "description": "文件相对路径（必填）"},
                "branch": {"type": "string", "description": "分支名（可选）"},
                "start_line": {"type": "integer", "description": "起始行（1-based，可选）"},
                "end_line": {"type": "integer", "description": "结束行（可选）"},
                "max_lines": {"type": "integer", "description": "最大返回行数（默认 500）"},
            },
            "required": ["repository_id", "file_path"],
        },
    },
    {
        "name": "search_delivery_knowledge",
        "description": (
            "检索交付知识库（历史决策/方案/事实实体，统一向量检索）。"
            "适合「以前怎么做的」「某模块的历史决策」类问题。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题（必填）"},
                "top_k": {"type": "integer", "description": "返回条数（默认 5，最大 20）"},
                "project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定项目 ID 列表",
                },
                "repository_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定仓库 ID 列表",
                },
                "entity_kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定实体类型",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_learning_cases",
        "description": (
            "检索历史学习案例（过往任务的失败根因/解决方案沉淀）。"
            "动手前先查同类任务踩过的坑；query 与 hints 拼装后为空则返回空结果。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题描述（建议必填）"},
                "work_item_type": {"type": "string", "description": "工作项类型过滤"},
                "repo_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关仓库名提示",
                },
                "file_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关文件路径提示",
                },
                "symbol_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关符号名提示",
                },
                "limit": {"type": "integer", "description": "返回条数（默认 5，最大 20）"},
            },
        },
    },
    {
        "name": "search_project_context",
        "description": (
            "语义检索项目工作区上下文（项目级 MEMORY/RESEARCH/STATE 文档）。"
            "适合查项目约定、需求背景、项目内已知状态。需要 project_id。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目 UUID（必填）"},
                "query": {"type": "string", "description": "检索问题（必填）"},
                "top_k": {"type": "integer", "description": "返回条数（默认 5，最大 20）"},
                "entity_kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定实体类型",
                },
            },
            "required": ["project_id", "query"],
        },
    },
    {
        "name": "lookup_project_by_branch",
        "description": (
            "按分支名反查所属项目（含项目上下文摘要）。"
            "不知道 project_id 时先用当前分支名调它拿项目信息，再调其他项目级工具。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "branch_name": {"type": "string", "description": "分支名（必填）"},
                "repository_id": {
                    "type": "string",
                    "description": "仓库 UUID（可选，跨仓同名分支时收窄）",
                },
            },
            "required": ["branch_name"],
        },
    },
]


def _is_valid_knowledge_endpoint(endpoint: str) -> bool:
    """校验 knowledge endpoint 的 scheme/host（镜像 remote_tools._is_valid_tools_endpoint）。

    端点会携带 PAT（``Authorization: Bearer``），非法 scheme（``javascript:`` /
    ``file://``）或缺 host → 拒绝构建，绝不向不可信端点注入 PAT（T-103-06）。
    """
    if not isinstance(endpoint, str):
        return False
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _make_knowledge_handler(
    tool_name: str,
    endpoint_base: str,
    user_token: str,
    session_id: str,
    quota: int,
    quota_counter: list[int],
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """构造单个知识工具的 async handler（工厂函数，闭包共享 quota_counter）。

    handler POST 业务参数 dict 到 ``{base}/api/mcp/tools/{tool_name}/``，带
    ``Authorization: Bearer <PAT>`` + ``X-Friday-Session-Id``。PAT 只进 header，
    绝不进日志/返回文本；非 200 不回显响应体（T-103-05）。全路径 return-not-raise。
    """
    url = f"{endpoint_base.rstrip('/')}/api/mcp/tools/{tool_name}/"

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        # 配额守门（T-103-07）：用尽后直接返回文案，不再发 HTTP。
        # 不带 is_error：这不是错误而是预算终点，避免模型把它当失败反复重试。
        if quota_counter[0] >= quota:
            # IN-04（103 审查）：warning 只在首次用尽打一条——agent 用尽后反复调
            # 工具时不刷屏（高频循环日志纪律）。计数器越界一格作为"已告警"哨兵
            # （7 个 handler 共享同一闭包计数器，全局恰告警一次），后续静默返回
            # 文案（文案本身已足够让 agent 停手）。
            if quota_counter[0] == quota:
                quota_counter[0] = quota + 1
                logger.warning(
                    "knowledge_tool_quota_exhausted",
                    tool=tool_name,
                    quota_used=quota,
                )
            return {"content": [{"type": "text", "text": QUOTA_EXHAUSTED_TEXT}]}
        quota_counter[0] += 1

        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json=args,  # MCP 工具视图直接吃业务参数（无 {name, arguments} 信封）
                    headers={
                        "Authorization": f"Bearer {user_token}",
                        "X-Friday-Session-Id": session_id,
                        "Content-Type": "application/json",
                    },
                    timeout=60.0,
                )
        except httpx.HTTPError as e:
            # 传输错误（连接失败/超时等）→ 结构化错误，不冒泡。
            logger.warning(
                "knowledge_tool_transport_error",
                tool=tool_name,
                quota_used=quota_counter[0],
            )
            return {
                "content": [{"type": "text", "text": f"知识工具传输错误: {e}"}],
                "is_error": True,
            }

        duration_ms = max(int((time.monotonic() - started_at) * 1000), 0)

        # 吊销/无权限 graceful：401/403 → 固定文案，不抛、不崩容器。
        if resp.status_code in (401, 403):
            logger.warning(
                "knowledge_tool_unauthorized",
                tool=tool_name,
                status=resp.status_code,
                duration_ms=duration_ms,
                quota_used=quota_counter[0],
            )
            return {
                "content": [{"type": "text", "text": "知识工具不可用：令牌已失效或无权限"}],
                "is_error": True,
            }
        # 其余非 200：只回显 HTTP code，**不回显响应体**——上游错误细节/敏感内容
        # 不得进 agent 可见文本（T-103-05）。
        if resp.status_code != 200:
            logger.warning(
                "knowledge_tool_http_error",
                tool=tool_name,
                status=resp.status_code,
                duration_ms=duration_ms,
                quota_used=quota_counter[0],
            )
            return {
                "content": [{"type": "text", "text": f"知识工具调用失败: HTTP {resp.status_code}"}],
                "is_error": True,
            }

        # 200：MCP 工具视图直接返回业务 JSON dict（含 run_id），整个 body 序列化
        # 为文本返回。非 JSON/非 dict（反代/网关 200 + text/html）→ 解析失败文案，
        # 单独兜底保证 handler 永不 raise。
        try:
            body = resp.json()
            if not isinstance(body, dict):
                raise ValueError("response body is not a JSON object")
        except ValueError:
            logger.warning(
                "knowledge_tool_bad_json",
                tool=tool_name,
                status=resp.status_code,
                duration_ms=duration_ms,
                quota_used=quota_counter[0],
            )
            return {
                "content": [{"type": "text", "text": "知识工具响应解析失败：非 JSON 响应"}],
                "is_error": True,
            }

        logger.info(
            "knowledge_tool_called",
            tool=tool_name,
            status=resp.status_code,
            duration_ms=duration_ms,
            quota_used=quota_counter[0],
        )
        return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}

    return handler


def build_knowledge_mcp_server(
    endpoint_base: str,
    user_token: str,
    session_id: str,
    quota: int,
) -> McpSdkServerConfig | None:
    """构建容器知识 MCP server（7 工具白名单硬编码）。

    Args:
        endpoint_base: Friday Server 基址（不带路径），拼 ``/api/mcp/tools/<name>/``。
        user_token: 用户 PAT，仅注入 Authorization header（脱敏）。
        session_id: 任务 session 标识，经 ``X-Friday-Session-Id`` 头下发，
            服务端入 ``InteractionRun.raw_request['task_session_id']`` 供关联查询。
        quota: per-task 调用配额（全部 7 工具共享一个计数器）。

    Returns:
        ``McpSdkServerConfig``；``endpoint_base`` / ``user_token`` 任一为空 →
        返回 None（三要素守门：白名单内建恒有，整体降级不挂，存量任务零回归）。
    """
    # 三要素守门（白名单 task 侧内建恒有）：endpoint 或 token 任一空 → 不挂 server。
    if not endpoint_base or not user_token:
        return None

    # 端点校验（T-103-06）：非法 scheme/host → 不挂 server，绝不向非法端点注入 PAT。
    # 只记 scheme，不记完整 URL（脱敏）。
    if not _is_valid_knowledge_endpoint(endpoint_base):
        endpoint_scheme = (
            urlparse(endpoint_base).scheme
            if isinstance(endpoint_base, str)
            else type(endpoint_base).__name__
        )
        logger.warning("knowledge_tool_invalid_endpoint", scheme=endpoint_scheme)
        return None

    # 配额闭包共享计数器：7 个工具 handler 共用同一 per-task 预算。
    quota_counter = [0]
    sdk_tools: list[SdkMcpTool[dict[str, Any]]] = [
        SdkMcpTool(
            name=schema["name"],
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=_make_knowledge_handler(
                schema["name"],
                endpoint_base,
                user_token,
                session_id,
                quota,
                quota_counter,
            ),
        )
        for schema in KNOWLEDGE_TOOL_SCHEMAS
    ]

    logger.info(
        "knowledge_mcp_server_created",
        tool_count=len(sdk_tools),
        quota=quota,
        tools=[t.name for t in sdk_tools],  # 不打印 token / endpoint
    )
    return create_sdk_mcp_server(name=KNOWLEDGE_MCP_SERVER_NAME, tools=sdk_tools)


def knowledge_allowed_tools() -> list[str]:
    """生成 allowed_tools 列表，格式 ``mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{name}``（7 条）。"""
    return [
        f"mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{schema['name']}" for schema in KNOWLEDGE_TOOL_SCHEMAS
    ]
