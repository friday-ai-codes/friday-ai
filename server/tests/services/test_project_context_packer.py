"""项目上下文打包器守护测试（Phase 80，RECALL-01/03）：

- fail-closed：非成员零召回零泄漏
- 聚合记忆/需求/工件
- token 预算降级（超预算按优先级裁剪低优层：history 先丢，memory 保留）
- RetrievalTrace 写入（条数/分层耗时）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.services import MemoryService, ProjectService
from interactions.models import RetrievalTrace
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO
from projects.models import Space
from services.project_context_packer import pack_project_context

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_member(*, key="pack-k", visibility=ProjectVisibility.PUBLIC_ORG):
    """建项目并显式设 visibility（绕过 update 白名单，仅测试夹具用，不进生产写路径）。"""
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user(f"owner-{key}")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    project = await type(project).objects.select_related("space").aget(pk=project.id)
    return project, owner


async def test_members_only_non_member_zero_recall_fail_closed():
    """members_only 非成员 → 零召回零泄漏（维持 fail-closed）。"""
    project, owner = await _make_project_with_member(
        key="mo-k", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    await MemoryService().append(
        project_id=project.id, content="机密决策", contributor=owner
    )
    stranger = await _make_user("stranger")
    packed = await pack_project_context(project, stranger)
    assert packed.text == ""
    assert packed.included_layers == []


async def test_public_org_non_member_can_recall():
    """public_org 非成员 → 读放行（按内容产出非空打包）。"""
    project, owner = await _make_project_with_member(
        key="po-k", visibility=ProjectVisibility.PUBLIC_ORG
    )
    await MemoryService().append(
        project_id=project.id, content="公开记忆条目", contributor=owner
    )
    stranger = await _make_user("stranger-po")
    packed = await pack_project_context(project, stranger)
    assert "公开记忆条目" in packed.text
    assert packed.included_layers != []


async def test_member_members_only_not_regressed():
    """成员 + members_only → 仍可召回（读放宽不回退成员既有权限）。"""
    project, owner = await _make_project_with_member(
        key="mo-mem-k", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    await MemoryService().append(
        project_id=project.id, content="成员可见记忆", contributor=owner
    )
    packed = await pack_project_context(project, owner)
    assert "成员可见记忆" in packed.text
    assert packed.included_layers != []


async def test_aggregates_memory_and_artifacts():
    project, owner = await _make_project_with_member()
    await MemoryService().append(
        project_id=project.id, content="记忆条目A", contributor=owner
    )
    art_type = await sync_to_async(ArtifactType.objects.create)(
        key="spec_pack", name="研发Spec", carrier="markdown", ragable=True, builtin=False
    )
    await sync_to_async(Artifact.objects.create)(
        project_id=project.id,
        type=art_type,
        carrier="markdown",
        title="设计文档",
        content_ref="正文片段内容",
        version=1,
    )
    packed = await pack_project_context(project, owner)
    assert "记忆条目A" in packed.text
    assert "设计文档" in packed.text
    assert "memory" in packed.included_layers
    assert packed.counts.get("memory", 0) >= 1


async def test_token_budget_degradation_trims_low_priority():
    project, owner = await _make_project_with_member()
    # 大量记忆把预算占满；history 为低优先级层应被裁剪。
    for i in range(20):
        await MemoryService().append(
            project_id=project.id,
            content=f"重要记忆 {i} " + ("x" * 200),
            contributor=owner,
        )
    history = [f"历史消息 {j} " + ("y" * 200) for j in range(20)]
    packed = await pack_project_context(
        project, owner, history_messages=history, token_budget=300
    )
    assert packed.degraded is True
    # 高优先级 memory 保留，低优先级 history 被裁剪。
    assert "memory" in packed.included_layers
    assert "history" not in packed.included_layers


async def test_retrieval_trace_written():
    project, owner = await _make_project_with_member()
    await MemoryService().append(
        project_id=project.id, content="x", contributor=owner
    )
    await pack_project_context(
        project, owner, query="设计", conversation_id="conv-pack-1"
    )
    count = await RetrievalTrace.objects.filter(
        source="chat_project_context", conversation_id="conv-pack-1"
    ).acount()
    assert count >= 1


def _rag_result(
    *,
    title: str,
    source_kind: str,
    project_id: str,
) -> SearchResultDTO:
    return SearchResultDTO(
        score=0.9,
        vector_score=0.9,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=uuid.uuid4(),
            entity_kind="document",
            version=1,
            title=title,
            valid_at=None,
            invalid_at=None,
            source_kind=source_kind,
            source_id=str(uuid.uuid4()),
            origin=source_kind,
            event_time=None,
            space_id=project_id,
            repository_id=None,
            provenance=ProvenanceLinks(),
        ),
    )


async def test_rag_layer_includes_session_capture_without_excluding_project_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 144 inclusion：按项目收窄，同时保留 Capture 与既有 DOCUMENT 来源。"""
    project, owner = await _make_project_with_member(key="rag-session-capture")
    search = AsyncMock(
        return_value=[
            _rag_result(
                title="会话精华",
                source_kind="session_capture",
                project_id=str(project.id),
            ),
            _rag_result(
                title="项目状态文档",
                source_kind="project_state",
                project_id=str(project.id),
            ),
        ]
    )
    monkeypatch.setattr(
        "knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar",
        search,
    )

    packed = await pack_project_context(project, owner, query="部署")

    kwargs = search.await_args.kwargs
    assert kwargs["project_ids"] == [str(project.id)]
    assert kwargs["include_document_kind"] is True
    assert kwargs.get("source_kinds") in (None, []) or kwargs["source_kinds"] != [
        "session_capture"
    ]
    assert "会话精华" in packed.text
    assert "项目状态文档" in packed.text
