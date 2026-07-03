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
    mock_client.get_document_content_by_url = AsyncMock(return_value=("# 渲染后\n内容", []))
    with patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(return_value=mock_client),
    ):
        view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "markdown"
    assert "渲染后" in view["content"]


@sync_to_async
def _setup_feature_list(key_suffix: str):
    """feature_list 工件用 seed 的内置类型（key 唯一，不能重复 create）。"""
    space = Space.objects.create(name="S", feishu_project_key=f"view-fl-{key_suffix}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    artifact_type, _created = ArtifactType.objects.get_or_create(
        key="feature_list", defaults={"name": "Feature List", "carrier": "markdown"}
    )
    return space, project, artifact_type


async def test_view_feature_list_json_renders_readable_markdown() -> None:
    _space, project, t = await _setup_feature_list("ok")
    content = (
        '{"modules": [{"module": "模块 1：入口与权益", "features": ['
        '{"name": "功能点 A：入口位置", "acceptance": ["- 当 用户进入功能页 时，展示入口"],'
        ' "source": "#### 功能点 A：入口位置\\n\\n- 功能描述：入口固定在右侧。"},'
        '{"name": "功能点 B：权益鉴权", "acceptance": ["持有课程包时展示"], "status": "已完成"}'
        "]}]}"
    )
    artifact = await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="Feature List（手动录入）",
        carrier="markdown", content_ref=content,
    )
    view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "markdown"
    # 不再回显原始 JSON
    assert '{"modules"' not in view["content"]
    # 模块/功能点标题 + source 原文 + 无 source 时验收列表
    assert "## 模块 1：入口与权益" in view["content"]
    assert "### 1. 功能点 A：入口位置" in view["content"]
    assert "- 功能描述：入口固定在右侧。" in view["content"]
    assert "### 2. 功能点 B：权益鉴权（已完成）" in view["content"]
    assert "**验收标准**" in view["content"]
    assert "- 持有课程包时展示" in view["content"]
    # source 段首与功能点名重复的标题被去掉（避免标题两连）
    assert "#### 功能点 A" not in view["content"]


async def test_view_feature_list_invalid_json_falls_back_to_raw() -> None:
    _space, project, t = await _setup_feature_list("raw")
    artifact = await ArtifactService().create_artifact(
        project_id=project.id, type_id=t.id, title="Feature List",
        carrier="markdown", content_ref="# 手写的 markdown\n不是 JSON",
    )
    view = await aget_artifact_view(await _reload(artifact.id))
    assert view["render_type"] == "markdown"
    assert "手写的 markdown" in view["content"]


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
