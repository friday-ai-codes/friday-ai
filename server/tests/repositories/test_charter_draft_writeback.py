"""``charter_draft_writeback.asubmit_charter_draft`` 三分支等价性测试（Phase 112-05，CHARTER-03）。

**等价性靠对照断言，不靠「diff 为空」这种不可机械验证的措辞**：本文件逐条锁死新模块与
``charter_service.adraft_charter`` 的落库语义等价，外加确认门专属的合并语义：

1. 无 charter → 建行 ``source=ai_draft`` / ``version=1``。
2. 已有 ``source=ai_draft`` → 正式字段就地更新且 ``version`` **不变**。
3. 已有 ``source=human_confirmed`` → **只写 ``draft_content``**，正式字段
   （positioning / owned_domains / boundaries / evolution）逐字段与写入前**完全相等**
   （CHARTER-01「AI 不覆盖人工」不变量在回灌路径上仍成立）。
4. ``merge=True`` 按 key 去重追加（同 domain / 同 rule 不重复），不同 key 追加而非覆盖；
   ``merge=False`` 按覆盖语义。
5. 归一复用：畸形草案经 ``normalize_charter_draft`` 回退，落库结果与直接调用该归一函数
   的结果**逐字相等**（证明没有另写一套白名单）。
6. 依赖失败：仓不存在 / 非法 uuid → 返 ``None`` 且不抛（best-effort，绝不反噬确认门锁定）。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from repositories.models import RepoCharter, Repository
from repositories.services.charter_draft_writeback import asubmit_charter_draft
from repositories.services.charter_service import normalize_charter_draft

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _draft(domain: str = "培优/学习提分", rule: str = "不承接课程权益鉴权") -> dict:
    return {
        "positioning": "C 端学生移动 H5 学习应用集",
        "owned_domains": [{"domain": domain, "status": "planned", "note": "", "citations": []}],
        "boundaries": [{"rule": rule, "decided_by": "human", "citations": []}],
        "evolution": "active",
    }


async def _reload(repo: Repository) -> RepoCharter:
    return await RepoCharter.objects.filter(repository=repo).afirst()


# ── 分支 1：无 charter → 建行 ───────────────────────────────────────────────


async def test_creates_ai_draft_row_when_absent() -> None:
    repo = await _make_repo()

    charter = await asubmit_charter_draft(str(repo.id), _draft())

    assert charter is not None
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.version == 1
    assert charter.positioning == "C 端学生移动 H5 学习应用集"
    assert [item["domain"] for item in charter.owned_domains] == ["培优/学习提分"]


# ── 分支 2：ai_draft → 就地更新且 version 不变 ───────────────────────────────


async def test_updates_ai_draft_in_place_without_bumping_version() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft())

    await asubmit_charter_draft(str(repo.id), _draft(domain="题库能力", rule="不承接支付结算"))

    charter = await _reload(repo)
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.version == 1, "草案就地更新不得翻版本"
    assert {item["domain"] for item in charter.owned_domains} == {"培优/学习提分", "题库能力"}
    assert {item["rule"] for item in charter.boundaries} == {"不承接课程权益鉴权", "不承接支付结算"}


# ── 分支 3：human_confirmed → 只写 draft_content（CHARTER-01 不变量）────────


async def test_human_confirmed_charter_only_receives_draft_content() -> None:
    repo = await _make_repo()
    confirmed = await RepoCharter.objects.acreate(
        repository=repo,
        source=RepoCharter.Source.HUMAN_CONFIRMED,
        version=3,
        positioning="人工确认的定位",
        owned_domains=[
            {"domain": "人工领域", "status": "implemented", "note": "", "citations": []}
        ],
        boundaries=[{"rule": "人工禁区", "decided_by": "human:zane", "citations": []}],
        evolution="maintenance_only",
    )
    before = {
        "positioning": confirmed.positioning,
        "owned_domains": confirmed.owned_domains,
        "boundaries": confirmed.boundaries,
        "evolution": confirmed.evolution,
        "version": confirmed.version,
    }

    charter = await asubmit_charter_draft(str(repo.id), _draft())

    assert charter is not None
    fresh = await _reload(repo)
    for field, value in before.items():
        assert getattr(fresh, field) == value, f"human_confirmed 章程的 {field} 被改写了"
    assert fresh.source == RepoCharter.Source.HUMAN_CONFIRMED
    assert [item["domain"] for item in fresh.draft_content["owned_domains"]] == ["培优/学习提分"]


async def test_human_confirmed_draft_content_merges_by_key() -> None:
    repo = await _make_repo()
    await RepoCharter.objects.acreate(
        repository=repo,
        source=RepoCharter.Source.HUMAN_CONFIRMED,
        version=2,
        positioning="人工定位",
    )
    await asubmit_charter_draft(str(repo.id), _draft())
    await asubmit_charter_draft(str(repo.id), _draft(domain="题库能力"))
    await asubmit_charter_draft(str(repo.id), _draft())

    fresh = await _reload(repo)
    domains = [item["domain"] for item in fresh.draft_content["owned_domains"]]
    assert sorted(domains) == ["培优/学习提分", "题库能力"], "同 domain 重复提交不得堆积"
    assert fresh.positioning == "人工定位"


# ── 分支 4：merge 语义 ─────────────────────────────────────────────────────


async def test_merge_false_overwrites_lists() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft())

    await asubmit_charter_draft(str(repo.id), _draft(domain="题库能力"), merge=False)

    charter = await _reload(repo)
    assert [item["domain"] for item in charter.owned_domains] == ["题库能力"]


async def test_merge_true_dedupes_same_rule() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft())
    await asubmit_charter_draft(str(repo.id), _draft())

    charter = await _reload(repo)
    assert len(charter.boundaries) == 1
    assert len(charter.owned_domains) == 1


# ── 分支 5：归一逐字复用 charter_service.normalize_charter_draft ─────────────


async def test_normalization_matches_charter_service_whitelist() -> None:
    repo = await _make_repo()
    malformed = {
        "positioning": "x" * 800,
        "owned_domains": [
            {"domain": "领域 A", "status": "不存在的状态", "note": "n", "citations": "not-a-list"},
            {"status": "planned"},  # 缺 domain → 跳过
        ],
        "boundaries": "not-a-list",
        "evolution": "vanished",
        "audience": "y" * 200,
    }
    expected = normalize_charter_draft(malformed)

    await asubmit_charter_draft(str(repo.id), malformed, merge=False)

    charter = await _reload(repo)
    assert charter.positioning == expected["positioning"]
    assert charter.owned_domains == expected["owned_domains"]
    assert charter.boundaries == expected["boundaries"]
    assert charter.evolution == expected["evolution"] == "active"
    assert charter.audience == expected["audience"]
    assert charter.owned_domains[0]["status"] == "implemented"
    assert charter.owned_domains[0]["citations"] == []


# ── 分支 6：依赖失败 best-effort ────────────────────────────────────────────


@pytest.mark.parametrize("repository_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000001"])
async def test_missing_repository_returns_none_without_raising(repository_id: str) -> None:
    assert await asubmit_charter_draft(repository_id, _draft()) is None
    assert await sync_to_async(RepoCharter.objects.count)() == 0
