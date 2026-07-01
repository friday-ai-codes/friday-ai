"""ArtifactService 守护测试：工件 CRUD + 版本 + 禁用类型只读/不可建 + RAG 调度（ARTIFACT-02/04/05）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import Artifact, ArtifactType, Project
from initiatives.services import ArtifactDisabledError, ArtifactService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_space() -> Space:
    return Space.objects.create(name="S", feishu_project_key="art-svc-key")


@sync_to_async
def _make_project(space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@sync_to_async
def _make_type(key="t1", carrier="markdown", ragable=True, enabled=True) -> ArtifactType:
    return ArtifactType.objects.create(
        key=key, name=key, carrier=carrier, ragable=ragable, enabled=enabled
    )


async def test_create_artifact_defaults_carrier_from_type() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(carrier="feishu_doc", ragable=True)
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        artifact = await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="需求", url="https://x.feishu.cn/docx/abc"
        )
    assert artifact.carrier == "feishu_doc"
    assert artifact.version == 1
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_ARTIFACT_CREATED, target_id=str(artifact.id)
    ).aexists()


async def test_create_on_disabled_type_refused() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(enabled=False)
    with pytest.raises(ArtifactDisabledError):
        await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="X", content_ref="y"
        )


async def test_update_bumps_version_on_content_change() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(carrier="markdown", ragable=True)
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        artifact = await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="X", content_ref="v1"
        )
        updated = await ArtifactService().update_artifact(
            artifact_id=artifact.id, content_ref="v2"
        )
    assert updated.version == 2


async def test_update_on_disabled_type_read_only() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(carrier="markdown", ragable=True)
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        artifact = await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="X", content_ref="v1"
        )
    # 禁用类型后既有实例只读
    await ArtifactService().update_type(type_id=t.id, enabled=False)
    with pytest.raises(ArtifactDisabledError):
        await ArtifactService().update_artifact(artifact_id=artifact.id, content_ref="v2")


async def test_ragable_text_carrier_schedules_ingestion() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(carrier="markdown", ragable=True)
    with patch(
        "knowledge.ingestion.aschedule_ingestion", new=AsyncMock()
    ) as sched:
        await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="X", content_ref="hello"
        )
    sched.assert_awaited()
    req = sched.call_args.args[0]
    assert req.source_kind == "artifact"


async def test_graphic_artifact_schedules_metadata_only_ingestion() -> None:
    """UI 稿图形外链（external_link / ragable=False）→ 仍调度摄取（元数据-only 登记，KDEP-01）。

    覆盖全部 ArtifactType 不遗漏：service 侧不再预筛，是否进向量由 normalizer 内部按
    ragable + 载体决定（非 ragable → vectorize=False 元数据-only）。
    """
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(key="ui", carrier="external_link", ragable=False)
    with patch(
        "knowledge.ingestion.aschedule_ingestion", new=AsyncMock()
    ) as sched:
        await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, title="UI", url="https://figma.com/file/x"
        )
    sched.assert_awaited()
    req = sched.call_args.args[0]
    assert req.source_kind == "artifact"


async def test_delete_artifact() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await _make_type(carrier="markdown", ragable=False)
    artifact = await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="X", content_ref="y"
    )
    await ArtifactService().delete_artifact(artifact_id=artifact.id)
    assert not await Artifact.objects.filter(pk=artifact.id).aexists()
