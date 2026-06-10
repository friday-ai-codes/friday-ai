"""run_git_diff_index 行级 diff 三态集成测试（Pitfall 6）。

mock git subprocess（name-status 返回空 diff 以走 no-changes 早退，跳过重索引；
numstat 返回受控输出），断言 IndexHistory.lines_added/lines_deleted 三态落库：
- 真实值（numstat 成功）
- None（numstat returncode≠0，shallow/加深失败的诚实降级——绝不写 0）
- None（全量索引根本不调 numstat，字段保持 default=None）
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from repositories.models import IndexHistory, IndexHistoryStatus, TriggerType
from services.indexer import IndexerService

pytestmark = pytest.mark.django_db(transaction=True)


class _FakeProc:
    """模拟 asyncio subprocess：communicate() 返回 (stdout, stderr)，带 returncode。"""

    def __init__(self, stdout: bytes, returncode: int) -> None:
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return (self._stdout, b"")


def _make_exec(numstat_stdout: bytes, numstat_rc: int) -> Any:
    """构造 create_subprocess_exec 替身：name-status 返回空，numstat 返回受控输出。"""

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        if "--numstat" in args:
            return _FakeProc(numstat_stdout, numstat_rc)
        # name-status：空输出 → diffs=[] → aupdate 后早退，跳过重索引路径
        return _FakeProc(b"", 0)

    return _fake_exec


async def _make_history(repository: Any) -> IndexHistory:
    return await IndexHistory.objects.acreate(
        repository=repository,
        trigger_type=TriggerType.WEBHOOK,
        status=IndexHistoryStatus.RUNNING,
    )


async def _run_diff(idx: IndexerService, history_id: str, exec_fn: Any) -> None:
    with (
        patch.object(idx, "_ensure_collection", new=AsyncMock()),
        patch("services.indexer.update_index_stage", new=AsyncMock()),
        patch("asyncio.create_subprocess_exec", new=exec_fn),
    ):
        await idx.run_git_diff_index(
            "/tmp/fake_repo", "aaaaaa", "bbbbbb", history_id=history_id
        )


async def test_real_numstat(repository) -> None:
    """numstat 成功 → lines_added/deleted 写真实值。"""
    history = await _make_history(repository)
    idx = IndexerService(str(repository.id))

    await _run_diff(idx, str(history.id), _make_exec(b"3\t1\tfile.py\0", 0))

    refreshed = await IndexHistory.objects.aget(id=history.id)
    assert refreshed.lines_added == 3
    assert refreshed.lines_deleted == 1


async def test_real_numstat_zero(repository) -> None:
    """numstat 成功但全二进制 → 写真实 0（区别于 None）。"""
    history = await _make_history(repository)
    idx = IndexerService(str(repository.id))

    await _run_diff(idx, str(history.id), _make_exec(b"-\t-\timg.png\0", 0))

    refreshed = await IndexHistory.objects.aget(id=history.id)
    assert refreshed.lines_added == 0
    assert refreshed.lines_deleted == 0


async def test_shallow_writes_null(repository) -> None:
    """numstat returncode≠0（模拟 shallow/加深失败）→ 写 None（非 0），不抛错。"""
    history = await _make_history(repository)
    idx = IndexerService(str(repository.id))

    await _run_diff(idx, str(history.id), _make_exec(b"", 1))

    refreshed = await IndexHistory.objects.aget(id=history.id)
    assert refreshed.lines_added is None
    assert refreshed.lines_deleted is None


async def test_full_index_null(repository) -> None:
    """全量索引不调 run_git_diff_index → 字段保持 default=None（不可计算）。"""
    history = await _make_history(repository)

    refreshed = await IndexHistory.objects.aget(id=history.id)
    assert refreshed.lines_added is None
    assert refreshed.lines_deleted is None
