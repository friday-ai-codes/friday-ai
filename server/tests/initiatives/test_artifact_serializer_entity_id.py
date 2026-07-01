"""ArtifactSerializer.entity_id 派生字段测试（Phase 99-02，KDEP-12 跳转锚点）。

验证序列化器暴露的 entity_id 与 generate_entity_id(DOCUMENT, artifact, id) 一致，
且与 Phase 98 关联查询内部使用的 document 实体 id 派生同源。
"""

from __future__ import annotations

import pytest

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from initiatives.serializers import ArtifactSerializer
from knowledge.models import EntityKind, generate_entity_id

pytestmark = pytest.mark.django_db


def test_artifact_serializer_exposes_deterministic_entity_id(project):
    iproj = InitiativeProject.objects.create(
        space=project,
        name="项目A",
        feishu_project_key="",
        visibility=ProjectVisibility.MEMBERS_ONLY,
    )
    atype = ArtifactType.objects.create(
        key="prd", name="PRD", carrier="markdown", ragable=True
    )
    artifact = Artifact.objects.create(
        project=iproj, type=atype, carrier="markdown", title="登录方案", version=1
    )

    data = ArtifactSerializer(artifact).data

    expected = str(generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id)))
    assert data["entity_id"] == expected
