"""工件在线查看读取守护测试（ARTIFACT-03）：md/外链/飞书 doc（mock）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import Artifact, ArtifactType, Project
from initiatives.services import ArtifactService
from initiatives.services.artifact_view import aget_artifact_view
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _setup(carrier, ragable=False, key="vt", url="", content_ref=""):
    space = Space.objects.create(name="S", feishu_project_key=f"view-{key}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    artifact_type = ArtifactType.objects.create(
        key=key, name=key, carrier=carrier, ragable=ragable
    )
    return space, project, artifact_type


@sync_to_async
def _reload(artifact_id) -> Artifact:
    return Artifact.objects.select_related("type", "project", "project__space").get(
        pk=artifact_id
    )


async def test_view_markdown_returns_content() -> None:
    _space, project, t = await _setup("markdown", key="md")
    artifact = await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="X", content_ref="# Hi\n正文"
    )
    view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "markdown"
    assert "正文" in view["content"]


async def test_view_external_link_metadata_only() -> None:
    _space, project, t = await _setup("external_link", key="ext")
    artifact = await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="UI", url="https://figma.com/file/x"
    )
    view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "link"
    assert view["url"] == "https://figma.com/file/x"
    assert "content" not in view


async def test_view_feishu_doc_renders_markdown() -> None:
    _space, project, t = await _setup("feishu_doc", ragable=True, key="fd")
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        artifact = await ArtifactService().create_artifact(
            project_id=project.id,
            type_id=t.id,
            title="需求",
            url="https://x.feishu.cn/docx/doctoken123",
        )
    mock_client = MagicMock()
    mock_client.get_document_content = AsyncMock(return_value=("# 渲染后\n内容", []))
    with patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(return_value=mock_client),
    ):
        view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "markdown"
    assert "渲染后" in view["content"]


async def test_view_feishu_doc_fetch_failure_fail_soft() -> None:
    _space, project, t = await _setup("feishu_doc", ragable=True, key="fderr")
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        artifact = await ArtifactService().create_artifact(
            project_id=project.id,
            type_id=t.id,
            title="需求",
            url="https://x.feishu.cn/docx/doctoken123",
        )
    with patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(side_effect=RuntimeError("无凭证")),
    ):
        view = await aget_artifact_view(await _reload(artifact.id))
    # fail-soft：返回错误字段而非抛
    assert view["render_type"] == "markdown"
    assert view["content"] == ""
    assert "error" in view
