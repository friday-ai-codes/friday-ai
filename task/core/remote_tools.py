"""RemoteTool 容器侧机制：把 remote_tools schema 列表动态注册为进程内 SDK MCP server。

每条 schema → 1 个 ``SdkMcpTool``；每个工具 handler 以直传 PAT 回调 Friday Server
的 ``/api/tools/execute/`` 端点（RBAC/吊销唯一真源）。蓝本来自
``server/agents/sdk/mcp_adapter.py``（直接构造 ``SdkMcpTool``，不走 ``@tool`` 装饰器）。

安全约束（RTOOL-03 脱敏）：
- PAT（``user_token``）只进 ``Authorization`` header，绝不进 structlog/print/返回文本。
- 日志只记 ``tool`` 名与 ``status``，从不记 token 值本身。

容错约束（RTOOL-04 graceful）：
- handler **不** ``raise_for_status``；401/403/非 200/传输错误一律返回结构化工具错误
  （``is_error``），**return 而非 raise**——agent 收到错误继续跑，不崩容器。

向后兼容（CONTEXT 决策）：
- 无 remote_tools / 无 user_token / 无 tools_endpoint 任一 → 返回 None（不挂 MCP server）。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx
import structlog
from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server

logger = structlog.get_logger(__name__)

REMOTE_MCP_SERVER_NAME = "friday-remote-tools"


def _make_handler(
    tool_name: str,
    tools_endpoint: str,
    user_token: str,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """构造单个工具的 async handler。

    handler 以 httpx POST ``{name, arguments}`` 到 ``tools_endpoint``，带
    ``Authorization: Bearer <PAT>``。PAT 只进 header，绝不进日志/返回文本（脱敏）。
    """

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        # PAT 只进 Authorization header，绝不进日志/返回文本（脱敏，RTOOL-03）。
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    tools_endpoint,
                    json={"name": tool_name, "arguments": args},
                    headers={
                        "Authorization": f"Bearer {user_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=60.0,
                )
        except httpx.HTTPError as e:
            # 传输错误（连接失败/超时等）→ 结构化错误，不冒泡（RTOOL-04）。
            logger.warning("remote_tool_transport_error", tool=tool_name, error=str(e))
            return {
                "content": [{"type": "text", "text": f"工具传输错误: {e}"}],
                "is_error": True,
            }

        # 吊销 graceful（RTOOL-04）：401/403 → 结构化工具错误，不抛、不崩容器。
        if resp.status_code in (401, 403):
            logger.warning(
                "remote_tool_unauthorized", tool=tool_name, status=resp.status_code
            )
            return {
                "content": [{"type": "text", "text": "工具不可用：令牌已失效或无权限"}],
                "is_error": True,
            }
        if resp.status_code != 200:
            logger.warning(
                "remote_tool_http_error", tool=tool_name, status=resp.status_code
            )
            return {
                "content": [
                    {"type": "text", "text": f"工具执行失败: HTTP {resp.status_code}"}
                ],
                "is_error": True,
            }

        # 200 但响应体可能非 JSON（如反代/网关/鉴权门户返回 200 + text/html）：
        # resp.json() 抛 json.JSONDecodeError（ValueError 子类，**不是** httpx.HTTPError），
        # 不在上面的传输错误 except 内。这里单独兜底，保证 handler 永不 raise
        # （RTOOL-04：handler 必须始终 return 结构化工具错误而非冒泡崩容器）。
        try:
            body = resp.json()  # {"ok": bool, "result"|"error": ...}
            if not isinstance(body, dict):
                raise ValueError("response body is not a JSON object")
        except ValueError:
            logger.warning(
                "remote_tool_bad_json", tool=tool_name, status=resp.status_code
            )
            return {
                "content": [{"type": "text", "text": "工具响应解析失败：非 JSON 响应"}],
                "is_error": True,
            }

        if body.get("ok"):
            return {"content": [{"type": "text", "text": str(body.get("result"))}]}
        return {
            "content": [{"type": "text", "text": str(body.get("error"))}],
            "is_error": True,
        }

    return handler


def build_remote_tools_mcp_server(
    remote_tools: list[dict[str, Any]],
    tools_endpoint: str,
    user_token: str,
) -> McpSdkServerConfig | None:
    """从 remote_tools schema 列表构建进程内 SDK MCP server。

    Args:
        remote_tools: RemoteTool schema 列表，每项含 ``name`` / ``description`` /
            ``input_schema``。
        tools_endpoint: Friday Server ``/api/tools/execute/`` 完整 URL。
        user_token: 用户直传 PAT，仅注入 Authorization header（脱敏）。

    Returns:
        ``McpSdkServerConfig``；若 remote_tools / user_token / tools_endpoint 任一为空，
        返回 None（向后兼容，不挂 MCP server）。
    """
    # 向后兼容（CONTEXT 决策）：无工具或无令牌或无端点 → 不挂 MCP server。
    if not remote_tools or not user_token or not tools_endpoint:
        return None

    sdk_tools: list[SdkMcpTool[dict[str, Any]]] = []
    for t in remote_tools:
        # name 缺失/为空 → 跳过该条坏 schema，不让一条坏数据 KeyError 拖垮整个
        # MCP server 构建（与 description/input_schema 的 .get 容错保持一致，WR-04）。
        name = t.get("name")
        if not name:
            logger.warning("remote_tool_missing_name", schema=t)
            continue
        sdk_tools.append(
            SdkMcpTool(
                name=name,
                description=t.get("description", ""),
                input_schema=t.get("input_schema", {}),
                handler=_make_handler(name, tools_endpoint, user_token),
            )
        )

    logger.info(
        "remote_mcp_server_created",
        tool_count=len(sdk_tools),
        tools=[t.name for t in sdk_tools],  # 不打印 token
    )
    return create_sdk_mcp_server(name=REMOTE_MCP_SERVER_NAME, tools=sdk_tools)


def remote_allowed_tools(remote_tools: list[dict[str, Any]]) -> list[str]:
    """生成 allowed_tools 列表，格式 ``mcp__{REMOTE_MCP_SERVER_NAME}__{name}``。

    与 build_remote_tools_mcp_server 一致：跳过无 name 的坏 schema（WR-04），
    避免 ``t["name"]`` 在坏数据上抛 KeyError。
    """
    allowed: list[str] = []
    for t in remote_tools:
        name = t.get("name")
        if not name:
            continue
        allowed.append(f"mcp__{REMOTE_MCP_SERVER_NAME}__{name}")
    return allowed
