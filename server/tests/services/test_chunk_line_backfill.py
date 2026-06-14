"""行号回填守护测试（IDX-02 前半，per 25-01 plan）。

覆盖两条链路：

1. `_build_points` 透传 `CodeChunk.start_line` / `end_line` 进 registry_rows
   （Task 1，纯函数，不依赖 DB）。
2. `_bulk_upsert_registry_atomic` 在 create + update 双路径落库 line_start /
   line_end，行号位移触发 update，None 落 NULL，错乱区间被 CheckConstraint 拒绝
   （Task 2，依赖 Django DB）。
"""

from __future__ import annotations

import pytest

from services.code_parser import CodeChunk
from services.indexer import IndexerService


def _make_chunk(
    content: str = "x",
    file_path: str = "src/a.py",
    *,
    language: str = "python",
    start_line: int = 1,
    end_line: int = 10,
) -> CodeChunk:
    """构造最小 CodeChunk 测试 fixture。"""
    return CodeChunk(
        content=content,
        file_path=file_path,
        file_hash="fh",
        language=language,
        start_line=start_line,
        end_line=end_line,
        node_type="function",
        context_header="",
    )


# ---------------------------------------------------------------------------
# Task 1: _build_points 透传行号
# ---------------------------------------------------------------------------


def test_build_points_carries_line_start_end() -> None:
    """start_line=5/end_line=12 的 chunk → registry_rows[0] 含 line_start=5/line_end=12。"""
    chunks = [_make_chunk(content="A", file_path="src/x.py", start_line=5, end_line=12)]
    embeddings = [[0.1] * 4]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert registry_rows[0]["line_start"] == 5
    assert registry_rows[0]["line_end"] == 12


def test_build_points_line_matches_qdrant_payload() -> None:
    """registry_rows 行号与同源 Qdrant payload start_line/end_line 完全一致。"""
    chunks = [_make_chunk(content="A", file_path="src/x.py", start_line=7, end_line=21)]
    embeddings = [[0.1] * 4]
    points, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert points[0]["payload"]["start_line"] == registry_rows[0]["line_start"]
    assert points[0]["payload"]["end_line"] == registry_rows[0]["line_end"]


def test_build_points_embedding_none_skips_registry_row() -> None:
    """embedding=None 的 chunk 不入 registry_rows（既有行为不回归，行号不影响跳过）。"""
    chunks = [
        _make_chunk(content="A", file_path="f.py", start_line=1, end_line=3),
        _make_chunk(content="B", file_path="f.py", start_line=5, end_line=9),
    ]
    embeddings: list[list[float] | None] = [None, [0.3]]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert len(registry_rows) == 1
    # 入列的是第二个 chunk（chunk_index=1，None chunk 占了 index 0）
    assert registry_rows[0]["chunk_index"] == 1
    assert registry_rows[0]["line_start"] == 5
    assert registry_rows[0]["line_end"] == 9


def test_build_points_registry_row_key_set_with_line_fields() -> None:
    """ChunkRegistryRow 键集合恰为既有键 + line_start + line_end（契约不漂移）。"""
    chunks = [_make_chunk(content="A", file_path="x.py")]
    embeddings = [[0.1]]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert set(registry_rows[0].keys()) == {
        "chunk_id",
        "content_hash",
        "repository_id",
        "file_path",
        "chunk_index",
        "branch_name",
        "line_start",
        "line_end",
    }


# ---------------------------------------------------------------------------
# Task 2: _bulk_upsert_registry_atomic 落库行号（create + update）
# ---------------------------------------------------------------------------


def _make_registry_row(
    *,
    chunk_id,
    repository_id: str,
    content_hash: str = "a" * 64,
    file_path: str = "src/a.py",
    chunk_index: int = 0,
    branch_name: str = "",
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "content_hash": content_hash,
        "repository_id": repository_id,
        "file_path": file_path,
        "chunk_index": chunk_index,
        "branch_name": branch_name,
        "line_start": line_start,
        "line_end": line_end,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_create_writes_line_fields(repository) -> None:
    """新 chunk get_or_create → 落库 row 的 line_start/line_end 等于传入值。"""
    from code_relations.models import ChunkRegistry
    from code_relations.utils import generate_chunk_id

    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    indexer = IndexerService(repository_id=str(repository.id))
    row = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        file_path="src/foo.py",
        line_start=5,
        line_end=12,
    )
    await indexer._upsert_chunk_registry_batch([row])

    obj = await ChunkRegistry.objects.aget(chunk_id=cid)
    assert obj.line_start == 5
    assert obj.line_end == 12


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_update_refreshes_line_fields_on_recut(repository) -> None:
    """同 chunk_id 二次写入且 content_hash 变化（重切分行号位移 5→8）→ 落库行号更新为新值。"""
    from code_relations.models import ChunkRegistry
    from code_relations.utils import generate_chunk_id

    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    indexer = IndexerService(repository_id=str(repository.id))

    row_v1 = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash="a" * 64,
        file_path="src/foo.py",
        line_start=5,
        line_end=12,
    )
    await indexer._upsert_chunk_registry_batch([row_v1])

    row_v2 = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash="b" * 64,
        file_path="src/foo.py",
        line_start=8,
        line_end=15,
    )
    await indexer._upsert_chunk_registry_batch([row_v2])

    obj = await ChunkRegistry.objects.aget(chunk_id=cid)
    assert obj.line_start == 8
    assert obj.line_end == 15


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_update_refreshes_line_fields_when_only_lines_move(repository) -> None:
    """仅行号变化（hash/路径/index 未变）也必须触发 update，避免反查错位。"""
    from code_relations.models import ChunkRegistry
    from code_relations.utils import generate_chunk_id

    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    indexer = IndexerService(repository_id=str(repository.id))

    row_v1 = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash="c" * 64,
        file_path="src/foo.py",
        line_start=1,
        line_end=4,
    )
    await indexer._upsert_chunk_registry_batch([row_v1])

    # content_hash 完全相同，仅行号位移（同内容在文件中整体下移）。
    row_v2 = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        content_hash="c" * 64,
        file_path="src/foo.py",
        line_start=10,
        line_end=13,
    )
    await indexer._upsert_chunk_registry_batch([row_v2])

    obj = await ChunkRegistry.objects.aget(chunk_id=cid)
    assert obj.line_start == 10
    assert obj.line_end == 13


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_none_line_fields_persist_null(repository) -> None:
    """传入 line_start=None/line_end=None → 落库 NULL，不违反 chunkreg_line_range_valid。"""
    from code_relations.models import ChunkRegistry
    from code_relations.utils import generate_chunk_id

    cid = generate_chunk_id(str(repository.id), "src/legacy.py", 0)
    indexer = IndexerService(repository_id=str(repository.id))
    row = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        file_path="src/legacy.py",
        line_start=None,
        line_end=None,
    )
    await indexer._upsert_chunk_registry_batch([row])

    obj = await ChunkRegistry.objects.aget(chunk_id=cid)
    assert obj.line_start is None
    assert obj.line_end is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_invalid_range_rejected_by_constraint(repository) -> None:
    """line_end < line_start → IntegrityError（DB 约束兜底，indexer 不静默落错乱区间）。"""
    from django.db.utils import IntegrityError

    from code_relations.utils import generate_chunk_id

    cid = generate_chunk_id(str(repository.id), "src/bad.py", 0)
    indexer = IndexerService(repository_id=str(repository.id))
    row = _make_registry_row(
        chunk_id=cid,
        repository_id=str(repository.id),
        file_path="src/bad.py",
        line_start=20,
        line_end=5,
    )
    with pytest.raises(IntegrityError):
        await indexer._upsert_chunk_registry_batch([row])
