"""边 metadata 幂等 upsert 收口测试（Phase 98-01 Task 1，KDEP-07）。

覆盖：
- graph_store.update_edge_metadata：活跃边就地覆盖 metadata / 边不存在响亮报错 /
  已失效边幂等返回（不复活历史 metadata）/ 不触碰四时间戳。
- apply_edge_specs 实体边分支：首次建边携带 spec.metadata / 重复应用覆盖 metadata
  不产生重复边 / metadata=None 的 spec 保持跳过（既有 REFERENCES 边零回归）。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from knowledge.graph_store import graph_store
from knowledge.ingestion import EdgeSpec, apply_edge_specs
from knowledge.models import EdgeRelation, KnowledgeEdge

pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# graph_store.update_edge_metadata
# ============================================================================


async def test_update_edge_metadata_overwrites_active_edge(entity_factory, edge_factory):
    """活跃边 metadata 就地覆盖为最新，四时间戳不变。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge = edge_factory(a, b, metadata={"source": "artifact", "score": 0.1})
        return edge

    edge = await sync_to_async(_setup)()
    await graph_store.update_edge_metadata(
        edge.id, metadata={"source": "artifact", "score": 0.9, "keywords": ["auth"]}
    )

    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.metadata == {"source": "artifact", "score": 0.9, "keywords": ["auth"]}
    assert refreshed.invalid_at is None
    assert refreshed.expired_at is None


async def test_update_edge_metadata_missing_edge_raises():
    """边不存在 → DoesNotExist（响亮，同 invalidate_edge 语义）。"""
    with pytest.raises(KnowledgeEdge.DoesNotExist):
        await graph_store.update_edge_metadata(uuid.uuid4(), metadata={"x": 1})


async def test_update_edge_metadata_invalidated_edge_is_noop(entity_factory, edge_factory):
    """已失效边幂等返回，绝不复活历史边 metadata。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        # invalid_at 必须严格晚于 valid_at（kedge_valid_range: invalid_at > valid_at）；
        # 两次 timezone.now() 可能落在同一微秒 tick 导致 invalid_at == valid_at 违约（时序 flaky），
        # 故显式让失效时间落在成立之后，保证约束确定性满足。
        valid = timezone.now()
        edge = edge_factory(
            a,
            b,
            valid_at=valid,
            invalid_at=valid + timedelta(seconds=1),
            metadata={"v": "old"},
        )
        return edge

    edge = await sync_to_async(_setup)()
    # 不抛错，幂等返回
    await graph_store.update_edge_metadata(edge.id, metadata={"v": "new"})

    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.metadata == {"v": "old"}


async def test_update_edge_metadata_none_becomes_empty_dict(entity_factory, edge_factory):
    """metadata 传 None/空 → 归一化为空 dict（不写 NULL）。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        return edge_factory(a, b, metadata={"stale": True})

    edge = await sync_to_async(_setup)()
    await graph_store.update_edge_metadata(edge.id, metadata={})
    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.metadata == {}


# ============================================================================
# apply_edge_specs 实体边 metadata upsert
# ============================================================================


async def test_apply_edge_specs_creates_edge_with_metadata(entity_factory):
    """首次应用带 metadata 的实体 EdgeSpec → 建边并写入 metadata。"""

    def _setup():
        return entity_factory(), entity_factory()

    src, tgt = await sync_to_async(_setup)()
    meta = {"source": "artifact", "artifact_id": "aid", "node_paths": ["a/b"], "score": 0.5}
    await apply_edge_specs(
        src.id,
        (EdgeSpec(relation=EdgeRelation.RELATES_TO, target_entity_id=tgt.id, metadata=meta),),
        event_time=timezone.now(),
    )

    edges = await sync_to_async(
        lambda: list(KnowledgeEdge.objects.filter(source_entity_id=src.id, invalid_at__isnull=True))
    )()
    assert len(edges) == 1
    assert edges[0].target_entity_id == tgt.id
    assert edges[0].metadata == meta


async def test_apply_edge_specs_reapply_overwrites_metadata_no_dup(entity_factory):
    """重复应用同 (source, target) 带 metadata 的 spec → 覆盖 metadata，不产生重复边。"""

    def _setup():
        return entity_factory(), entity_factory()

    src, tgt = await sync_to_async(_setup)()
    now = timezone.now()
    await apply_edge_specs(
        src.id,
        (
            EdgeSpec(
                relation=EdgeRelation.RELATES_TO,
                target_entity_id=tgt.id,
                metadata={"score": 0.1},
            ),
        ),
        event_time=now,
    )
    await apply_edge_specs(
        src.id,
        (
            EdgeSpec(
                relation=EdgeRelation.RELATES_TO,
                target_entity_id=tgt.id,
                metadata={"score": 0.9, "keywords": ["k"]},
            ),
        ),
        event_time=now,
    )

    edges = await sync_to_async(
        lambda: list(KnowledgeEdge.objects.filter(source_entity_id=src.id, invalid_at__isnull=True))
    )()
    assert len(edges) == 1
    assert edges[0].metadata == {"score": 0.9, "keywords": ["k"]}


async def test_apply_edge_specs_none_metadata_keeps_skip(entity_factory, edge_factory):
    """metadata=None 的 spec 命中已存在活跃边 → 保持跳过，既有边 metadata 不变（零回归）。"""

    def _setup():
        src, tgt = entity_factory(), entity_factory()
        edge = edge_factory(
            src, tgt, relation=EdgeRelation.REFERENCES, metadata={"existing": True}
        )
        return src, tgt, edge

    src, tgt, edge = await sync_to_async(_setup)()
    await apply_edge_specs(
        src.id,
        (EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=tgt.id, metadata=None),),
        event_time=timezone.now(),
    )

    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.metadata == {"existing": True}
    edge_count = await KnowledgeEdge.objects.filter(
        source_entity_id=src.id, relation=EdgeRelation.REFERENCES, invalid_at__isnull=True
    ).acount()
    assert edge_count == 1
