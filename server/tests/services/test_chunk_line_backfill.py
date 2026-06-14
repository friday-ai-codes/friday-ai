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
