"""HDIFF-02 守护测试：as-of 查询 + 重索引对账失效 + best-effort 钩子降级。

覆盖（33-02）：
- ``TestAsOfQuery``：``amodifies_chunk_edges`` 历史 as_of 见当年成立边、当前视图只见
  未失效边；invalidate 置位后 as_of<invalid_at 仍可见、>=invalid_at 与当前视图不可见；
  naive as_of 经 require_aware 拒绝；repository_id-scoped 路径同款 bi-temporal 谓词。
- ``TestReconcile``：``areconcile_modifies_chunk_edges`` 把过期 MODIFIES_CHUNK 边置
  invalid_at（chunk 删除 / 内容取代两类信号；置位不删除；幂等；缺指纹保守；
  时间次序 invalid_at>valid_at；逐边降级；跨 repo 隔离）。
- ``TestReconcileHookFailSafe``：indexer 钩子 ``_run_modifies_chunk_reconcile``
  对账抛异常时吞掉 + warning，绝不阻断索引 success。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from knowledge.graph_store import graph_store
from knowledge.ingestion import EdgeSpec, apply_edge_specs
from knowledge.models import EdgeRelation, EntityKind, KnowledgeEdge
from knowledge.modifies_chunk import amodifies_chunk_edges

# apply_edge_specs / graph_store（sync_to_async 跨线程）需要真实事务隔离
pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo(name: str):
    """Repository sync 工厂。"""
    from repositories.models import Repository

    return Repository.objects.create(
        name=name,
        git_url=f"https://gitlab.com/test/{name}.git",
        git_platform="gitlab",
        default_branch="main",
    )


def _make_chunk(
    repo,
    *,
    chunk_id: uuid.UUID | None = None,
    content_hash: str = "0" * 64,
    file_path: str = "src/auth.py",
    chunk_index: int = 0,
) -> uuid.UUID:
    """ChunkRegistry base 命名空间（branch_name=""）sync 工厂，返回 chunk_id。"""
    from code_relations.models import ChunkRegistry

    entry = ChunkRegistry.objects.create(
        chunk_id=chunk_id or uuid.uuid4(),
        content_hash=content_hash,
        repository=repo,
        branch_name="",
        file_path=file_path,
        chunk_index=chunk_index,
        line_start=1,
        line_end=20,
    )
    return entry.chunk_id


async def _make_modifies_chunk_edge(
    *,
    repo,
    target_chunk_id: uuid.UUID,
    content_hash: str | None,
    event_time: datetime,
):
    """建 code_change 实体（绑定 repository）+ 一条 MODIFIES_CHUNK 边（经 apply_edge_specs 收口）。

    metadata.chunk_content_hash 冻结当年指纹（None=历史边缺指纹，键不写入）。
    返回 (source_entity, edge)。
    """
    from knowledge.models import EntityOrigin, KnowledgeEntity, generate_entity_id

    def _create_entity() -> KnowledgeEntity:
        sid = uuid.uuid4().hex
        return KnowledgeEntity.objects.create(
            id=generate_entity_id(EntityKind.CODE_CHANGE, "task_result", sid),
            kind=EntityKind.CODE_CHANGE,
            source_kind="task_result",
            source_id=sid,
            origin=EntityOrigin.WORKFLOW,
            title="测试代码变更",
            event_time=event_time,
            repository=repo,
        )

    source = await sync_to_async(_create_entity)()
    metadata: dict = {"file_path": "src/auth.py", "resolution": "symbol"}
    if content_hash is not None:
        metadata["chunk_content_hash"] = content_hash
    await apply_edge_specs(
        source.id,
        (
            EdgeSpec(
                relation=EdgeRelation.MODIFIES_CHUNK,
                target_chunk_id=target_chunk_id,
                metadata=metadata,
            ),
        ),
        event_time=event_time,
    )
    edge = await KnowledgeEdge.objects.aget(target_chunk_id=target_chunk_id, source_entity=source)
    return source, edge


class TestAsOfQuery:
    """amodifies_chunk_edges：历史/当前视图区分（chunk-scoped + repo-scoped）。"""

    async def test_as_of_sees_historical_edge_current_view_hides_invalidated(self) -> None:
        """invalidate 置位后：as_of<invalid_at 见当年成立边；as_of>=invalid_at 与当前视图不见。"""
        repo = await sync_to_async(_make_repo)("asof-repo")
        cid = await sync_to_async(_make_chunk)(repo)
        t0 = timezone.now() - timedelta(hours=2)  # valid_at（当年成立）
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=t0
        )
        t_invalid = timezone.now() + timedelta(hours=2)
        await graph_store.invalidate_edge(edge.id, invalid_at=t_invalid)

        as_of_mid = timezone.now()  # created_at(过去) <= mid < invalid_at(未来)
        visible = await amodifies_chunk_edges(target_chunk_id=cid, as_of=as_of_mid)
        assert len(visible) == 1
        assert visible[0].edge_id == edge.id
        assert visible[0].relation == EdgeRelation.MODIFIES_CHUNK

        # as_of 落在失效之后 → 不可见
        after = await amodifies_chunk_edges(
            target_chunk_id=cid, as_of=timezone.now() + timedelta(hours=3)
        )
        assert after == []

        # 当前视图（as_of=None）→ 已失效边不可见
        current = await amodifies_chunk_edges(target_chunk_id=cid, as_of=None)
        assert current == []

    async def test_naive_as_of_rejected(self) -> None:
        """naive datetime 经 require_aware 拒绝（ValueError）。"""
        with pytest.raises(ValueError):
            await amodifies_chunk_edges(target_chunk_id=uuid.uuid4(), as_of=datetime(2020, 1, 1))

    async def test_repository_scoped_as_of_and_current_view(self) -> None:
        """repo-scoped 路径：同款 bi-temporal 谓词；当前视图排除已失效，as_of 见当年边。"""
        repo = await sync_to_async(_make_repo)("asof-repo-scoped")
        cid = await sync_to_async(_make_chunk)(repo)
        t0 = timezone.now() - timedelta(hours=2)
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=t0
        )

        # 失效前：当前视图可见
        before = await amodifies_chunk_edges(repository_id=str(repo.id), as_of=None)
        assert [r.edge_id for r in before] == [edge.id]

        t_invalid = timezone.now() + timedelta(hours=2)
        await graph_store.invalidate_edge(edge.id, invalid_at=t_invalid)

        # 失效后：当前视图不可见，as_of(当年) 仍可见
        assert await amodifies_chunk_edges(repository_id=str(repo.id), as_of=None) == []
        historical = await amodifies_chunk_edges(repository_id=str(repo.id), as_of=timezone.now())
        assert [r.edge_id for r in historical] == [edge.id]
