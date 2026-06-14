"""`find_chunk_at` 反查守护测试（IDX-02 后半，per 25-02 plan Task 1）。

覆盖：
- 区间命中：line_start<=line<=line_end → 返回该 chunk_id（含闭区间边界）。
- 区间外 → 返回空列表。
- 多 chunk 覆盖同一行 → 全部返回，最小区间（最具体）排在前。
- 被排除文件（.env / *.pem）→ 空列表（fail-closed），并打 exclusion.blocked 埋点。
- build_matcher_for_repo 抛异常 → 空列表（构造失败 fail-closed）。
- 路径归一化：'./src/a.py' 与 'src/a.py' 命中同一 chunk。
- NULL 行号 row 不被命中（历史未回填数据 graceful）。
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from services.chunk_lookup import find_chunk_at

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_row(
    repository,
    *,
    file_path: str = "src/a.py",
    chunk_index: int = 0,
    branch_name: str = "",
    line_start: int | None = 10,
    line_end: int | None = 30,
):
    from code_relations.models import ChunkRegistry

    return await ChunkRegistry.objects.acreate(
        chunk_id=uuid.uuid4(),
        content_hash="a" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=chunk_index,
        branch_name=branch_name,
        line_start=line_start,
        line_end=line_end,
    )


async def test_hit_returns_chunk_id(repository) -> None:
    row = await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    result = await find_chunk_at(str(repository.id), "src/a.py", 15)
    assert [r["chunk_id"] for r in result] == [str(row.chunk_id)]
    assert result[0]["line_start"] == 10
    assert result[0]["line_end"] == 30
    assert result[0]["file_path"] == "src/a.py"


async def test_boundary_inclusive(repository) -> None:
    await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    # 闭区间边界 line==line_start / line==line_end 均命中
    assert len(await find_chunk_at(str(repository.id), "src/a.py", 10)) == 1
    assert len(await find_chunk_at(str(repository.id), "src/a.py", 30)) == 1


async def test_out_of_range_returns_empty(repository) -> None:
    await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    assert await find_chunk_at(str(repository.id), "src/a.py", 5) == []
    assert await find_chunk_at(str(repository.id), "src/a.py", 31) == []


async def test_most_specific_first(repository) -> None:
    wide = await _make_row(
        repository, file_path="src/a.py", chunk_index=0, line_start=1, line_end=50
    )
    narrow = await _make_row(
        repository, file_path="src/a.py", chunk_index=1, line_start=10, line_end=20
    )
    result = await find_chunk_at(str(repository.id), "src/a.py", 15)
    ids = [r["chunk_id"] for r in result]
    assert ids == [str(narrow.chunk_id), str(wide.chunk_id)]


async def test_excluded_file_failclosed(repository) -> None:
    # .env 命中内置排除默认 → fail-closed 不返回，且打 exclusion.blocked 埋点
    await _make_row(repository, file_path=".env", line_start=1, line_end=5)
    with patch("services.chunk_lookup.log_exclusion_blocked") as blocked:
        result = await find_chunk_at(str(repository.id), ".env", 3)
    assert result == []
    blocked.assert_called_once()


async def test_excluded_pem_failclosed(repository) -> None:
    await _make_row(repository, file_path="certs/server.pem", line_start=1, line_end=5)
    result = await find_chunk_at(str(repository.id), "certs/server.pem", 3)
    assert result == []


async def test_matcher_build_failure_failclosed(repository) -> None:
    await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    with patch(
        "services.chunk_lookup.build_matcher_for_repo",
        side_effect=RuntimeError("boom"),
    ):
        result = await find_chunk_at(str(repository.id), "src/a.py", 15)
    assert result == []


async def test_path_normalization(repository) -> None:
    row = await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    # './src/a.py' 归一为 'src/a.py' → 命中同一 chunk
    result = await find_chunk_at(str(repository.id), "./src/a.py", 15)
    assert [r["chunk_id"] for r in result] == [str(row.chunk_id)]


async def test_illegal_path_returns_empty(repository) -> None:
    await _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
    # 绝对路径 / 越界路径 normalize_rel_path → None → 空返回
    assert await find_chunk_at(str(repository.id), "/etc/passwd", 1) == []
    assert await find_chunk_at(str(repository.id), "../../escape", 1) == []


async def test_null_line_rows_not_hit(repository) -> None:
    # 历史未回填（line_start/line_end NULL）的 row 不应被命中
    await _make_row(repository, file_path="src/legacy.py", line_start=None, line_end=None)
    assert await find_chunk_at(str(repository.id), "src/legacy.py", 1) == []


async def test_branch_isolation(repository) -> None:
    await _make_row(
        repository, file_path="src/a.py", branch_name="feature", line_start=10, line_end=30
    )
    # 默认 branch_name="" 查询不命中 feature 分支 chunk
    assert await find_chunk_at(str(repository.id), "src/a.py", 15) == []
    # 指定分支命中
    result = await find_chunk_at(str(repository.id), "src/a.py", 15, branch_name="feature")
    assert len(result) == 1
