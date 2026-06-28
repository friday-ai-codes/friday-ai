"""ArtifactService 行为测试（Chassis v2 · P1）。

覆盖 create（校验 + v1 + current）/ add_version（hash 复用 vs supersedes 链）/
status + approve / registry 校验拦截 / 任意 artifact_type 可注册。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from delivery.artifacts import (
    is_registered,
    register_artifact_type,
    registered_types,
    validate_content,
)
from delivery.models import (
    ArtifactApprovalStatus,
    ArtifactStatus,
    ArtifactVersion,
)
from delivery.services import ArtifactContentInvalid, ArtifactService


def _valid_plan_content(title: str = "标题") -> dict:
    return {
        "title": title,
        "summary": "摘要",
        "execution_plan": [
            {
                "id": "t1",
                "name": "任务一",
                "repository_id": "repo-1",
                "repository_name": "repo",
                "branch_strategy": "feature",
            }
        ],
    }


def test_technical_plan_type_registered():
    assert is_registered("technical_plan")
    assert "technical_plan" in registered_types()


def test_validate_content_unregistered_type_fails():
    ok, err = validate_content("does_not_exist", {})
    assert ok is False
    assert "未注册" in (err or "")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_builds_artifact_v1_current():
    svc = ArtifactService()
    artifact = await svc.create("technical_plan", _valid_plan_content())
    assert artifact.current_version_id is not None
    assert artifact.status == ArtifactStatus.DRAFT
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)
    assert v1.version_no == 1
    assert v1.content_hash != ""
    count = await sync_to_async(ArtifactVersion.objects.filter(artifact=artifact).count)()
    assert count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_invalid_content_rejected():
    svc = ArtifactService()
    with pytest.raises(ArtifactContentInvalid):
        await svc.create("technical_plan", {"title": "缺 execution_plan"})


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_add_version_hash_dedup_and_supersedes():
    svc = ArtifactService()
    artifact = await svc.create("technical_plan", _valid_plan_content("v1"))
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)

    # 相同内容：hash 相等，复用 current 不翻版本
    same = await svc.add_version(artifact, _valid_plan_content("v1"))
    assert same.id == v1.id
    count = await sync_to_async(ArtifactVersion.objects.filter(artifact=artifact).count)()
    assert count == 1

    # 不同内容：建新版本 v2，supersedes=v1，推进 current
    v2 = await svc.add_version(artifact, _valid_plan_content("v2"))
    assert v2.version_no == 2
    assert v2.supersedes_id == v1.id
    await artifact.arefresh_from_db()
    assert artifact.current_version_id == v2.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_approve_version_flows_status():
    svc = ArtifactService()
    artifact = await svc.create("technical_plan", _valid_plan_content())
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)

    await svc.approve_version(v1, approved=True)
    await v1.arefresh_from_db()
    await artifact.arefresh_from_db()
    assert v1.approval_status == ArtifactApprovalStatus.APPROVED
    assert artifact.status == ArtifactStatus.APPROVED


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_custom_artifact_type_roundtrip():
    """证明任意 process 可注册新 artifact_type 走同一 service（泛化性验证）。"""
    register_artifact_type(
        "review_report_test",
        validator=lambda c: (("verdict" in c), None if "verdict" in c else "缺 verdict"),
    )
    svc = ArtifactService()
    artifact = await svc.create("review_report_test", {"verdict": "pass", "notes": "ok"})
    assert artifact.artifact_type == "review_report_test"
    assert artifact.current_version_id is not None

    with pytest.raises(ArtifactContentInvalid):
        await svc.create("review_report_test", {"notes": "missing verdict"})
