"""``GET /api/knowledge/related/`` 的 ``?relations=`` 透传（Phase 116-04 Task 1，VIEW-04）。

守五件事：

1. ⭐ **端到端反查**：造一条 ``蓝图实体 -REFERENCES-> 被引实体`` 的活跃边，从**被引方**
   带 ``?direction=in&relations=REFERENCES&max_hops=1`` 调**真实端点**，返回体里必须含
   **引用方**。⛔ 不接受止于 ``KnowledgeEdge.objects.filter(...).exists()`` 的断言——
   边全部正确入库、端点 200、页面空白正是本相位要消灭的失败形态（T-116-27）。
2. ⭐ **反向对照（证明第 1 条非恒真）**：同一个 URL **不传** ``relations`` ⇒ 返回空，
   因为 ``_DEFAULT_RELATIONS``（``knowledge/related.py:18-22``）是
   ``[HAS_PLAN, IMPLEMENTED_BY, RELATES_TO]``、**不含 REFERENCES**。这条同时是护栏：
   任何人图省事把 ``REFERENCES`` 加进默认集，它立刻转红（T-116-36）。
3. **非法 relation → 400**（全非法 / 部分非法都拒），与既有 ``direction`` 校验同形。
4. **不传 ``relations`` 时行为逐字不变**：``HAS_PLAN`` 边仍能被默认集查到（既有实体
   详情页零回归）。
5. **``max_hops`` 的一跳/二跳差异**：三级引用链上，一跳只回直接引用者，二跳才带出更远的
   ——这是前端「被谁引用」必须显式传 ``max_hops=1`` 的理由（view 与前端默认都是 2）。
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from knowledge.models import EdgeRelation, EntityKind

pytestmark = pytest.mark.django_db


def _url(entity_id) -> str:
    return f"/api/knowledge/related/{entity_id}/"


def _make_entity(entity_factory, version_factory, project, *, kind, source_kind, source_id):
    entity = entity_factory(space=project, kind=kind, source_kind=source_kind, source_id=source_id)
    version_factory(entity)
    return entity


def _blueprint_and_target(entity_factory, version_factory, project, edge_factory):
    """``蓝图实体 -REFERENCES-> 被引 knowledge_entity`` 的最小图。"""
    blueprint = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="blueprint",
        source_id="artifact-1",
    )
    target = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.DOCUMENT,
        source_kind="feishu_document",
        source_id="doc-token-1",
    )
    edge_factory(
        blueprint,
        target,
        relation=EdgeRelation.REFERENCES,
        valid_at=timezone.now(),
    )
    return blueprint, target


def test_reverse_lookup_returns_referrer_end_to_end(
    entity_factory,
    version_factory,
    edge_factory,
    project,
    user,
    project_memberships,
    authenticated_client,
):
    """⭐ 端到端：被引方 ``?direction=in&relations=REFERENCES&max_hops=1`` 查回引用方。"""
    blueprint, target = _blueprint_and_target(
        entity_factory, version_factory, project, edge_factory
    )

    resp = authenticated_client.get(
        _url(target.id),
        {"direction": "in", "relations": EdgeRelation.REFERENCES, "max_hops": 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [item["entity_id"] for item in body] == [str(blueprint.id)]
    assert body[0]["relation"] == EdgeRelation.REFERENCES
    assert body[0]["depth"] == 1


def test_reverse_lookup_without_relations_is_empty(
    entity_factory,
    version_factory,
    edge_factory,
    project,
    user,
    project_memberships,
    authenticated_client,
):
    """⭐ 反向对照 + 护栏：不传 relations ⇒ 空（``REFERENCES`` 不在默认集里）。

    有人把 ``REFERENCES`` 加进 ``_DEFAULT_RELATIONS`` 时本条转红。
    """
    _, target = _blueprint_and_target(entity_factory, version_factory, project, edge_factory)

    resp = authenticated_client.get(_url(target.id), {"direction": "in", "max_hops": 1})

    assert resp.status_code == 200
    assert resp.json() == []


def test_invalid_relation_returns_400(
    entity_factory, version_factory, project, user, project_memberships, authenticated_client
):
    entity = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="blueprint",
        source_id="artifact-400",
    )

    resp = authenticated_client.get(_url(entity.id), {"relations": "NOT_A_RELATION"})

    assert resp.status_code == 400
    assert "relations must be a subset of" in resp.json()["detail"]
    assert EdgeRelation.REFERENCES in resp.json()["detail"]


def test_partially_invalid_relations_returns_400(
    entity_factory, version_factory, project, user, project_memberships, authenticated_client
):
    """部分非法也整体拒——半个白名单等于没有白名单。"""
    entity = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="blueprint",
        source_id="artifact-400b",
    )

    resp = authenticated_client.get(_url(entity.id), {"relations": "REFERENCES,BOGUS"})

    assert resp.status_code == 400


def test_default_relations_unchanged_when_param_absent(
    entity_factory,
    version_factory,
    edge_factory,
    project,
    user,
    project_memberships,
    authenticated_client,
):
    """不传 relations 时既有三条默认关系行为逐字不变（HAS_PLAN 仍可查）。"""
    work_item = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.WORK_ITEM,
        source_kind="feishu_work_item",
        source_id="p:t:1",
    )
    plan = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="workflow_plan",
        source_id="exec:node",
    )
    edge_factory(work_item, plan, relation=EdgeRelation.HAS_PLAN)

    resp = authenticated_client.get(_url(work_item.id), {"direction": "out", "max_hops": 1})

    assert resp.status_code == 200
    assert [item["entity_id"] for item in resp.json()] == [str(plan.id)]


def _reference_chain(entity_factory, version_factory, edge_factory, project):
    """A -REFERENCES-> B -REFERENCES-> C。"""
    a = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="blueprint",
        source_id="chain-a",
    )
    b = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.TECH_PLAN,
        source_kind="blueprint",
        source_id="chain-b",
    )
    c = _make_entity(
        entity_factory,
        version_factory,
        project,
        kind=EntityKind.DOCUMENT,
        source_kind="feishu_document",
        source_id="chain-c",
    )
    edge_factory(a, b, relation=EdgeRelation.REFERENCES)
    edge_factory(b, c, relation=EdgeRelation.REFERENCES)
    return a, b, c


def test_max_hops_one_returns_only_direct_referrer(
    entity_factory,
    version_factory,
    edge_factory,
    project,
    user,
    project_memberships,
    authenticated_client,
):
    """⭐ 一跳只回直接引用者——前端「被谁引用」必须显式传 max_hops=1 的理由。"""
    _a, b, c = _reference_chain(entity_factory, version_factory, edge_factory, project)

    resp = authenticated_client.get(
        _url(c.id),
        {"direction": "in", "relations": EdgeRelation.REFERENCES, "max_hops": 1},
    )

    assert resp.status_code == 200
    assert [item["entity_id"] for item in resp.json()] == [str(b.id)]


def test_max_hops_two_returns_transitive_referrer(
    entity_factory,
    version_factory,
    edge_factory,
    project,
    user,
    project_memberships,
    authenticated_client,
):
    """二跳才带出间接引用者（默认 max_hops=2 会把它混进「直接引用者」，T-116-35）。"""
    a, b, c = _reference_chain(entity_factory, version_factory, edge_factory, project)

    resp = authenticated_client.get(
        _url(c.id),
        {"direction": "in", "relations": EdgeRelation.REFERENCES, "max_hops": 2},
    )

    assert resp.status_code == 200
    assert {item["entity_id"] for item in resp.json()} == {str(a.id), str(b.id)}
