"""SemanticEdgeBuilder Pitfall 3 perf gate（per implementation contract / contract）。

10k chunks builder wall-clock < 60s。CI 默认 skip（pyproject
``addopts = "-m 'not perf'"``）；本地用
``uv run --group dev pytest -m perf tests/code_relations/test_builders/test_semantic_perf.py``
主动运行。

本 gate 验 builder 内部不会引入 O(n²) 退化（mock client 零延迟，10k 次 scroll +
query_points 顺序调用纯 Python overhead 应 < 5s；阈值 60s 给 CI 抖动留余量）。
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from code_relations.builders.semantic_edge import SemanticEdgeBuilder

_LIMIT_SECONDS = 60.0
_NUM_DIRTY = 10_000
_CANDIDATES_PER_CHUNK = 5


@pytest.mark.perf
@pytest.mark.django_db(transaction=True)
async def test_semantic_10k_chunks_under_60s(repository) -> None:
    """10k dirty chunks 顺序跑 SemanticEdgeBuilder，wall-clock < 60s（contract）。"""
    dirty_ids = [uuid.uuid4() for _ in range(_NUM_DIRTY)]

    mock_client = MagicMock()

    def _scroll(*args: object, **kwargs: object) -> tuple[list[MagicMock], None]:
        p = MagicMock()
        p.id = "11111111-2222-3333-4444-555555555555"
        p.payload = {"file_path": "a.py"}
        p.vector = [0.1] * 1024
        return [p], None

    def _query(*args: object, **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.points = []
        for i in range(_CANDIDATES_PER_CHUNK):
            sp = MagicMock()
            sp.id = f"22222222-0000-0000-0000-{i:012d}"
            sp.score = 0.9
            r.points.append(sp)
        return r

    mock_client.scroll.side_effect = _scroll
    mock_client.query_points.side_effect = _query

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        t0 = time.monotonic()
        edges = await SemanticEdgeBuilder().build(repository, dirty_ids)
        elapsed = time.monotonic() - t0

    assert elapsed < _LIMIT_SECONDS, (
        f"Pitfall 3 perf gate violation: 10k dirty chunks took {elapsed:.1f}s, "
        f"required < {_LIMIT_SECONDS}s (per contract)"
    )
    assert len(edges) == _NUM_DIRTY * _CANDIDATES_PER_CHUNK
    assert mock_client.query_points.call_count == _NUM_DIRTY
    assert mock_client.scroll.call_count == _NUM_DIRTY
