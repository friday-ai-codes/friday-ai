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

import pytest
from asgiref.sync import sync_to_async

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
async def test_cross_repo_success(indexed_repo, cross_repo_call_factory) -> None:
    """跨仓一跳：对端仓成功 → ``cross_repo: true`` + ``match_confidence`` 原值。

    Task 1 前半：``_find_peer_call_sites`` 只收真跨仓行、按对端仓分组、原值透传。
    Task 2 后半：``collect_cross_repo_impact`` 成功条目形态。

    （Req: IMPACT-03, 决策: D-13 / D-25）
    """
    from repositories.models import IndexStatus, Repository
    from services.code_graph_cross_repo import _find_peer_call_sites

    def _seed() -> tuple:
        from codegraph.models import ApiCallSite, CrossRepoApiCall

        peer = Repository.objects.create(
            name="peer-frontend-repo",
            git_url="https://example.com/peer-frontend.git",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
            is_deleted=False,
            last_indexed_commit_sha="b" * 40,
        )
        endpoint_file = "src/api/views.py"
        handler_name = "order_create"
        # 两条真跨仓：call_site 在仓 B，endpoint 在本仓。
        # ⚠️ ApiWrapper 对 (repo, branch, file, function_symbol) 唯一——同一 peer 上第二条
        # call site 复用第一条的 wrapper / endpoint，避免 factory 再插一条同名 wrapper。
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
        # 同仓行：两端都在本仓 —— 必须被 `.exclude` 掉，否则同一条影响数两遍。
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
        return peer, endpoint_file, handler_name

    peer, endpoint_file, handler_name = await sync_to_async(_seed)()
    local_id = str(indexed_repo.id)
    peer_id = str(peer.id)

    grouped = await _find_peer_call_sites(
        local_repository_id=local_id,
        symbol_file_path=endpoint_file,
        symbol_name=handler_name,
    )

    assert set(grouped.keys()) == {peer_id}
    hits = grouped[peer_id]
    assert len(hits.call_sites) == 2
    # 组内按 (caller_file, line_number) 稳定排序。
    assert [s["caller_file"] for s in hits.call_sites] == [
        "web/src/pages/checkout.ts",
        "web/src/pages/order.ts",
    ]
    # 同仓那条不在结果里。
    assert all(
        s["caller_file"] != "web/src/local/same_repo.ts" for s in hits.call_sites
    )
    # match_confidence 原值透传（⛔ 未被折算成 1.0 / 0.3 之类的档位常量）。
    assert all(s["match_confidence"] == 0.63 for s in hits.call_sites)
    assert hits.max_match_confidence == 0.63


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 Task 2 落地")
def test_unauthorized_repo_redacted() -> None:
    """``GraphAccessDenied`` → 整仓折叠 ``REDACTED_REPOSITORY``，不泄漏仓名/路径/符号名（D-12）。

    折叠条目按 D-30 **不带** ``affected_count``：计数会泄漏一个调用方无权访问的仓库的内部
    规模，构成存在性预言机。

    （Req: IMPACT-03, 决策: D-12 / D-30）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 Task 2 落地")
def test_peer_unavailable_fail_soft() -> None:
    """``GraphNotIndexed`` / ``GraphBuildTimeout`` → ``unavailable_reason`` 条目，本仓结果
    照常返回（D-14）。

    fail-soft 但**必须显式声明**：静默丢弃会让 agent 以为影响面更小。

    （Req: IMPACT-03, 决策: D-14）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 Task 2 落地")
def test_hop_budget() -> None:
    """``max_cross_repo_hops=1`` 不递归（D-11）。

    （Req: IMPACT-03, 决策: D-11）
    """
    pytest.fail("Wave 0 桩")
