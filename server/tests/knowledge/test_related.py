"""related 图关联测试（Phase 15-03）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from knowledge.models import EdgeRelation, EntityKind
from knowledge.related import fetch_related_entities

pytestmark = pytest.mark.django_db(transaction=True)


async def _chain(entity_factory, edge_factory, version_factory, project):
    wi = await sync_to_async(entity_factory)(kind=EntityKind.WORK_ITEM, project=project)
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, project=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, project=project)
    await sync_to_async(version_factory)(wi)
    await sync_to_async(version_factory)(plan)
    await sync_to_async(version_factory)(code)
    await sync_to_async(edge_factory)(wi, plan, relation=EdgeRelation.HAS_PLAN)
    await sync_to_async(edge_factory)(plan, code, relation=EdgeRelation.IMPLEMENTED_BY)
    return wi, plan, code


async def test_related_out_from_work_item(entity_factory, edge_factory, version_factory, project, user, project_memberships):
    wi, plan, code = await _chain(entity_factory, edge_factory, version_factory, project)
    related = await fetch_related_entities(wi.id, user=user, direction="out", max_hops=2)
    kinds = {r.entity_kind for r in related}
    assert EntityKind.TECH_PLAN in kinds
    assert EntityKind.CODE_CHANGE in kinds


async def test_related_in_from_code_change(entity_factory, edge_factory, version_factory, project, user, project_memberships):
    wi, plan, code = await _chain(entity_factory, edge_factory, version_factory, project)
    related = await fetch_related_entities(code.id, user=user, direction="in", max_hops=2)
    kinds = {r.entity_kind for r in related}
    assert EntityKind.TECH_PLAN in kinds
    assert EntityKind.WORK_ITEM in kinds


async def test_related_both_merges(entity_factory, edge_factory, version_factory, project, user, project_memberships):
    wi, plan, code = await _chain(entity_factory, edge_factory, version_factory, project)
    related = await fetch_related_entities(plan.id, user=user, direction="both", max_hops=2)
    assert len(related) >= 2


async def test_related_as_of_filters(entity_factory, edge_factory, version_factory, project, user, project_memberships):
    wi, plan, _ = await _chain(entity_factory, edge_factory, version_factory, project)
    past = timezone.now()
    related = await fetch_related_entities(
        wi.id, user=user, direction="out", max_hops=2, as_of=past
    )
    assert isinstance(related, list)


async def test_related_unauthorized(entity_factory, edge_factory, version_factory, project, other_user):
    wi, _, _ = await _chain(entity_factory, edge_factory, version_factory, project)
    assert await fetch_related_entities(wi.id, user=other_user) == []
