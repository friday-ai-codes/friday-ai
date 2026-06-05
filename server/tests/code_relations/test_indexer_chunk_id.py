"""`IndexerService._build_points` chunk_id 改造单测（Pitfall 1 / contract）。

不依赖 Django DB —— `_build_points` 是纯函数 staticmethod，仅做 uuid5 / sha256 /
per-file counter 计算。
"""

from __future__ import annotations

import hashlib
import inspect

from code_relations.utils import generate_chunk_id
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
    """构造最小 CodeChunk 测试 fixture（避免重复样板字段）。"""
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


def test_build_points_uses_uuid5() -> None:
    """同 file 两 chunk → 两个 point_id 与 generate_chunk_id(...) uuid5 完全一致。"""
    chunks = [
        _make_chunk(content="A", file_path="src/x.py"),
        _make_chunk(content="B", file_path="src/x.py"),
    ]
    embeddings = [[0.1] * 4, [0.2] * 4]
    points, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert points[0]["id"] == str(generate_chunk_id("repo-A", "src/x.py", 0))
    assert points[1]["id"] == str(generate_chunk_id("repo-A", "src/x.py", 1))
    assert len(registry_rows) == 2
    assert registry_rows[0]["chunk_index"] == 0
    assert registry_rows[1]["chunk_index"] == 1


def test_build_points_per_file_chunk_index_resets() -> None:
    """同 file 递增、不同 file 重置：chunk_index 序列 [0, 1, 0]。"""
    chunks = [
        _make_chunk(content="A", file_path="f1.py"),
        _make_chunk(content="B", file_path="f1.py"),
        _make_chunk(content="C", file_path="f2.py"),
    ]
    embeddings = [[0.1], [0.2], [0.3]]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    indices = [r["chunk_index"] for r in registry_rows]
    assert indices == [0, 1, 0]


def test_build_points_chunk_index_increments_when_embedding_none() -> None:
    """embedding=None 跳过 point，但 chunk_index 仍递增（重切分稳定性 contract）。

    3 chunks 同 file，embeddings=[vec, None, vec] →
    - points 长度 == 2（跳过 None）
    - registry_rows 长度 == 2
    - 第二个 point 的 chunk_index 应该是 2（不是 1，因为 None chunk 占了 index 1）
    """
    chunks = [
        _make_chunk(content="A", file_path="f.py"),
        _make_chunk(content="B", file_path="f.py"),
        _make_chunk(content="C", file_path="f.py"),
    ]
    embeddings: list[list[float] | None] = [[0.1], None, [0.3]]
    points, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert len(points) == 2
    assert len(registry_rows) == 2
    assert registry_rows[0]["chunk_index"] == 0
    assert registry_rows[1]["chunk_index"] == 2
    assert points[1]["id"] == str(generate_chunk_id("repo-A", "f.py", 2))


def test_build_points_content_hash_sha256() -> None:
    """content_hash = sha256(content.encode('utf-8')).hexdigest()，长度 64。"""
    chunks = [_make_chunk(content="hello", file_path="x.py")]
    embeddings = [[0.1]]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    expected = hashlib.sha256(b"hello").hexdigest()
    assert registry_rows[0]["content_hash"] == expected
    assert len(registry_rows[0]["content_hash"]) == 64


def test_build_points_deterministic_across_calls() -> None:
    """同 chunks 两次调用 → 两次 points[i]['id'] 与 registry_rows[i]['chunk_id'] 完全相等。"""
    chunks = [
        _make_chunk(content="A", file_path="a.py"),
        _make_chunk(content="B", file_path="b.py"),
    ]
    embeddings = [[0.1], [0.2]]
    points1, rows1 = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-X"
    )
    points2, rows2 = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-X"
    )
    assert points1[0]["id"] == points2[0]["id"]
    assert points1[1]["id"] == points2[1]["id"]
    assert rows1[0]["chunk_id"] == rows2[0]["chunk_id"]
    assert rows1[1]["chunk_id"] == rows2[1]["chunk_id"]


def test_build_points_no_uuid4_in_function_body() -> None:
    """Pitfall 1 防御性测试：源码层守住 _build_points 不再调用 uuid4。

    用 `uuid.uuid4` / `uuid4()` 调用语法做精确匹配，避免误伤 docstring 内的「uuid4」
    历史改造说明字样（plan 阶段允许 docstring 提及历史路径）。
    """
    src = inspect.getsource(IndexerService._build_points)
    assert "uuid.uuid4" not in src, (
        "Pitfall 1 violation: _build_points must not call uuid.uuid4"
    )
    assert "uuid4()" not in src, (
        "Pitfall 1 violation: _build_points must not call uuid4()"
    )
    assert "generate_chunk_id" in src
    assert "sha256" in src


def test_build_points_returns_tuple() -> None:
    """返回值必须是 (list, list) tuple（旧版本返回单 list 已废止）。"""
    chunks = [_make_chunk(content="A", file_path="x.py")]
    embeddings = [[0.1]]
    result = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


def test_build_points_registry_row_fields_complete() -> None:
    """registry_rows 每行必须含 6 个字段（含 initial implementation 新增的 branch_name）。"""
    chunks = [_make_chunk(content="A", file_path="x.py")]
    embeddings = [[0.1]]
    _, registry_rows = IndexerService._build_points(
        chunks, embeddings, None, False, repository_id="repo-A"
    )
    row = registry_rows[0]
    assert set(row.keys()) == {
        "chunk_id",
        "content_hash",
        "repository_id",
        "file_path",
        "chunk_index",
        "branch_name",
    }
    assert row["repository_id"] == "repo-A"
    assert row["file_path"] == "x.py"
    # base 路径（is_base_branch=False 且 branch_name=None）归一化为 ""，字节不变
    assert row["branch_name"] == ""
