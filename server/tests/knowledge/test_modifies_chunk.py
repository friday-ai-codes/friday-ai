"""MODIFIES_CHUNK chunk 边通路测试（Plan 14-01 Task 2，ENH-01 边写入/幂等/反查）。

覆盖（方法名一律 ``test_chunk_*`` 前缀，``-k chunk`` 精确选中——规划定案测试命名约定）：
1. chunk 边三连发幂等：同 EdgeSpec 经 apply_edge_specs 3 次 → 恰 1 条活跃边，
   metadata 与首次一致（Pitfall 4 代码级幂等）
2. XOR 校验：双填 / 双空 spec → warning 跳过该 spec，不 raise 整批
3. 实体边零回归：HAS_PLAN exclusive 语义不变 + 实体边/chunk 边混合批互不干扰
4. chunk_in_edges 反查：返回活跃入边（含 source_id/metadata）；invalidate 后不可见

14-03 在本文件扩展符号对齐阶梯用例组。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from structlog.testing import capture_logs

from knowledge.graph_store import graph_store
from knowledge.ingestion import EdgeSpec, apply_edge_specs
from knowledge.models import EdgeRelation, KnowledgeEdge

# apply_edge_specs / graph_store（sync_to_async 跨线程）需要真实事务隔离
pytestmark = pytest.mark.django_db(transaction=True)

CHUNK_METADATA = {
    "file_path": "src/auth.py",
    "symbol": "login",
    "commit_sha": "a" * 40,
    "resolution": "symbol",
}


def _make_chunk_registry_entry(repo_name: str = "chunk-repo") -> uuid.UUID:
    """ChunkRegistry 测试数据 sync 工厂（test_triggers.py 同款风格）：返回 chunk_id。"""
    from code_relations.models import ChunkRegistry
    from repositories.models import Repository

    repo = Repository.objects.create(
        name=repo_name,
        git_url=f"https://gitlab.com/test/{repo_name}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    entry = ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repo,
        branch_name="",
        file_path="src/auth.py",
        chunk_index=0,
        line_start=1,
        line_end=20,
    )
    return entry.chunk_id


class TestChunkEdgeIdempotency:
    """apply_edge_specs chunk 边分支：幂等 / XOR 校验 / 实体边零回归。"""

    async def test_chunk_edge_triple_fire_idempotent(self, entity_factory) -> None:
        """同 chunk EdgeSpec 三连发 → 恰 1 条活跃边，metadata 与首次一致。"""
        source = await sync_to_async(entity_factory)()
        cid = await sync_to_async(_make_chunk_registry_entry)()
        event_time = timezone.now()
        spec = EdgeSpec(
            relation=EdgeRelation.MODIFIES_CHUNK,
            target_chunk_id=cid,
            metadata=CHUNK_METADATA,
        )

        for _ in range(3):
            await apply_edge_specs(source.id, (spec,), event_time=event_time)

        assert (
            await KnowledgeEdge.objects.filter(
                target_chunk_id=cid, invalid_at__isnull=True
            ).acount()
            == 1
        )
        edge = await KnowledgeEdge.objects.aget(target_chunk_id=cid)
        assert edge.metadata == CHUNK_METADATA
        assert edge.source_entity_id == source.id
        assert edge.relation == EdgeRelation.MODIFIES_CHUNK

    async def test_chunk_spec_xor_violation_skipped_with_warning(self, entity_factory) -> None:
        """双填 / 双空 spec → warning 跳过，不 raise 整批；合法 spec 仍被处理。"""
        source, target = await sync_to_async(lambda: (entity_factory(), entity_factory()))()
        cid = uuid.uuid4()
        event_time = timezone.now()
        both_filled = EdgeSpec(
            relation=EdgeRelation.MODIFIES_CHUNK,
            target_entity_id=target.id,
            target_chunk_id=cid,
        )
        both_none = EdgeSpec(relation=EdgeRelation.RELATES_TO)
        valid = EdgeSpec(relation=EdgeRelation.MODIFIES_CHUNK, target_chunk_id=cid)

        with capture_logs() as cap:
            await apply_edge_specs(
                source.id, (both_filled, both_none, valid), event_time=event_time
            )

        warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
        assert warnings.count("knowledge_ingest_edge_spec_invalid") == 2
        # 非法 spec 零写入，合法 spec 正常建边（不被整批拖垮）
        assert await KnowledgeEdge.objects.acount() == 1
        edge = await KnowledgeEdge.objects.aget()
        assert edge.target_chunk_id == cid

    async def test_chunk_and_entity_edges_mixed_batch_no_interference(self, entity_factory) -> None:
        """实体边零回归：混合批中 HAS_PLAN exclusive 换 target 置位旧边，
        chunk 边不受 exclusive 影响照常保留。"""
        source, target_a, target_b = await sync_to_async(
            lambda: (entity_factory(), entity_factory(), entity_factory())
        )()
        cid = uuid.uuid4()
        event_time = timezone.now()

        # 首批：HAS_PLAN → target_a + chunk 边
        await apply_edge_specs(
            source.id,
            (
                EdgeSpec(EdgeRelation.HAS_PLAN, target_a.id, exclusive=True),
                EdgeSpec(relation=EdgeRelation.MODIFIES_CHUNK, target_chunk_id=cid),
            ),
            event_time=event_time,
        )
        assert await KnowledgeEdge.objects.acount() == 2

        # 第二批：HAS_PLAN 换 target → 旧实体边置位 + 新边；chunk 边幂等复用
        await apply_edge_specs(
            source.id,
            (
                EdgeSpec(EdgeRelation.HAS_PLAN, target_b.id, exclusive=True),
                EdgeSpec(relation=EdgeRelation.MODIFIES_CHUNK, target_chunk_id=cid),
            ),
            event_time=timezone.now(),
        )

        old_edge = await KnowledgeEdge.objects.aget(target_entity_id=target_a.id)
        new_edge = await KnowledgeEdge.objects.aget(target_entity_id=target_b.id)
        chunk_edge = await KnowledgeEdge.objects.aget(target_chunk_id=cid)
        assert old_edge.invalid_at is not None  # exclusive 语义不变（既有行为零回归）
        assert new_edge.invalid_at is None
        assert chunk_edge.invalid_at is None  # chunk 边不被实体边 exclusive 干扰
        assert await KnowledgeEdge.objects.acount() == 3


class TestChunkInEdges:
    """graph_store.chunk_in_edges 反查（图访问收口）。"""

    async def test_chunk_in_edges_returns_active_then_hides_invalidated(
        self, entity_factory
    ) -> None:
        """建 code_change →MODIFIES_CHUNK→ chunk 边后反查命中（含 source_id/metadata）；
        invalidate 后默认不可见。"""
        source = await sync_to_async(entity_factory)()
        cid = await sync_to_async(_make_chunk_registry_entry)("chunk-repo-2")
        event_time = timezone.now()
        await apply_edge_specs(
            source.id,
            (
                EdgeSpec(
                    relation=EdgeRelation.MODIFIES_CHUNK,
                    target_chunk_id=cid,
                    metadata=CHUNK_METADATA,
                ),
            ),
            event_time=event_time,
        )

        records = await graph_store.chunk_in_edges(cid)
        assert len(records) == 1
        record = records[0]
        assert record.source_id == source.id
        assert record.target_chunk_id == cid
        assert record.relation == EdgeRelation.MODIFIES_CHUNK
        assert record.metadata == CHUNK_METADATA
        assert record.invalid_at is None

        # 失效置位后默认不可见
        await graph_store.invalidate_edge(record.edge_id, invalid_at=timezone.now())
        assert await graph_store.chunk_in_edges(cid) == []
