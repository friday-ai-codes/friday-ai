"""蓝图三模型 + Artifact.blueprint_status 字段形状守护（Phase 111-02 Task 1）。

覆盖：

- BlueprintStatus 恰为 11 值闭集（DESIGN §4.2）。
- Artifact.blueprint_status 默认空串（旧 v0 数据不参与状态机）。
- BlueprintThread（含 anchor=None 全局线程）/ BlueprintThreadMessage /
  BlueprintReviewer 可建可读回。
- (artifact, user) 唯一约束：重复 reviewer 触发 IntegrityError。
- ThreadKind / ThreadStatus 值集合断言（DESIGN §6.1）。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError

from delivery.models import (
    Artifact,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAnchorStatus,
    ThreadAuthorType,
    ThreadKind,
    ThreadStatus,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_artifact(**kwargs) -> Artifact:
    return await Artifact.objects.acreate(artifact_type="technical_plan", **kwargs)


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


# ---- 枚举闭集 ----


def test_blueprint_status_is_exactly_11_values() -> None:
    assert set(BlueprintStatus.values) == {
        "researching",
        "drafting",
        "ai_reviewing",
        "needs_clarification",
        "pending_review",
        "confirmed",
        "implementing",
        "implemented",
        "archived",
        "failed",
        "superseded",
    }


def test_thread_kind_values() -> None:
    assert set(ThreadKind.values) == {
        "ai_clarification",
        "ai_review_finding",
        "human_comment",
        "repo_confirmation",
    }


def test_thread_status_values() -> None:
    assert set(ThreadStatus.values) == {"open", "answered", "resolved", "dismissed"}


# ---- 字段默认与形状 ----


async def test_artifact_blueprint_status_defaults_to_empty() -> None:
    artifact = await _make_artifact()
    fresh = await Artifact.objects.aget(id=artifact.id)
    assert fresh.blueprint_status == ""


async def test_thread_message_reviewer_roundtrip() -> None:
    artifact = await _make_artifact()
    user = await _make_user()

    # anchor=None 全局线程
    thread = await BlueprintThread.objects.acreate(
        artifact=artifact,
        anchor=None,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
        initiated_by_user_id="system",
    )
    fresh_thread = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh_thread.anchor is None
    assert fresh_thread.anchor_status == ThreadAnchorStatus.ANCHORED
    assert fresh_thread.status == ThreadStatus.OPEN
    assert fresh_thread.blocking is True
    assert fresh_thread.options == []
    assert fresh_thread.return_stage == ""

    # 带锚点线程
    anchored = await BlueprintThread.objects.acreate(
        artifact=artifact,
        anchor={
            "section_path": "implementation_overview.items[impl_01].how",
            "block_id": "blk_01",
            "start_offset": 0,
            "end_offset": 12,
            "quoted_text": "示例引用文本",
        },
        kind=ThreadKind.AI_CLARIFICATION,
    )
    fresh_anchored = await BlueprintThread.objects.aget(id=anchored.id)
    assert fresh_anchored.anchor["block_id"] == "blk_01"

    message = await BlueprintThreadMessage.objects.acreate(
        thread=thread,
        author_type=ThreadAuthorType.HUMAN,
        author=user,
        body="确认仓库清单",
    )
    fresh_message = await BlueprintThreadMessage.objects.aget(id=message.id)
    assert fresh_message.thread_id == thread.id
    assert fresh_message.author_id == user.id
    assert fresh_message.body == "确认仓库清单"

    reviewer = await BlueprintReviewer.objects.acreate(
        artifact=artifact,
        user=user,
        first_action="repo_confirmation",
    )
    fresh_reviewer = await BlueprintReviewer.objects.aget(id=reviewer.id)
    assert fresh_reviewer.first_action == "repo_confirmation"


# ---- 唯一约束 ----


async def test_reviewer_unique_per_artifact_user() -> None:
    artifact = await _make_artifact()
    user = await _make_user()
    await BlueprintReviewer.objects.acreate(
        artifact=artifact, user=user, first_action="final_approve"
    )
    with pytest.raises(IntegrityError):
        await BlueprintReviewer.objects.acreate(
            artifact=artifact, user=user, first_action="manual_add"
        )
