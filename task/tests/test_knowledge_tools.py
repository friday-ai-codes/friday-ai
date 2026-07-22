"""容器知识 MCP（AGENT-02）task 侧测试：降级/白名单/handler 容错/配额/脱敏。

镜像 test_remote_tools.py 测试法（无 live Claude）：SDK MCP server 的 handler 是
普通 async 函数，直接调 ``handler(args)``，monkeypatch ``httpx.AsyncClient.post``
返回伪响应，断言返回结构与脱敏；不 import ``claude_agent_sdk.query``、不触网。

覆盖契约：
- 三要素守门：endpoint / token 任一空 → build 返回 None（存量任务零回归）。
- 端点校验：非法 scheme（javascript:/file://）→ None，绝不向非法端点注入 PAT（T-103-06）。
- 白名单：恰 7 个工具；``knowledge_allowed_tools()`` 前缀正确。
- handler：200 JSON → 文本含业务字段；401 → 固定文案 is_error；500 → 文案不含响应体
  （T-103-05）；非 JSON 200 → 解析失败文案；传输错误 → return 不 raise。
- 配额：quota 用尽后返回配额文案且不再发 HTTP（T-103-07）。
- 头正确：Authorization Bearer + X-Friday-Session-Id。
- 脱敏：日志无 token 明文。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from core.knowledge_tools import (
    KNOWLEDGE_MCP_SERVER_NAME,
    KNOWLEDGE_TOOL_SCHEMAS,
    QUOTA_EXHAUSTED_TEXT,
    _make_knowledge_handler,
    build_knowledge_mcp_server,
    knowledge_allowed_tools,
)

ENDPOINT_BASE = "https://friday.example.com"
SECRET_PAT = "friday_pat_SECRET123"
SESSION_ID = "task-session-abc"

EXPECTED_TOOL_NAMES = [
    "search_rag_chunks",
    "grep_repository",
    "get_repository_file",
    "search_delivery_knowledge",
    "search_learning_cases",
    "search_project_context",
    "lookup_project_by_branch",
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


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: Any) -> list[dict[str, Any]]:
    """monkeypatch httpx.AsyncClient.post 返回伪响应；返回调用记录列表（url/kwargs）。"""
    calls: list[dict[str, Any]] = []

    async def _fake_post(self: Any, url: str, *args: Any, **kwargs: Any) -> Any:
        calls.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    return calls


def _patch_post_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    async def _fake_post(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)


def _handler(quota: int = 200, quota_counter: list[int] | None = None):
    return _make_knowledge_handler(
        "search_rag_chunks",
        ENDPOINT_BASE,
        SECRET_PAT,
        SESSION_ID,
        quota,
        quota_counter if quota_counter is not None else [0],
    )


async def _server_tool_names(config: Any) -> list[str]:
    """从 McpSdkServerConfig 的 instance 读出已注册工具名（调 list_tools 请求处理器）。"""
    from mcp import types as mcp_types

    instance = config["instance"]
    handler = instance.request_handlers[mcp_types.ListToolsRequest]
    result = await handler(mcp_types.ListToolsRequest(method="tools/list"))
    return [t.name for t in result.root.tools]


# =========================================================================
# 三要素守门 + 端点校验（降级零回归）
# =========================================================================


def test_no_endpoint_returns_none() -> None:
    """endpoint 空 → 返回 None（三要素守门，不挂 server，存量任务零回归）。"""
    assert build_knowledge_mcp_server("", SECRET_PAT, SESSION_ID, 200) is None


def test_no_token_returns_none() -> None:
    """token 空 → 返回 None（三要素守门）。"""
    assert build_knowledge_mcp_server(ENDPOINT_BASE, "", SESSION_ID, 200) is None


@pytest.mark.parametrize(
    "bad_endpoint",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://evil.example.com/x",
        "not-a-url",
        "//no-scheme.example.com/x",
    ],
)
def test_invalid_endpoint_returns_none(bad_endpoint: str) -> None:
    """endpoint scheme 非 http/https 或缺 host → None，绝不向非法端点注入 PAT（T-103-06）。"""
    assert build_knowledge_mcp_server(bad_endpoint, SECRET_PAT, SESSION_ID, 200) is None


@pytest.mark.parametrize(
    "ok_endpoint",
    ["https://friday.example.com", "http://localhost:10241"],
)
def test_valid_endpoint_builds_server(ok_endpoint: str) -> None:
    """http/https + 非空 host → 正常构建 server（不误伤合法值）。"""
    assert build_knowledge_mcp_server(ok_endpoint, SECRET_PAT, SESSION_ID, 200) is not None


# =========================================================================
# 白名单：恰 7 个工具 + allowed_tools 前缀
# =========================================================================


@pytest.mark.asyncio
async def test_server_has_exactly_seven_whitelist_tools() -> None:
    """构建出的 server 工具集恰为 7 个白名单名字。"""
    config = build_knowledge_mcp_server(ENDPOINT_BASE, SECRET_PAT, SESSION_ID, 200)
    assert config is not None
    assert config["type"] == "sdk"
    assert config["name"] == KNOWLEDGE_MCP_SERVER_NAME
    names = await _server_tool_names(config)
    assert sorted(names) == sorted(EXPECTED_TOOL_NAMES)


def test_knowledge_allowed_tools_naming() -> None:
    """allowed_tools 为 7 条 mcp__friday-knowledge__{name}。"""
    allowed = knowledge_allowed_tools()
    assert allowed == [f"mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{name}" for name in EXPECTED_TOOL_NAMES]


def test_schemas_required_fields_accurate() -> None:
    """input_schema required 字段对照 serializers.py（抽查关键工具）。"""
    by_name = {s["name"]: s for s in KNOWLEDGE_TOOL_SCHEMAS}
    assert by_name["search_rag_chunks"]["input_schema"]["required"] == ["query"]
    assert by_name["grep_repository"]["input_schema"]["required"] == ["pattern"]
    assert by_name["get_repository_file"]["input_schema"]["required"] == [
        "repository_id",
        "file_path",
    ]
    assert by_name["search_project_context"]["input_schema"]["required"] == [
        "project_id",
        "query",
    ]
    assert by_name["lookup_project_by_branch"]["input_schema"]["required"] == ["branch_name"]


# =========================================================================
# handler：响应解析（200 直接业务 JSON dict，无 {ok} 信封）+ 容错
# =========================================================================


@pytest.mark.asyncio
async def test_handler_200_returns_business_json_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 JSON → 整个 body 序列化为文本返回（含业务字段），无 is_error。"""
    _patch_post(
        monkeypatch,
        _FakeResponse(200, {"results": [{"file_path": "src/main.py"}], "run_id": "r-1"}),
    )
    result = await _handler()({"query": "q", "repository_id": "rid"})

    assert not result.get("is_error")
    text = result["content"][0]["text"]
    assert "src/main.py" in text
    assert "run_id" in text


@pytest.mark.asyncio
async def test_handler_401_fixed_text_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """401（令牌吊销）→ 固定文案 is_error，绝不抛异常。"""
    _patch_post(monkeypatch, _FakeResponse(401, {"error_code": "authentication_failed"}))
    result = await _handler()({})

    assert result.get("is_error") is True
    assert result["content"][0]["text"] == "知识工具不可用：令牌已失效或无权限"


@pytest.mark.asyncio
async def test_handler_500_does_not_echo_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """500 → 文案只含 HTTP code，不回显响应体（构造含 secret 的 body 断言不出现，T-103-05）。"""
    _patch_post(
        monkeypatch,
        _FakeResponse(500, {"detail": "upstream secret-DBPASSWORD leaked in error"}),
    )
    result = await _handler()({})

    assert result.get("is_error") is True
    text = result["content"][0]["text"]
    assert "HTTP 500" in text
    assert "secret-DBPASSWORD" not in str(result)


@pytest.mark.asyncio
async def test_handler_200_non_json_returns_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 但响应体非 JSON（反代/网关 200 + HTML）→ 解析失败文案 is_error，不 raise。"""
    _patch_post(monkeypatch, _BadJsonResponse())
    result = await _handler()({})

    assert result.get("is_error") is True
    assert "解析失败" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_handler_transport_error_returns_not_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx 传输错误 → 捕获并返回 is_error，不冒泡崩容器。"""
    _patch_post_raises(monkeypatch, httpx.ConnectError("connection refused"))
    result = await _handler()({})

    assert result.get("is_error") is True
    assert "传输错误" in result["content"][0]["text"]


# =========================================================================
# 配额守门（T-103-07）
# =========================================================================


@pytest.mark.asyncio
async def test_quota_exhausted_returns_text_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """quota=2 时第 3 次调用返回配额文案且无 HTTP 请求发出（mock 计数为 2）。"""
    calls = _patch_post(monkeypatch, _FakeResponse(200, {"results": [], "run_id": "r"}))
    handler = _handler(quota=2)

    r1 = await handler({"query": "a"})
    r2 = await handler({"query": "b"})
    r3 = await handler({"query": "c"})

    assert len(calls) == 2, "配额用尽后不再发 HTTP"
    assert not r1.get("is_error") and not r2.get("is_error")
    assert r3["content"][0]["text"] == QUOTA_EXHAUSTED_TEXT
    assert not r3.get("is_error"), "配额文案不带 is_error（预算终点非错误）"


@pytest.mark.asyncio
async def test_quota_exhausted_warning_logged_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配额用尽 warning 只打一条（103 审查 IN-04）：agent 用尽后反复调工具不刷屏，
    后续调用静默返回文案。"""
    import structlog

    _patch_post(monkeypatch, _FakeResponse(200, {"results": [], "run_id": "r"}))
    handler = _handler(quota=1)

    await handler({"query": "a"})  # 消耗配额
    with structlog.testing.capture_logs() as captured:
        r2 = await handler({"query": "b"})
        r3 = await handler({"query": "c"})
        r4 = await handler({"query": "d"})

    exhausted_events = [e for e in captured if e["event"] == "knowledge_tool_quota_exhausted"]
    assert len(exhausted_events) == 1, "用尽 warning 只打首次一条"
    assert exhausted_events[0]["quota_used"] == 1
    for r in (r2, r3, r4):
        assert r["content"][0]["text"] == QUOTA_EXHAUSTED_TEXT
        assert not r.get("is_error")


@pytest.mark.asyncio
async def test_quota_counter_shared_across_tools() -> None:
    """server 内 7 工具共享同一闭包计数器：build 后不同工具消耗同一预算。"""
    from mcp import types as mcp_types

    config = build_knowledge_mcp_server(ENDPOINT_BASE, SECRET_PAT, SESSION_ID, 1)
    assert config is not None
    instance = config["instance"]
    call_handler = instance.request_handlers[mcp_types.CallToolRequest]

    async def _call(tool: str, arguments: dict) -> str:
        req = mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(name=tool, arguments=arguments),
        )
        result = await call_handler(req)
        return result.root.content[0].text

    # 第 1 次（transport error：无 mock 网络，ConnectError 也消耗配额）
    text1 = await _call("search_rag_chunks", {"query": "q"})
    # 第 2 次换一个工具，配额已被第 1 次用完 → 返回配额文案
    text2 = await _call("grep_repository", {"pattern": "p"})

    assert text1 != QUOTA_EXHAUSTED_TEXT
    assert text2 == QUOTA_EXHAUSTED_TEXT


# =========================================================================
# 请求头正确性：Authorization Bearer + X-Friday-Session-Id + URL 拼接
# =========================================================================


@pytest.mark.asyncio
async def test_request_carries_auth_and_session_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """请求携带 Authorization Bearer 与 X-Friday-Session-Id；body 直接为业务参数 dict。"""
    calls = _patch_post(monkeypatch, _FakeResponse(200, {"run_id": "r"}))
    await _handler()({"query": "q", "repository_id": "rid"})

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == f"{ENDPOINT_BASE}/api/mcp/tools/search_rag_chunks/"
    assert call["headers"]["Authorization"] == f"Bearer {SECRET_PAT}"
    assert call["headers"]["X-Friday-Session-Id"] == SESSION_ID
    # body 直接是业务参数（无 {name, arguments} 信封）
    assert call["json"] == {"query": "q", "repository_id": "rid"}
    assert call["timeout"] == 60.0


@pytest.mark.asyncio
async def test_endpoint_trailing_slash_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """endpoint_base 带尾斜杠 → URL 不出现双斜杠。"""
    calls = _patch_post(monkeypatch, _FakeResponse(200, {"run_id": "r"}))
    handler = _make_knowledge_handler(
        "grep_repository", ENDPOINT_BASE + "/", SECRET_PAT, SESSION_ID, 200, [0]
    )
    await handler({"pattern": "x"})

    assert calls[0]["url"] == f"{ENDPOINT_BASE}/api/mcp/tools/grep_repository/"


# =========================================================================
# 脱敏：PAT 绝不进日志 / 返回文本（T-103-05）
# =========================================================================


@pytest.mark.asyncio
async def test_token_not_in_logs_or_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功 + 401 + 传输错误三路：日志与 handler 返回文本均不含 PAT 明文。"""
    import structlog

    handler = _handler()

    _patch_post(monkeypatch, _FakeResponse(200, {"results": [], "run_id": "r"}))
    with structlog.testing.capture_logs() as captured_ok:
        result_ok = await handler({"q": "v"})

    _patch_post(monkeypatch, _FakeResponse(401, {"detail": "revoked"}))
    with structlog.testing.capture_logs() as captured_401:
        result_401 = await handler({"q": "v"})

    _patch_post_raises(monkeypatch, httpx.ConnectError("refused"))
    with structlog.testing.capture_logs() as captured_err:
        result_err = await handler({"q": "v"})

    all_logs_text = str(captured_ok) + str(captured_401) + str(captured_err)
    assert SECRET_PAT not in all_logs_text, "PAT 绝不进日志"
    assert SECRET_PAT not in str(result_ok) + str(result_401) + str(result_err), (
        "PAT 绝不进返回文本"
    )


@pytest.mark.asyncio
async def test_logs_do_not_contain_args_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """日志只记 tool/status/耗时/配额，不记入参明文。"""
    import structlog

    _patch_post(monkeypatch, _FakeResponse(200, {"run_id": "r"}))
    with structlog.testing.capture_logs() as captured:
        await _handler()({"query": "SENSITIVE-QUERY-CONTENT"})

    assert "SENSITIVE-QUERY-CONTENT" not in str(captured), "入参明文绝不进日志"


def test_build_logs_do_not_contain_endpoint_url() -> None:
    """build 日志不记 endpoint 完整 URL 与 token。"""
    import structlog

    with structlog.testing.capture_logs() as captured:
        build_knowledge_mcp_server("https://internal-host.example.com", SECRET_PAT, SESSION_ID, 200)

    text = str(captured)
    assert SECRET_PAT not in text
    assert "internal-host.example.com" not in text
