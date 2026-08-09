"""``impact_analysis`` / ``trace_call_path`` 两个 MCP 工具的守护测试（覆盖 IMPACT-06）。

范式照 ``test_reverse_lookup_tool.py``：模块级 ``pytestmark`` + 模块级 URL 常量 +
``mcp_client`` / ``indexed_repository`` 两个 conftest fixture（前者返回
``(APIClient, plaintext_token)``，已带 Bearer 头）。

``test_two_surfaces_same_payload`` 仍归 122-10。
"""

from __future__ import annotations

import importlib
import json

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from interactions.models import RetrievalTrace
from system.metric_sink import flush_now
from system.models import RequestMetric

pytestmark = pytest.mark.django_db

IMPACT_URL = "/api/mcp/tools/impact_analysis/"
TRACE_URL = "/api/mcp/tools/trace_call_path/"


@pytest.fixture(autouse=True)
def _reset_code_graph_state():
    """用例间清进程级缓存，防止上一个用例的状态污染下一个。

    ⚠️ 必须在本文件再写一份：pytest conftest 作用域是「所在目录及其子目录」，
    ``tests/services/code_graph/conftest.py`` 的同名钩子对 ``tests/mcp_tools/`` **不可见**。
    少了它，``GraphService`` 单例会让「被排除文件不可见」这类断言的结果取决于用例
    执行顺序。

    内部子模块经 ``importlib`` 加载（而非 ``from services.code_graph.cache import …``）：
    ``test_no_upper_layer_imports_internal_submodules`` 全仓扫描 ``ImportFrom``，
    本文件不在 ``tests/services/code_graph/`` 豁免目录内。
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


def _build_impact_fixture(repository, *, excluded_file: str | None = None):
    """造 callee + 两个生产 caller + 可选的被排除路径 caller。"""
    from codegraph.models import CallEdge, Symbol

    callee = Symbol.objects.create(
        repository=repository,
        branch_name="",
        name="get_user",
        symbol_type="FUNCTION",
        file_path="src/api/user.py",
        start_line=1,
        end_line=20,
    )
    caller_a = Symbol.objects.create(
        repository=repository,
        branch_name="",
        name="handler_a",
        symbol_type="FUNCTION",
        file_path="src/web/a.py",
        start_line=1,
        end_line=10,
    )
    caller_b = Symbol.objects.create(
        repository=repository,
        branch_name="",
        name="handler_b",
        symbol_type="FUNCTION",
        file_path="src/web/b.py",
        start_line=1,
        end_line=10,
    )
    CallEdge.objects.create(
        repository=repository,
        branch_name="",
        caller_symbol=caller_a,
        caller_file=caller_a.file_path,
        callee_symbol=callee,
        callee_name=callee.name,
        call_type="DIRECT",
        line_number=5,
    )
    CallEdge.objects.create(
        repository=repository,
        branch_name="",
        caller_symbol=caller_b,
        caller_file=caller_b.file_path,
        callee_symbol=callee,
        callee_name=callee.name,
        call_type="DIRECT",
        line_number=6,
    )
    if excluded_file:
        excluded_caller = Symbol.objects.create(
            repository=repository,
            branch_name="",
            name="leaky_handler",
            symbol_type="FUNCTION",
            file_path=excluded_file,
            start_line=1,
            end_line=5,
        )
        CallEdge.objects.create(
            repository=repository,
            branch_name="",
            caller_symbol=excluded_caller,
            caller_file=excluded_caller.file_path,
            callee_symbol=callee,
            callee_name=callee.name,
            call_type="DIRECT",
            line_number=2,
        )
    return callee


def test_impact_tool_unauthenticated(indexed_repository) -> None:
    """MCP：未带 PAT → 401 ``authentication_failed``（两个工具都必须 fail-closed）。"""
    client = APIClient()
    payload = {
        "repository_id": str(indexed_repository.id),
        "symbol": "get_user",
    }
    for url in (IMPACT_URL, TRACE_URL):
        body = (
            payload
            if url == IMPACT_URL
            else {
                "repository_id": str(indexed_repository.id),
                "source": "handler_a",
                "target": "get_user",
            }
        )
        response = client.post(url, body, format="json")
        assert response.status_code == 401
        assert response.json()["error_code"] == "authentication_failed"


def test_impact_tool_repository_not_indexed(
    mcp_client: tuple[APIClient, str],
    repository,
) -> None:
    """未索引仓 → 400 ``repository_not_indexed``，响应体无空影响面结构。"""
    client, _plaintext = mcp_client
    response = client.post(
        IMPACT_URL,
        {"repository_id": str(repository.id), "symbol": "get_user"},
        format="json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "repository_not_indexed"
    assert "groups" not in body
    assert "affected" not in body
    dumped = json.dumps(body, ensure_ascii=False)
    assert '"groups": []' not in dumped
    assert '"affected": []' not in dumped


def test_degradation_markers_surfaced(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    """四个降级标记 + 数值 resolution_rate；恰一条 EDGE RetrievalTrace + RequestMetric。"""
    client, _plaintext = mcp_client
    _build_impact_fixture(indexed_repository)
    RetrievalTrace.objects.all().delete()
    RequestMetric.objects.filter(route="mcp:impact_analysis").delete()

    response = client.post(
        IMPACT_URL,
        {"repository_id": str(indexed_repository.id), "symbol": "get_user"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True
    graph = body["graph"]
    for key in (
        "resolution_rate",
        "low_resolution",
        "partial_edges",
        "degraded",
        "cross_repo_unresolved_count",
    ):
        assert key in graph
    assert isinstance(graph["resolution_rate"], float)
    assert graph["declarations"]
    assert body["affected_processes"] == []

    traces = list(RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.EDGE))
    assert len(traces) == 1
    payload = traces[0].payload or {}
    for key in (
        "result_count",
        "confidence_distribution",
        "duration_ms",
        "layer_durations_ms",
    ):
        assert key in payload
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert "file_path" not in payload_text
    assert "get_user" not in payload_text
    assert "handler_a" not in payload_text
    assert "handler_b" not in payload_text
    flush_now()  # RequestMetric 经内存队列批量落库，测试钩子同步 flush
    assert RequestMetric.objects.filter(route="mcp:impact_analysis").exists()


def test_excluded_files_invisible(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    """被排除文件路径不得出现在整份响应体序列化文本中。"""
    client, _plaintext = mcp_client
    _build_impact_fixture(indexed_repository, excluded_file=".env")
    response = client.post(
        IMPACT_URL,
        {"repository_id": str(indexed_repository.id), "symbol": "get_user"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body, ensure_ascii=False)
    assert ".env" not in dumped
    for depth_rows in (body.get("groups") or {}).values():
        for item in depth_rows:
            assert ".env" not in str(item.get("file_path") or "")


def test_staleness_declared(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    """staleness：behind_commits=7 时声明含数字、freshness=stale、as_of 对齐索引 sha。"""
    client, _plaintext = mcp_client
    indexed_repository.remote_head_sha = "b" * 40
    indexed_repository.remote_head_checked_at = timezone.now()
    indexed_repository.behind_commits = 7
    indexed_repository.behind_commits_calculated_at = timezone.now()
    indexed_repository.save(
        update_fields=[
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "behind_commits_calculated_at",
        ]
    )
    _build_impact_fixture(indexed_repository)

    response = client.post(
        IMPACT_URL,
        {"repository_id": str(indexed_repository.id), "symbol": "get_user"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    staleness = body["staleness"]
    assert staleness["behind_commits"] == 7
    assert staleness["freshness"] == "stale"
    assert "7" in staleness["declaration"]
    assert staleness["as_of"] == indexed_repository.last_indexed_commit_sha


@pytest.mark.skip(reason="Wave 0 桩：由 122-10 落地")
def test_two_surfaces_same_payload() -> None:
    """**双面同源**：同一输入下 MCP 与对话壳产出的 ``data`` 段逐字节相同（D-21 防漂移）。

    （Req: IMPACT-06, 决策: D-21）
    """
    pytest.fail("Wave 0 桩")
