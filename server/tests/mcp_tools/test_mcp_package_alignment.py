"""mcp npm 包工具面 == 服务端 snapshot 对齐守卫（quick-260723）。

纯文件读取 + 正则，无 DB。背景：`@friday-ai-codes/mcp` stdio server 以
``mcp/src/tools.ts`` 的 ``FRIDAY_TOOLS`` 为**静态白名单**（未知工具直接拒绝），
历史上曾漂移到只暴露 23/30 个工具——skills 文档引用的 ``reverse_lookup_requirements``
与整组项目上下文工具（``lookup_project_by_branch`` 等）经 MCP 完全调不到，而既有
``test_skills_snapshot_guard`` 只校验「SKILL.md 引用 ⊆ 服务端 snapshot」，拦不住
这种「服务端有、npm 包没有」的漂移。

本守卫补上第三方对齐：``mcp/src/tools.ts`` 工具名集合 **==** ``TOOL_SCHEMA_SNAPSHOT``
键集（双向：包里多出服务端没有的工具、或服务端新工具忘同步进包，CI 都直接红）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT

# server/tests/mcp_tools/ → 上三级 = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_TS = REPO_ROOT / "mcp" / "src" / "tools.ts"

# FRIDAY_TOOLS 条目形如 `name: 'route_repositories',`；annotations 与 schema 字段
# 不带 `name: '` 前缀，不会误报。
_TOOL_NAME_RE = re.compile(r"^\s*name: '([a-z0-9_]+)',$", re.MULTILINE)
_PROPERTY_NAME_RE = re.compile(r"^\s{8}([a-z][a-z0-9_]*):", re.MULTILINE)


def _package_tool_names() -> set[str]:
    return set(_TOOL_NAME_RE.findall(TOOLS_TS.read_text(encoding="utf-8")))


def _package_request_keys(tool_name: str) -> set[str]:
    """只解析指定工具的 ``inputSchema.properties``，不扩大旧工具字段门禁。"""

    source = TOOLS_TS.read_text(encoding="utf-8")
    name_marker = f"name: '{tool_name}',"
    start = source.find(name_marker)
    assert start >= 0, f"{tool_name} 尚未加入 {TOOLS_TS}"
    properties_start = source.find("properties: {", start)
    required_start = source.find("required:", properties_start)
    assert properties_start >= 0 and required_start >= 0, f"{tool_name} inputSchema 结构无法解析"
    return set(_PROPERTY_NAME_RE.findall(source[properties_start:required_start]))


def test_tools_ts_discovered() -> None:
    """防子模块未 checkout / 路径漂移让主守卫静默空跑假绿。"""
    if not TOOLS_TS.exists():
        pytest.skip(
            "mcp/ 子模块未 checkout（本地开发环境按需初始化）；CI 须 checkout 子模块使本守卫生效"
        )
    assert _package_tool_names(), f"未从 {TOOLS_TS} 解析到任何工具名——正则或文件结构漂移"


def test_mcp_package_tools_match_server_snapshot() -> None:
    """mcp/src/tools.ts 工具名集合 == TOOL_SCHEMA_SNAPSHOT 键集（双向对齐）。"""
    if not TOOLS_TS.exists():
        pytest.skip("mcp/ 子模块未 checkout")
    package_names = _package_tool_names()
    server_names = set(TOOL_SCHEMA_SNAPSHOT)

    missing_in_package = sorted(server_names - package_names)
    extra_in_package = sorted(package_names - server_names)
    assert not missing_in_package and not extra_in_package, (
        "mcp npm 包与服务端工具面漂移：\n"
        f"  服务端有、包缺失（agent 经 MCP 调不到）：{missing_in_package}\n"
        f"  包有、服务端缺失（调用必 404）：{extra_in_package}"
    )


def test_report_session_knowledge_serializer_matches_snapshot() -> None:
    """新 serializer 与独立 snapshot 请求键精确一致。"""

    from mcp_tools import serializers as serializer_module

    serializer_cls = getattr(serializer_module, "ReportSessionKnowledgeRequestSerializer", None)
    assert serializer_cls is not None, "ReportSessionKnowledgeRequestSerializer 尚未实现"
    serializer_keys = set(serializer_cls().fields)
    snapshot_keys = set(TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]["request"])
    assert serializer_keys == snapshot_keys


def test_report_session_knowledge_request_keys_aligned() -> None:
    """仅锁新工具 serializer、服务端 snapshot、npm properties 三面对齐。"""

    from mcp_tools import serializers as serializer_module

    serializer_cls = getattr(serializer_module, "ReportSessionKnowledgeRequestSerializer", None)
    assert serializer_cls is not None, "ReportSessionKnowledgeRequestSerializer 尚未实现"
    serializer_keys = set(serializer_cls().fields)
    snapshot_keys = set(TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]["request"])
    package_keys = _package_request_keys("report_session_knowledge")
    assert serializer_keys == snapshot_keys == package_keys


def test_search_session_knowledge_request_keys_aligned() -> None:
    """会话知识检索 serializer、服务端 snapshot、npm properties 三面对齐。"""

    from mcp_tools import serializers as serializer_module

    serializer_cls = getattr(serializer_module, "SearchSessionKnowledgeRequestSerializer", None)
    assert serializer_cls is not None, "SearchSessionKnowledgeRequestSerializer 尚未实现"
    serializer_keys = set(serializer_cls().fields)
    snapshot_keys = set(TOOL_SCHEMA_SNAPSHOT["search_session_knowledge"]["request"])
    package_keys = _package_request_keys("search_session_knowledge")
    assert serializer_keys == snapshot_keys == package_keys
