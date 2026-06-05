"""implementation payload sync E2E（per contract）。

100 chunks + 50 edges 走 `_run_all_builders_and_sync_payload` 全链路；
断言 batch_set_payload 被调**恰好一次**（per contract / contract）+ payload 满足
top-20 + 5KB 约束（per contract）+ 50 ChunkEdge 入库（per contract）。

绕开 builder 实际 AST/git/qdrant 调用：BUILDERS patched 为空 list，预先用
`abulk_create` 注入 50 ChunkEdge 进 DB，验证 aggregator + payload sync 链路。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from code_relations import tasks as tasks_module
from code_relations.constants import MAX_NEIGHBORS_PER_CHUNK, MAX_PAYLOAD_SIZE_BYTES
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from code_relations.tasks import _run_all_builders_and_sync_payload


@pytest.mark.django_db(transaction=True)
async def test_e2e_100_chunks_50_edges_single_batch_set_payload(repository) -> None:
    """100 chunks（前 50 个有边）→ aggregator 产出 50 updates → batch_set_payload 调 1 次。

    断言矩阵：
    - mock_batch.call_count == 1（per contract）
    - len(updates_arg) == 50（前 50 有边的 chunk）
    - 每 update payload "related_chunks" 长度 ≤ 20（per contract top-N）
    - 每 update payload bytes < 5 KB（per contract size cap）
    - DB ChunkEdge.objects.acount() == 50（per contract 入库）
    """
    chunk_ids = [uuid.uuid4() for _ in range(100)]

    registry_rows = [
        ChunkRegistry(
            chunk_id=cid,
            content_hash="x" * 64,
            repository=repository,
            file_path=f"src/file_{i:03d}.py",
            chunk_index=0,
        )
        for i, cid in enumerate(chunk_ids)
    ]
    await ChunkRegistry.objects.abulk_create(registry_rows)

    # 前 50 chunk 各精确产出 1 条 ChunkEdge → 50 sources × 1 edge = 50 ChunkEdge
    # → 聚合器为这 50 个 source 各输出一条 update（其余 50 个 chunk 无边不入）。
    edges_to_create: list[ChunkEdge] = [
        ChunkEdge(
            source_chunk_id=chunk_ids[i],
            target_chunk_id=chunk_ids[(i + 1) % 100],
            edge_type=EdgeType.CALL,
            weight=0.9 - 0.005 * i,
            metadata={"call_count": 1},
            repository=repository,
        )
        for i in range(50)
    ]
    await ChunkEdge.objects.abulk_create(edges_to_create)
    assert await ChunkEdge.objects.acount() == 50

    with patch.object(tasks_module, "BUILDERS", []):
        with patch(
            "services.qdrant_service.QdrantService.batch_set_payload",
            new_callable=AsyncMock,
        ) as mock_batch:
            await _run_all_builders_and_sync_payload(str(repository.id), chunk_ids)

    assert mock_batch.call_count == 1, (
        f"batch_set_payload 应仅调一次（per contract），实际 {mock_batch.call_count} 次"
    )

    call_args = mock_batch.call_args
    repo_arg, updates_arg = call_args.args[0], call_args.args[1]
    assert repo_arg == str(repository.id)

    assert len(updates_arg) == 50, (
        f"前 50 chunk 各有边 → 50 updates，实际 {len(updates_arg)}"
    )

    edge_type_values = {e.value for e in EdgeType}
    for point_id, payload in updates_arg:
        assert isinstance(point_id, str)
        assert "related_chunks" in payload
        related = payload["related_chunks"]
        assert isinstance(related, list)
        assert len(related) <= MAX_NEIGHBORS_PER_CHUNK
        payload_bytes = len(json.dumps(payload).encode())
        assert payload_bytes < MAX_PAYLOAD_SIZE_BYTES, (
            f"payload 超 5KB：{payload_bytes} bytes for point {point_id}"
        )
        for entry in related:
            assert len(entry) == 3
            cid_str, edge_type_str, weight_float = entry
            assert isinstance(cid_str, str)
            uuid.UUID(cid_str)  # 验合法 UUID
            assert edge_type_str in edge_type_values
            assert 0.0 <= weight_float <= 1.0

    assert await ChunkEdge.objects.acount() == 50
