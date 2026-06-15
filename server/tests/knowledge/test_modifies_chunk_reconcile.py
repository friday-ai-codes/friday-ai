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
from knowledge.modifies_chunk import amodifies_chunk_edges, areconcile_modifies_chunk_edges

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

    async def test_backfilled_edge_visible_at_as_of_before_created_at(self) -> None:
        """WR-02：回填历史边（valid_at 在过去、created_at=摄取当下）在其"当年"as_of
        （落在 valid_at 之后、created_at 之前）下可见——纯业务时间线 as-of，不混入
        系统时间线 created_at 谓词（否则 created_at>as_of 误过滤）。chunk-scoped 与
        repo-scoped 两条路径同款。"""
        repo = await sync_to_async(_make_repo)("asof-backfill")
        cid = await sync_to_async(_make_chunk)(repo)
        # valid_at=两年前合并；created_at=auto_now_add=摄取当下（现在）
        valid_at = timezone.now() - timedelta(days=730)
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=valid_at
        )

        # as_of 落在合并那年（valid_at < as_of < created_at(现在)）
        as_of = timezone.now() - timedelta(days=365)

        # repo-scoped 路径：回填边在其当年可见
        repo_scoped = await amodifies_chunk_edges(repository_id=str(repo.id), as_of=as_of)
        assert [r.edge_id for r in repo_scoped] == [edge.id]

        # chunk-scoped 路径（chunk_in_edges business_only=True）：同款可见
        chunk_scoped = await amodifies_chunk_edges(target_chunk_id=cid, as_of=as_of)
        assert [r.edge_id for r in chunk_scoped] == [edge.id]

        # 合并之前的 as_of（< valid_at）：尚未成立，不可见
        before_valid = await amodifies_chunk_edges(
            repository_id=str(repo.id), as_of=valid_at - timedelta(days=1)
        )
        assert before_valid == []


def _delete_chunk(chunk_id: uuid.UUID) -> None:
    """删除 ChunkRegistry 行（模拟文件删除 / chunk 收缩）。"""
    from code_relations.models import ChunkRegistry

    ChunkRegistry.objects.filter(chunk_id=chunk_id).delete()


class TestReconcile:
    """areconcile_modifies_chunk_edges：过期边置 invalid_at（置位不删）+ 双信号 + 降级 + 隔离。"""

    async def test_chunk_deleted_edge_invalidated_not_removed(self) -> None:
        """信号①：target_chunk_id 在当前 ChunkRegistry 已不存在 → 边被置 invalid_at（行保留）。"""
        repo = await sync_to_async(_make_repo)("recon-deleted")
        cid = await sync_to_async(_make_chunk)(repo, content_hash="a" * 64)
        now = timezone.now()
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=now
        )
        await sync_to_async(_delete_chunk)(cid)

        invalidated = await areconcile_modifies_chunk_edges(
            str(repo.id), invalid_at=timezone.now()
        )
        assert invalidated == 1

        refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
        assert refreshed.invalid_at is not None  # 置位
        assert refreshed.invalid_at > refreshed.valid_at  # 时间次序约束
        # 置位不删除：边行仍在
        assert await KnowledgeEdge.objects.filter(id=edge.id).acount() == 1

    async def test_content_hash_drift_edge_invalidated(self) -> None:
        """信号②：chunk 仍在但 content_hash 漂移（冻结指纹 != 当前）→ 边失效。"""
        repo = await sync_to_async(_make_repo)("recon-drift")
        cid = await sync_to_async(_make_chunk)(repo, content_hash="new" + "0" * 61)
        now = timezone.now()
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="old" + "0" * 61, event_time=now
        )

        invalidated = await areconcile_modifies_chunk_edges(
            str(repo.id), invalid_at=timezone.now()
        )
        assert invalidated == 1
        refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
        assert refreshed.invalid_at is not None

    async def test_unchanged_chunk_not_invalidated_and_idempotent(self) -> None:
        """未变：content_hash 一致 → 不失效；二次对账仍 0 失效（幂等可重入）。"""
        repo = await sync_to_async(_make_repo)("recon-unchanged")
        cid = await sync_to_async(_make_chunk)(repo, content_hash="a" * 64)
        now = timezone.now()
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=now
        )

        first = await areconcile_modifies_chunk_edges(str(repo.id), invalid_at=timezone.now())
        assert first == 0
        second = await areconcile_modifies_chunk_edges(str(repo.id), invalid_at=timezone.now())
        assert second == 0
        refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
        assert refreshed.invalid_at is None

    async def test_missing_fingerprint_conservative(self) -> None:
        """缺指纹保守：metadata 无 chunk_content_hash 且 chunk 仍在 → 不失效。"""
        repo = await sync_to_async(_make_repo)("recon-nohash")
        cid = await sync_to_async(_make_chunk)(repo, content_hash="a" * 64)
        now = timezone.now()
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash=None, event_time=now
        )

        invalidated = await areconcile_modifies_chunk_edges(
            str(repo.id), invalid_at=timezone.now()
        )
        assert invalidated == 0
        refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
        assert refreshed.invalid_at is None

    async def test_anomalous_future_valid_at_degrades_without_raising(self) -> None:
        """逐边降级：valid_at 在未来的过期边 invalidate 触发 kedge_valid_range，
        逐边 try/except 吞掉不掀翻批次（best-effort）。"""
        repo = await sync_to_async(_make_repo)("recon-anomaly")
        cid = await sync_to_async(_make_chunk)(repo, content_hash="a" * 64)
        future = timezone.now() + timedelta(hours=10)  # valid_at 在未来
        _, edge = await _make_modifies_chunk_edge(
            repo=repo, target_chunk_id=cid, content_hash="a" * 64, event_time=future
        )
        await sync_to_async(_delete_chunk)(cid)  # 判定为过期

        # invalid_at=now < valid_at(future) → invalidate_edge 内 aupdate 撞 kedge_valid_range
        invalidated = await areconcile_modifies_chunk_edges(
            str(repo.id), invalid_at=timezone.now()
        )
        # 异常边被逐边降级跳过，不计入失效，不上抛
        assert invalidated == 0
        refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
        assert refreshed.invalid_at is None  # 未被置位（降级跳过）

    async def test_cross_repo_isolation(self) -> None:
        """跨 repo 隔离：对账只触及本 repo 的边，他 repo 边不受影响。"""
        repo_a = await sync_to_async(_make_repo)("recon-iso-a")
        repo_b = await sync_to_async(_make_repo)("recon-iso-b")
        cid_a = await sync_to_async(_make_chunk)(repo_a, content_hash="a" * 64)
        cid_b = await sync_to_async(_make_chunk)(repo_b, content_hash="b" * 64)
        now = timezone.now()
        _, edge_a = await _make_modifies_chunk_edge(
            repo=repo_a, target_chunk_id=cid_a, content_hash="a" * 64, event_time=now
        )
        _, edge_b = await _make_modifies_chunk_edge(
            repo=repo_b, target_chunk_id=cid_b, content_hash="b" * 64, event_time=now
        )
        # 两个 repo 的 chunk 都删除（都过期），但只对账 repo_a
        await sync_to_async(_delete_chunk)(cid_a)
        await sync_to_async(_delete_chunk)(cid_b)

        invalidated = await areconcile_modifies_chunk_edges(
            str(repo_a.id), invalid_at=timezone.now()
        )
        assert invalidated == 1
        assert (await KnowledgeEdge.objects.aget(id=edge_a.id)).invalid_at is not None
        # repo_b 的边未被本 repo 对账触及
        assert (await KnowledgeEdge.objects.aget(id=edge_b.id)).invalid_at is None


class TestReconcileHookFailSafe:
    """indexer._run_modifies_chunk_reconcile 钩子 best-effort 降级（不阻断索引）。"""

    async def test_hook_swallows_reconcile_exception(self, monkeypatch) -> None:
        """对账抛异常 → 钩子吞掉 + warning，绝不上抛（对齐 D-04/T-25-12 降级范式）。"""
        from services import indexer

        async def _boom(*args, **kwargs):
            raise RuntimeError("reconcile boom")

        monkeypatch.setattr(
            "knowledge.modifies_chunk.areconcile_modifies_chunk_edges", _boom
        )
        # 不抛即通过（best-effort 吞异常）
        await indexer._run_modifies_chunk_reconcile("some-repo-id")
