"""QdrantService.batch_set_payload 单元测试（per initial implementation contract）。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from services.qdrant_service import QdrantService


async def test_empty_updates_skips_client_call() -> None:
    with patch.object(QdrantService, "get_client") as mock_get_client:
        await QdrantService.batch_set_payload("repo-uuid", [])
        mock_get_client.assert_not_called()


async def test_1500_updates_split_to_3_batches() -> None:
    mock_client = MagicMock()
    with patch.object(QdrantService, "get_client", return_value=mock_client):
        updates = [
            (f"uuid-{i}", {"related_chunks": [["x", "CALL", 0.5]]})
            for i in range(1500)
        ]
        await QdrantService.batch_set_payload("repo-uuid", updates, batch_size=500)
        assert mock_client.batch_update_points.call_count == 3
        for call in mock_client.batch_update_points.call_args_list:
            ops = call.kwargs["update_operations"]
            assert len(ops) == 500
            assert all(isinstance(op, models.SetPayloadOperation) for op in ops)


async def test_set_payload_operation_structure() -> None:
    mock_client = MagicMock()
    with patch.object(QdrantService, "get_client", return_value=mock_client):
        payload = {"related_chunks": [["chunk-x", "CALL", 0.7]]}
        await QdrantService.batch_set_payload("repo-uuid", [("point-a", payload)])
        assert mock_client.batch_update_points.call_count == 1
        ops = mock_client.batch_update_points.call_args.kwargs["update_operations"]
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, models.SetPayloadOperation)
        assert op.set_payload.payload == payload
        assert op.set_payload.points == ["point-a"]


async def test_collection_name_derived_from_repo_id() -> None:
    mock_client = MagicMock()
    with patch.object(QdrantService, "get_client", return_value=mock_client):
        await QdrantService.batch_set_payload("repo-uuid-abc", [("p1", {"x": 1})])
        kwargs = mock_client.batch_update_points.call_args.kwargs
        assert kwargs["collection_name"] == QdrantService.get_collection_name(
            "repo-uuid-abc"
        )
        assert kwargs["wait"] is False


async def test_unexpected_response_caught_and_not_reraised() -> None:
    mock_client = MagicMock()
    mock_client.batch_update_points.side_effect = UnexpectedResponse(
        status_code=500,
        reason_phrase="boom",
        content=b"",
        headers=httpx.Headers({}),
    )
    with patch.object(QdrantService, "get_client", return_value=mock_client):
        # 不抛
        await QdrantService.batch_set_payload("repo-uuid", [("p", {"x": 1})])


async def test_timeout_caught_and_not_reraised() -> None:
    mock_client = MagicMock()

    def _slow_batch(*args: object, **kwargs: object) -> None:
        import time as _t

        _t.sleep(2.0)

    mock_client.batch_update_points.side_effect = _slow_batch
    with patch.object(QdrantService, "get_client", return_value=mock_client):
        # timeout=0.1 强制超时；batch_set_payload 内部 catch + log，外层不抛
        await asyncio.wait_for(
            QdrantService.batch_set_payload(
                "repo-uuid",
                [("p", {"x": 1})],
                timeout=0.1,
            ),
            timeout=2.0,
        )
