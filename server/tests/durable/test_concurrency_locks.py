"""并发治理槽位锁池守护（CONC-01）。

覆盖：
- 稳定 slot 计算（跨进程一致、在 [0,N) 范围、N<=0 clamp）
- SystemSetting 读取 N（默认值 / 自定义 / 非法回退）
- ProcrastinateBackend.defer 把 lock 透传进 configure_options（与 queueing_lock 正交）
- DurableTaskService.defer lock 参数向后端透传
"""

from __future__ import annotations

import pytest

from durable.concurrency import (
    DEFAULT_GRAPH_CONCURRENCY,
    DEFAULT_INDEX_CONCURRENCY,
    graph_slot_lock,
    index_slot_lock,
)

# ---------------------------------------------------------------------------
# 稳定 slot 计算（纯函数，无 DB）
# ---------------------------------------------------------------------------


def test_slot_lock_format_and_range() -> None:
    for i in range(50):
        lock = index_slot_lock(f"repo-{i}", 5)
        assert lock.startswith("index-slot-")
        slot = int(lock.rsplit("-", 1)[1])
        assert 0 <= slot < 5


def test_slot_lock_stable_across_calls() -> None:
    """同一 repo_id 多次计算恒定同槽（防重复索引的命门，不可受 PYTHONHASHSEED 影响）。"""
    a = index_slot_lock("repo-abc", 7)
    b = index_slot_lock("repo-abc", 7)
    assert a == b
    # graph 与 index 前缀不同，互不串台
    assert graph_slot_lock("repo-abc", 7).startswith("graph-slot-")


def test_slot_lock_clamps_nonpositive_n() -> None:
    """N<=0 防御：clamp 到单槽（slot 0），绝不除零。"""
    assert index_slot_lock("r", 0) == "index-slot-0"
    assert index_slot_lock("r", -3) == "index-slot-0"


def test_slot_distribution_spreads_repos() -> None:
    """不同 repo 应分散到多个槽位（不是全部挤一个）。"""
    slots = {index_slot_lock(f"repo-{i}", 5) for i in range(100)}
    assert len(slots) == 5  # 100 个 repo 应覆盖全部 5 槽


# ---------------------------------------------------------------------------
# SystemSetting 读取 N
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_concurrency_settings_default_when_missing() -> None:
    from durable.concurrency import get_graph_concurrency_sync, get_index_concurrency_sync

    assert get_index_concurrency_sync() == DEFAULT_INDEX_CONCURRENCY
    assert get_graph_concurrency_sync() == DEFAULT_GRAPH_CONCURRENCY


@pytest.mark.django_db
def test_concurrency_settings_custom_value() -> None:
    from durable.concurrency import get_index_concurrency_sync
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.create(key=SettingKeys.CONCURRENCY_INDEX_MAX, value="2")
    assert get_index_concurrency_sync() == 2


@pytest.mark.django_db
def test_concurrency_settings_invalid_falls_back_default() -> None:
    from durable.concurrency import get_index_concurrency_sync
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.create(key=SettingKeys.CONCURRENCY_INDEX_MAX, value="not-a-number")
    assert get_index_concurrency_sync() == DEFAULT_INDEX_CONCURRENCY


@pytest.mark.django_db
def test_concurrency_settings_zero_falls_back_default() -> None:
    from durable.concurrency import get_index_concurrency_sync
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.create(key=SettingKeys.CONCURRENCY_INDEX_MAX, value="0")
    assert get_index_concurrency_sync() == DEFAULT_INDEX_CONCURRENCY


# ---------------------------------------------------------------------------
# defer lock 透传
# ---------------------------------------------------------------------------


class _FakeDeferrer:
    def __init__(self, recorder: dict) -> None:
        self._recorder = recorder

    async def defer_async(self, **payload):
        self._recorder["payload"] = payload
        return 12345


class _FakeTask:
    def __init__(self, recorder: dict) -> None:
        self._recorder = recorder

    def configure(self, **options):
        self._recorder["configure_options"] = options
        return _FakeDeferrer(self._recorder)


class _FakeApp:
    def __init__(self, recorder: dict) -> None:
        self.tasks = {"durable_index": _FakeTask(recorder)}


async def test_procrastinate_backend_passes_lock_into_configure(monkeypatch) -> None:
    """lock 进 configure_options，与 queueing_lock(=idempotency_key) 正交并存。"""
    import procrastinate.contrib.django as pcd

    from durable.backends import ProcrastinateBackend

    recorder: dict = {}
    monkeypatch.setattr(pcd, "app", _FakeApp(recorder), raising=False)

    backend = ProcrastinateBackend()
    job_id = await backend.defer(
        "durable_index",
        {"repository_id": "r1"},
        queue="index",
        idempotency_key="index:r1",
        lock="index-slot-3",
    )

    assert job_id == "12345"
    opts = recorder["configure_options"]
    assert opts["queue"] == "index"
    assert opts["queueing_lock"] == "index:r1"  # todo 去重
    assert opts["lock"] == "index-slot-3"        # doing 并发槽（正交）


async def test_procrastinate_backend_omits_lock_when_none(monkeypatch) -> None:
    """不传 lock 时 configure_options 不含 lock 键（零回归）。"""
    import procrastinate.contrib.django as pcd

    from durable.backends import ProcrastinateBackend

    recorder: dict = {}
    monkeypatch.setattr(pcd, "app", _FakeApp(recorder), raising=False)

    backend = ProcrastinateBackend()
    await backend.defer("durable_index", {"repository_id": "r1"}, queue="index")

    assert "lock" not in recorder["configure_options"]


async def test_durable_service_forwards_lock_to_inprocess(monkeypatch) -> None:
    """DurableTaskService.defer 把 lock 透传给后端（in-process 接受但忽略）。"""
    from durable import backends
    from durable.service import DurableTaskService

    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured.update(kwargs)
        captured["task"] = task
        return "job-1"

    monkeypatch.setattr(backends.in_process_backend, "defer", _fake_defer)
    monkeypatch.setattr("durable.service.use_procrastinate_backend", lambda: False)

    await DurableTaskService.defer(
        "durable_index", {"repository_id": "r1"}, queue="index", lock="index-slot-1"
    )

    assert captured["lock"] == "index-slot-1"
