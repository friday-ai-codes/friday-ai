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
    entity = await sync_to_async(entity_factory)(project=project)
    await sync_to_async(version_factory)(entity, version=1, is_latest=False)
    await sync_to_async(version_factory)(entity, version=2, is_latest=False)
    await sync_to_async(version_factory)(entity, version=3, is_latest=True)

    nodes = await build_entity_timeline(entity.id, user=user, include_superseded=True)
    assert len(nodes) == 3
    assert [n.version for n in nodes] == [1, 2, 3]


async def test_timeline_code_change_attached(entity_factory, version_factory, edge_factory, project, user, project_memberships):
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, project=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, project=project)
    await sync_to_async(version_factory)(plan, version=1)
    await sync_to_async(edge_factory)(plan, code, relation=EdgeRelation.IMPLEMENTED_BY)

    nodes = await build_entity_timeline(plan.id, user=user)
    assert len(nodes) == 1
    assert len(nodes[0].code_changes) >= 1


async def test_timeline_exclude_superseded(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(project=project)
    v1_time = entity.event_time
    await sync_to_async(version_factory)(entity, version=1, is_latest=False, invalid_at=v1_time + timezone.timedelta(hours=1))
    await sync_to_async(version_factory)(entity, version=2, is_latest=True)

    nodes = await build_entity_timeline(entity.id, user=user, include_superseded=False)
    assert all(n.version >= 2 for n in nodes)


async def test_timeline_zero_qdrant_calls(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(project=project)
    await sync_to_async(version_factory)(entity)
    with patch("services.qdrant_service.QdrantService.hybrid_search_by_name") as mock_qdrant:
        await build_entity_timeline(entity.id, user=user)
        mock_qdrant.assert_not_called()


async def test_timeline_unauthorized_user(entity_factory, version_factory, project, other_user):
    entity = await sync_to_async(entity_factory)(project=project)
    await sync_to_async(version_factory)(entity)
    assert await build_entity_timeline(entity.id, user=other_user) == []
