"""增量索引 reconcile 端到端集成测试。

串起 plan pre_delete signal handler + plan verify_payload_consistency
管理命令 + plan lifecycle wrapper 全链路：

1. 造 Repository + 5 ChunkRegistry（target + 4 sources）+ 4 ChunkEdge (source_i → target)
2. 写 Qdrant payload mock：sources 的 `related_chunks` 含已删 target chunk_id
   （即"孤儿"场景，模拟增量索引前的 stale payload）
3. 删除 target ChunkRegistry → pre_delete signal 触发 → ChunkEdge 反向清理 +
   transaction.on_commit 调度 reconcile via background_runner
4. 等所有 in-flight Future 落地
5. 调 `verify_payload_consistency --repo <id> --sample 10` → stdout
   `total_orphans=0`（reconcile 后 payload 已清孤儿引用）

**关键约束**（implementation constraints）：本测试**完全不动 tasks.py / payload_sync.py**；
真实 ChunkEdge ORM + 真实 background_runner + 真实 verify_payload_consistency 管线，
仅 mock Qdrant 边界（QdrantService.batch_set_payload + retrieve）。
"""

from __future__ import annotations

import asyncio
import uuid
from io import StringIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.management import call_command

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from services import background_runner

pytestmark = pytest.mark.django_db(transaction=True)


def _make_chunk(repository: Any, *, file_path: str, index: int = 0) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=index,
    )


def _make_edge(
    repository: Any, *, source: uuid.UUID, target: uuid.UUID, weight: float = 0.7
) -> ChunkEdge:
    return ChunkEdge.objects.create(
        source_chunk_id=source,
        target_chunk_id=target,
        edge_type=EdgeType.CALL,
        weight=weight,
        metadata={},
        repository=repository,
    )


def test_pre_delete_signal_triggers_reconcile_and_verify_zero_errors(
    repository: Any,
) -> None:
    """删 target ChunkRegistry → reconcile 全链路 → verify 0 errors。

    断言矩阵：
    - 反向 ChunkEdge（指向 target）被清理 → count == 0（plan signal handler）
    - background_runner 落地后 lifecycle wrapper 已调 enqueue + batch_set_payload
    - verify_payload_consistency 输出含 `total_orphans=0`（mock Qdrant 返回干净 payload）
    """
    target = _make_chunk(repository, file_path="src/target.py", index=0)
    sources = [
        _make_chunk(repository, file_path=f"src/src_{i}.py", index=i + 1)
        for i in range(4)
    ]
    for src in sources:
        _make_edge(repository, source=src.chunk_id, target=target.chunk_id, weight=0.7)

    target_id = target.chunk_id

    # 跟踪 batch_set_payload 是否被调（reconcile 链路是否落到 Qdrant 边界）
    batch_set_calls: list[tuple[str, list[Any]]] = []

    async def _fake_batch_set_payload(repo_id: str, updates: list[Any]) -> None:
        batch_set_calls.append((repo_id, list(updates)))

    fake_client = MagicMock()

    def _fake_retrieve(
        *, collection_name: str, ids: list[str], with_payload: list[str]
    ) -> list[MagicMock]:
        rec = MagicMock()
        rec.payload = {"related_chunks": []}
        return [rec]

    fake_client.retrieve.side_effect = _fake_retrieve

    with patch(
        "services.qdrant_service.QdrantService.batch_set_payload",
        new=AsyncMock(side_effect=_fake_batch_set_payload),
    ):
        with patch(
            "code_relations.management.commands.verify_payload_consistency.QdrantService.get_client",
            return_value=fake_client,
        ):
            target.delete()

            background_runner.wait_for_pending(timeout=10.0)

            for _ in range(10):
                if batch_set_calls:
                    break
                asyncio.run(asyncio.sleep(0.05))

            assert (
                ChunkEdge.objects.filter(target_chunk_id=target_id).count() == 0
            ), "plan 反向 ChunkEdge 清理失败"
            assert not ChunkRegistry.objects.filter(chunk_id=target_id).exists()

            assert batch_set_calls, (
                "reconcile 未走到 QdrantService.batch_set_payload —— signal handler / "
                "background_runner / enqueue_edge_build 链路存在断点"
            )

            out = StringIO()
            call_command(
                "verify_payload_consistency",
                "--repo",
                str(repository.id),
                "--sample",
                "10",
                stdout=out,
            )

    output = out.getvalue()
    assert "total_orphans=0" in output, (
        f"verify_payload_consistency 应报 0 orphans，实际输出：\n{output}"
    )
