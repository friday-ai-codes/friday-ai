"""图谱文件级断点（GraphFileIndex）跳过 / 续跑测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from repositories.models import GraphFileIndex
from services.indexer import IndexerService

pytestmark = pytest.mark.django_db(transaction=True)


def _prepare_indexer(repository: Any, tmp_path: Path) -> tuple[IndexerService, AsyncMock]:
    (tmp_path / "mod.py").write_text("def foo():\n    return bar()\n")
    idx = IndexerService(str(repository.id))
    idx._graph_extractor = object()  # type: ignore[assignment]
    writer = AsyncMock()
    writer.write_bundle = AsyncMock(
        return_value={"symbols": 1, "imports": 0, "calls": 1, "endpoints": 0}
    )
    idx._graph_writer = writer  # type: ignore[assignment]
    return idx, writer.write_bundle


async def test_checkpoint_written_after_extract(repository, tmp_path, settings) -> None:
    settings.ENABLE_CODEGRAPH = True
    idx, _ = _prepare_indexer(repository, tmp_path)

    stats = await idx._extract_and_write_graph(
        repo_path=str(tmp_path),
        file_paths=["mod.py"],
        repository_id=str(repository.id),
    )
    assert stats["files_processed"] == 1

    exists = await GraphFileIndex.objects.filter(
        repository_id=str(repository.id), branch_name="", file_path="mod.py"
    ).aexists()
    assert exists, "write_bundle 成功后应登记 GraphFileIndex 断点"


async def test_skip_unchanged_skips_already_built_file(repository, tmp_path, settings) -> None:
    settings.ENABLE_CODEGRAPH = True
    idx, write_bundle = _prepare_indexer(repository, tmp_path)

    # 第一次：登记断点。
    await idx._extract_and_write_graph(
        repo_path=str(tmp_path),
        file_paths=["mod.py"],
        repository_id=str(repository.id),
        skip_unchanged=True,
    )
    assert write_bundle.call_count == 1

    # 第二次 skip_unchanged：hash 未变 → 跳过，write_bundle 不再调用。
    stats = await idx._extract_and_write_graph(
        repo_path=str(tmp_path),
        file_paths=["mod.py"],
        repository_id=str(repository.id),
        skip_unchanged=True,
    )
    assert write_bundle.call_count == 1, "续跑应跳过 hash 未变的已构建文件"
    assert stats["files_processed"] == 1  # 跳过的文件仍计入已处理


async def test_changed_hash_is_rebuilt(repository, tmp_path, settings) -> None:
    settings.ENABLE_CODEGRAPH = True
    idx, write_bundle = _prepare_indexer(repository, tmp_path)

    await idx._extract_and_write_graph(
        repo_path=str(tmp_path),
        file_paths=["mod.py"],
        repository_id=str(repository.id),
        skip_unchanged=True,
    )
    assert write_bundle.call_count == 1

    # 修改文件内容 → hash 变化 → skip_unchanged 也应重建。
    (tmp_path / "mod.py").write_text("def foo():\n    return baz()\n\ndef extra():\n    pass\n")
    await idx._extract_and_write_graph(
        repo_path=str(tmp_path),
        file_paths=["mod.py"],
        repository_id=str(repository.id),
        skip_unchanged=True,
    )
    assert write_bundle.call_count == 2, "hash 变化的文件必须重建，不能被断点跳过"
