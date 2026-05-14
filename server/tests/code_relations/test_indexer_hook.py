"""Phase indexer hook integration test（per ）。
验证 `IndexerService._extract_and_write_graph` 末尾 hook 行为：
- IndexerService.__init__ 含 `_session_dirty_chunk_ids` 实例属性（默认空 set）
- _extract_and_write_graph 末尾调 `enqueue_edge_build(repo_id, dirty)` 一次
- session_dirty_chunk_ids 调用后清空（避免下次重复 enqueue）
- hook 失败 catch + warning，不抛回 indexer（异常隔离）
- 空 dirty → 不调 enqueue_edge_build
"""
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from services.indexer import IndexerService
def test_init_creates_empty_session_dirty_chunk_ids -> None:
 """IndexerService.__init__ 初始化 _session_dirty_chunk_ids 为空 set。"""
 idx = IndexerService("11111111-1111-1111-1111-111111111111")
 assert idx._session_dirty_chunk_ids == set
 assert isinstance(idx._session_dirty_chunk_ids, set)
@pytest.mark.django_db(transaction=True)
async def test_extract_and_write_graph_invokes_enqueue_edge_build(
 repository, tmp_path, settings
) -> None:
 """_extract_and_write_graph 末尾 hook 调用 enqueue_edge_build 一次 + dirty 透传。"""
 settings.ENABLE_CODEGRAPH = True
 idx = IndexerService(str(repository.id))
 dirty = {uuid.uuid4 for _ in range(3)}
 idx._session_dirty_chunk_ids = set(dirty)
 with patch(
 "code_relations.tasks.enqueue_edge_build",
 new_callable=AsyncMock,
 ) as mock_enqueue:
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=,
 repository_id=str(repository.id),
 )
 mock_enqueue.assert_awaited_once
 args = mock_enqueue.await_args.args
 assert args[0] == str(repository.id)
 assert set(args[1]) == dirty
 assert idx._session_dirty_chunk_ids == set
 assert stats.get("edge_build_enqueued") is True
 assert stats.get("dirty_chunk_count") == 3
@pytest.mark.django_db(transaction=True)
async def test_hook_failure_does_not_break_indexer(
 repository, tmp_path, settings
) -> None:
 """hook 内 enqueue_edge_build 抛错 → catch + warning，_extract_and_write_graph 不抛。"""
 settings.ENABLE_CODEGRAPH = True
 idx = IndexerService(str(repository.id))
 idx._session_dirty_chunk_ids = {uuid.uuid4}
 with patch(
 "code_relations.tasks.enqueue_edge_build",
 side_effect=RuntimeError("boom"),
 ):
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=,
 repository_id=str(repository.id),
 )
 assert stats.get("edge_build_enqueued") is False
@pytest.mark.django_db(transaction=True)
async def test_no_dirty_skips_enqueue(repository, tmp_path, settings) -> None:
 """_session_dirty_chunk_ids 空 → 不调 enqueue_edge_build，stats 标 False。"""
 settings.ENABLE_CODEGRAPH = True
 idx = IndexerService(str(repository.id))
 idx._session_dirty_chunk_ids = set
 with patch(
 "code_relations.tasks.enqueue_edge_build",
 new_callable=AsyncMock,
 ) as mock_enqueue:
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=,
 repository_id=str(repository.id),
 )
 mock_enqueue.assert_not_awaited
 assert stats.get("edge_build_enqueued") is False
@pytest.mark.django_db(transaction=True)
async def test_feature_flag_disabled_skips_hook_and_graph(
 repository, tmp_path, settings
) -> None:
 """ENABLE_CODEGRAPH=False → 函数早 return reason='disabled'，hook 不跑。"""
 settings.ENABLE_CODEGRAPH = False
 idx = IndexerService(str(repository.id))
 idx._session_dirty_chunk_ids = {uuid.uuid4}
 with patch(
 "code_relations.tasks.enqueue_edge_build",
 new_callable=AsyncMock,
 ) as mock_enqueue:
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=,
 repository_id=str(repository.id),
 )
 mock_enqueue.assert_not_awaited
 assert stats.get("reason") == "disabled"
