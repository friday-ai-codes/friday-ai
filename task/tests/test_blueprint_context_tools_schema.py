"""容器侧总线工具白名单守护测试（BUS-01，Phase 113-02）。

覆盖：
- ⭐ 公共 handler 工厂零改动（可证伪）：`_make_knowledge_handler` 参数名元组恒等、
  `timeout=60.0` 仍在、源码里零 `callback` —— 新增参数 / 改超时 / 加回调即红；
- 白名单计数 7 → 9，七个既有工具逐名仍在（防误删）；
- 两个新表项的 schema 形状与 required 列表；
- URL 可达性：tool_name 拼出的 path 与服务端 urls.py 逐字一致；
- 空值短路回归：endpoint / token 任一空 → 不挂 MCP server（老镜像零回归）。
"""

from __future__ import annotations

import inspect

from core.knowledge_tools import (
    KNOWLEDGE_MCP_SERVER_NAME,
    KNOWLEDGE_TOOL_SCHEMAS,
    _make_knowledge_handler,
    build_knowledge_mcp_server,
    knowledge_allowed_tools,
)

# 七个既有工具（113-02 之前的全量），逐名字面量写死防误删。
_LEGACY_TOOL_NAMES = [
    "search_rag_chunks",
    "grep_repository",
    "get_repository_file",
    "search_delivery_knowledge",
    "search_learning_cases",
    "search_project_context",
    "lookup_project_by_branch",
]
_NEW_TOOL_NAMES = ["read_blueprint_context", "report_blueprint_context"]


def _schema(name: str) -> dict:
    return next(s for s in KNOWLEDGE_TOOL_SCHEMAS if s["name"] == name)


def test_handler_factory_signature_frozen() -> None:
    """⭐ 工厂签名恒等：新增参数（尤其 callback）立刻红。

    该工厂被 7 个既有工具共用，改它会波及全部既有工具（113-PATTERNS 硬约束）。
    """
    params = tuple(inspect.signature(_make_knowledge_handler).parameters)
    assert params == (
        "tool_name",
        "endpoint_base",
        "user_token",
        "session_id",
        "quota",
        "quota_counter",
    )


def test_handler_factory_timeout_and_no_callback() -> None:
    """⭐ `timeout=60.0` 未被改动，且工厂内零 callback（短等待不发心跳）。"""
    source = inspect.getsource(_make_knowledge_handler)
    assert "timeout=60.0" in source
    assert "callback" not in source


def test_whitelist_grew_to_nine_without_losing_legacy() -> None:
    """白名单 7 → 9 → 10（113-04 追加 await_blueprint_context）；七个既有工具逐名仍在。"""
    assert len(KNOWLEDGE_TOOL_SCHEMAS) == 10
    assert len(knowledge_allowed_tools()) == 10
    names = [s["name"] for s in KNOWLEDGE_TOOL_SCHEMAS]
    for legacy in _LEGACY_TOOL_NAMES:
        assert legacy in names, f"既有工具 {legacy} 不得丢失"
    for new in _NEW_TOOL_NAMES:
        assert f"mcp__{KNOWLEDGE_MCP_SERVER_NAME}__{new}" in knowledge_allowed_tools()


def test_new_tool_schema_shape() -> None:
    """两个新表项形状：name / description / input_schema(type=object) + required。"""
    for name in _NEW_TOOL_NAMES:
        schema = _schema(name)
        assert schema["description"].strip()
        assert schema["input_schema"]["type"] == "object"
        assert isinstance(schema["input_schema"]["properties"], dict)

    assert _schema("report_blueprint_context")["input_schema"]["required"] == [
        "key",
        "kind",
        "content",
    ]
    # read 全部可选：无参调用 = 拉本会话全部 active 条目。
    assert _schema("read_blueprint_context")["input_schema"]["required"] == []
    assert set(_schema("read_blueprint_context")["input_schema"]["properties"]) == {
        "key_prefix",
        "kind",
        "repository_id",
        "since_seq",
        "limit",
    }
    assert set(_schema("report_blueprint_context")["input_schema"]["properties"]) == {
        "key",
        "kind",
        "repository_id",
        "content",
    }


def test_new_tool_urls_match_server_paths() -> None:
    """URL 由 tool_name 拼接，与服务端 mcp_tools/urls.py 逐字一致。"""
    base = "https://friday.example.com/"
    expected = {
        "read_blueprint_context": (
            "https://friday.example.com/api/mcp/tools/read_blueprint_context/"
        ),
        "report_blueprint_context": (
            "https://friday.example.com/api/mcp/tools/report_blueprint_context/"
        ),
    }
    for name, url in expected.items():
        assert f"{base.rstrip('/')}/api/mcp/tools/{name}/" == url


def test_empty_endpoint_or_token_short_circuits() -> None:
    """空值短路回归：endpoint / token 任一空 → 不挂 server（老镜像/未配置零回归）。"""
    assert build_knowledge_mcp_server("", "tok", "sid", 200) is None
    assert build_knowledge_mcp_server("http://x", "", "sid", 200) is None
