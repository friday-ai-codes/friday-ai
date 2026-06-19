"""5 处 index/graph 生产入队点迁移守护（MIGRATE-01 / SC1）。

锁定两类契约：
- grep 守护：5 个生产入队文件零 ``wrap_resumable`` / ``submit_resumable`` 残留
  （三套并存对 index/graph 真正收口；复用 test_no_direct_import.py 的 rg 子进程范式）。
- queue/key 守护：每处 defer 使用 ``durable_index`` / ``durable_graph`` 任务名 +
  正确 queue 常量 + deterministic idempotency_key（``index:{repo_id}`` /
  ``graph:{repo_id}``）。纯 helper（#1 ``_schedule_index``、#5 resume handler）经
  monkeypatch 捕获调用参数直接断言；#2/#3/#4（async + DB 前置）以源码内容静态断言
  覆盖（避免在守护测试里拉起完整 view/DB）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from durable.queues import QUEUE_GRAPH, QUEUE_INDEX
from durable.service import DurableTaskService

# server/ 根（tests/durable/<this> → parents[2]）。
_SERVER_ROOT = Path(__file__).resolve().parents[2]

# 5 处生产入队文件（相对 server/）。
_ENQUEUE_FILES = (
    "repositories/index_views.py",
    "repositories/views.py",
    "tasks/index_trigger_tasks.py",
    "codegraph/views.py",
    "resumable/handlers.py",
)

_RESIDUE_RE = r"wrap_resumable|submit_resumable"


# ---------------------------------------------------------------------------
# grep 守护：5 个入队文件零 wrap_resumable / submit_resumable 残留
# ---------------------------------------------------------------------------


def test_no_resumable_dispatch_residue_in_enqueue_files() -> None:
    """5 处生产 index/graph 入队点不再经旧 resumable 提交路径派发（SC1 收口）。"""
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("ripgrep (rg) 不可用，跳过迁移 grep 守护")

    abs_files = [str(_SERVER_ROOT / f) for f in _ENQUEUE_FILES]
    result = subprocess.run(
        [rg, "-n", _RESIDUE_RE, *abs_files],
        capture_output=True,
        text=True,
        check=False,
    )
    # rg 退出码：0=有命中（违规），1=无命中（期望），>=2=出错。
    if result.returncode >= 2:
        raise AssertionError(f"ripgrep 扫描失败：{result.stderr.strip()}")
    assert result.returncode == 1, (
        "MIGRATE-01 违反：以下入队文件仍残留 wrap_resumable/submit_resumable：\n"
        f"{result.stdout.strip()}"
    )


# ---------------------------------------------------------------------------
# 静态守护：5 处入队点 defer 任务名 + queue + deterministic key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel_path", "needles"),
    [
        (
            "repositories/index_views.py",
            ('"durable_index"', "queue=QUEUE_INDEX", 'idempotency_key=f"index:{repository_id}"'),
        ),
        (
            "repositories/views.py",
            ('"durable_index"', "queue=QUEUE_INDEX", 'idempotency_key=f"index:{repo_id}"'),
        ),
        (
            "tasks/index_trigger_tasks.py",
            ('"durable_index"', "queue=QUEUE_INDEX", 'idempotency_key=f"index:{repo_id}"'),
        ),
        (
            "codegraph/views.py",
            ('"durable_graph"', "queue=QUEUE_GRAPH", 'idempotency_key=f"graph:{repo_id_str}"'),
        ),
        (
            "resumable/handlers.py",
            (
                '"durable_index"',
                '"durable_graph"',
                'idempotency_key=f"index:{repository_id}"',
                'idempotency_key=f"graph:{repository_id}"',
            ),
        ),
    ],
)
def test_enqueue_points_use_defer_with_queue_and_key(rel_path: str, needles: tuple[str, ...]) -> None:
    """每处入队点源码含 durable 任务名 + 正确 queue 常量 + deterministic idempotency_key。"""
    content = (_SERVER_ROOT / rel_path).read_text(encoding="utf-8")
    assert "DurableTaskService.defer" in content, f"{rel_path} 未见 DurableTaskService.defer"
    for needle in needles:
        assert needle in content, f"{rel_path} 缺少 defer 契约片段：{needle!r}"


# ---------------------------------------------------------------------------
# 行为守护：纯 helper（#1 _schedule_index、#5 resume handler）defer 入参
# ---------------------------------------------------------------------------


def test_schedule_index_defers_durable_index_with_key(monkeypatch) -> None:
    """#1 ``_schedule_index`` 经 async_to_sync 投递 durable_index，queue/key 正确。"""
    from repositories.index_views import _schedule_index

    captured = AsyncMock(return_value="index:repo-1")
    monkeypatch.setattr(DurableTaskService, "defer", captured)

    job_id = _schedule_index("repo-1", "hist-1", branch="dev", trigger="manual")

    assert job_id == "index:repo-1"
    captured.assert_awaited_once()
    args, kwargs = captured.call_args
    assert args[0] == "durable_index"
    assert args[1] == {
        "repository_id": "repo-1",
        "history_id": "hist-1",
        "branch": "dev",
        "trigger": "manual",
    }
    assert kwargs["queue"] == QUEUE_INDEX
    assert kwargs["idempotency_key"] == "index:repo-1"


class _FakeResumableTask:
    """resume handler 仅读 ``payload`` / ``target_id``，构造最小替身即可。"""

    def __init__(self, payload: dict, target_id: str) -> None:
        self.payload = payload
        self.target_id = target_id


def test_resume_index_defers_durable_index_with_key(monkeypatch) -> None:
    """#5 resume_index 改走 defer：durable_index + index:{repo_id}，history_id=None（任务体自建）。"""
    from resumable.handlers import resume_index

    captured = AsyncMock(return_value="index:R")
    monkeypatch.setattr(DurableTaskService, "defer", captured)

    resume_index(_FakeResumableTask({"repository_id": "R", "branch": "feat", "trigger": "webhook"}, "R"))

    captured.assert_awaited_once()
    args, kwargs = captured.call_args
    assert args[0] == "durable_index"
    assert args[1] == {
        "repository_id": "R",
        "history_id": None,
        "branch": "feat",
        "trigger": "webhook",
    }
    assert kwargs["queue"] == QUEUE_INDEX
    assert kwargs["idempotency_key"] == "index:R"


def test_resume_graph_defers_durable_graph_with_key(monkeypatch) -> None:
    """#5 resume_graph 改走 defer：durable_graph + graph:{repo_id}，history_id=None。"""
    from resumable.handlers import resume_graph

    captured = AsyncMock(return_value="graph:R")
    monkeypatch.setattr(DurableTaskService, "defer", captured)

    resume_graph(_FakeResumableTask({"repository_id": "R", "branch": None, "trigger": "manual"}, "R"))

    captured.assert_awaited_once()
    args, kwargs = captured.call_args
    assert args[0] == "durable_graph"
    assert args[1] == {
        "repository_id": "R",
        "history_id": None,
        "branch": None,
        "trigger": "manual",
    }
    assert kwargs["queue"] == QUEUE_GRAPH
    assert kwargs["idempotency_key"] == "graph:R"
