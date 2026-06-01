"""Phase：per-run delta 回填集成测试（Pitfall A / Pitfall 7）。
驱动 `_extract_and_write_graph` 处理一个真实 .py 文件，mock graph_writer.write_bundle
返回受控计数，断言 symbols/imports/calls/endpoints_added 经 running_history 回填到
对应 IndexHistory 行：
- history_id 透传路径（增量索引）
- history_id=None 经 running_history fallback 路径（全量/分支索引——Pitfall A 核心）
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
import pytest
from repositories.models import IndexHistory, IndexHistoryStatus, TriggerType
from services.indexer import IndexerService
pytestmark = pytest.mark.django_db(transaction=True)
_BUNDLE_COUNTS = {"symbols": 7, "imports": 3, "calls": 5, "endpoints": 0}
def _prepare_indexer(repository: Any, tmp_path: Path) -> IndexerService:
 """造真实 .py 文件 + mock write_bundle 返回固定计数（stats 据此累加）。"""
 (tmp_path / "mod.py").write_text("def foo:\n return bar\n")
 idx = IndexerService(str(repository.id))
 # 预置非 None 抽取/写入服务，跳过 _init_graph_services 真实初始化；
 # 抽取仍走模块级 get_extractor（真实 python 抽取），write_bundle 用 mock 计数。
 idx._graph_extractor = object # type: ignore[assignment]
 writer = AsyncMock
 writer.write_bundle = AsyncMock(return_value=dict(_BUNDLE_COUNTS))
 idx._graph_writer = writer # type: ignore[assignment]
 return idx
async def test_delta_backfill_with_history_id(
 repository, tmp_path, settings
) -> None:
 """增量路径：history_id 透传 → *_added == 本次 stats 累加值。"""
 settings.ENABLE_CODEGRAPH = True
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.WEBHOOK,
 status=IndexHistoryStatus.RUNNING,
 )
 idx = _prepare_indexer(repository, tmp_path)
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=["mod.py"],
 repository_id=str(repository.id),
 history_id=str(history.id),
 )
 # 确认抽取确实跑通（write_bundle 被调），否则 stats 全 0 测试失真
 assert stats["files_processed"] == 1
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.symbols_added == _BUNDLE_COUNTS["symbols"]
 assert refreshed.imports_added == _BUNDLE_COUNTS["imports"]
 assert refreshed.calls_added == _BUNDLE_COUNTS["calls"]
 assert refreshed.endpoints_added == _BUNDLE_COUNTS["endpoints"]
async def test_delta_backfill_full_index_fallback(
 repository, tmp_path, settings
) -> None:
 """全量路径（history_id=None）：delta 经 running_history fallback 仍写得进（Pitfall A）。"""
 settings.ENABLE_CODEGRAPH = True
 # 全量索引透传 history_id=None；fallback 须命中该 RUNNING 行
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 )
 idx = _prepare_indexer(repository, tmp_path)
 stats = await idx._extract_and_write_graph(
 repo_path=str(tmp_path),
 file_paths=["mod.py"],
 repository_id=str(repository.id),
 history_id=None,
 )
 assert stats["files_processed"] == 1
 refreshed = await IndexHistory.objects.aget(id=history.id)
 # Pitfall A 回归核心：history_id=None 时若误用形参，这里会保持 default=0
 assert refreshed.symbols_added == _BUNDLE_COUNTS["symbols"]
 assert refreshed.imports_added == _BUNDLE_COUNTS["imports"]
 assert refreshed.calls_added == _BUNDLE_COUNTS["calls"]
