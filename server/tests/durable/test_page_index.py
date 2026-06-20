"""run_page_index 真实生成 + target-hash 幂等守护（PAGEIDX-01）。

锁定三类语义：

- hash 未变（target_hash == compute_source_hash）→ ``skipped``，spy 验证 build_full **未被调用**；
- hash 缺省 / 不等 → 调 build_full 一次落新 snapshot，返回含 ``source_hash``；hash 已落
  active snapshot 后第二次执行（带该 hash）跳过——**无重复 active snapshot 行**；
- ``compute_source_hash`` 对相同仓库集合确定性同值，任一仓 ai_summary 变化 → hash 变化。

build_full 内部 LLM 聚类（``_llm_cluster``）触网，测试一律桩掉，仅验证 hash 跳过 /
重建 / snapshot 去重语义，不触发真实 provider 调用（pytest-socket 默认禁网）。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from codegraph.services.corpus_tree import CorpusTreeService
from durable.tasks_impl import run_page_index

# ---------------------------------------------------------------------------
# Test 1：hash 未变 → skipped 且不调 build_full
# ---------------------------------------------------------------------------


async def test_run_page_index_skips_when_hash_unchanged(monkeypatch) -> None:
    """target_hash == 当前计算 hash → 返回 skipped，build_full 未被调用。"""
    build_spy = AsyncMock(return_value={"status": "ok", "snapshot_id": "s"})
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="HASH-X")
    )

    res = await run_page_index(target_id="corpus_tree", target_hash="HASH-X")

    assert res == {
        "status": "skipped",
        "reason": "hash_unchanged",
        "target_id": "corpus_tree",
    }
    build_spy.assert_not_called()


async def test_run_page_index_builds_when_hash_absent(monkeypatch) -> None:
    """target_hash 缺省（空串）→ 调 build_full 一次，返回含当前 source_hash。"""
    build_spy = AsyncMock(return_value={"status": "ok", "snapshot_id": "s"})
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="HASH-NEW")
    )

    res = await run_page_index(target_id="corpus_tree")

    build_spy.assert_awaited_once()
    assert res == {
        "status": "ok",
        "target_id": "corpus_tree",
        "source_hash": "HASH-NEW",
    }


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

    # 第一次：无 target_hash → 真实 build_full 落 snapshot。
    first = await run_page_index(target_id="corpus_tree", target_hash="")
    assert first["status"] == "ok"
    assert first["source_hash"]
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1

    stored_hash = first["source_hash"]

    # 第二次：带已落 hash（仓库未变）→ skipped，不新增 active snapshot。
    second = await run_page_index(target_id="corpus_tree", target_hash=stored_hash)
    assert second["status"] == "skipped"
    assert second["reason"] == "hash_unchanged"
    assert await CorpusTreeSnapshot.objects.filter(is_active=True).acount() == 1
    # 总 snapshot 行数也未增（无重复构建）。
    assert await CorpusTreeSnapshot.objects.acount() == 1


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
