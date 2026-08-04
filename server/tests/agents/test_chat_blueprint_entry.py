"""chat 入口三条断链的行为守卫（Phase 116-03 Task 3）。

守六件事：

1. ⭐ **等澄清的健康会话返回挂起 marker 而不是失败**（P-7 头号靶子）：一条停在 ``spec_gate``
   （``waiting_clarification`` + 一条 open+blocking ``ai_clarification`` 线程）的 chat 蓝图
   会话，工具必须返回 ``success is True`` 的挂起 marker。现状是
   ``ToolResult(success=False, error="plan session failed")`` —— **用户看到「方案编排失败」，
   其实系统在等他回答问题**。
2. ⭐ **``repo_confirmation`` 线程同样算挂起**：判据**不传 ``kind```` 的证据（与
   ``blueprint_resume`` 的 pause 短路同源，两类线程都算）。
3. **零线程时不误挂起**（断言非恒真）：``waiting_clarification`` 但无 open+blocking 线程 ⇒
   不返回挂起 marker，落到终态映射。
4. ⭐ **终态按蓝图状态分档**：``pending_review`` ⇒ 成功；``failed`` ⇒ 失败；
   ⛔ 响应体里不出现字面 ``blueprint_status`` 键。
5. ⭐ **barrier 回灌满足 waiter**：key 为 ``str(session.id)`` 的 blocking task 被满足；
   并列一条 **key 错配的反向对照**证明第一条不是恒真。
6. **非 chat 入口不回灌**：``entrypoint="workflow"`` 的蓝图会话 ⇒ ``task_completed`` 零调用。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.plan_research_tools import (
    PLAN_CLARIFICATION_RENDER_MARKER,
    _map_terminal_blueprint,
    _maybe_suspend,
)

pytestmark = pytest.mark.django_db(transaction=True)

_BLUEPRINT = "technical_blueprint"


async def _amake_blueprint_session(
    *,
    status: str,
    entrypoint: str = "chat",
    blueprint_status: str = "researching",
    thread_kind: str | None = "ai_clarification",
    thread_status: str = "open",
    blocking: bool = True,
    question: str = "这个需求要不要覆盖移动端？",
):
    """造一条 chat 蓝图会话 + 其蓝图 Artifact/Version（可选一条阻塞线程）。"""
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        BlueprintThread,
        BlueprintThreadMessage,
        ConvergenceSession,
    )

    session = await ConvergenceSession.objects.acreate(
        process_type=_BLUEPRINT,
        entrypoint=entrypoint,
        current_stage="spec_gate",
        status=status,
    )
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    # ⛔ 不经 BlueprintLifecycleService（INV-6 只约束 server/ 源码，测试直写以固定初态）。
    await Artifact.objects.filter(id=artifact.id).aupdate(blueprint_status=blueprint_status)
    version = await ArtifactVersion.objects.acreate(
        artifact=artifact,
        version_no=1,
        content={"schema_version": "blueprint/v1"},
        content_hash="h",
    )
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_artifact_version=version)
    session = await ConvergenceSession.objects.aget(id=session.id)

    if thread_kind is not None:
        thread = await BlueprintThread.objects.acreate(
            artifact=artifact,
            kind=thread_kind,
            status=thread_status,
            blocking=blocking,
        )
        await BlueprintThreadMessage.objects.acreate(thread=thread, author_type="ai", body=question)
    return session, artifact


# ═══════════════════════════════════════════════════════════════════════════
# 1-3. 断链二上半：_maybe_suspend 的蓝图分支
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_healthy_awaiting_clarification_returns_suspend_marker_not_failure() -> None:
    """⭐ 头号靶子：等澄清的健康蓝图会话必须回**挂起 marker**，⛔ 不是「方案编排失败」。

    ⭐ 断言写成 ``success is True`` 而不是「不等于某值」—— 那是与现状
    （``success=False, error="plan session failed"``）的**直接对立面**。
    """
    from delivery.models import ConvergenceSessionStatus

    session, artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    result = await _maybe_suspend(session, str(uuid.uuid4()))

    assert result is not None
    assert result.success is True
    assert result.output["marker"] == PLAN_CLARIFICATION_RENDER_MARKER
    assert result.output["pending"] is True
    assert result.output["session_id"] == str(session.id)
    # 键集与旧链分支的两处差异：clarification_id 位放 thread_id + 追加 artifact_id
    assert result.output["artifact_id"] == str(artifact.id)
    assert result.output["question"] == "这个需求要不要覆盖移动端？"
    assert result.output["allow_freeform"] is True


@pytest.mark.asyncio
async def test_repo_confirmation_thread_also_suspends() -> None:
    """⭐ 判据**不传 ``kind``** 的证据：``repo_confirmation`` 线程同样算挂起。

    与 ``blueprint_resume`` 的 pause 短路同源（那里也不传 ``kind``）。只认
    ``ai_clarification`` 会让确认门挂起的会话被报成失败。
    """
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
        thread_kind="repo_confirmation",
        question="请确认关联仓库清单",
    )

    result = await _maybe_suspend(session, str(uuid.uuid4()))

    assert result is not None
    assert result.success is True
    assert result.output["marker"] == PLAN_CLARIFICATION_RENDER_MARKER


@pytest.mark.asyncio
async def test_no_open_blocking_thread_does_not_suspend() -> None:
    """断言非恒真：``waiting_clarification`` 但无 open+blocking 线程 ⇒ 不挂起。"""
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION, thread_kind=None
    )

    assert await _maybe_suspend(session, str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_resolved_thread_does_not_suspend() -> None:
    """已解决的线程不算阻塞（``status=resolved``）⇒ 不挂起。"""
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION, thread_status="resolved"
    )

    assert await _maybe_suspend(session, str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_legacy_session_still_uses_the_old_criteria() -> None:
    """开关关闭时的零回归：``technical_plan`` 会话仍走旧链两个分支（蓝图分支不误伤）。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="chat",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
    )

    # 无 Clarification ⇒ 旧链判据返回 None（⛔ 不该走蓝图分支去查 BlueprintThread）
    assert await _maybe_suspend(session, str(uuid.uuid4())) is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. 断链二下半：_map_terminal_blueprint 的分档
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pending_review_is_success_not_failure() -> None:
    """⭐ ``pending_review``（= 等人审）是**成功**：方案已产出，⛔ 不是「编排失败」。"""
    from delivery.models import ConvergenceSessionStatus

    session, artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE,
        blueprint_status="pending_review",
        thread_kind=None,
    )

    result = await _map_terminal_blueprint(session, str(uuid.uuid4()))

    assert result.success is True
    assert result.output["current_status"] == "pending_review"
    assert result.output["artifact_id"] == str(artifact.id)
    # ⛔ INV-6：响应体键名不得出现字面 blueprint_status
    assert "blueprint_status" not in result.output


@pytest.mark.asyncio
async def test_needs_clarification_terminal_returns_suspend_marker() -> None:
    """⭐ 终态时蓝图状态为 ``needs_clarification`` ⇒ 仍回挂起 marker，⛔ 不报失败。"""
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="needs_clarification"
    )

    result = await _map_terminal_blueprint(session, str(uuid.uuid4()))

    assert result.success is True
    assert result.output["marker"] == PLAN_CLARIFICATION_RENDER_MARKER


@pytest.mark.asyncio
async def test_failed_blueprint_is_a_failure() -> None:
    """``failed`` 才是失败（分档的另一端，证明上面几条不是恒真）。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.FAILED, blueprint_status="failed", thread_kind=None
    )
    await ConvergenceSession.objects.filter(id=session.id).aupdate(error={"message": "融合器炸了"})
    session = await ConvergenceSession.objects.aget(id=session.id)

    result = await _map_terminal_blueprint(session, str(uuid.uuid4()))

    assert result.success is False
    assert "融合器炸了" in (result.error or "")


@pytest.mark.asyncio
async def test_intermediate_status_is_not_reported_as_failure() -> None:
    """其余中间态（``drafting``）一律成功 + 「仍在进行中」⇒ ⛔ 不误报失败。"""
    from delivery.models import ConvergenceSessionStatus

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="drafting", thread_kind=None
    )

    result = await _map_terminal_blueprint(session, str(uuid.uuid4()))

    assert result.success is True
    assert result.output["current_status"] == "drafting"


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. 断链一：两个蓝图 barrier 的 CHAT 回灌
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_barrier_feedback_satisfies_the_waiter_with_the_registered_key() -> None:
    """⭐ 回灌用 ``str(session.id)`` 作 key —— 与 chat 注册 blocking task 时逐字对齐。

    key 不一致的症状是 waiter 永远等不到，且**不抛异常**（对话永远停在「深入调研容器运行
    中…」）。
    """
    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    task_completed = AsyncMock(return_value=True)
    with patch(
        "orchestration.barrier.get_barrier_manager",
        return_value=type("M", (), {"task_completed": task_completed})(),
    ):
        await _afeedback_chat_blueprint_barrier(session)

    task_completed.assert_awaited_once()
    key, result = task_completed.await_args.args
    assert key == str(session.id)
    assert result["task_id"] == str(session.id)
    assert result["task_type"] == "plan_research"
    # ⭐ 蓝图 DONE = 等人审，对 chat 用户而言**方案已产出** ⇒ 那也是成功。
    assert result["success"] is True
    assert result["output"] == str(session.current_artifact_version_id)


@pytest.mark.asyncio
async def test_research_barrier_feeds_back_after_resuming() -> None:
    """⭐ 走真实 barrier 入口：全部调研终态 ⇒ 续驱**之后**回灌（断链一的正面用例）。

    这条是变异 (b)「去掉两个 barrier 里的回灌调用」的**翻转位** —— 去掉后 waiter 拿不到
    结果，且**不抛异常**（对话永远停在「深入调研容器运行中…」）。
    """
    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _trigger_blueprint_research_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    task_completed = AsyncMock(return_value=True)
    with (
        patch(
            "services.process_runtime.blueprint_resume.aresume_blueprint_session",
            AsyncMock(return_value=session),
        ),
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=type("M", (), {"task_completed": task_completed})(),
        ),
    ):
        await _trigger_blueprint_research_barrier(session)

    task_completed.assert_awaited_once()
    assert task_completed.await_args.args[0] == str(session.id)


@pytest.mark.asyncio
async def test_a_mismatched_key_would_not_satisfy_the_waiter() -> None:
    """反向对照：key 错配（随机 uuid）时 waiter 不被满足 ⇒ 上一条不是恒真。"""
    from orchestration.barrier import BarrierManager

    manager = BarrierManager()
    satisfied = await manager.task_completed(
        str(uuid.uuid4()),
        {
            "task_id": str(uuid.uuid4()),
            "task_type": "plan_research",
            "success": True,
            "output": "",
            "error": "",
        },
    )
    assert satisfied is False


@pytest.mark.asyncio
async def test_non_chat_entrypoint_is_never_fed_back() -> None:
    """非 chat 入口不回灌（与 ``_schedule_chat_plan_resume`` 的 CHAT 守门对称）。"""
    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE,
        entrypoint="workflow",
        blueprint_status="pending_review",
        thread_kind=None,
    )

    task_completed = AsyncMock(return_value=True)
    with patch(
        "orchestration.barrier.get_barrier_manager",
        return_value=type("M", (), {"task_completed": task_completed})(),
    ):
        await _afeedback_chat_blueprint_barrier(session)

    task_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_still_suspended_session_is_not_fed_back_as_failure() -> None:
    """仍挂起的会话不回灌（否则会以 ``success=False`` 提前把 chat 阻塞任务误解析为失败）。"""
    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    task_completed = AsyncMock(return_value=True)
    with patch(
        "orchestration.barrier.get_barrier_manager",
        return_value=type("M", (), {"task_completed": task_completed})(),
    ):
        await _afeedback_chat_blueprint_barrier(session)

    task_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_barrier_feedback_never_bites_back() -> None:
    """整段 best-effort：回灌内部异常绝不冒泡到 barrier / 容器回调。"""
    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    with patch("orchestration.barrier.get_barrier_manager", side_effect=RuntimeError("boom")):
        await _afeedback_chat_blueprint_barrier(session)  # ⛔ 不抛


def test_both_blueprint_barriers_share_one_feedback_helper() -> None:
    """⭐ 回灌是**一个共享 helper 的两处调用**，⛔ 不是两份复制（两份必然漂移）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "subagent" / "api" / "callbacks.py").read_text(
        encoding="utf-8"
    )
    assert src.count("async def _afeedback_chat_blueprint_barrier") == 1
    assert src.count("_afeedback_chat_blueprint_barrier") >= 3


# ═══════════════════════════════════════════════════════════════════════════
# 7. 116-REVIEW MN-04：重挂起留痕 + 作答链的第二条出路
#
# 回退前 `_afeedback_chat_blueprint_barrier` 只挂在**两个容器回调** barrier 上。守门本身
# 是对的（非终态回灌会把 waiter 误解析成失败），但**没有第二条出路**：会话此后若由
# REST / MCP / 查看器的作答链（`aresume_after_gate_action`）驱到 DONE，那条链上没有任何
# 一处回灌 ⇒ 对话里的「深入调研容器运行中…」占位永久停在那里（115-MJ-02 的同一形状）。
# 且这一档比 analog 弱：analog 打了 `chat_plan_resume_resuspended`，蓝图这条是裸 return。
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_resuspended_session_leaves_a_trace_like_the_analog() -> None:
    """⭐ 重挂起这一档必须留痕（analog 打 ``chat_plan_resume_resuspended``）。"""
    from structlog.testing import capture_logs

    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )

    task_completed = AsyncMock(return_value=True)
    with (
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=type("M", (), {"task_completed": task_completed})(),
        ),
        capture_logs() as cap,
    ):
        await _afeedback_chat_blueprint_barrier(session)

    task_completed.assert_not_awaited()
    events = [e for e in cap if e["event"] == "blueprint_chat_barrier_resuspended"]
    assert len(events) == 1
    assert events[0]["category"] == "sampling"
    assert events[0]["component"] == "subagent"
    assert events[0]["session_id"] == str(session.id)
    assert events[0]["status"] == ConvergenceSessionStatus.WAITING_CLARIFICATION


@pytest.mark.asyncio
async def test_terminal_session_leaves_no_resuspend_trace() -> None:
    """非恒真对照：真的到终态时**不落**这条事件（⛔ 留痕不是无差别刷屏）。"""
    from structlog.testing import capture_logs

    from delivery.models import ConvergenceSessionStatus
    from subagent.api.callbacks import _afeedback_chat_blueprint_barrier

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    with (
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=type("M", (), {"task_completed": AsyncMock(return_value=True)})(),
        ),
        capture_logs() as cap,
    ):
        await _afeedback_chat_blueprint_barrier(session)

    assert [e for e in cap if e["event"] == "blueprint_chat_barrier_resuspended"] == []


@pytest.mark.asyncio
async def test_answer_chain_is_the_second_exit_that_feeds_the_waiter() -> None:
    """⭐ 断链二：作答链的共同出口驱到终态时也必须回灌。

    116 队列化后，全部作答链（REST / MCP / 查看器）的共同出口是 worker 任务体
    ``arun_blueprint_resume``（端点侧的 ``aresume_after_gate_action`` 只入队）——
    回退前这条链**一处都不回灌**，对话里的占位永久停住。
    """
    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    task_completed = AsyncMock(return_value=True)
    with (
        patch(
            "services.process_runtime.blueprint_resume."
            "adrive_blueprint_session_to_pause_or_terminal",
            AsyncMock(return_value=session),
        ),
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=type("M", (), {"task_completed": task_completed})(),
        ),
    ):
        await arun_blueprint_resume(str(session.id), initiated_by_user_id="u-1")

    task_completed.assert_awaited_once()
    assert task_completed.await_args.args[0] == str(session.id)


@pytest.mark.asyncio
async def test_answer_chain_hook_respects_the_non_chat_guard() -> None:
    """非恒真对照：非 chat 入口的会话走同一条作答链 ⇒ 仍然不回灌（守门没被绕过）。"""
    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE,
        entrypoint="workflow",
        blueprint_status="pending_review",
        thread_kind=None,
    )

    task_completed = AsyncMock(return_value=True)
    with (
        patch(
            "services.process_runtime.blueprint_resume."
            "adrive_blueprint_session_to_pause_or_terminal",
            AsyncMock(return_value=session),
        ),
        patch(
            "orchestration.barrier.get_barrier_manager",
            return_value=type("M", (), {"task_completed": task_completed})(),
        ),
    ):
        await arun_blueprint_resume(str(session.id), initiated_by_user_id="u-1")

    task_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_chain_hook_never_bites_back_on_the_gate_action() -> None:
    """⭐ 回灌 best-effort：内部炸了也绝不反噬续驱任务体（仍正常完成并返回结果）。"""
    from delivery.models import ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    session, _artifact = await _amake_blueprint_session(
        status=ConvergenceSessionStatus.DONE, blueprint_status="pending_review", thread_kind=None
    )

    with (
        patch(
            "services.process_runtime.blueprint_resume."
            "adrive_blueprint_session_to_pause_or_terminal",
            AsyncMock(return_value=session),
        ),
        patch(
            "subagent.api.callbacks._afeedback_chat_blueprint_barrier",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        result = await arun_blueprint_resume(str(session.id), initiated_by_user_id="u-1")

    assert result["resolved"] is True
    assert result["session_id"] == str(session.id)
