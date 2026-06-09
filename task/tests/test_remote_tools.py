"""RTOOL-02/03/04 task 侧 RED 脚手架：SDK MCP server 构建 + 工具 handler 回调 + 脱敏。

本文件钉死 RemoteTool 闭环在 task 容器侧的可验证行为契约：
- RTOOL-02：从 `remote_tools` schema 列表动态注册 N 个 SdkMcpTool；无工具/无令牌/无端点 → 不挂 server（向后兼容）。
- RTOOL-03：PAT 仅进 Authorization header，绝不进日志/返回文本（脱敏）。
- RTOOL-04：工具回调命中 401/吊销 → 返回结构化工具错误（is_error），绝不抛异常 / 崩溃容器。

测试法（无 live Claude）：SDK MCP server 的 handler 是普通 async 函数，直接调 `handler(args)`，
monkeypatch `httpx.AsyncClient.post` 返回伪响应，断言返回结构与脱敏；**不** import
`claude_agent_sdk.query`、不依赖真实网络。

impl（`task/core/remote_tools.py`）落地前：`importorskip` 优雅跳过（无 collection error）；
落地后即为硬断言。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

# impl 未落地 → 优雅 skip，无 collection error（mirror Phase 10 10-01 守卫范式）。
remote_tools_mod = pytest.importorskip("core.remote_tools")

build_remote_tools_mcp_server = getattr(
    remote_tools_mod, "build_remote_tools_mcp_server", None
)
_make_handler = getattr(remote_tools_mod, "_make_handler", None)
remote_allowed_tools = getattr(remote_tools_mod, "remote_allowed_tools", None)
REMOTE_MCP_SERVER_NAME = getattr(remote_tools_mod, "REMOTE_MCP_SERVER_NAME", "")

TOOLS_ENDPOINT = "https://friday.example.com/api/tools/execute/"
SECRET_PAT = "friday_pat_SECRET123"

TWO_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "a",
        "description": "da",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "b",
        "description": "db",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class _FakeResponse:
    """伪 httpx 响应：仅暴露 status_code + json()，供 handler 单测。"""

    def __init__(self, status_code: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


class _BadJsonResponse:
    """200 但响应体非 JSON：``json()`` 抛 ValueError（模拟反代/网关返回 text/html）。"""

    status_code = 200

    def json(self) -> Any:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    async def _fake_post(self: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)


def _patch_post_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    async def _fake_post(self: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        raise exc

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)


async def _server_tool_names(config: Any) -> list[str]:
    """从 McpSdkServerConfig 的 instance 读出已注册工具名（调 list_tools 请求处理器）。"""
    from mcp import types as mcp_types

    instance = config["instance"]
    handler = instance.request_handlers[mcp_types.ListToolsRequest]
    result = await handler(mcp_types.ListToolsRequest(method="tools/list"))
    return [t.name for t in result.root.tools]


# =========================================================================
# RTOOL-02：SDK MCP server 构建 + 向后兼容
# =========================================================================


@pytest.mark.asyncio
async def test_builds_n_tools() -> None:
    """2 条 schema + 非空 token + endpoint → 构建含 2 个工具（名为 a/b）的 MCP server。"""
    config = build_remote_tools_mcp_server(TWO_SCHEMAS, TOOLS_ENDPOINT, SECRET_PAT)
    assert config is not None
    assert config["type"] == "sdk"
    assert config["name"] == REMOTE_MCP_SERVER_NAME
    names = await _server_tool_names(config)
    assert sorted(names) == ["a", "b"]


def test_no_remote_tools_returns_none() -> None:
    """无 remote_tools → 返回 None（向后兼容，不挂 server）。"""
    assert build_remote_tools_mcp_server([], TOOLS_ENDPOINT, SECRET_PAT) is None


def test_no_token_returns_none() -> None:
    """无用户令牌 → 返回 None（向后兼容，不挂 server）。"""
    assert build_remote_tools_mcp_server(TWO_SCHEMAS, TOOLS_ENDPOINT, "") is None


def test_no_endpoint_returns_none() -> None:
    """无工具端点 → 返回 None（向后兼容，不挂 server）。"""
    assert build_remote_tools_mcp_server(TWO_SCHEMAS, "", SECRET_PAT) is None


def test_remote_allowed_tools_naming() -> None:
    """allowed_tools 名格式为 mcp__{REMOTE_MCP_SERVER_NAME}__{name}。"""
    allowed = remote_allowed_tools(TWO_SCHEMAS)
    assert allowed == [
        f"mcp__{REMOTE_MCP_SERVER_NAME}__a",
        f"mcp__{REMOTE_MCP_SERVER_NAME}__b",
    ]


@pytest.mark.asyncio
async def test_malformed_schema_without_name_skipped() -> None:
    """schema 列表中一条缺 name → 跳过坏条，不抛 KeyError，其余工具正常注册（WR-04）。"""
    schemas: list[dict[str, Any]] = [
        {"name": "a", "input_schema": {}},
        {"description": "no name", "input_schema": {}},  # 坏条：缺 name
    ]
    config = build_remote_tools_mcp_server(schemas, TOOLS_ENDPOINT, SECRET_PAT)
    assert config is not None
    names = await _server_tool_names(config)
    assert names == ["a"]


def test_remote_allowed_tools_skips_missing_name() -> None:
    """remote_allowed_tools 同样跳过无 name 的坏 schema，不抛 KeyError（WR-04）。"""
    schemas: list[dict[str, Any]] = [{"name": "a"}, {"description": "no name"}]
    assert remote_allowed_tools(schemas) == [f"mcp__{REMOTE_MCP_SERVER_NAME}__a"]


# =========================================================================
# RTOOL-02：handler 成功路径
# =========================================================================


@pytest.mark.asyncio
async def test_handler_success_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """handler 收 200 + {ok, result} → 返回 content 文本（含 result），无 is_error。"""
    _patch_post(monkeypatch, _FakeResponse(200, {"ok": True, "result": "DONE"}))
    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    result = await handler({"x": 1})

    assert "content" in result
    text = result["content"][0]["text"]
    assert "DONE" in text
    assert not result.get("is_error")


# =========================================================================
# RTOOL-04：吊销 / 异常 graceful（返回结构化错误，绝不抛）
# =========================================================================


@pytest.mark.asyncio
async def test_handler_401_returns_tool_error_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handler 收 401（令牌吊销）→ 返回 is_error 结构化错误，**绝不抛异常**（RTOOL-04 graceful）。"""
    _patch_post(monkeypatch, _FakeResponse(401, {"detail": "token revoked"}))
    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    result = await handler({})

    assert result.get("is_error") is True
    assert "content" in result


@pytest.mark.asyncio
async def test_handler_transport_error_graceful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handler 遇 httpx 传输错误 → 捕获并返回 is_error，不冒泡。"""
    _patch_post_raises(monkeypatch, httpx.HTTPError("connection refused"))
    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    result = await handler({})

    assert result.get("is_error") is True


@pytest.mark.asyncio
async def test_handler_non200_returns_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handler 收 500 → 返回 is_error，不抛。"""
    _patch_post(monkeypatch, _FakeResponse(500, {"error": "boom"}))
    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    result = await handler({})

    assert result.get("is_error") is True


@pytest.mark.asyncio
async def test_handler_200_non_json_returns_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handler 收 200 但响应体非 JSON（resp.json() 抛 ValueError）→ 返回 is_error，
    **绝不抛异常**（RTOOL-04 graceful / WR-01：反代返回 200 + HTML 也不崩容器）。
    """
    _patch_post(monkeypatch, _BadJsonResponse())
    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    result = await handler({})

    assert result.get("is_error") is True
    assert "content" in result


# =========================================================================
# RTOOL-03：脱敏 —— PAT 绝不进日志 / 返回文本
# =========================================================================


@pytest.mark.asyncio
async def test_token_not_in_logs_or_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功 + 401 两路：捕获日志文本与 handler 返回文本均不含 PAT 明文（T-11-01）。"""
    import structlog

    handler = _make_handler("a", TOOLS_ENDPOINT, SECRET_PAT)

    # 成功路
    _patch_post(monkeypatch, _FakeResponse(200, {"ok": True, "result": "DONE"}))
    with structlog.testing.capture_logs() as captured_ok:
        result_ok = await handler({"q": "v"})

    # 401 路
    _patch_post(monkeypatch, _FakeResponse(401, {"detail": "revoked"}))
    with structlog.testing.capture_logs() as captured_401:
        result_401 = await handler({"q": "v"})

    all_logs_text = str(captured_ok) + str(captured_401)
    assert SECRET_PAT not in all_logs_text, "PAT 绝不进日志"
    assert SECRET_PAT not in str(result_ok), "PAT 绝不进返回文本"
    assert SECRET_PAT not in str(result_401), "PAT 绝不进返回文本"
