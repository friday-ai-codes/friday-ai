"""Pitfall 2 perf gate（per initial implementation contract + contract）。

1k chunks 批量 payload 同步必须 < 1s wall-clock；对应 ROADMAP §initial implementation success criterion
"1k chunks sync wall-clock < 1s"。CI 默认 skip（@pytest.mark.perf），本地用
`pytest -m perf server/tests/code_relations/test_batch_payload_perf.py` 跑。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from services.qdrant_service import QdrantService


@pytest.mark.perf
async def test_batch_set_payload_1k_under_1s() -> None:
    mock_client = MagicMock()
    mock_client.batch_update_points.return_value = None

    updates = [
        (
            f"uuid-{i:08d}",
            {"related_chunks": [[f"nb-{j}", "CALL", 0.5] for j in range(20)]},
        )
        for i in range(1000)
    ]

    with patch.object(QdrantService, "get_client", return_value=mock_client):
        t0 = time.monotonic()
        await QdrantService.batch_set_payload("repo-uuid", updates, batch_size=500)
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, (
        f"Pitfall 2 perf gate violation: 1k chunks batch_set_payload took {elapsed:.3f}s, "
        f"required < 1.0s (per contract)"
    )
    assert mock_client.batch_update_points.call_count == 2
