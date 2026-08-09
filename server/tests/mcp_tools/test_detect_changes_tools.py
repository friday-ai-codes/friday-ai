"""``detect_changes`` MCP + 对话双面守护用例桩（覆盖 IMPACT-06 延续 / D-13）。

范式照 ``test_impact_trace_tools.py``：模块级 ``pytestmark`` + URL 常量 +
``mcp_client`` fixture。

⛔ 不得 mock ``run_detect_changes``——双面哨兵必须打真实共享编排（或同源真实路径），
否则 MCP↔对话同源断言失去意义。

Wave 0（Plan 123-00）只登记节点；MCP 壳由 123-03、对话壳由 123-04、
双面/trace 由 123-05 填实。
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.django_db

DETECT_CHANGES_URL = "/api/mcp/tools/detect_changes/"


@pytest.fixture(autouse=True)
def _reset_code_graph_state():
    """用例间清进程级缓存，防止上一个用例的状态污染下一个。

    ⚠️ 必须在本文件再写一份：pytest conftest 作用域是「所在目录及其子目录」，
    ``tests/services/code_graph/conftest.py`` 的同名钩子对 ``tests/mcp_tools/`` **不可见**。
    """
    from services.exclusion import invalidate_matcher_cache

    def _reset() -> None:
        invalidate_matcher_cache()
        try:
            access = importlib.import_module("services.code_graph.access")
        except ImportError:
            pass
        else:
            access.invalidate_matcher_fingerprint_cache()

        try:
            cache = importlib.import_module("services.code_graph.cache")
        except ImportError:
            return
        cache._reset_for_tests()

    _reset()
    yield
    _reset()


@pytest.mark.skip(reason="Wave 0 桩：由 123-03 落地")
def test_mcp_detect_changes_requires_pat() -> None:
    """无 PAT → 401（fail-closed）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 123-03 落地")
def test_mcp_detect_changes_success_envelope() -> None:
    """MCP 成功信封含 ok / staleness / affected 字段形状。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 123-04 落地")
def test_conversational_detect_changes_registered() -> None:
    """对话侧 detect_changes @tool 已注册且 schema 对齐。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 123-05 落地")
def test_two_surfaces_same_payload_detect_changes() -> None:
    """MCP↔对话 data 逐字节同源（去 run_id）；含成功 + 硬错误态。"""
    pytest.fail("Wave 0 桩")


def test_tool_trace_payload_detect_changes_counts_only() -> None:
    """RetrievalTrace 只记计数，无路径/符号名（T-123-TRACE）。

    本用例无 DB：构造假编排信封 → ``tool_trace_payload`` → 序列化文本断言。
    MCP 壳接线由 123-03/05 覆盖；计数分支在本 plan（123-02）转绿。
    """
    import json

    from services.code_graph_tools import tool_trace_payload

    fake = {
        "ok": True,
        "tool": "detect_changes",
        "repository_id": "repo-uuid-1",
        "diff_base_sha": "a" * 40,
        "diff_head_sha": "b" * 40,
        "files": [
            {
                "path": "src/secret_leak.py",
                "change_type": "modified",
                "symbols": [
                    {
                        "uid": "sym-1",
                        "name": "leaky_helper",
                        "file_path": "src/secret_leak.py",
                        "changeType": "modified",
                        "impact_seed": True,
                    }
                ],
            }
        ],
        "impacts": [
            {"symbol_id": "sym-1", "impact": {"ok": True}},
            {
                "symbol_id": "sym-2",
                "impact_error": "graph_unavailable",
                "unavailable_reason": "x",
            },
        ],
        "summary": {
            "affected_symbol_count": 1,
            "impact_seed_count": 1,
            "truncated": False,
            "not_expanded": False,
            "file_count": 1,
        },
        "graph": {"resolution_rate": 0.17, "degraded": ""},
    }
    payload = tool_trace_payload(
        fake, tool="detect_changes", duration_ms=12, orchestration_ms=8
    )
    assert isinstance(payload, dict)
    assert payload["result_count"] == 1
    assert payload["total_found"] == 1
    assert payload["files_touched"] == 1
    assert payload["impacts_ok"] == 1
    assert payload["impacts_failed"] == 1
    assert payload["truncated"] == 0
    assert payload["risk_level"] == ""
    assert payload["cross_repo_entry_count"] == 0

    dumped = json.dumps(payload, ensure_ascii=False)
    assert "file_path" not in dumped
    assert "secret_leak" not in dumped
    assert "leaky_helper" not in dumped
    assert "src/" not in dumped
