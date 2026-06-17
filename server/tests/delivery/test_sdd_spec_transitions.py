"""SddSpecService 状态机流转守护（Phase 50-02，SPECST-01/02）。

覆盖 D-50-1/D-50-2：

- 合法流转逐条通过：submit_for_review/approve/reject/mark_implemented/archive。
- 非法流转 fail-loud（抛 SddSpecTransitionError）。
- 幂等/防双推进：重复 approve / 已推进 → 条件更新影响 0 行 → raise。
- approve/reject 单一事务原子建评审 + 驱动状态（reject 回 draft，decision=reject）。
- 更新 0 行时评审被回滚（无孤儿评审）。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import SddSpec, SddSpecReview, SddSpecStatus
from delivery.services import SddSpecService
from delivery.services.sdd_spec_service import SddSpecTransitionError
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_spec(status: str = SddSpecStatus.DRAFT) -> SddSpec:
    repo = await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    return await SddSpec.objects.acreate(repository=repo, status=status)


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _status(spec_id) -> str:
    spec = await SddSpec.objects.aget(id=spec_id)
    return spec.status


# ---- 合法流转逐条 ----


async def test_submit_for_review_draft_to_in_review() -> None:
    spec = await _make_spec(SddSpecStatus.DRAFT)
    await SddSpecService().submit_for_review(spec.id)
    assert await _status(spec.id) == SddSpecStatus.IN_REVIEW


async def test_approve_in_review_to_approved_creates_review() -> None:
    spec = await _make_spec(SddSpecStatus.IN_REVIEW)
    user = await _make_user()
    await SddSpecService().approve(spec.id, reviewer=user, comment="LGTM")
    assert await _status(spec.id) == SddSpecStatus.APPROVED
    review = await SddSpecReview.objects.aget(spec_id=spec.id)
    assert review.decision == "approve"
    assert review.comment == "LGTM"
    assert review.reviewer_id == user.id


async def test_reject_in_review_to_draft_creates_review() -> None:
    spec = await _make_spec(SddSpecStatus.IN_REVIEW)
    user = await _make_user()
    await SddSpecService().reject(spec.id, reviewer=user, comment="需修订")
    assert await _status(spec.id) == SddSpecStatus.DRAFT
    review = await SddSpecReview.objects.aget(spec_id=spec.id)
    assert review.decision == "reject"
    assert review.comment == "需修订"


async def test_mark_implemented_approved_to_implemented() -> None:
    spec = await _make_spec(SddSpecStatus.APPROVED)
    await SddSpecService().mark_implemented(spec.id)
    assert await _status(spec.id) == SddSpecStatus.IMPLEMENTED


async def test_archive_any_non_archived_to_archived() -> None:
    for src in (
        SddSpecStatus.DRAFT,
        SddSpecStatus.IN_REVIEW,
        SddSpecStatus.APPROVED,
        SddSpecStatus.IMPLEMENTED,
    ):
        spec = await _make_spec(src)
        await SddSpecService().archive(spec.id)
        assert await _status(spec.id) == SddSpecStatus.ARCHIVED


# ---- 非法流转 fail-loud ----


async def test_illegal_submit_from_approved_raises() -> None:
    spec = await _make_spec(SddSpecStatus.APPROVED)
    with pytest.raises(SddSpecTransitionError):
        await SddSpecService().submit_for_review(spec.id)
    assert await _status(spec.id) == SddSpecStatus.APPROVED


async def test_illegal_approve_from_draft_raises() -> None:
    spec = await _make_spec(SddSpecStatus.DRAFT)
    user = await _make_user()
    with pytest.raises(SddSpecTransitionError):
        await SddSpecService().approve(spec.id, reviewer=user)
    assert await _status(spec.id) == SddSpecStatus.DRAFT


async def test_archive_already_archived_raises() -> None:
    spec = await _make_spec(SddSpecStatus.ARCHIVED)
    with pytest.raises(SddSpecTransitionError):
        await SddSpecService().archive(spec.id)


# ---- 幂等 / 防双推进 ----


async def test_double_approve_second_raises_idempotent() -> None:
    spec = await _make_spec(SddSpecStatus.IN_REVIEW)
    user = await _make_user()
    await SddSpecService().approve(spec.id, reviewer=user)
    assert await _status(spec.id) == SddSpecStatus.APPROVED
    # 已推进，第二次 approve 条件更新影响 0 行 → fail-loud
    with pytest.raises(SddSpecTransitionError):
        await SddSpecService().approve(spec.id, reviewer=user)


# ---- 原子性：更新 0 行回滚评审，无孤儿 ----


async def test_failed_transition_rolls_back_review_no_orphan() -> None:
    """对 draft 调 approve（非法）→ 评审不应被持久化（事务回滚）。"""
    spec = await _make_spec(SddSpecStatus.DRAFT)
    user = await _make_user()
    with pytest.raises(SddSpecTransitionError):
        await SddSpecService().approve(spec.id, reviewer=user, comment="x")
    assert await SddSpecReview.objects.filter(spec_id=spec.id).acount() == 0
