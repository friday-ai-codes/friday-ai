"""implementation Task 2：`rebuild_chunk_edges` 管理命令单测。

覆盖 6 条用例（requirements + 互斥校验 / 幂等 / 断点续跑语义）：

1. test_repo_and_all_mutually_exclusive
   `--repo` 与 `--all` 同传 → CommandError（错误信息含 "互斥"）。
2. test_no_args_raises_command_error
   两参数都不传 → CommandError（错误信息含 "必须指定"）。
3. test_dry_run_no_writes
   `--repo --dry-run` → 输出预估行，不调 enqueue_edge_build，last_built_at 仍 NULL。
4. test_single_repo_backfill
   `--repo <uuid>` → enqueue_edge_build 被调一次（args 含 repo_id + chunk_ids），
   命令结束后 ChunkRegistry.last_built_at IS NOT NULL。
5. test_all_iterates_indexed_repos_only
   3 仓库（2 INDEXED + 1 NOT_INDEXED）→ enqueue 调用次数 = 2。
6. test_idempotent_skips_built_chunks
   全部 chunk last_built_at NOT NULL → enqueue 调 0 次（断点续跑：dry_count == 0）。
7. test_invalid_repo_uuid_raises
   `--repo "not-a-uuid"` → CommandError。
8. test_help_lists_three_arguments
   `manage.py help rebuild_chunk_edges` 输出含三参数（--repo / --all / --dry-run）。
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from code_relations.models import ChunkRegistry
from code_relations.utils import generate_chunk_id
from repositories.models import IndexStatus, Repository

pytestmark = pytest.mark.django_db(transaction=True)


def _make_chunk(
    repository: Repository,
    *,
    file_path: str,
    index: int = 0,
    last_built_at: object = None,
) -> ChunkRegistry:
    cid = generate_chunk_id(str(repository.id), file_path, index)
    kwargs: dict[str, object] = {
        "chunk_id": cid,
        "content_hash": "a" * 64,
        "repository": repository,
        "file_path": file_path,
        "chunk_index": index,
    }
    if last_built_at is not None:
        kwargs["last_built_at"] = last_built_at
    return ChunkRegistry.objects.create(**kwargs)


@pytest.fixture
def indexed_repo(db) -> Repository:
    """单 INDEXED 仓库 fixture（区别于 tests/conftest.py 默认 NOT_INDEXED）。"""
    return Repository.objects.create(
        name="Indexed Repo",
        git_url="https://github.com/test/indexed.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )


def test_repo_and_all_mutually_exclusive(indexed_repo: Repository) -> None:
    out = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            "--all",
            stdout=out,
        )
    assert "互斥" in str(exc_info.value)


def test_no_args_raises_command_error() -> None:
    out = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command("rebuild_chunk_edges", stdout=out)
    assert "必须指定" in str(exc_info.value)


def test_dry_run_no_writes(indexed_repo: Repository) -> None:
    _make_chunk(indexed_repo, file_path="src/a.py", index=0)
    _make_chunk(indexed_repo, file_path="src/b.py", index=0)

    mock_enqueue = AsyncMock(return_value=None)
    out = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        mock_enqueue,
    ):
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            "--dry-run",
            stdout=out,
        )

    output = out.getvalue()
    assert "[DRY-RUN]" in output
    assert "dry_run=True" in output
    assert "pending_chunks=2" in output
    mock_enqueue.assert_not_called()
    # last_built_at 仍是 NULL（dry-run 不更新）
    assert (
        ChunkRegistry.objects.filter(
            repository=indexed_repo, last_built_at__isnull=True
        ).count()
        == 2
    )


def test_single_repo_backfill(indexed_repo: Repository) -> None:
    c1 = _make_chunk(indexed_repo, file_path="src/a.py", index=0)
    c2 = _make_chunk(indexed_repo, file_path="src/b.py", index=0)

    mock_enqueue = AsyncMock(return_value=None)
    out = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        mock_enqueue,
    ):
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            stdout=out,
        )

    assert mock_enqueue.await_count == 1, "enqueue_edge_build 应被调一次"
    call_args = mock_enqueue.await_args
    assert call_args is not None
    repo_arg, chunk_ids_arg = call_args.args
    assert repo_arg == str(indexed_repo.id)
    assert set(chunk_ids_arg) == {c1.chunk_id, c2.chunk_id}

    # 命令完成后该仓库所有 ChunkRegistry.last_built_at IS NOT NULL
    assert (
        ChunkRegistry.objects.filter(
            repository=indexed_repo, last_built_at__isnull=False
        ).count()
        == 2
    )


def test_all_iterates_indexed_repos_only(db) -> None:
    indexed_a = Repository.objects.create(
        name="Indexed A",
        git_url="https://github.com/test/a.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    indexed_b = Repository.objects.create(
        name="Indexed B",
        git_url="https://github.com/test/b.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    not_indexed = Repository.objects.create(
        name="Not Indexed",
        git_url="https://github.com/test/c.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.NOT_INDEXED,
    )
    _make_chunk(indexed_a, file_path="src/a.py", index=0)
    _make_chunk(indexed_b, file_path="src/b.py", index=0)
    _make_chunk(not_indexed, file_path="src/c.py", index=0)

    mock_enqueue = AsyncMock(return_value=None)
    out = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        mock_enqueue,
    ):
        call_command("rebuild_chunk_edges", "--all", stdout=out)

    assert mock_enqueue.await_count == 2, "仅 2 个 INDEXED 仓库被处理"
    repo_ids_called = {call.args[0] for call in mock_enqueue.await_args_list}
    assert repo_ids_called == {str(indexed_a.id), str(indexed_b.id)}
    assert str(not_indexed.id) not in repo_ids_called


def test_idempotent_skips_built_chunks(indexed_repo: Repository) -> None:
    """断点续跑：last_built_at NOT NULL 的 chunk 不再 dispatch。"""
    from django.utils import timezone

    now = timezone.now()
    _make_chunk(
        indexed_repo, file_path="src/a.py", index=0, last_built_at=now
    )
    _make_chunk(
        indexed_repo, file_path="src/b.py", index=0, last_built_at=now
    )

    mock_enqueue = AsyncMock(return_value=None)
    out = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        mock_enqueue,
    ):
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            stdout=out,
        )

    assert mock_enqueue.await_count == 0, (
        "所有 chunk 已 backfill，断点续跑应跳过 enqueue"
    )


def test_invalid_repo_uuid_raises(db) -> None:
    out = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            "not-a-uuid",
            stdout=out,
        )
    assert "UUID" in str(exc_info.value)


def test_builder_failure_keeps_last_built_at_null(
    indexed_repo: Repository,
) -> None:
    """work item 回归：builder spawn 的背景 task 抛异常 → ``last_built_at`` 不应被更新。

    implementation REVIEW work item 揭示 ``asyncio.gather(..., return_exceptions=True)``
    把异常吞成返回值，外层 ``try/except`` 永远捕不到 → 失败 chunk 被错误标完成。
    修复后 ``_dispatch_and_drain`` 检测 ``BaseException`` 返回值 → 显式
    ``raise RuntimeError`` 让 ``_process_repo`` ``except`` 分支跳过 update。
    """
    import asyncio

    from code_relations import tasks as tasks_module

    _make_chunk(indexed_repo, file_path="src/a.py", index=0)
    _make_chunk(indexed_repo, file_path="src/b.py", index=0)

    async def _spawn_failing_task(
        repository_id: str, dirty_chunk_ids: list
    ) -> None:
        async def _boom() -> None:
            raise RuntimeError("simulated builder failure")

        task = asyncio.create_task(_boom())
        tasks_module._BACKGROUND_TASKS.add(task)
        task.add_done_callback(tasks_module._BACKGROUND_TASKS.discard)

    out = StringIO()
    err = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        new=_spawn_failing_task,
    ):
        with pytest.raises(SystemExit) as exit_info:
            call_command(
                "rebuild_chunk_edges",
                "--repo",
                str(indexed_repo.id),
                stdout=out,
                stderr=err,
            )

    assert exit_info.value.code == 1, (
        "contract：dispatch 失败应让命令以退出码 1 退出"
    )
    assert "[FAIL]" in err.getvalue(), (
        f"应输出 [FAIL] 提示；stderr={err.getvalue()!r}"
    )
    assert "failed_repos=1" in out.getvalue(), (
        f"summary 应区分 failed_repos；stdout={out.getvalue()!r}"
    )
    assert (
        ChunkRegistry.objects.filter(
            repository=indexed_repo, last_built_at__isnull=True
        ).count()
        == 2
    ), "builder 失败时 last_built_at 仍应为 NULL（断点续跑下次重试）"


def test_since_includes_older_built_chunks(indexed_repo: Repository) -> None:
    """contract 回归：传 ``--since`` 时 ``last_built_at < since`` 的旧行被重建。"""
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    old = now - timedelta(days=30)

    _make_chunk(indexed_repo, file_path="src/null.py", index=0)
    _make_chunk(
        indexed_repo, file_path="src/old.py", index=0, last_built_at=old
    )
    _make_chunk(
        indexed_repo, file_path="src/fresh.py", index=0, last_built_at=now
    )

    mock_enqueue = AsyncMock(return_value=None)
    out = StringIO()
    since_iso = (now - timedelta(days=1)).isoformat()
    with patch(
        "code_relations.management.commands.rebuild_chunk_edges.enqueue_edge_build",
        mock_enqueue,
    ):
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            "--since",
            since_iso,
            stdout=out,
        )

    assert mock_enqueue.await_count == 1
    repo_arg, chunk_ids_arg = mock_enqueue.await_args.args
    chunk_ids_set = set(chunk_ids_arg)
    assert len(chunk_ids_set) == 2, (
        f"--since 应覆盖 NULL + 30 天前的两行；实际 {len(chunk_ids_set)} 行"
    )


def test_since_naive_datetime_raises(indexed_repo: Repository) -> None:
    """contract：``--since`` 不带 timezone 时拒绝（USE_TZ=True 项目惯例）。"""
    out = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            "--since",
            "2026-01-01T00:00:00",
            stdout=out,
        )
    assert "naive" in str(exc_info.value).lower() or "timezone" in str(exc_info.value)


def test_since_invalid_format_raises(indexed_repo: Repository) -> None:
    """contract：``--since`` 非 ISO8601 → CommandError。"""
    out = StringIO()
    with pytest.raises(CommandError) as exc_info:
        call_command(
            "rebuild_chunk_edges",
            "--repo",
            str(indexed_repo.id),
            "--since",
            "not-a-date",
            stdout=out,
        )
    assert "ISO8601" in str(exc_info.value) or "since" in str(exc_info.value).lower()


def test_help_lists_three_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    """`manage.py help rebuild_chunk_edges` 输出含三参数（smoke）。

    argparse `--help` 走 sys.stdout 而非 call_command 的 stdout 参数，
    所以用 capsys 捕获。
    """
    with pytest.raises(SystemExit):
        call_command("rebuild_chunk_edges", "--help")
    captured = capsys.readouterr()
    output = captured.out
    assert "--repo" in output
    assert "--all" in output
    assert "--dry-run" in output
