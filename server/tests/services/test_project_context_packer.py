"""项目上下文打包器守护测试（Phase 80，RECALL-01/03）：

- fail-closed：非成员零召回零泄漏
- 聚合记忆/需求/工件
- token 预算降级（超预算按优先级裁剪低优层：history 先丢，memory 保留）
- RetrievalTrace 写入（条数/分层耗时）
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import Artifact, ArtifactType
from initiatives.services import MemoryService, ProjectService
from interactions.models import RetrievalTrace
from projects.models import Space
from services.project_context_packer import pack_project_context

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="pack-k", created_by=owner
    )
    project = await type(project).objects.select_related("space").aget(pk=project.id)
    return project, owner


async def test_non_member_zero_recall_fail_closed():
    project, owner = await _make_project_with_member()
    await MemoryService().append(
        project_id=project.id, content="机密决策", contributor=owner
    )
    stranger = await _make_user("stranger")
    packed = await pack_project_context(project, stranger)
    assert packed.text == ""
    assert packed.included_layers == []


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
