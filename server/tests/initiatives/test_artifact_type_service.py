"""ArtifactType 守护测试：CRUD + 禁用 + 删除保护 + builtin 禁删（ARTIFACT-01/05）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import Artifact, ArtifactType, Project
from initiatives.services import ArtifactService, ArtifactTypeError
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_space() -> Space:
    return Space.objects.create(name="S", feishu_project_key="art-type-key")


@sync_to_async
def _make_project(space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@sync_to_async
def _make_builtin_type(key="builtin_x") -> ArtifactType:
    # 直接造一个 builtin 类型验证禁删（transaction=True 会清空迁移 seed 行，故不依赖 seed）。
    return ArtifactType.objects.create(
        key=key, name="内置", carrier="feishu_doc", ragable=True, builtin=True
    )


def test_seed_migration_defines_eight_builtin_types() -> None:
    """seed 迁移定义内置 8 类（不依赖 DB，避免 TransactionTestCase 清表干扰）。"""
    import importlib

    mod = importlib.import_module("initiatives.migrations.0004_seed_artifact_types")
    assert len(mod.BUILTIN_TYPES) == 8
    keys = {t[0] for t in mod.BUILTIN_TYPES}
    assert "requirement_doc" in keys and "ui_design" in keys
    # UI 稿不可 RAG，文字类可 RAG
    by_key = {t[0]: t for t in mod.BUILTIN_TYPES}
    assert by_key["ui_design"][3] is False
    assert by_key["requirement_doc"][3] is True


async def test_create_custom_type() -> None:
    t = await ArtifactService().create_type(
        key="custom_doc", name="自定义文档", carrier="markdown", ragable=True
    )
    assert t.builtin is False
    assert t.enabled is True
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_ARTIFACT_TYPE_CREATED, target_id=str(t.id)
    ).aexists()


async def test_update_type_disable() -> None:
    t = await ArtifactService().create_type(
        key="disable_me", name="X", carrier="markdown"
    )
    updated = await ArtifactService().update_type(type_id=t.id, enabled=False)
    assert updated.enabled is False


async def test_delete_custom_type_ok() -> None:
    t = await ArtifactService().create_type(key="del_me", name="X", carrier="markdown")
    await ArtifactService().delete_type(type_id=t.id)
    assert not await ArtifactType.objects.filter(pk=t.id).aexists()


async def test_delete_builtin_type_refused() -> None:
    builtin = await _make_builtin_type()
    with pytest.raises(ArtifactTypeError):
        await ArtifactService().delete_type(type_id=builtin.id)
    assert await ArtifactType.objects.filter(pk=builtin.id).aexists()


async def test_delete_type_with_instances_protected() -> None:
    space = await _make_space()
    project = await _make_project(space)
    t = await ArtifactService().create_type(
        key="has_inst", name="X", carrier="markdown"
    )
    await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="A", content_ref="x"
    )
    with pytest.raises(ArtifactTypeError):
        await ArtifactService().delete_type(type_id=t.id)
    # 受保护：类型与实例都还在
    assert await ArtifactType.objects.filter(pk=t.id).aexists()
    assert await Artifact.objects.filter(type=t).aexists()
