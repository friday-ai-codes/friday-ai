"""BlueprintContextEntry 的 ``seq`` 分配守护（PLAN 113-01 Task 3，DESIGN §5.6）。

守五件事：

1. **串行单调**：连续 ``append_entry`` 5 次 → 重读 DB 得 ``seq == [1,2,3,4,5]``（严格无
   重复、无空洞——``since_seq`` 增量语义全靠它）。
2. ⭐ **确定性冲突重试（可证伪性的主承担者）**：monkeypatch ``_next_seq`` 让首次调用返回
   已被占用的陈旧值，模拟「两 writer 读到同一 ``max(seq)``」→ 唯一约束抛
   ``IntegrityError`` → 被捕获重试后仍写入成功，且该会话内 seq 仍无重复无空洞。
   **不依赖任何真并发调度**，故必然可复现、可证伪。
3. ⭐ **真线程并发（选 PLAN 方案 ①，非「按 postgres 条件跳过」）**：``ThreadPoolExecutor``
   跑 8 个同步 worker，每个 worker 先 ``connection.close()`` 断开继承连接（各线程各持独立
   DB 连接才可能真竞争）后走 service 的同步写入路径 → 断言 8 条 seq 恰为 1..8。
   **选①的理由**：方案 ②（``skipif(vendor != "postgresql")``）在默认 SQLite 套件里等于零
   覆盖；而实测方案 ① 在 SQLite 上会真实撞出 ``database table is locked``——这本身就是
   「8 个线程确实同时在写同一张表」的硬证据。SQLite 无行锁（``select_for_update`` 是
   no-op），故 worker 侧吸收该 ``OperationalError`` 并重投（重投会重新读 ``max(seq)``，
   不掩盖被测机制），并**反向断言重投次数 > 0**——若哪天写入被悄悄串行化，这条断言先挂，
   本用例不会退化成平凡通过。seq 重复或缺号则前三条断言直接失败。
   ⚠️ 本文件**零使用** ``asyncio`` 的 ``gather`` 作并发证据：``sync_to_async`` 默认
   ``thread_sensitive=True`` 会把全部写入串行到同一线程，那种断言必然平凡通过。
4. **跨会话独立**：两个 session 各写 3 条，各自 seq 均为 1..3（会话内单调，不共享全局序）。
5. **唯一约束存在**：``_meta.constraints`` 里有 ``uq_blueprint_context_session_seq``。

async service 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.db import OperationalError, connection

from delivery.models import (
    BlueprintContextEntry,
    ContextEntryKind,
    ConvergenceSession,
)
from delivery.services.blueprint_context_service import BlueprintContextService

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---- 工厂 ----


async def _make_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint="chat",
        current_stage="repo_plan",
    )


async def _seqs(session: ConvergenceSession) -> list[int]:
    """从 DB 重读该会话全部条目的 seq（升序）——不信内存对象。"""
    return [
        row["seq"]
        async for row in BlueprintContextEntry.objects.filter(convergence_session=session)
        .order_by("seq")
        .values("seq")
    ]


# ---- 1. 串行单调 ----


async def test_serial_appends_produce_contiguous_seq() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    for i in range(5):
        await service.append_entry(
            session=session,
            key=f"repo:r{i}.api_surface",
            kind=ContextEntryKind.API_SURFACE,
            content={"i": i},
        )

    assert await _seqs(session) == [1, 2, 3, 4, 5]


# ---- 2. 确定性冲突重试 ----


async def test_stale_next_seq_triggers_integrity_error_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两 writer 读到同一 ``max(seq)`` 的确定性复现：首次返回陈旧值 → IntegrityError → 重试成功。"""
    session = await _make_session()
    service = BlueprintContextService()

    await service.append_entry(
        session=session,
        key="repo:a.api_surface",
        kind=ContextEntryKind.API_SURFACE,
        content={"n": 1},
    )

    real_next_seq = BlueprintContextService._next_seq
    calls: list[int] = []

    def _stale_first(self, session_id):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            # 陈旧值：seq=1 已被上一条占用 → UniqueConstraint 必然抛 IntegrityError
            return 1
        return real_next_seq(self, session_id)

    monkeypatch.setattr(BlueprintContextService, "_next_seq", _stale_first)

    entry = await service.append_entry(
        session=session,
        key="repo:b.api_surface",
        kind=ContextEntryKind.API_SURFACE,
        content={"n": 2},
    )

    # ① 桩被调用 ≥2 次 ⇒ 首次冲突确实走了重试分支
    assert len(calls) >= 2
    # ② append_entry 返回成功（不抛、不静默失败）
    assert entry.seq == 2
    # ③ 唯一约束兜底后 seq 无重复无空洞
    seqs = await _seqs(session)
    assert len(seqs) == len(set(seqs))
    assert sorted(seqs) == list(range(1, len(seqs) + 1))


# ---- 3. 真线程并发 ----


def _is_sqlite_lock_error(exc: Exception) -> bool:
    """SQLite 的表级写锁（``database table is locked``）——它证明线程竞争真的发生了。

    仅 SQLite 会这样：它没有行锁，整表写串行化失败直接抛 ``OperationalError``（不是
    ``IntegrityError``，故不走 service 的唯一约束兜底重试）。pg/MySQL 走真行锁，不会
    产生这个错。**测试侧**吸收它并重投，让被测机制回到「seq 分配」本身：重投会重新读
    ``max(seq)``，所以一旦锁父行 + 唯一约束这条防线失效，重复/缺号仍会被下面的断言逮到。
    """
    return connection.vendor == "sqlite" and "locked" in str(exc).lower()


def _worker(session_id, index: int) -> int:
    """同步 worker：先断开继承的 DB 连接（各线程独立连接才可能真竞争），再走写入路径。

    返回本 worker 因 SQLite 表锁重投的次数（>0 即真竞争的直接证据）。
    """
    connection.close()
    service = BlueprintContextService()
    retries = 0
    while True:
        try:
            session = ConvergenceSession.objects.get(pk=session_id)
            async_to_sync(service.append_entry)(
                session=session,
                key=f"repo:w{index}.api_surface",
                kind=ContextEntryKind.FINDING,
                content={"worker": index},
            )
            connection.close()
            return retries
        except OperationalError as exc:
            if not _is_sqlite_lock_error(exc) or retries >= 20:
                connection.close()
                raise
            retries += 1
            connection.close()
            time.sleep(0.02 * retries)


async def test_threaded_concurrent_appends_have_no_duplicate_or_gap() -> None:
    session = await _make_session()
    session_id = session.id

    def _run() -> list[int]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_worker, session_id, i) for i in range(8)]
            return [future.result() for future in futures]

    # thread_sensitive=False：让 _run 在独立线程执行，8 个 worker 才真的各持独立连接
    retries = await sync_to_async(_run, thread_sensitive=False)()

    seqs = await _seqs(session)
    assert len(seqs) == 8
    assert len(set(seqs)) == 8
    assert sorted(seqs) == list(range(1, 9))
    # 竞争真的发生过：SQLite 后端必有 worker 撞上表写锁并重投（pg 走行锁，可为 0）
    if connection.vendor == "sqlite":
        assert sum(retries) > 0, (
            "8 路线程一次未撞锁 ⇒ 并发未真实发生（worker 可能被串行化），断言等于零覆盖"
        )


# ---- 4. 跨会话独立 ----


async def test_seq_is_per_session_not_global() -> None:
    first = await _make_session()
    second = await _make_session()
    service = BlueprintContextService()

    for session in (first, second):
        for i in range(3):
            await service.append_entry(
                session=session,
                key=f"contract:c{i}",
                kind=ContextEntryKind.CONTRACT,
                content={"i": i},
            )

    assert await _seqs(first) == [1, 2, 3]
    assert await _seqs(second) == [1, 2, 3]


# ---- 5. 唯一约束存在（运行时断言，非 grep） ----


def test_unique_constraint_declared() -> None:
    names = {
        getattr(constraint, "name", "") for constraint in BlueprintContextEntry._meta.constraints
    }
    assert "uq_blueprint_context_session_seq" in names


def test_seq_field_is_not_autofield() -> None:
    """seq 必须是普通 PositiveIntegerField —— 全局 AutoField/DB 序列会让会话内连续性失效。"""
    field = BlueprintContextEntry._meta.get_field("seq")
    assert field.get_internal_type() == "PositiveIntegerField"
    assert not field.primary_key
