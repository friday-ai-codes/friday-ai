"""impact 壳层编排的异常与短路分支（覆盖 D-24 / D-03 / D-19）。

与 ``test_impact.py`` 的分工：内核是纯函数、零 DB；本文件测的是**壳层**——取图预算、
``GraphError`` 翻译、以及重名时在取图**之前**短路。这三件事都要库，所以单独成文件，
不污染内核用例的零 DB 纪律。

Wave 0（Plan 122-01）只落骨架，用例由 122-05 / 122-07 填实。
"""

from __future__ import annotations

from unittest import mock

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings
from django.utils import timezone

from services.code_graph import (
    CodeGraph,
    GraphAccessDenied,
    GraphBuildTimeout,
    GraphError,
    GraphMeta,
    GraphNotIndexed,
)
from services.code_graph_tools import (
    degradation_payload,
    fetch_graph_for_tool,
    graph_error_to_tool_error,
)

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
async def test_over_budget_uses_seeded_subgraph(indexed_repo, symbols_factory) -> None:
    """超预算仓：壳层传了 ``seed_symbol_ids`` + ``depth``，不吃 ``GraphError``。

    ⚠️ ``get_graph`` 的缺省 ``depth`` 是 2，壳层**必须显式传 depth**，否则 d3 残缺。

    两个断言**并列**是这条用例的全部要害：同一个超预算仓、同一个 ``get_graph``，
    带种子正常返回子图、不带种子直接抛 ``GraphError``——种子透传是那条分支的**唯一**
    区别。只测前半的话，一个「超预算就自动降级」的假想实现照样能过，而 Phase 121 实际
    交付的是「超预算 ⇒ 显式抛错并要求调用方给种子」（``cache.py:970``）。

    （Req: IMPACT-01, 决策: D-24）
    """
    from services.code_graph import cache as cache_module

    def _seed():
        return symbols_factory("seed_fn", "src/seed.py")

    seed = await sync_to_async(_seed)()
    seed_id = str(seed.id)
    repo_id = str(indexed_repo.id)

    # 单图上限 1 字节：一个符号就已经触顶，超预算分支必然被触发。
    with override_settings(CODE_GRAPH_MAX_GRAPH_BYTES=1):
        cache_module._reset_for_tests()
        service = cache_module.get_graph_service()

        # 手写 spy 而不是 ``mock.patch(..., wraps=…)``：被 spy 的是一个 async 方法，
        # AsyncMock 的 wraps 语义在各版本间有过反复，这里只要「转发 + 记下 kwargs」。
        captured: dict = {}
        real_get_graph = service.get_graph

        async def _spy(*args, **kwargs):
            captured.update(kwargs)
            return await real_get_graph(*args, **kwargs)

        with mock.patch.object(service, "get_graph", _spy):
            graph = await fetch_graph_for_tool(
                repo_id, "", user=None, seed_symbol_ids=[seed_id], depth=3
            )

        assert isinstance(graph, CodeGraph)
        assert graph.meta.degraded.startswith("on_demand_subgraph")

        # ``depth`` 与 ``seed_symbol_ids`` 真的传到了 ``get_graph``——省略 depth 会让
        # 子图半径按缺省 2 收敛，比 impact 的 max_depth=3 浅一层。
        assert captured["depth"] == 3
        assert captured["seed_symbol_ids"] == [seed_id]

        # 并列的反面：同一条件下**不带种子**，`get_graph` 抛错而不是给一张空图/截断图。
        with pytest.raises(GraphError):
            await service.get_graph(repo_id, "", user=None)


@pytest.mark.django_db(transaction=True)
async def test_graph_error_translated_not_swallowed(indexed_repo) -> None:
    """内核不吞 ``GraphError``，由壳层逐类翻译成明确的工具错误文案（D-03）。

    ⛔ 未索引仓的 impact 必须是**错误响应**而不是 ``{"affected": []}``——空影响面会被 agent
    读成「改这里没影响」，是最危险的误导。⛔ 翻译时只取 ``exc.message``，不把 ``str(exc)``
    直出（``__str__`` 会拼上含 ``estimated_bytes`` 的内部 ``details``）。

    （Req: IMPACT-01, 决策: D-03）
    """
    from repositories.models import IndexStatus

    def _unindex() -> None:
        indexed_repo.index_status = IndexStatus.NOT_INDEXED
        indexed_repo.save(update_fields=["index_status"])

    await sync_to_async(_unindex)()

    # ① 原语不吞：异常原样上抛，⛔ 不在这一层折成空结果。
    with pytest.raises(GraphNotIndexed) as excinfo:
        await fetch_graph_for_tool(
            str(indexed_repo.id), "", user=None, seed_symbol_ids=["x"], depth=3
        )

    code, message = graph_error_to_tool_error(excinfo.value)
    assert code == "repository_not_indexed"
    assert message

    # ② 三个子类各自翻成**不同**的 error_code，⛔ 不许统一折成兜底档。
    codes = {
        graph_error_to_tool_error(exc)[0]
        for exc in (
            GraphNotIndexed("a"),
            GraphAccessDenied("b"),
            GraphBuildTimeout("c"),
        )
    }
    assert codes == {
        "repository_not_indexed",
        "repository_access_denied",
        "graph_build_timeout",
    }

    # ③ 内部内存量不得出墙（T-122-错误细节泄漏）：``__str__`` 会把 details 拼上去，
    #    翻译只取映射表常量 + ``exc.message``。
    leaky = GraphError("x", {"estimated_bytes": 999})
    assert "estimated_bytes" in str(leaky) and "999" in str(leaky)
    _, leaky_message = graph_error_to_tool_error(leaky)
    assert "999" not in leaky_message
    assert "estimated_bytes" not in leaky_message


def _meta(**overrides) -> GraphMeta:
    """造一个 ``GraphMeta``。默认是「全量装配、无任何降级」的干净形态。"""
    fields = {
        "repository_id": "repo-1",
        "branch": "",
        "node_count": 12,
        "edge_count": 20,
        "estimated_bytes": 1024,
        "resolution_rate": 0.17,
        "low_resolution": False,
        "partial_edges": False,
        "partial_reason": "",
        "degraded": "",
        "cross_repo_unresolved_count": 0,
        "cross_repo_branch_unfiltered": False,
        "excluded_file_count": 0,
        "include_low_confidence": False,
        "built_signature": "sig",
        "built_at": timezone.now(),
    }
    fields.update(overrides)
    return GraphMeta(**fields)


def test_degradation_payload_declares_resolution_rate_numerically() -> None:
    """降级标记与**数值** ``resolution_rate`` 一律透出，⛔ 不只给布尔量（D-23）。

    生产 218 个仓的解析率中位数只有 0.17、最高 0.56——``low_resolution`` 表达的是
    「比本仓常态更差」，⛔ 不是「解析率够不够用」。所以解析率声明**无条件**出现，
    哪怕 ``low_resolution is False``；只透布尔量的实现会在这条用例上当场红。

    （决策: D-23）
    """
    clean = degradation_payload(_meta(resolution_rate=0.17, low_resolution=False))

    assert clean["resolution_rate"] == 0.17
    assert isinstance(clean["resolution_rate"], float)
    # 关键的一条：布尔量为 False 时解析率声明**仍然**在。
    assert any("83%" in d for d in clean["declarations"]), clean["declarations"]

    # 键名与 GraphMeta 字段名逐字一致，五个标记类字段一个都不许漏。
    assert {
        "resolution_rate",
        "low_resolution",
        "partial_edges",
        "partial_reason",
        "degraded",
        "cross_repo_unresolved_count",
        "cross_repo_branch_unfiltered",
        "include_low_confidence",
        "node_count",
        "edge_count",
        "excluded_file_count",
        "declarations",
    } == set(clean)

    # ``degraded`` 的两档措辞必须不同：前者的子图在其深度内完整，后者缺了一部分邻接
    # ——上层据此才知道「影响面就这么大」这句话能不能说。
    subgraph = degradation_payload(_meta(degraded="on_demand_subgraph"))
    truncated = degradation_payload(_meta(degraded="on_demand_subgraph_truncated"))
    subgraph_note = [d for d in subgraph["declarations"] if d not in clean["declarations"]]
    truncated_note = [d for d in truncated["declarations"] if d not in clean["declarations"]]
    assert subgraph_note and truncated_note
    assert subgraph_note != truncated_note

    # 其余三个标记各自带出一条声明。
    partial = degradation_payload(_meta(partial_edges=True, partial_reason="edge_build"))
    assert len(partial["declarations"]) > len(clean["declarations"])
    unresolved = degradation_payload(_meta(cross_repo_unresolved_count=4))
    assert any("4" in d for d in unresolved["declarations"])
    unfiltered = degradation_payload(_meta(cross_repo_branch_unfiltered=True))
    assert len(unfiltered["declarations"]) > len(clean["declarations"])


@pytest.mark.skip(reason="Wave 0 桩：由 122-07 落地")
def test_ambiguous_symbol_short_circuits_before_graph_fetch() -> None:
    """重名时在**取图之前**短路成候选列表，不白建一张图（D-19）。

    （Req: IMPACT-05, 决策: D-19）
    """
    pytest.fail("Wave 0 桩")
