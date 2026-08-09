"""跨仓一跳的四条分支（覆盖 IMPACT-03）。

🚨 **全部靠合成数据**：生产库 ``CrossRepoApiCall`` / ``ApiCallSite`` / ``ApiWrapper`` 均为
**0 行**（上游产出器依赖 volar LSP，server 镜像无 Node，归 LSP-01 / Phase 127）。本文件的
绿测**不得**被表述成「跨仓能力已在真实数据上验证」（D-26）——Phase 127 补齐 LSP 后需回来
用真实样本复验。

造数走 conftest 的 ``cross_repo_call_factory``（``endpoint_repository`` 传另一个仓即造出真
跨仓行）。⚠️ 图里 ``kind == "cross_repo"`` 的边**从来不跨仓**（``loader`` 只在两端同为本仓
时才建边），所以跨仓穿越走 ORM 直查而不是沿图边走（D-25）。
"""

from __future__ import annotations

import json
from unittest import mock

import networkx as nx
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _make_peer_repo(*, name: str, sha_char: str = "b"):
    from repositories.models import IndexStatus, Repository

    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        is_deleted=False,
        last_indexed_commit_sha=sha_char * 40,
    )


def _peer_code_graph(*, repository_id: str, seed_id: str, seed_file: str, seed_name: str):
    """造一张对端仓合成图：``upstream → seed``，供 ``analyze_impact`` 产出非空 groups。"""
    from services.code_graph import CodeGraph, GraphMeta

    graph = nx.MultiDiGraph()
    graph.add_node(
        seed_id,
        name=seed_name,
        symbol_type="FUNCTION",
        file_path=seed_file,
        start_line=40,
        end_line=50,
    )
    graph.add_node(
        "upstream",
        name="pageMount",
        symbol_type="FUNCTION",
        file_path="web/src/pages/app.ts",
        start_line=1,
        end_line=10,
    )
    graph.add_edge(
        "upstream",
        seed_id,
        kind="call",
        confidence="resolved",
        line_number=2,
    )
    nx.freeze(graph)
    return CodeGraph(
        meta=GraphMeta(
            repository_id=repository_id,
            branch="",
            node_count=2,
            edge_count=1,
            estimated_bytes=256,
            resolution_rate=1.0,
            low_resolution=False,
            partial_edges=False,
            partial_reason="",
            degraded="",
            cross_repo_unresolved_count=0,
            cross_repo_branch_unfiltered=False,
            excluded_file_count=0,
            include_low_confidence=False,
            built_signature="sig",
            built_at=timezone.now(),
        ),
        graph=graph,
    )


@pytest.mark.django_db(transaction=True)
async def test_cross_repo_success(indexed_repo, cross_repo_call_factory) -> None:
    """跨仓一跳：对端仓成功 → ``cross_repo: true`` + ``match_confidence`` 原值。

    （Req: IMPACT-03, 决策: D-13 / D-25）
    """
    from codegraph.models import ApiCallSite, CrossRepoApiCall, Symbol
    from services.code_graph_cross_repo import (
        _find_peer_call_sites,
        collect_cross_repo_impact,
    )

    def _seed() -> tuple:
        peer = _make_peer_repo(name="peer-frontend-repo")
        endpoint_file = "src/api/views.py"
        handler_name = "order_create"
        # ⚠️ ApiWrapper 对 (repo, branch, file, function_symbol) 唯一——同一 peer 上第二条
        # call site 复用第一条的 wrapper / endpoint。
        first = cross_repo_call_factory(
            peer,
            caller_file="web/src/pages/order.ts",
            caller_function="submitOrder",
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.63,
            caller_line=40,
            endpoint_repository=indexed_repo,
        )
        second_site = ApiCallSite.objects.create(
            repository=peer,
            api_wrapper=first.call_site.api_wrapper,
            caller_file="web/src/pages/checkout.ts",
            caller_function="placeOrder",
            line_number=12,
        )
        CrossRepoApiCall.objects.create(
            call_site=second_site,
            endpoint=first.endpoint,
            match_confidence=0.63,
        )
        cross_repo_call_factory(
            indexed_repo,
            caller_file="web/src/local/same_repo.ts",
            caller_function="localCaller",
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.9,
            caller_line=99,
            endpoint_repository=indexed_repo,
        )
        symbol = Symbol.objects.create(
            repository=peer,
            branch_name="",
            name="submitOrder",
            symbol_type="FUNCTION",
            file_path="web/src/pages/order.ts",
            start_line=40,
            end_line=50,
        )
        return peer, endpoint_file, handler_name, symbol

    peer, endpoint_file, handler_name, symbol = await sync_to_async(_seed)()
    local_id = str(indexed_repo.id)
    peer_id = str(peer.id)
    seed_id = str(symbol.id)

    grouped = await _find_peer_call_sites(
        local_repository_id=local_id,
        symbol_file_path=endpoint_file,
        symbol_name=handler_name,
    )

    assert set(grouped.keys()) == {peer_id}
    hits = grouped[peer_id]
    assert len(hits.call_sites) == 2
    assert [s["caller_file"] for s in hits.call_sites] == [
        "web/src/pages/checkout.ts",
        "web/src/pages/order.ts",
    ]
    assert all(
        s["caller_file"] != "web/src/local/same_repo.ts" for s in hits.call_sites
    )
    assert all(s["match_confidence"] == 0.63 for s in hits.call_sites)
    assert hits.max_match_confidence == 0.63

    peer_graph = _peer_code_graph(
        repository_id=peer_id,
        seed_id=seed_id,
        seed_file="web/src/pages/order.ts",
        seed_name="submitOrder",
    )

    async def _fake_fetch(
        repo_id,
        branch,
        *,
        user,
        seed_symbol_ids,
        depth,
        include_low_confidence=False,
    ):
        assert str(repo_id) == peer_id
        assert seed_id in [str(s) for s in seed_symbol_ids]
        return peer_graph

    with mock.patch(
        "services.code_graph_cross_repo.fetch_graph_for_tool",
        _fake_fetch,
    ):
        result = await collect_cross_repo_impact(
            local_repository_id=local_id,
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=1,
            max_depth=3,
            min_confidence=0.0,
        )

    assert len(result) == 1
    entry = result[0]
    assert entry["cross_repo"] is True
    assert entry["repository_id"] == peer_id
    assert entry["match_confidence"] == 0.63
    assert entry["unresolved_call_sites"] == 1  # placeOrder 无 Symbol
    assert "groups" in entry["impact"]
    assert "summary" in entry["impact"]
    assert entry["impact"]["summary"]["total_found"] >= 1
    assert "upstream" in {
        item["symbol_id"]
        for depth_items in entry["impact"]["groups"].values()
        for item in depth_items
    }


@pytest.mark.django_db(transaction=True)
async def test_unauthorized_repo_redacted(indexed_repo, cross_repo_call_factory) -> None:
    """``GraphAccessDenied`` → 整仓折叠 ``REDACTED_REPOSITORY``，不泄漏仓名/路径/符号名。

    （Req: IMPACT-03, 决策: D-12 / D-30）
    """
    from services.code_graph import REDACTED_REPOSITORY, GraphAccessDenied, access
    from services.code_graph_cross_repo import collect_cross_repo_impact

    def _seed() -> tuple:
        peer = _make_peer_repo(name="secret-frontend-repo", sha_char="c")
        endpoint_file = "src/api/secret.py"
        handler_name = "secret_handler"
        caller_file = "web/src/pages/secret.ts"
        caller_function = "callSecret"
        cross_repo_call_factory(
            peer,
            caller_file=caller_file,
            caller_function=caller_function,
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.7,
            caller_line=7,
            endpoint_repository=indexed_repo,
        )
        return peer, endpoint_file, handler_name, caller_file, caller_function

    peer, endpoint_file, handler_name, caller_file, caller_function = await sync_to_async(
        _seed
    )()
    peer_id = str(peer.id)
    peer_name = peer.name

    async def _deny(user, repository_id):
        if str(repository_id) == peer_id:
            raise GraphAccessDenied("无权访问该仓库")
        return None

    with mock.patch.object(access, "ensure_repository_readable", _deny):
        result = await collect_cross_repo_impact(
            local_repository_id=str(indexed_repo.id),
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=1,
            max_depth=3,
            min_confidence=0.0,
        )

    assert len(result) == 1
    entry = result[0]
    assert set(entry.keys()) == {"cross_repo", "repository"}
    assert entry["cross_repo"] is True
    assert entry["repository"] == REDACTED_REPOSITORY

    dumped = json.dumps(result, ensure_ascii=False)
    assert peer_id not in dumped
    assert peer_name not in dumped
    assert caller_file not in dumped
    assert caller_function not in dumped


@pytest.mark.django_db(transaction=True)
async def test_peer_unavailable_fail_soft(indexed_repo, cross_repo_call_factory) -> None:
    """``GraphNotIndexed`` / ``GraphBuildTimeout`` → ``unavailable_reason``，另一仓仍成功。

    （Req: IMPACT-03, 决策: D-14）
    """
    from codegraph.models import Symbol
    from services.code_graph import GraphBuildTimeout, GraphNotIndexed
    from services.code_graph_cross_repo import collect_cross_repo_impact

    def _seed() -> tuple:
        bad = _make_peer_repo(name="peer-unindexed", sha_char="d")
        good = _make_peer_repo(name="peer-healthy", sha_char="e")
        endpoint_file = "src/api/views.py"
        handler_name = "order_create"
        cross_repo_call_factory(
            bad,
            caller_file="web/src/pages/bad.ts",
            caller_function="badCaller",
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.5,
            caller_line=1,
            endpoint_repository=indexed_repo,
        )
        cross_repo_call_factory(
            good,
            caller_file="web/src/pages/good.ts",
            caller_function="goodCaller",
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.8,
            caller_line=2,
            endpoint_repository=indexed_repo,
        )
        symbol = Symbol.objects.create(
            repository=good,
            branch_name="",
            name="goodCaller",
            symbol_type="FUNCTION",
            file_path="web/src/pages/good.ts",
            start_line=2,
            end_line=12,
        )
        return bad, good, endpoint_file, handler_name, symbol

    bad, good, endpoint_file, handler_name, symbol = await sync_to_async(_seed)()
    bad_id = str(bad.id)
    good_id = str(good.id)
    seed_id = str(symbol.id)
    good_graph = _peer_code_graph(
        repository_id=good_id,
        seed_id=seed_id,
        seed_file="web/src/pages/good.ts",
        seed_name="goodCaller",
    )

    async def _fetch_not_indexed(
        repo_id,
        branch,
        *,
        user,
        seed_symbol_ids,
        depth,
        include_low_confidence=False,
    ):
        if str(repo_id) == bad_id:
            raise GraphNotIndexed("仓库尚未建立索引")
        return good_graph

    with mock.patch(
        "services.code_graph_cross_repo.fetch_graph_for_tool",
        _fetch_not_indexed,
    ):
        result = await collect_cross_repo_impact(
            local_repository_id=str(indexed_repo.id),
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=1,
            max_depth=3,
            min_confidence=0.0,
        )

    success = [e for e in result if "impact" in e]
    unavailable = [e for e in result if "unavailable_reason" in e]
    assert len(success) == 1 and len(unavailable) == 1
    assert success[0]["repository_id"] == good_id
    assert success[0]["cross_repo"] is True
    assert unavailable[0] == {
        "cross_repo": True,
        "repository_id": bad_id,
        "unavailable_reason": "repository_not_indexed",
    }

    async def _fetch_timeout(
        repo_id,
        branch,
        *,
        user,
        seed_symbol_ids,
        depth,
        include_low_confidence=False,
    ):
        if str(repo_id) == bad_id:
            raise GraphBuildTimeout("建图超时")
        return good_graph

    with mock.patch(
        "services.code_graph_cross_repo.fetch_graph_for_tool",
        _fetch_timeout,
    ):
        timeout_result = await collect_cross_repo_impact(
            local_repository_id=str(indexed_repo.id),
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=1,
            max_depth=3,
            min_confidence=0.0,
        )

    timeout_unavailable = [e for e in timeout_result if "unavailable_reason" in e]
    assert len(timeout_unavailable) == 1
    assert timeout_unavailable[0]["unavailable_reason"] == "graph_build_timeout"


@pytest.mark.django_db(transaction=True)
async def test_hop_budget(indexed_repo, cross_repo_call_factory) -> None:
    """``max_hops=0`` 不查库；``max_hops=1`` 不递归到第三仓（D-11）。

    （Req: IMPACT-03, 决策: D-11）
    """
    from codegraph.models import Symbol
    from services.code_graph_cross_repo import collect_cross_repo_impact

    def _seed() -> tuple:
        peer_b = _make_peer_repo(name="peer-b", sha_char="f")
        peer_c = _make_peer_repo(name="peer-c", sha_char="1")
        endpoint_file = "src/api/views.py"
        handler_name = "order_create"
        # B → A（本仓）
        cross_repo_call_factory(
            peer_b,
            caller_file="web/src/pages/b.ts",
            caller_function="bCaller",
            endpoint_file=endpoint_file,
            handler_name=handler_name,
            match_confidence=0.7,
            caller_line=3,
            endpoint_repository=indexed_repo,
        )
        # C → B（第三仓指向 B；若递归会出现在结果里）
        cross_repo_call_factory(
            peer_c,
            caller_file="web/src/pages/c.ts",
            caller_function="cCaller",
            endpoint_file="web/src/pages/b.ts",
            handler_name="bCaller",
            match_confidence=0.6,
            caller_line=4,
            endpoint_repository=peer_b,
        )
        symbol = Symbol.objects.create(
            repository=peer_b,
            branch_name="",
            name="bCaller",
            symbol_type="FUNCTION",
            file_path="web/src/pages/b.ts",
            start_line=3,
            end_line=13,
        )
        return peer_b, peer_c, endpoint_file, handler_name, symbol

    peer_b, peer_c, endpoint_file, handler_name, symbol = await sync_to_async(_seed)()
    peer_b_id = str(peer_b.id)
    peer_c_id = str(peer_c.id)
    seed_id = str(symbol.id)
    peer_graph = _peer_code_graph(
        repository_id=peer_b_id,
        seed_id=seed_id,
        seed_file="web/src/pages/b.ts",
        seed_name="bCaller",
    )

    fetch_calls: list[str] = []

    async def _fake_fetch(
        repo_id,
        branch,
        *,
        user,
        seed_symbol_ids,
        depth,
        include_low_confidence=False,
    ):
        fetch_calls.append(str(repo_id))
        return peer_graph

    with (
        mock.patch(
            "services.code_graph_cross_repo.fetch_graph_for_tool",
            _fake_fetch,
        ),
        mock.patch(
            "services.code_graph_cross_repo._find_peer_call_sites",
            new_callable=mock.AsyncMock,
        ) as find_spy,
    ):
        empty = await collect_cross_repo_impact(
            local_repository_id=str(indexed_repo.id),
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=0,
            max_depth=3,
            min_confidence=0.0,
        )
    assert empty == []
    assert fetch_calls == []
    find_spy.assert_not_called()

    fetch_calls.clear()
    with mock.patch(
        "services.code_graph_cross_repo.fetch_graph_for_tool",
        _fake_fetch,
    ):
        result = await collect_cross_repo_impact(
            local_repository_id=str(indexed_repo.id),
            symbol_file_path=endpoint_file,
            symbol_name=handler_name,
            user=None,
            max_hops=1,
            max_depth=3,
            min_confidence=0.0,
        )

    repo_ids = {e.get("repository_id") for e in result if "repository_id" in e}
    assert peer_b_id in repo_ids
    assert peer_c_id not in repo_ids
    assert peer_c_id not in fetch_calls
