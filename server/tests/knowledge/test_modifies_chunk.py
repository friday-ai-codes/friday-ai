"""MODIFIES_CHUNK chunk 边通路测试（Plan 14-01/14-03，ENH-01 边写入/幂等/反查/阶梯）。

覆盖（14-01，方法名 ``test_chunk_*`` 前缀，``-k chunk`` 精确选中）：
1. chunk 边三连发幂等：同 EdgeSpec 经 apply_edge_specs 3 次 → 恰 1 条活跃边，
   metadata 与首次一致（Pitfall 4 代码级幂等）
2. XOR 校验：双填 / 双空 spec → warning 跳过该 spec，不 raise 整批
3. 实体边零回归：HAS_PLAN exclusive 语义不变 + 实体边/chunk 边混合批互不干扰
4. chunk_in_edges 反查：返回活跃入边（含 source_id/metadata）；invalidate 后不可见

覆盖（14-03 Task 2，``TestResolutionLadder``）：resolve_modified_chunks 对齐阶梯
① 符号级（Symbol.chunk_id 行重叠）→ ② 行号级（ChunkRegistry 行重叠）→
③ 文件级降级（封顶 MAX_FILE_LEVEL_EDGES_PER_FILE）→ ④ unresolved 记录；
生成文件/解析失败跳过；apply_edge_specs 写入后 chunk_in_edges 反查链路成立。
对齐查询恒 ``branch_name=""``（base 命名空间，Pitfall 7）。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from structlog.testing import capture_logs

from knowledge.diff_archive import (
    MAX_FILE_LEVEL_EDGES_PER_FILE,
    FileDiff,
    resolve_modified_chunks,
)
from knowledge.graph_store import graph_store
from knowledge.ingestion import EdgeSpec, apply_edge_specs
from knowledge.models import EdgeRelation, EntityKind, KnowledgeEdge

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


# ---------------------------------------------------------------------------
# 14-03 Task 2：ENH-01 符号对齐阶梯 resolve_modified_chunks
# ---------------------------------------------------------------------------

COMMIT_SHA = "b" * 40
FILE_PATH = "src/service.py"


def _make_repo(name: str):
    """Repository sync 工厂。"""
    from repositories.models import Repository

    return Repository.objects.create(
        name=name,
        git_url=f"https://gitlab.com/test/{name}.git",
        git_platform="gitlab",
        default_branch="main",
    )


def _make_symbol(repo, *, start: int, end: int, chunk_id: uuid.UUID, name: str = "handler"):
    """Symbol sync 工厂（base 命名空间 branch_name=""，chunk_id 已回填形态）。"""
    from codegraph.models import Symbol

    return Symbol.objects.create(
        repository=repo,
        branch_name="",
        name=name,
        symbol_type="FUNCTION",
        file_path=FILE_PATH,
        start_line=start,
        end_line=end,
        chunk_id=chunk_id,
    )


def _make_chunk(repo, *, line_start=None, line_end=None, chunk_index: int = 0) -> uuid.UUID:
    """ChunkRegistry sync 工厂（base 命名空间；行号可空 = 历史未回填形态）。"""
    from code_relations.models import ChunkRegistry

    entry = ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repo,
        branch_name="",
        file_path=FILE_PATH,
        chunk_index=chunk_index,
        line_start=line_start,
        line_end=line_end,
    )
    return entry.chunk_id


def _file_diff(**kw) -> FileDiff:
    """默认 modified + hunk (5,12) 的 FileDiff 工厂。"""
    defaults: dict = {
        "path": FILE_PATH,
        "old_path": FILE_PATH,
        "change_type": "modified",
        "additions": 3,
        "deletions": 1,
        "hunk_ranges": [(5, 12)],
    }
    defaults.update(kw)
    return FileDiff(**defaults)


class TestResolutionLadder:
    """对齐阶梯六用例（①符号级 ②行号级 ③文件级封顶 ④unresolved ⑤跳过 ⑥反查）。"""

    async def test_symbol_level_resolution(self) -> None:
        """① Symbol(branch_name=""，行重叠，chunk_id 非 NULL) → resolution=symbol。"""
        repo = await sync_to_async(_make_repo)("ladder-symbol")
        cid = uuid.uuid4()
        await sync_to_async(_make_symbol)(repo, start=1, end=20, chunk_id=cid, name="login")
        # feature 分支同位符号不应命中（Pitfall 7：恒查 base 命名空间）
        from codegraph.models import Symbol

        await sync_to_async(Symbol.objects.create)(
            repository=repo,
            branch_name="feature/x",
            name="login",
            symbol_type="FUNCTION",
            file_path=FILE_PATH,
            start_line=1,
            end_line=20,
            chunk_id=uuid.uuid4(),
        )

        specs, file_diffs = await resolve_modified_chunks(repo, [_file_diff()], COMMIT_SHA)

        assert len(specs) == 1
        spec = specs[0]
        assert spec.relation == EdgeRelation.MODIFIES_CHUNK
        assert spec.target_chunk_id == cid
        assert spec.metadata is not None
        assert spec.metadata["resolution"] == "symbol"
        assert spec.metadata["file_path"] == FILE_PATH
        assert spec.metadata["symbol"] == "login"
        assert spec.metadata["commit_sha"] == COMMIT_SHA
        assert spec.metadata["hunk_ranges"] == [[5, 12]]
        assert file_diffs[0].unresolved_symbols == []

    async def test_chunk_line_level_resolution(self) -> None:
        """② 无 Symbol 命中但 ChunkRegistry 行区间重叠 → resolution=symbol。"""
        repo = await sync_to_async(_make_repo)("ladder-line")
        cid = await sync_to_async(_make_chunk)(repo, line_start=1, line_end=30)
        # 行号未回填的 chunk 不参与 ②（NULL 过滤）
        await sync_to_async(_make_chunk)(repo, chunk_index=1)

        specs, _ = await resolve_modified_chunks(repo, [_file_diff()], COMMIT_SHA)

        assert len(specs) == 1
        assert specs[0].target_chunk_id == cid
        assert specs[0].metadata is not None
        assert specs[0].metadata["resolution"] == "symbol"

    async def test_file_level_fallback_capped(self) -> None:
        """③ ①②全空但文件有 25 个 chunk → 恰 20 条边（封顶）+ 5 条 unresolved。"""
        repo = await sync_to_async(_make_repo)("ladder-file")

        def _make_25() -> None:
            for i in range(25):
                _make_chunk(repo, chunk_index=i)  # 行号 NULL：②必空，落 ③

        await sync_to_async(_make_25)()

        specs, file_diffs = await resolve_modified_chunks(repo, [_file_diff()], COMMIT_SHA)

        assert len(specs) == MAX_FILE_LEVEL_EDGES_PER_FILE == 20
        assert all(s.metadata is not None and s.metadata["resolution"] == "file" for s in specs)
        unresolved = file_diffs[0].unresolved_symbols
        assert len(unresolved) == 5
        assert all(r["file_path"] == FILE_PATH and r["commit_sha"] == COMMIT_SHA for r in unresolved)

    async def test_unresolved_for_new_file(self) -> None:
        """④ 新增文件（base 无任何 chunk）→ 零边 + unresolved 记录（懒解析跟踪）。"""
        repo = await sync_to_async(_make_repo)("ladder-unresolved")
        fd = _file_diff(change_type="added", hunk_ranges=[(1, 40)])

        specs, file_diffs = await resolve_modified_chunks(repo, [fd], COMMIT_SHA)

        assert specs == []
        unresolved = file_diffs[0].unresolved_symbols
        assert len(unresolved) == 1
        assert unresolved[0]["file_path"] == FILE_PATH
        assert unresolved[0]["commit_sha"] == COMMIT_SHA

    async def test_generated_and_parse_failed_skipped(self) -> None:
        """⑤ is_generated / parse_failed 文件不进入阶梯：有可命中数据仍零边零 unresolved。"""
        repo = await sync_to_async(_make_repo)("ladder-skip")
        await sync_to_async(_make_symbol)(repo, start=1, end=20, chunk_id=uuid.uuid4())

        specs, file_diffs = await resolve_modified_chunks(
            repo,
            [_file_diff(is_generated=True), _file_diff(parse_failed=True)],
            COMMIT_SHA,
        )

        assert specs == []
        assert all(fd.unresolved_symbols == [] for fd in file_diffs)

    async def test_reverse_lookup_via_chunk_in_edges(self, entity_factory) -> None:
        """⑥ apply_edge_specs 写入对齐产物后，chunk_in_edges 反查 source 可达（ENH-01 验收）。"""
        repo = await sync_to_async(_make_repo)("ladder-reverse")
        cid = await sync_to_async(_make_chunk)(repo, line_start=1, line_end=30)
        code_change = await sync_to_async(entity_factory)(
            kind=EntityKind.CODE_CHANGE, source_kind="task_result"
        )
        event_time = timezone.now()

        specs, _ = await resolve_modified_chunks(repo, [_file_diff()], COMMIT_SHA)
        await apply_edge_specs(code_change.id, tuple(specs), event_time=event_time)

        records = await graph_store.chunk_in_edges(cid)
        assert len(records) == 1
        assert records[0].source_id == code_change.id
        assert records[0].relation == EdgeRelation.MODIFIES_CHUNK
        assert records[0].metadata["commit_sha"] == COMMIT_SHA
