"""SddSpecReview append-only 评审记录模型守护（Phase 50-01，SPECST-02）。

覆盖 D-50-2：

- 字段契约：spec FK CASCADE related_name=reviews、reviewer FK SET_NULL null、
  decision choices(approve/reject)、comment TextField(blank)、created_at(auto_now_add)。
- append-only 契约：模型类自身命名空间无任何 edit/delete/apply/update 业务写方法
  （守 INV-6 + 不可篡改，写入唯一经 50-02 SddSpecService）。
- ORM 级联语义（Task 2）：删 spec 级联删评审（CASCADE）；删 reviewer 用户保留评审记录
  且 reviewer 置空（SET_NULL）；spec.reviews 倒序返回。
"""

from __future__ import annotations

import uuid

import pytest
from django.db import models

from delivery.models import ReviewDecision, SddSpecReview


def test_review_decision_choices() -> None:
    """ReviewDecision 仅 approve/reject 两枚举值。"""
    assert ReviewDecision.APPROVE == "approve"
    assert ReviewDecision.REJECT == "reject"
    assert {c[0] for c in ReviewDecision.choices} == {"approve", "reject"}


def test_spec_fk_cascade() -> None:
    """spec FK → delivery.SddSpec，on_delete=CASCADE，related_name=reviews。"""
    field = SddSpecReview._meta.get_field("spec")
    assert isinstance(field, models.ForeignKey)
    assert field.remote_field.on_delete is models.CASCADE
    assert field.remote_field.related_name == "reviews"


def test_reviewer_fk_set_null() -> None:
    """reviewer FK → AUTH_USER_MODEL，on_delete=SET_NULL，null 允许（删用户不灭记录）。"""
    field = SddSpecReview._meta.get_field("reviewer")
    assert isinstance(field, models.ForeignKey)
    assert field.remote_field.on_delete is models.SET_NULL
    assert field.null is True


def test_decision_and_comment_fields() -> None:
    """decision 为 choices 字段；comment 为可空白 TextField；created_at auto_now_add。"""
    decision = SddSpecReview._meta.get_field("decision")
    assert decision.choices is not None
    assert {c[0] for c in decision.choices} == {"approve", "reject"}

    comment = SddSpecReview._meta.get_field("comment")
    assert isinstance(comment, models.TextField)
    assert comment.blank is True

    created_at = SddSpecReview._meta.get_field("created_at")
    assert created_at.auto_now_add is True


def test_meta_table_and_ordering() -> None:
    """db_table / ordering 倒序 / (spec, created_at) 索引。"""
    assert SddSpecReview._meta.db_table == "delivery_sdd_spec_review"
    assert list(SddSpecReview._meta.ordering) == ["-created_at"]
    index_field_sets = [tuple(idx.fields) for idx in SddSpecReview._meta.indexes]
    assert ("spec", "created_at") in index_field_sets


def test_append_only_no_business_write_methods() -> None:
    """append-only：模型类自身命名空间不含任何业务写方法（不可篡改，INV-6）。"""
    own_attrs = set(vars(SddSpecReview))
    forbidden = {
        "update",
        "edit",
        "apply",
        "delete_review",
        "approve",
        "reject",
        "set_decision",
    }
    leaked = own_attrs & forbidden
    assert not leaked, f"append-only 违反：SddSpecReview 不应定义业务写方法 {leaked}"


@pytest.mark.django_db(transaction=True)
async def test_cascade_setnull_and_ordering() -> None:
    """ORM 语义：spec.reviews 倒序；删 spec 级联删评审；删 reviewer 置空记录仍存。"""
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from delivery.models import SddSpec
    from repositories.models import Repository

    user_model = get_user_model()

    repo = await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    spec = await SddSpec.objects.acreate(repository=repo)
    reviewer = await user_model.objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")

    r1 = await SddSpecReview.objects.acreate(spec=spec, reviewer=reviewer, decision="approve")
    r2 = await SddSpecReview.objects.acreate(spec=spec, reviewer=reviewer, decision="reject")

    # (a) 倒序：最近创建的在前
    ordered = await sync_to_async(list)(spec.reviews.all())
    assert [r.id for r in ordered] == [r2.id, r1.id]

    # (c) 删 reviewer 用户：评审仍存且 reviewer_id 置空（SET_NULL）
    await reviewer.adelete()
    r1_refetched = await SddSpecReview.objects.aget(id=r1.id)
    assert r1_refetched.reviewer_id is None

    # (b) 删 spec：评审被级联删除（CASCADE）
    await spec.adelete()
    assert await SddSpecReview.objects.filter(id__in=[r1.id, r2.id]).acount() == 0
