"""run_page_index 真实生成 + 自上次构建跳过 幂等守护（PAGEIDX-01 / CR-01）。

锁定四类语义（比对基线是**上一次已构建 active 快照的 source_hash**，非入队时刻指纹）：

- 已有基线且当前指纹 == 基线（自上次构建未变）→ ``skipped``，spy 验证 build_full **未被调用**；
- 无 active 快照（**首次构建**）→ 调 build_full 一次落新 snapshot，返回 build_full 落库 hash；
- 基线存在但当前指纹 != 基线（输入已变）→ 重建；
- 端到端：以 rebuild view 实际派发的 payload（不含 target_hash）驱动，首次/变化建、未变跳——
  锁死 CR-01「入队==执行指纹同源恒跳过」回归，并断言重复执行**无重复 active snapshot 行**；
- ``compute_source_hash`` 对相同仓库集合确定性同值，任一仓 ai_summary 变化 → hash 变化。

build_full 内部 LLM 聚类（``_llm_cluster``）触网，测试一律桩掉，仅验证跳过 / 重建 /
snapshot 去重语义，不触发真实 provider 调用（pytest-socket 默认禁网）。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from codegraph.services.corpus_tree import CorpusTreeService
from durable.tasks_impl import run_page_index

# ---------------------------------------------------------------------------
# Test 1：自上次构建未变（基线 == 当前指纹）→ skipped 且不调 build_full
# ---------------------------------------------------------------------------


async def test_run_page_index_skips_when_unchanged_since_last_build(monkeypatch) -> None:
    """active 快照基线 == 当前指纹 → 返回 skipped，build_full 未被调用。"""
    build_spy = AsyncMock(return_value={"status": "ok", "snapshot_id": "s"})
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="HASH-X")
    )
    monkeypatch.setattr(
        CorpusTreeService, "get_active_source_hash", AsyncMock(return_value="HASH-X")
    )

    # 即便历史 payload 仍携带 target_hash，也不得据此判定（**kwargs 吞掉、忽略）。
    res = await run_page_index(target_id="corpus_tree", target_hash="HASH-X")

    assert res == {
        "status": "skipped",
        "reason": "hash_unchanged",
        "target_id": "corpus_tree",
    }
    build_spy.assert_not_called()


async def test_run_page_index_builds_on_first_build(monkeypatch) -> None:
    """无 active 快照（首次构建）→ 调 build_full 一次，返回 build_full 落库 source_hash。"""
    build_spy = AsyncMock(
        return_value={"status": "ok", "snapshot_id": "s", "source_hash": "HASH-NEW"}
    )
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="HASH-NEW")
    )
    monkeypatch.setattr(
        CorpusTreeService, "get_active_source_hash", AsyncMock(return_value=None)
    )

    res = await run_page_index(target_id="corpus_tree")

    build_spy.assert_awaited_once()
    assert res == {
        "status": "ok",
        "target_id": "corpus_tree",
        "source_hash": "HASH-NEW",
    }


async def test_run_page_index_rebuilds_when_changed_since_last_build(monkeypatch) -> None:
    """基线存在但当前指纹已变（!= 基线）→ 调 build_full 重建。"""
    build_spy = AsyncMock(
        return_value={"status": "ok", "snapshot_id": "s", "source_hash": "HASH-NEW"}
    )
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="HASH-NEW")
    )
    monkeypatch.setattr(
        CorpusTreeService, "get_active_source_hash", AsyncMock(return_value="HASH-OLD")
    )

    res = await run_page_index(target_id="corpus_tree")

    build_spy.assert_awaited_once()
    assert res["status"] == "ok"
    assert res["source_hash"] == "HASH-NEW"


# ---------------------------------------------------------------------------
# Test 2：hash 变 → 真实 build_full 落 snapshot；重复执行无重复 snapshot
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_run_page_index_builds_then_skips_no_duplicate_snapshot(monkeypatch) -> None:
    """hash 变调 build_full 落 snapshot；hash 已落后第二次执行跳过——无重复 active snapshot 行。"""
    from repositories.models import CorpusTreeSnapshot, Repository

    repo = await Repository.objects.acreate(
        name="page-index-repo",
        git_url="https://github.com/example/page-index.git",
        git_platform="github",
        default_branch="main",
        ai_summary=json.dumps({"overview": "用户中心"}),
    )

    # 桩 LLM 聚类，避免触网；返回把该仓归入一个域节点的合法树。
    monkeypatch.setattr(
        CorpusTreeService,
        "_llm_cluster",
        AsyncMock(
            return_value=[
                {
                    "title": "用户",
                    "summary": "用户域",
                    "children": [],
                    "repo_ids": [str(repo.id)],
                }
            ]
        ),
    )

    # 第一次：无 active 快照（首次构建）→ 真实 build_full 落 snapshot。
    first = await run_page_index(target_id="corpus_tree")
    assert first["status"] == "ok"
    assert first["source_hash"]
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1

    # 第二次：仓库未变（基线 == 当前指纹）→ skipped，不新增 active snapshot。
    second = await run_page_index(target_id="corpus_tree")
    assert second["status"] == "skipped"
    assert second["reason"] == "hash_unchanged"
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1
    # 总 snapshot 行数也未增（无重复构建）。
    assert await CorpusTreeSnapshot.objects.acount() == 1


@pytest.mark.django_db(transaction=True)
async def test_rebuild_view_payload_builds_then_skips_then_rebuilds(monkeypatch) -> None:
    """端到端守护（CR-01 回归锁）：以 rebuild view 实际 payload（不含 target_hash）驱动。

    模拟 ``KnowledgeTreeRebuildView`` 派发的 payload ``{"target_id": "corpus_tree"}``：
    首次（无 active 快照）必建、未变跳过、输入变化后再次重建——证明默认 durable 路径
    在数据变化与首次构建时**确实调用 build_full**，而非旧实现的恒跳过。
    """
    from repositories.models import CorpusTreeSnapshot, Repository

    repo = await Repository.objects.acreate(
        name="rebuild-e2e-repo",
        git_url="https://github.com/example/rebuild-e2e.git",
        git_platform="github",
        default_branch="main",
        ai_summary=json.dumps({"overview": "订单履约"}),
    )
    monkeypatch.setattr(
        CorpusTreeService,
        "_llm_cluster",
        AsyncMock(
            return_value=[
                {
                    "title": "履约",
                    "summary": "订单域",
                    "children": [],
                    "repo_ids": [str(repo.id)],
                }
            ]
        ),
    )

    # rebuild view 入队的真实 payload（不含 target_hash）。
    payload = {"target_id": "corpus_tree"}

    # 首次：无 active 快照 → 必建。
    first = await run_page_index(**payload)
    assert first["status"] == "ok"
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1
    first_hash = first["source_hash"]
    assert first_hash

    # 再次同 payload、仓库未变 → 跳过，不新增 active 快照。
    second = await run_page_index(**payload)
    assert second["status"] == "skipped"
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1

    # 输入变化（ai_summary 变更）→ 同 payload 再次重建，落新 active 快照、hash 推进。
    repo.ai_summary = json.dumps({"overview": "订单履约与售后"})
    await repo.asave(update_fields=["ai_summary"])

    third = await run_page_index(**payload)
    assert third["status"] == "ok"
    assert third["source_hash"] != first_hash
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1
    # 历史快照保留（重建写新行再切换）：共 2 行，仅 1 active。
    assert await CorpusTreeSnapshot.objects.acount() == 2


# ---------------------------------------------------------------------------
# Test 3：compute_source_hash 确定性 + 输入变化敏感
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_compute_source_hash_deterministic_and_sensitive() -> None:
    """相同仓库集合恒等同值（64 hex）；某仓 ai_summary 变化 → hash 变化。"""
    from repositories.models import Repository

    repo = await Repository.objects.acreate(
        name="hash-repo",
        git_url="https://github.com/example/hash-repo.git",
        git_platform="github",
        default_branch="main",
        ai_summary=json.dumps({"overview": "A"}),
    )

    h1 = await CorpusTreeService.compute_source_hash()
    h2 = await CorpusTreeService.compute_source_hash()
    assert h1 == h2
    assert len(h1) == 64

    repo.ai_summary = json.dumps({"overview": "B"})
    await repo.asave(update_fields=["ai_summary"])

    h3 = await CorpusTreeService.compute_source_hash()
    assert h3 != h1


@pytest.mark.django_db(transaction=True)
async def test_compute_source_hash_ignores_private_facet_keys() -> None:
    """``_`` 前缀私有 facet 键不参与指纹（仅其变化不改 hash）。"""
    from repositories.models import Repository

    repo = await Repository.objects.acreate(
        name="facet-repo",
        git_url="https://github.com/example/facet-repo.git",
        git_platform="github",
        default_branch="main",
        facets={"团队归属": "平台", "_private": "v1"},
    )

    h1 = await CorpusTreeService.compute_source_hash()

    repo.facets = {"团队归属": "平台", "_private": "v2"}
    await repo.asave(update_fields=["facets"])
    assert await CorpusTreeService.compute_source_hash() == h1

    repo.facets = {"团队归属": "中台", "_private": "v2"}
    await repo.asave(update_fields=["facets"])
    assert await CorpusTreeService.compute_source_hash() != h1
