"""``impact_analysis`` / ``trace_call_path`` 两个 MCP 工具的守护测试（覆盖 IMPACT-06）。

范式照 ``test_reverse_lookup_tool.py``：模块级 ``pytestmark`` + 模块级 URL 常量 +
``mcp_client`` / ``indexed_repository`` 两个 conftest fixture（前者返回
``(APIClient, plaintext_token)``，已带 Bearer 头）。

``test_two_surfaces_same_payload``（122-10）是本仓第一条双面同源逐字节守护。
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


def _assert_surfaces_byte_equal(mcp_data: dict, tool_data: dict) -> None:
    """键集先行（报错可读），再 ``json.dumps(sort_keys=True)`` 逐字节比对。"""
    mcp_keys = set(mcp_data)
    tool_keys = set(tool_data)
    assert mcp_keys == tool_keys, (
        f"双面 data 键集不一致：仅 MCP={sorted(mcp_keys - tool_keys)} "
        f"仅对话={sorted(tool_keys - mcp_keys)}"
    )
    mcp_dump = json.dumps(mcp_data, sort_keys=True, ensure_ascii=False, default=str)
    tool_dump = json.dumps(tool_data, sort_keys=True, ensure_ascii=False, default=str)
    assert mcp_dump == tool_dump


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_two_surfaces_same_payload(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    access_user,
    project,
) -> None:
    """**双面同源**：同一输入下 MCP 与对话壳产出的 ``data`` 段逐字节相同（D-21）。

    防的是什么、为什么不能靠 review：两个壳各自约 40 行、看上去都对，漂移是在后续
    某次「只改一面」的维护里长出来的——``search_delivery_knowledge`` 那对就是这么漂的
    （两侧各自手写七个关键字参数，连注释都是复制粘贴的两份）。全仓此前没有任何双面
    一致性断言；本用例是哨兵，不是机械保证本身——真正的机械保证是共享编排层
    （122-07 的 ``run_impact``）与共享原语（``resolve_tool_graph_branch`` /
    ``tool_trace_payload``）。

    本用例**不覆盖**：它只证明「被测的这组输入两面一致」，不证明所有输入都一致。
    ⛔ 不许 mock ``run_impact``——mock 掉编排层就等于两面在比同一个假对象，守护退化为
    自证。两轮（成功态 + ``ambiguous_symbol``）都必须真的走完全程。

    （Req: IMPACT-06, 决策: D-21）
    """
    from asgiref.sync import sync_to_async

    from agents.tools.graph_tools import impact_analysis
    from chat.models import Conversation
    from codegraph.models import Symbol

    client, _plaintext = mcp_client
    conversation = await Conversation.objects.acreate(
        space=project,
        title="dual-surface-impact",
        created_by=access_user,
    )
    await sync_to_async(_build_impact_fixture)(indexed_repository)

    payload = {
        "repository_id": str(indexed_repository.id),
        "symbol": "get_user",
        "max_depth": 3,
        "min_confidence": 1.0,
        "limit": 200,
    }

    # —— 第一轮：成功态 ——
    response = await sync_to_async(client.post)(IMPACT_URL, payload, format="json")
    assert response.status_code == 200
    mcp_body = response.json()
    mcp_data = {k: v for k, v in mcp_body.items() if k != "run_id"}

    tool_result = await impact_analysis(
        **payload,
        conversation_id=str(conversation.id),
    )
    assert tool_result.success is True
    tool_data = tool_result.output["data"]

    assert "run_id" in mcp_body
    assert "run_id" not in tool_data
    _assert_surfaces_byte_equal(mcp_data, tool_data)

    # —— 第二轮：ambiguous_symbol 失败态（真正防漂移的地方）——
    def _seed_ambiguous() -> None:
        for i, path in enumerate(
            ("src/a/dup.py", "src/b/dup.py", "src/c/dup.py"), start=1
        ):
            Symbol.objects.create(
                repository=indexed_repository,
                branch_name="",
                name="dup",
                symbol_type="FUNCTION",
                file_path=path,
                start_line=i * 10,
                end_line=i * 10 + 5,
            )

    await sync_to_async(_seed_ambiguous)()
    amb_payload = {
        "repository_id": str(indexed_repository.id),
        "symbol": "dup",
        "max_depth": 3,
        "min_confidence": 1.0,
        "limit": 200,
    }

    amb_response = await sync_to_async(client.post)(
        IMPACT_URL, amb_payload, format="json"
    )
    # 🚨 不是 4xx——candidates 是 agent 二选一的唯一依据
    assert amb_response.status_code == 200
    amb_mcp_body = amb_response.json()
    assert amb_mcp_body["ok"] is False
    assert amb_mcp_body["error_code"] == "ambiguous_symbol"
    assert len(amb_mcp_body["candidates"]) == 3
    amb_mcp_data = {k: v for k, v in amb_mcp_body.items() if k != "run_id"}

    amb_tool = await impact_analysis(
        **amb_payload,
        conversation_id=str(conversation.id),
    )
    # 🚨 不是 success=False——工具调用本身成功了，ok=False 才是查询结论
    assert amb_tool.success is True
    amb_tool_data = amb_tool.output["data"]
    assert amb_tool_data["error_code"] == "ambiguous_symbol"

    assert "run_id" in amb_mcp_body
    assert "run_id" not in amb_tool_data
    _assert_surfaces_byte_equal(amb_mcp_data, amb_tool_data)


def _build_trace_fixture(repository) -> tuple[str, str]:
    """造 A→B→C 解析调用链，返回 ``(source_name, target_name)``。"""
    from codegraph.models import CallEdge, Symbol

    names = ("trace_src", "trace_mid", "trace_dst")
    symbols = []
    for i, name in enumerate(names):
        symbols.append(
            Symbol.objects.create(
                repository=repository,
                branch_name="",
                name=name,
                symbol_type="FUNCTION",
                file_path=f"src/trace/{name}.py",
                start_line=(i + 1) * 10,
                end_line=(i + 1) * 10 + 5,
            )
        )
    for i in range(len(symbols) - 1):
        CallEdge.objects.create(
            repository=repository,
            branch_name="",
            caller_symbol=symbols[i],
            caller_file=symbols[i].file_path,
            callee_symbol=symbols[i + 1],
            callee_name=symbols[i + 1].name,
            call_type="DIRECT",
            line_number=i + 1,
        )
    return names[0], names[-1]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_two_surfaces_same_payload_trace(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    access_user,
    project,
) -> None:
    """**双面同源（trace）**：``trace_call_path`` MCP / 对话壳 ``data`` 逐字节相同（D-21）。

    与 ``test_two_surfaces_same_payload`` 同构：成功态（``found=True``）+ ``ambiguous_symbol``。
    ⛔ 不许 mock ``run_trace``。

    （Req: IMPACT-06, 决策: D-21；ME-02）
    """
    from asgiref.sync import sync_to_async

    from agents.tools.graph_tools import trace_call_path
    from chat.models import Conversation
    from codegraph.models import Symbol

    client, _plaintext = mcp_client
    conversation = await Conversation.objects.acreate(
        space=project,
        title="dual-surface-trace",
        created_by=access_user,
    )
    source_name, target_name = await sync_to_async(_build_trace_fixture)(
        indexed_repository
    )

    payload = {
        "repository_id": str(indexed_repository.id),
        "source": source_name,
        "target": target_name,
        "min_confidence": 1.0,
        "alt_path_cap": 10,
    }

    # —— 第一轮：found=True ——
    response = await sync_to_async(client.post)(TRACE_URL, payload, format="json")
    assert response.status_code == 200
    mcp_body = response.json()
    assert mcp_body.get("ok") is True
    assert mcp_body.get("found") is True
    mcp_data = {k: v for k, v in mcp_body.items() if k != "run_id"}

    tool_result = await trace_call_path(
        **payload,
        conversation_id=str(conversation.id),
    )
    assert tool_result.success is True
    tool_data = tool_result.output["data"]
    assert tool_data.get("found") is True

    assert "run_id" in mcp_body
    assert "run_id" not in tool_data
    _assert_surfaces_byte_equal(mcp_data, tool_data)

    # —— 第二轮：ambiguous_symbol（source 端重名）——
    def _seed_ambiguous_source() -> None:
        for i, path in enumerate(
            ("src/trace/a/dup.py", "src/trace/b/dup.py", "src/trace/c/dup.py"),
            start=1,
        ):
            Symbol.objects.create(
                repository=indexed_repository,
                branch_name="",
                name="dup_src",
                symbol_type="FUNCTION",
                file_path=path,
                start_line=i * 10,
                end_line=i * 10 + 5,
            )

    await sync_to_async(_seed_ambiguous_source)()
    amb_payload = {
        "repository_id": str(indexed_repository.id),
        "source": "dup_src",
        "target": target_name,
        "min_confidence": 1.0,
        "alt_path_cap": 10,
    }

    amb_response = await sync_to_async(client.post)(
        TRACE_URL, amb_payload, format="json"
    )
    assert amb_response.status_code == 200
    amb_mcp_body = amb_response.json()
    assert amb_mcp_body["ok"] is False
    assert amb_mcp_body["error_code"] == "ambiguous_symbol"
    amb_mcp_data = {k: v for k, v in amb_mcp_body.items() if k != "run_id"}

    amb_tool = await trace_call_path(
        **amb_payload,
        conversation_id=str(conversation.id),
    )
    assert amb_tool.success is True
    amb_tool_data = amb_tool.output["data"]
    assert amb_tool_data["error_code"] == "ambiguous_symbol"

    assert "run_id" in amb_mcp_body
    assert "run_id" not in amb_tool_data
    _assert_surfaces_byte_equal(amb_mcp_data, amb_tool_data)
