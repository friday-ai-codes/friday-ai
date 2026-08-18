"""``charter_draft_writeback.asubmit_charter_draft`` append-only 契约测试。

1. 无 charter → 建行 ``source=ai_draft`` / ``version=1``。
2. 已有行 → 正式字段冻结；新 key → appendices；标量/语义 → proposals。
3. ``draft_content`` 永不被自动化写入。
4. 指纹重复不增长侧信道；省略 fingerprint 不把已存非空指纹清空。
5. 归一复用 ``normalize_charter_draft``。
6. 依赖失败 best-effort。
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


def _draft(domain: str = "培优/学习提分", rule: str = "不承接课程权益鉴权", **extra) -> dict:
    base = {
        "positioning": extra.pop("positioning", "C 端学生移动 H5 学习应用集"),
        "owned_domains": [{"domain": domain, "status": "planned", "note": "", "citations": []}],
        "boundaries": [{"rule": rule, "decided_by": "human", "citations": []}],
        "evolution": "active",
    }
    base.update(extra)
    return base


async def _reload(repo: Repository) -> RepoCharter:
    return await RepoCharter.objects.filter(repository=repo).afirst()


async def test_creates_ai_draft_row_when_absent() -> None:
    repo = await _make_repo()

    charter = await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="fp-create")

    assert charter is not None
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.version == 1
    assert charter.positioning == "C 端学生移动 H5 学习应用集"
    assert [item["domain"] for item in charter.owned_domains] == ["培优/学习提分"]
    assert charter.baseline_fingerprint == "fp-create"
    assert charter.baseline_locked_at is not None


async def test_existing_row_formal_unchanged_new_key_appendix() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="fp1")

    await asubmit_charter_draft(
        str(repo.id), _draft(domain="题库能力", rule="不承接支付结算"), fingerprint="fp2"
    )

    charter = await _reload(repo)
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.version == 1
    assert charter.positioning == "C 端学生移动 H5 学习应用集"
    assert [item["domain"] for item in charter.owned_domains] == ["培优/学习提分"]
    assert charter.draft_content == {}
    appendix_domains = [
        a["item"]["domain"]
        for a in (charter.appendices or [])
        if a.get("kind") == "owned_domains" and isinstance(a.get("item"), dict)
    ]
    assert "题库能力" in appendix_domains
    assert charter.baseline_fingerprint == "fp2"


async def test_human_confirmed_formal_unchanged_no_draft_content() -> None:
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

    charter = await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="fp-h")

    assert charter is not None
    fresh = await _reload(repo)
    for field, value in before.items():
        assert getattr(fresh, field) == value, f"human_confirmed 章程的 {field} 被改写了"
    assert fresh.source == RepoCharter.Source.HUMAN_CONFIRMED
    assert fresh.draft_content == {}
    assert fresh.change_proposals or fresh.appendices


async def test_merge_false_does_not_wipe_formal_lists() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="fp1")

    await asubmit_charter_draft(
        str(repo.id), _draft(domain="题库能力"), merge=False, fingerprint="fp2"
    )

    charter = await _reload(repo)
    assert [item["domain"] for item in charter.owned_domains] == ["培优/学习提分"]
    assert charter.draft_content == {}


async def test_fingerprint_repeat_no_side_channel_growth() -> None:
    repo = await _make_repo()
    first = await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="same")
    second = await asubmit_charter_draft(
        str(repo.id), _draft(domain="新领域"), fingerprint="same"
    )
    assert first is not None and second is not None
    assert len(second.appendices or []) == len(first.appendices or [])
    assert len(second.change_proposals or []) == len(first.change_proposals or [])


async def test_omitted_fingerprint_preserves_stored_nonempty() -> None:
    repo = await _make_repo()
    await asubmit_charter_draft(str(repo.id), _draft(), fingerprint="keep-fp")
    # 证据为空时 resolve 仍会算出固定 hash；显式验证 stored 非空路径：
    # 传入与 stored 相同的指纹后省略再写不应清空
    fresh = await asubmit_charter_draft(str(repo.id), _draft())
    assert fresh is not None
    assert fresh.baseline_fingerprint  # 不得被清空为 ""


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

    await asubmit_charter_draft(str(repo.id), malformed, merge=False, fingerprint="fp-n")

    charter = await _reload(repo)
    assert charter.positioning == expected["positioning"]
    assert charter.owned_domains == expected["owned_domains"]
    assert charter.boundaries == expected["boundaries"]
    assert charter.evolution == expected["evolution"] == "active"
    assert charter.audience == expected["audience"]
    assert charter.owned_domains[0]["status"] == "implemented"
    assert charter.owned_domains[0]["citations"] == []


@pytest.mark.parametrize("repository_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000001"])
async def test_missing_repository_returns_none_without_raising(repository_id: str) -> None:
    assert await asubmit_charter_draft(repository_id, _draft()) is None
    assert await sync_to_async(RepoCharter.objects.count)() == 0
