"""implementation：verify_payload_consistency 管理命令单测。

覆盖 6 条用例（contract / contract + must_haves 异常隔离条款）：

1. test_no_errors_when_payload_intact
   所有 neighbor.chunk_id 都在 ChunkRegistry → stdout `total_orphans=0`。
2. test_detects_orphan_neighbors
   注入孤儿 neighbor → stdout `total_orphans>=1` + dry-run 不调 enqueue。
3. test_fix_triggers_enqueue_for_dirty_sources
   `--fix` + 含 orphan → enqueue_edge_build 被调一次，dirty_ids 含 source chunk_id。
4. test_qdrant_failure_isolated_per_chunk
   单 chunk Qdrant 拉取失败 → catch + skipped++ + 继续采样下一个（per must_haves 异常隔离）。
5. test_invalid_repo_raises_command_error
   `--repo <不存在 UUID>` → CommandError（运维 fast-fail）。
6. test_invalid_sample_raises_command_error
   `--sample 0` → CommandError（避免无效采样静默通过）。
"""

from __future__ import annotations

import uuid
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from code_relations.models import ChunkRegistry

pytestmark = pytest.mark.django_db(transaction=True)


def _make_chunk(
    repository: object, *, chunk_id: uuid.UUID | None = None, file_path: str = "src/foo.py", index: int = 0
) -> ChunkRegistry:
    return ChunkRegistry.objects.create(
        chunk_id=chunk_id or uuid.uuid4(),
        content_hash="0" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=index,
    )


def _record(payload: dict) -> MagicMock:
    """模拟 qdrant_client Record（提供 .payload 属性）。"""
    rec = MagicMock()
    rec.payload = payload
    return rec


def test_no_errors_when_payload_intact(repository) -> None:
    """所有 payload neighbor 都在 registry → total_orphans=0。"""
    c1 = _make_chunk(repository, file_path="src/a.py", index=0)
    c2 = _make_chunk(repository, file_path="src/b.py", index=1)
    c3 = _make_chunk(repository, file_path="src/c.py", index=2)

    payload_for: dict[uuid.UUID, dict] = {
        c1.chunk_id: {"related_chunks": [[str(c2.chunk_id), "CALL", 0.9]]},
        c2.chunk_id: {"related_chunks": [[str(c3.chunk_id), "IMPORT", 0.8]]},
        c3.chunk_id: {"related_chunks": [[str(c1.chunk_id), "SAME_FILE", 0.5]]},
    }

    def fake_retrieve(*, collection_name: str, ids: list[str], with_payload: list[str]) -> list[MagicMock]:
        # work item：verify 命令现在批量传 ids；按 ids list 全部返回对应 record
        records = []
        for id_str in ids:
            cid = uuid.UUID(id_str)
            rec = _record(payload_for[cid])
            rec.id = id_str
            records.append(rec)
        return records

    fake_client = MagicMock()
    fake_client.retrieve.side_effect = fake_retrieve

    out = StringIO()
    with patch(
        "code_relations.management.commands.verify_payload_consistency.QdrantService.get_client",
        return_value=fake_client,
    ):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "10",
            stdout=out,
        )

    output = out.getvalue()
    assert "total_orphans=0" in output, output
    assert "total_chunks_checked=3" in output, output


def test_detects_orphan_neighbors(repository) -> None:
    """neighbor.chunk_id 不在 registry → total_orphans>=1，dry-run 不触发 enqueue。"""
    src = _make_chunk(repository, file_path="src/a.py", index=0)
    orphan_id = uuid.uuid4()  # 不在 ChunkRegistry

    fake_client = MagicMock()
    rec = _record({"related_chunks": [[str(orphan_id), "CALL", 0.9]]})
    rec.id = str(src.chunk_id)
    fake_client.retrieve.return_value = [rec]

    out = StringIO()
    with (
        patch(
            "code_relations.management.commands.verify_payload_consistency.QdrantService.get_client",
            return_value=fake_client,
        ),
        patch(
            "code_relations.management.commands.verify_payload_consistency.enqueue_edge_build",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "5",
            stdout=out,
        )

    output = out.getvalue()
    assert "total_orphans=1" in output, output
    mock_enqueue.assert_not_called()


def test_fix_triggers_enqueue_for_dirty_sources(repository) -> None:
    """--fix 模式 + orphan → enqueue_edge_build 被调，dirty_ids 含含 orphan 的 source chunk_id。"""
    src = _make_chunk(repository, file_path="src/a.py")
    orphan_id = uuid.uuid4()

    fake_client = MagicMock()
    rec = _record({"related_chunks": [[str(orphan_id), "CALL", 0.9]]})
    rec.id = str(src.chunk_id)
    fake_client.retrieve.return_value = [rec]

    out = StringIO()
    with (
        patch(
            "code_relations.management.commands.verify_payload_consistency.QdrantService.get_client",
            return_value=fake_client,
        ),
        patch(
            "code_relations.management.commands.verify_payload_consistency.enqueue_edge_build",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "5",
            "--fix",
            stdout=out,
        )

    mock_enqueue.assert_called_once()
    call_args = mock_enqueue.call_args
    repo_arg = call_args.args[0]
    dirty_ids = call_args.args[1]
    assert repo_arg == str(repository.id)
    assert src.chunk_id in dirty_ids


def test_qdrant_failure_isolated_per_chunk(repository) -> None:
    """单 chunk Qdrant 拉取抛错 → catch + skipped++ + 继续；命令成功退出。"""
    _make_chunk(repository, file_path="src/a.py", index=0)
    _make_chunk(repository, file_path="src/b.py", index=1)

    fake_client = MagicMock()
    fake_client.retrieve.side_effect = RuntimeError("simulated qdrant down")

    out = StringIO()
    with patch(
        "code_relations.management.commands.verify_payload_consistency.QdrantService.get_client",
        return_value=fake_client,
    ):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "5",
            stdout=out,
        )

    output = out.getvalue()
    assert "total_skipped=2" in output, output
    assert "total_orphans=0" in output, output


def test_invalid_repo_raises_command_error(db) -> None:
    """--repo <不存在 UUID> → CommandError；不静默通过。"""
    bogus = uuid.uuid4()
    with pytest.raises(CommandError):
        call_command("verify_payload_consistency", "--repo", str(bogus))


def test_invalid_sample_raises_command_error(repository) -> None:
    """--sample <=0 → CommandError；避免无效采样静默通过。"""
    with pytest.raises(CommandError):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "0",
        )


def test_sample_above_upper_bound_raises_command_error(repository) -> None:
    """work item regression：--sample 超过上限 → CommandError；防大仓 ORDER BY RANDOM 塌方。"""
    with pytest.raises(CommandError, match="超过上限"):
        call_command(
            "verify_payload_consistency",
            "--repo",
            str(repository.id),
            "--sample",
            "1000000",
        )


def test_dispatch_and_drain_only_awaits_new_tasks(repository) -> None:
    """work item regression：_dispatch_and_drain 只 await 本次新 spawn 的 task。

    背景：旧实现 `pending = list(_BACKGROUND_TASKS)` 全量 snapshot → 多仓
    校验时会跨 dispatch 串行 await 别人的 task；甚至跨 loop 报
    "Task attached to a different loop"。新实现照 lifecycle.py before/after
    diff 模式。
    """
    import asyncio

    from code_relations import tasks as tasks_module
    from code_relations.management.commands import verify_payload_consistency as cmd

    src = _make_chunk(repository, file_path="src/a.py")

    async def _run() -> None:
        # 注入一个"别人的"长 await task，模拟跨 dispatch 残留
        async def _other_task() -> None:
            await asyncio.sleep(60)

        other = asyncio.create_task(_other_task())
        tasks_module._BACKGROUND_TASKS.add(other)
        other.add_done_callback(tasks_module._BACKGROUND_TASKS.discard)
        try:
            with patch(
                "code_relations.management.commands.verify_payload_consistency.enqueue_edge_build",
                new_callable=AsyncMock,
            ) as mock_enq:
                # mock 不 spawn 任何新 task，drain 应立即返回（不去 await `other`）
                await cmd.Command._dispatch_and_drain(
                    str(repository.id), [src.chunk_id]
                )
                mock_enq.assert_called_once()
        finally:
            other.cancel()
            try:
                await other
            except (asyncio.CancelledError, BaseException):
                pass

    # 用 wait_for 给 _run 一个紧凑超时；如果 drain 错误地 await `other`
    # （sleep 60s），会触发 TimeoutError → 测试失败
    asyncio.run(asyncio.wait_for(_run(), timeout=2.0))
