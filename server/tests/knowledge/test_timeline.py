"""timeline 纯 PG 轨迹测试（Phase 15-03）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from knowledge.models import EdgeRelation, EntityKind
from knowledge.timeline import build_entity_timeline

pytestmark = pytest.mark.django_db(transaction=True)


async def test_timeline_versions_ordered(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(space=project)
    await sync_to_async(version_factory)(entity, version=1, is_latest=False)
    await sync_to_async(version_factory)(entity, version=2, is_latest=False)
    await sync_to_async(version_factory)(entity, version=3, is_latest=True)

    nodes = await build_entity_timeline(entity.id, user=user, include_superseded=True)
    assert len(nodes) == 3
    assert [n.version for n in nodes] == [1, 2, 3]


async def test_timeline_code_change_attached(entity_factory, version_factory, edge_factory, project, user, project_memberships):
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    await sync_to_async(version_factory)(plan, version=1)
    await sync_to_async(edge_factory)(plan, code, relation=EdgeRelation.IMPLEMENTED_BY)

    nodes = await build_entity_timeline(plan.id, user=user)
    assert len(nodes) == 1
    assert len(nodes[0].code_changes) >= 1


async def test_timeline_exclude_superseded(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(space=project)
    v1_time = entity.event_time
    await sync_to_async(version_factory)(entity, version=1, is_latest=False, invalid_at=v1_time + timezone.timedelta(hours=1))
    await sync_to_async(version_factory)(entity, version=2, is_latest=True)

    nodes = await build_entity_timeline(entity.id, user=user, include_superseded=False)
    assert all(n.version >= 2 for n in nodes)


async def test_timeline_zero_qdrant_calls(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(space=project)
    await sync_to_async(version_factory)(entity)
    with patch("services.qdrant_service.QdrantService.hybrid_search_by_name") as mock_qdrant:
        await build_entity_timeline(entity.id, user=user)
        mock_qdrant.assert_not_called()


async def test_timeline_unauthorized_user(entity_factory, version_factory, project, other_user):
    entity = await sync_to_async(entity_factory)(space=project)
    await sync_to_async(version_factory)(entity)
    assert await build_entity_timeline(entity.id, user=other_user) == []


async def test_timeline_as_of_excludes_future_code_change(
    entity_factory, version_factory, edge_factory, project, user, project_memberships
):
    """as_of 在边 valid_at 之前 → timeline 不含该 code_change（ENH-04）。"""
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    version_valid = timezone.now() - timezone.timedelta(days=3)
    await sync_to_async(version_factory)(plan, version=1, valid_at=version_valid, event_time=version_valid)
    future_valid = timezone.now() + timezone.timedelta(days=7)
    await sync_to_async(edge_factory)(
        plan, code, relation=EdgeRelation.IMPLEMENTED_BY, valid_at=future_valid
    )
    past_as_of = timezone.now() - timezone.timedelta(days=1)
    nodes = await build_entity_timeline(plan.id, user=user, as_of=past_as_of)
    assert len(nodes) == 1
    assert len(nodes[0].code_changes) == 0


async def test_timeline_node_provenance_feishu(
    entity_factory, version_factory, project, user, project_memberships
):
    """timeline 节点自身（非嵌套 code_change）provenance 应填充 feishu_url（W2）。"""
    entity = await sync_to_async(entity_factory)(space=project)
    feishu_url = "https://project.feishu.cn/x/story/detail/123"
    await sync_to_async(version_factory)(entity, version=1, payload={"feishu_url": feishu_url})

    nodes = await build_entity_timeline(entity.id, user=user, include_superseded=True)
    assert len(nodes) == 1
    assert nodes[0].provenance.feishu_url == feishu_url


async def test_timeline_code_change_not_cross_contaminated(
    entity_factory, version_factory, edge_factory, project, user, project_memberships
):
    """不同版本节点的 code_changes 按时间窗口归属，不互相串味（W2 bug 修复）。"""
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    code1 = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    code2 = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    await sync_to_async(version_factory)(code1, version=1)
    await sync_to_async(version_factory)(code2, version=1)

    t1 = timezone.now() - timezone.timedelta(days=10)
    t2 = timezone.now() - timezone.timedelta(days=2)
    # v1 在 [t1, t2) 有效；v2 在 [t2, ∞) 有效
    await sync_to_async(version_factory)(
        plan, version=1, is_latest=False, valid_at=t1, event_time=t1, invalid_at=t2
    )
    await sync_to_async(version_factory)(plan, version=2, is_latest=True, valid_at=t2, event_time=t2)
    # code1 边在 v1 窗口内生效；code2 边在 v2 窗口内生效
    await sync_to_async(edge_factory)(
        plan, code1, relation=EdgeRelation.IMPLEMENTED_BY, valid_at=t1 + timezone.timedelta(days=1)
    )
    await sync_to_async(edge_factory)(
        plan, code2, relation=EdgeRelation.IMPLEMENTED_BY, valid_at=t2 + timezone.timedelta(days=1)
    )

    nodes = await build_entity_timeline(plan.id, user=user, include_superseded=True)
    by_version = {n.version: n for n in nodes}
    assert set(by_version) == {1, 2}
    v1_targets = {cc.entity_id for cc in by_version[1].code_changes}
    v2_targets = {cc.entity_id for cc in by_version[2].code_changes}
    assert code1.id in v1_targets and code1.id not in v2_targets
    assert code2.id in v2_targets and code2.id not in v1_targets


async def test_timeline_as_of_passthrough_service(
    entity_factory, version_factory, project, user, project_memberships
):
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    entity = await sync_to_async(entity_factory)(space=project)
    await sync_to_async(version_factory)(entity, version=1)
    as_of = timezone.now()
    svc = DeliveryKnowledgeSearchService()
    nodes = await svc.get_timeline(entity.id, user=user, as_of=as_of)
    assert isinstance(nodes, list)
