"""会话驱动租约测试 —— 「同一会话同时只允许一个驱动者跑 stage handler」。

这一层锁的是一次**真实事故**的形状：蓝图会话的 AI 审查被并发跑了 7 遍。根因是
``ProcessEngine.advance`` 只在**写回**那一瞬间做 CAS，handler 本体（分钟级 LLM 调用 +
批量开线程）毫无保护，而驱动者是多入口的（durable 续驱 job / 两个容器回调 barrier /
动作端点 / 僵尸会话扫描），且回调 barrier 是**电平判据**——「都产出了吗」一旦为真就恒为真，
于是每个后到的回调都再入队一次续驱。

守六件事：

1. ⭐ **N 个并发驱动者只有 1 个真跑 handler**（头号靶子，直接对应那 7 次重复审查）。
2. ⭐ 抢不到的驱动者**原地返回而不是报错**——多入口触发续驱是常态，不是错误路径。
3. **释放后可再抢**：一次驱动结束不该把会话锁死。
4. ⭐ **可重入**：续驱 helper 包住循环、循环里的 ``advance`` 再获取一次，不该自锁。
5. ⭐ **超时自愈**：持有者崩溃（不释放）后租约过期，下一个驱动者能接管，会话不永久卡死。
6. ⭐ **fail-open**：租约 DB 操作异常时按「抢到了」放行——租约是省钱的优化，不是正确性
   屏障，绝不能因为它挂了让整条编排停摆。

``async`` 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from services.process_runtime.drive_lease import asession_drive_lease

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        id=uuid.uuid4(),
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        status=ConvergenceSessionStatus.RUNNING,
        current_stage="ai_review",
    )


# ══════════════════════════════════════════════════════════════════════════
# 1-2. ⭐ N 个并发驱动者只有一个真跑；抢不到的原地返回
# ══════════════════════════════════════════════════════════════════════════


async def test_only_one_of_many_concurrent_drivers_runs_the_handler() -> None:
    """⭐ 7 个并发驱动者（复刻事故规模）⇒ handler 恰好跑 1 次。"""
    session = await _make_session()
    ran: list[int] = []
    skipped: list[int] = []

    async def _driver(index: int) -> None:
        async with asession_drive_lease(session.id, reason="test") as acquired:
            if not acquired:
                skipped.append(index)
                return
            ran.append(index)
            # 持有期间让出事件循环：不 sleep 的话第一个驱动者可能在别人开始前就释放完，
            # 这条用例就退化成「串行跑 7 次」而验不到任何东西。
            await asyncio.sleep(0.05)

    await asyncio.gather(*(_driver(i) for i in range(7)))

    assert len(ran) == 1, f"并发驱动者里有 {len(ran)} 个跑了 handler，租约没拦住"
    assert len(skipped) == 6
    # ⭐ 抢不到是**正常返回**而不是抛异常：多入口触发续驱是常态。
    assert sorted(ran + skipped) == list(range(7))


async def test_lease_is_released_and_reacquirable() -> None:
    """释放后下一个驱动者能抢到（一次驱动不该把会话锁死）。"""
    session = await _make_session()

    async with asession_drive_lease(session.id, reason="first") as first:
        assert first is True
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.drive_lease_owner == ""
    assert fresh.drive_lease_until is None

    async with asession_drive_lease(session.id, reason="second") as second:
        assert second is True


# ══════════════════════════════════════════════════════════════════════════
# 3. ⭐ 可重入（续驱 helper 包住循环 + 循环里的 advance 再获取一次）
# ══════════════════════════════════════════════════════════════════════════


async def test_nested_acquire_in_same_context_is_reentrant() -> None:
    """⭐ 嵌套获取直接放行，且**内层退出不释放**——释放归最外层。"""
    session = await _make_session()

    async with asession_drive_lease(session.id, reason="outer") as outer:
        assert outer is True
        async with asession_drive_lease(session.id, reason="inner") as inner:
            assert inner is True, "自锁：续驱 helper 包住循环后循环里的 advance 会全被拦下"
        # 内层退出后租约仍在（否则外层剩下的步骤就在裸奔）。
        held = await ConvergenceSession.objects.aget(id=session.id)
        assert held.drive_lease_owner != ""

    released = await ConvergenceSession.objects.aget(id=session.id)
    assert released.drive_lease_owner == ""


async def test_reentrancy_is_scoped_per_session_not_per_context() -> None:
    """⭐ 持有 A 的租约**不该**让同上下文里的 B 免抢占。

    僵尸会话扫描就是在同一个上下文里逐条驱动不同会话：判据若是「本上下文是否持有任意
    租约」，第一条之后的每一条都会被误判成「外层已持有」而跳过抢占 —— 租约对扫描这条
    路径彻底失效，而扫描恰恰是绕过队列 lock 的那条路径。
    """
    session_a = await _make_session()
    session_b = await _make_session()
    # B 已被别的驱动者持有且未过期。
    await ConvergenceSession.objects.filter(id=session_b.id).aupdate(
        drive_lease_owner="别的驱动者",
        drive_lease_until=timezone.now() + timedelta(seconds=600),
    )

    async with asession_drive_lease(session_a.id, reason="a") as got_a:
        assert got_a is True
        async with asession_drive_lease(session_b.id, reason="b") as got_b:
            assert got_b is False, "持有 A 的租约把 B 也一起放行了 ⇒ 扫描路径上租约失效"


async def test_reentrancy_does_not_leak_across_concurrent_tasks() -> None:
    """可重入判据是 contextvar ⇒ **另一个任务**不该蹭到别人的重入放行。"""
    session = await _make_session()
    other_acquired: list[bool] = []
    inner_started = asyncio.Event()

    async def _other() -> None:
        await inner_started.wait()
        async with asession_drive_lease(session.id, reason="other") as ok:
            other_acquired.append(ok)

    async def _holder() -> None:
        async with asession_drive_lease(session.id, reason="holder"):
            inner_started.set()
            await asyncio.sleep(0.05)

    await asyncio.gather(_holder(), _other())

    assert other_acquired == [False], "contextvar 串味：别的任务蹭到了重入放行"


# ══════════════════════════════════════════════════════════════════════════
# 4. ⭐ 超时自愈（持有者崩溃不让会话永久卡死）
# ══════════════════════════════════════════════════════════════════════════


async def test_expired_lease_can_be_taken_over() -> None:
    """⭐ 持有者崩溃（租约没释放）⇒ 过期后下一个驱动者接管。"""
    session = await _make_session()
    await ConvergenceSession.objects.filter(id=session.id).aupdate(
        drive_lease_owner="崩掉的持有者",
        drive_lease_until=timezone.now() - timedelta(seconds=1),
    )

    async with asession_drive_lease(session.id, reason="takeover") as acquired:
        assert acquired is True, "租约不过期 ⇒ 持有者一崩会话就永久卡死"


async def test_unexpired_lease_blocks_takeover() -> None:
    """对照组：租约**没过期**时不许接管（证明上一条不是恒真）。"""
    session = await _make_session()
    await ConvergenceSession.objects.filter(id=session.id).aupdate(
        drive_lease_owner="仍在跑的持有者",
        drive_lease_until=timezone.now() + timedelta(seconds=600),
    )

    async with asession_drive_lease(session.id, reason="too_early") as acquired:
        assert acquired is False


async def test_release_never_steals_a_lease_taken_over_by_someone_else() -> None:
    """本次驱动超时后租约已被别人合法抢走 ⇒ 本次的释放**不许**动它。"""
    session = await _make_session()

    async with asession_drive_lease(session.id, reason="slow"):
        # 模拟「超时后被接管」：owner 被改成别人。
        await ConvergenceSession.objects.filter(id=session.id).aupdate(
            drive_lease_owner="接管者",
            drive_lease_until=timezone.now() + timedelta(seconds=600),
        )

    after = await ConvergenceSession.objects.aget(id=session.id)
    assert after.drive_lease_owner == "接管者", "误放了别人的租约 ⇒ 又会出现并发驱动"


# ══════════════════════════════════════════════════════════════════════════
# 5. ⭐ fail-open（租约挂了绝不反噬编排）
# ══════════════════════════════════════════════════════════════════════════


async def test_acquire_failure_fails_open(monkeypatch) -> None:
    """⭐ 抢占 DB 异常 ⇒ 按「抢到了」放行。租约是优化，不是正确性屏障。"""
    from services.process_runtime import drive_lease as mod

    async def _boom(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("DB 抖了")

    monkeypatch.setattr(mod, "_aacquire", _boom)

    with pytest.raises(RuntimeError):
        # 先证明桩确实会抛（否则下面那条断言可能因为桩没生效而恒真）。
        await mod._aacquire("x", "y", 1)

    monkeypatch.undo()

    # 真实实现的 fail-open：让底层 ORM 调用炸掉。
    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("DB 抖了")

    monkeypatch.setattr(ConvergenceSession.objects, "filter", _explode)

    async with asession_drive_lease(uuid.uuid4(), reason="fail_open") as acquired:
        assert acquired is True, "租约挂了却把编排也拦下 ⇒ 整条链停摆"


async def test_falsy_session_id_is_passed_through() -> None:
    """会话 id 为空是调用方 bug，但不该因此卡住驱动。"""
    async with asession_drive_lease(None, reason="no_id") as acquired:
        assert acquired is True
