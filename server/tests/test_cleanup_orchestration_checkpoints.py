"""implementation contract 测试 — cleanup_orchestration_checkpoints management command。

覆盖 VALIDATION.md work item 锁定的 test 名：
- test_normal_cleanup
- test_dry_run
- test_status_filter_excludes_running
- test_recent_not_deleted
- test_empty_no_crash
- test_adelete_thread_failure_does_not_stop_batch
- test_batch_size_boundary_500
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import AsyncMock

import pytest
from django.core.management import call_command
from django.utils import timezone

from chat.models import Conversation
from orchestration.models import OrchestrationRun
from projects.models import Space


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def _project(db: None) -> Space:
    return Space.objects.create(name="Cleanup Test Space")


@pytest.fixture
def conversation(_project: Space) -> Conversation:
    return Conversation.objects.create(space=_project, title="清理测试对话")


def _backdate(run: OrchestrationRun, days: int) -> None:
    """手动 backdate updated_at（绕过 auto_now 保护）。"""
    OrchestrationRun.objects.filter(pk=run.pk).update(
        updated_at=timezone.now() - timedelta(days=days)
    )


@pytest.fixture
def old_completed_run(conversation: Conversation) -> OrchestrationRun:
    """10 天前的 COMPLETED 运行（cleanup 命中目标）。"""
    run = OrchestrationRun.objects.create(
        conversation=conversation,
        thread_id=str(conversation.id),
        status=OrchestrationRun.Status.COMPLETED,
    )
    _backdate(run, days=10)
    return run


@pytest.fixture
def old_error_run(conversation: Conversation) -> OrchestrationRun:
    """10 天前的 ERROR 运行（cleanup 也应命中）。"""
    # 为避免和 old_completed_run 的 thread_id 冲突，另起 conversation
    from chat.models import Conversation as Conv  # noqa: N813

    another_conv = Conv.objects.create(
        space=conversation.space, title="另一个错误对话"
    )
    run = OrchestrationRun.objects.create(
        conversation=another_conv,
        thread_id=str(another_conv.id),
        status=OrchestrationRun.Status.ERROR,
    )
    _backdate(run, days=10)
    return run


@pytest.fixture
def recent_completed_run(conversation: Conversation) -> OrchestrationRun:
    """当前 COMPLETED（不应被清理）。"""
    another_conv = Conversation.objects.create(
        space=conversation.space, title="近期完成对话"
    )
    return OrchestrationRun.objects.create(
        conversation=another_conv,
        thread_id=str(another_conv.id),
        status=OrchestrationRun.Status.COMPLETED,
    )


@pytest.fixture
def old_running_run(conversation: Conversation) -> OrchestrationRun:
    """10 天前但 status=RUNNING 的运行（status filter 必须排除）。"""
    another_conv = Conversation.objects.create(
        space=conversation.space, title="活跃运行对话"
    )
    run = OrchestrationRun.objects.create(
        conversation=another_conv,
        thread_id=str(another_conv.id),
        status=OrchestrationRun.Status.RUNNING,
    )
    _backdate(run, days=10)
    return run


@pytest.fixture
def mock_saver(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Mock get_checkpointer 返回 AsyncMock，避免真 SQLite IO。"""
    saver = AsyncMock()
    saver.adelete_thread = AsyncMock(return_value=None)

    async def _get() -> AsyncMock:
        return saver

    monkeypatch.setattr(
        "orchestration.management.commands.cleanup_orchestration_checkpoints.get_checkpointer",
        _get,
    )
    return saver


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.django_db
def test_normal_cleanup(
    old_completed_run: OrchestrationRun,
    old_error_run: OrchestrationRun,
    mock_saver: AsyncMock,
) -> None:
    """contract 正常清理：COMPLETED + ERROR + updated_at<now-7d 都被删除，adelete_thread 被调用。"""
    out = StringIO()
    call_command("cleanup_orchestration_checkpoints", "--days=7", stdout=out)

    # ORM 行已删
    assert not OrchestrationRun.objects.filter(pk=old_completed_run.pk).exists()
    assert not OrchestrationRun.objects.filter(pk=old_error_run.pk).exists()

    # SQLite adelete_thread 被调用（各 thread_id 一次）
    assert mock_saver.adelete_thread.await_count == 2
    awaited_thread_ids = {
        call.args[0] for call in mock_saver.adelete_thread.await_args_list
    }
    assert old_completed_run.thread_id in awaited_thread_ids
    assert old_error_run.thread_id in awaited_thread_ids

    # 成功输出
    assert "已清理" in out.getvalue()


@pytest.mark.django_db
def test_dry_run(
    old_completed_run: OrchestrationRun,
    mock_saver: AsyncMock,
) -> None:
    """contract dry-run：不真删，输出 '[dry-run] would delete ...'。"""
    out = StringIO()
    call_command(
        "cleanup_orchestration_checkpoints", "--days=7", "--dry-run", stdout=out
    )
    output = out.getvalue()
    assert "[dry-run]" in output
    assert "would delete" in output

    # 不应删除 ORM 行，也不应调用 adelete_thread
    assert OrchestrationRun.objects.filter(pk=old_completed_run.pk).exists()
    mock_saver.adelete_thread.assert_not_awaited()


@pytest.mark.django_db
def test_status_filter_excludes_running(
    old_running_run: OrchestrationRun,
    mock_saver: AsyncMock,
) -> None:
    """contract status filter：10 天前但 status=RUNNING 的运行不被清理（security mitigation-01 mitigation）。"""
    call_command("cleanup_orchestration_checkpoints", "--days=7")
    assert OrchestrationRun.objects.filter(pk=old_running_run.pk).exists()
    mock_saver.adelete_thread.assert_not_awaited()


@pytest.mark.django_db
def test_recent_not_deleted(
    recent_completed_run: OrchestrationRun,
    mock_saver: AsyncMock,
) -> None:
    """contract 边界：当前 COMPLETED 不被清理。"""
    call_command("cleanup_orchestration_checkpoints", "--days=7")
    assert OrchestrationRun.objects.filter(pk=recent_completed_run.pk).exists()
    mock_saver.adelete_thread.assert_not_awaited()


@pytest.mark.django_db
def test_empty_no_crash(db: None, mock_saver: AsyncMock) -> None:
    """contract 边界：0 条符合条件时正常完成，adelete_thread 调用 0 次。"""
    out = StringIO()
    call_command("cleanup_orchestration_checkpoints", "--days=7", stdout=out)
    mock_saver.adelete_thread.assert_not_awaited()
    # 成功输出中含 "0 runs"
    assert "0 runs" in out.getvalue()


@pytest.mark.django_db
def test_adelete_thread_failure_does_not_stop_batch(
    old_completed_run: OrchestrationRun,
    old_error_run: OrchestrationRun,
    mock_saver: AsyncMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """contract 异常隔离：单 thread 删除失败不阻塞整批（security mitigation-08 mitigation）。"""
    # 第一次抛错，第二次成功
    mock_saver.adelete_thread.side_effect = [
        RuntimeError("fake SQL error"),
        None,
    ]

    call_command("cleanup_orchestration_checkpoints", "--days=7")

    # ORM 行已删（adelete_thread 调用之前）
    assert not OrchestrationRun.objects.filter(pk=old_completed_run.pk).exists()
    assert not OrchestrationRun.objects.filter(pk=old_error_run.pk).exists()

    # 两个 thread 都被尝试过（未中断）
    assert mock_saver.adelete_thread.await_count == 2

    # structlog warning 事件写 stdout（项目 structlog 配置走 JSONRenderer → sys.stdout）
    captured = capsys.readouterr()
    assert (
        "cleanup_orchestration_checkpoint_delete_thread_failed"
        in captured.out
    )


@pytest.mark.django_db
def test_batch_size_boundary_500(
    _project: Space,
    mock_saver: AsyncMock,
) -> None:
    """contract batch_size=500 边界：501 条 thread_id 应被分 2 批 ORM delete，
    adelete_thread 仍调用 501 次（SQLite 操作按 thread 粒度）。"""
    # 构造 501 条 old COMPLETED runs（同一 project 下分别起 conversation）
    created_thread_ids: set[str] = set()
    for _ in range(501):
        conv = Conversation.objects.create(
            space=_project, title=f"批量测试-{uuid.uuid4().hex[:6]}"
        )
        run = OrchestrationRun.objects.create(
            conversation=conv,
            thread_id=str(conv.id),
            status=OrchestrationRun.Status.COMPLETED,
        )
        _backdate(run, days=10)
        created_thread_ids.add(str(conv.id))

    call_command(
        "cleanup_orchestration_checkpoints", "--days=7", "--batch-size=500"
    )

    # ORM 全部清空（501 条都删）
    remaining = OrchestrationRun.objects.filter(
        thread_id__in=list(created_thread_ids)
    ).count()
    assert remaining == 0

    # adelete_thread 调用 501 次
    assert mock_saver.adelete_thread.await_count == 501
